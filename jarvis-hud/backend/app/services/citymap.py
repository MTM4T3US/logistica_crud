"""Mapa real da cidade (OpenStreetMap) para a cena 3D do HUD.

Baixa UMA vez, pela Overpass API, as ruas, prédios, água, parques e alguns pontos de referência num
raio em torno do centro da cidade, converte para metros num plano local (x = leste, z = sul) e guarda
em `backend/data/mapa/`. As próximas aberturas usam o arquivo salvo (válido por 60 dias).

Dados © colaboradores do OpenStreetMap, licença ODbL — a atribuição aparece no HUD.
Prédios só existem onde alguém os mapeou: o HUD não inventa prédios onde o OSM não tem.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx

ATTRIBUTION = "© colaboradores do OpenStreetMap (ODbL)"
MAX_AGE_S = 60 * 86400
MAX_BUILDINGS = 30000
MAX_BYTES = 80_000_000

ROAD_CLASS = {
    "motorway": 0, "trunk": 0, "primary": 0, "motorway_link": 0, "trunk_link": 0, "primary_link": 0,
    "secondary": 1, "secondary_link": 1, "tertiary": 1, "tertiary_link": 1,
    "unclassified": 2, "residential": 2, "living_street": 2, "pedestrian": 2,
    "service": 3,
}
POI_KINDS = {"townhall": "prefeitura", "hospital": "hospital", "university": "universidade", "college": "faculdade",
             "bus_station": "rodoviária", "police": "polícia", "fire_station": "bombeiros", "stadium": "estádio"}


def overpass_query(lat: float, lon: float, radius: int) -> str:
    r, rw = radius, int(radius * 1.6)
    roads = "|".join(ROAD_CLASS)
    pois = "|".join(k for k in POI_KINDS if k != "stadium")
    return f"""[out:json][timeout:90];
(
  way["highway"~"^({roads})$"](around:{r},{lat},{lon});
  way["building"](around:{r},{lat},{lon});
  way["waterway"~"^(river|stream|canal)$"](around:{rw},{lat},{lon});
  way["natural"="water"](around:{rw},{lat},{lon});
  relation["natural"="water"](around:{rw},{lat},{lon});
  way["leisure"~"^(park|stadium|pitch)$"](around:{r},{lat},{lon});
  node["amenity"~"^({pois})$"](around:{r},{lat},{lon});
  way["amenity"~"^({pois})$"](around:{r},{lat},{lon});
);
out geom tags;"""


class Projector:
    """Graus → metros num plano tangente ao centro (precisão de centímetros em poucos km)."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.kz = 110_574.0

    def __call__(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, -(lat - self.lat0) * self.kz


def _flat(pts: list[tuple[float, float]]) -> list[float]:
    """Coordenadas arredondadas a 10 cm: arquivo menor sem perder nada visível."""
    out: list[float] = []
    for x, z in pts:
        out += [round(x, 1), round(z, 1)]
    return out


def _height(tags: dict[str, str], area: float) -> tuple[float, bool]:
    """Altura em metros e se ela veio do mapa (True) ou foi estimada (False)."""
    for key in ("height", "building:height"):
        m = re.match(r"^\s*([\d.]+)", tags.get(key, ""))
        if m:
            return max(2.5, min(300.0, float(m.group(1)))), True
    m = re.match(r"^\s*(\d+)", tags.get("building:levels", ""))
    if m:
        return max(2.5, min(300.0, int(m.group(1)) * 3.0 + 1.0)), True
    if tags.get("building") in ("apartments", "commercial", "office", "hotel", "hospital", "university"):
        return 10.0, False
    return (6.0 if area > 900 else 4.0), False


def _area(pts: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * z2 - x2 * z1 for (x1, z1), (x2, z2) in zip(pts, pts[1:] + pts[:1]))) / 2


def convert(raw: dict[str, Any], lat0: float, lon0: float, city: str, radius: int) -> dict[str, Any]:
    proj = Projector(lat0, lon0)
    roads: list[list[Any]] = []
    buildings: list[list[Any]] = []
    water: list[list[Any]] = []
    parks: list[list[Any]] = []
    pois: list[list[Any]] = []
    tagged_heights = 0

    def line(geom: list[dict[str, float]]) -> list[tuple[float, float]]:
        return [proj(g["lat"], g["lon"]) for g in geom if "lat" in g and "lon" in g]

    for el in raw.get("elements", []):
        tags = el.get("tags") or {}
        kind = el.get("type")
        if kind == "node":
            amen = tags.get("amenity")
            if amen in POI_KINDS:
                x, z = proj(el["lat"], el["lon"])
                pois.append([tags.get("name") or POI_KINDS[amen], POI_KINDS[amen], round(x, 1), round(z, 1)])
            continue
        if kind == "relation":
            if tags.get("natural") == "water":
                for mem in el.get("members", []):
                    if mem.get("role") == "outer" and mem.get("geometry"):
                        pts = line(mem["geometry"])
                        if len(pts) >= 3:
                            water.append(["area", _flat(pts)])
            continue
        pts = line(el.get("geometry") or [])
        if len(pts) < 2:
            continue
        if "highway" in tags and tags["highway"] in ROAD_CLASS:
            roads.append([ROAD_CLASS[tags["highway"]], _flat(pts)])
        elif "building" in tags and len(pts) >= 4:
            ring = pts[:-1] if pts[0] == pts[-1] else pts
            area = _area(ring)
            if area < 8:
                continue
            h, real = _height(tags, area)
            tagged_heights += real
            buildings.append([round(h, 1), _flat(ring)])
        elif tags.get("waterway") in ("river", "stream", "canal"):
            water.append([tags["waterway"], _flat(pts)])
        elif tags.get("natural") == "water" and len(pts) >= 4:
            water.append(["area", _flat(pts[:-1] if pts[0] == pts[-1] else pts)])
        elif tags.get("leisure") in ("park", "stadium", "pitch") and len(pts) >= 4:
            parks.append([tags["leisure"], _flat(pts[:-1] if pts[0] == pts[-1] else pts)])
        elif tags.get("amenity") in POI_KINDS:
            cx = sum(p[0] for p in pts) / len(pts)
            cz = sum(p[1] for p in pts) / len(pts)
            pois.append([tags.get("name") or POI_KINDS[tags["amenity"]], POI_KINDS[tags["amenity"]], round(cx, 1), round(cz, 1)])

    # muitos prédios: fica com os mais próximos do centro
    if len(buildings) > MAX_BUILDINGS:
        buildings.sort(key=lambda b: min(math.hypot(b[1][i], b[1][i + 1]) for i in range(0, len(b[1]), 2)))
        buildings = buildings[:MAX_BUILDINGS]
    return {
        "version": 1, "city": city, "center": [lat0, lon0], "radius_m": radius, "fetched_at": time.time(),
        "attribution": ATTRIBUTION, "roads": roads, "buildings": buildings, "water": water, "parks": parks, "pois": pois,
        "counts": {"roads": len(roads), "buildings": len(buildings), "buildings_with_height": tagged_heights,
                   "water": len(water), "parks": len(parks), "pois": len(pois)},
    }


class CityMap:
    def __init__(self, folder: Path, city: str, lat: float, lon: float, radius_m: int, overpass_url: str,
                 client: httpx.AsyncClient | None = None):
        self.folder, self.city, self.lat, self.lon, self.radius, self.url = folder, city, lat, lon, radius_m, overpass_url
        self._client = client
        self._mem: dict[str, Any] | None = None
        slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-") or "cidade"
        self.path = folder / f"{slug}-{radius_m}m.json"

    def cached(self) -> dict[str, Any] | None:
        if self._mem is not None:
            return self._mem
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self._mem = data
        return data

    def status(self) -> dict[str, Any]:
        data = self.cached()
        if not data:
            return {"ready": False, "city": self.city}
        return {"ready": True, "city": data["city"], "counts": data["counts"], "fetched_at": data["fetched_at"], "attribution": data["attribution"]}

    async def get(self, force: bool = False) -> dict[str, Any]:
        data = self.cached()
        if data and not force and time.time() - data.get("fetched_at", 0) < MAX_AGE_S:
            return {"ok": True, **data}
        client = self._client or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        try:
            resp = await client.post(self.url, data={"data": overpass_query(self.lat, self.lon, self.radius)},
                                     headers={"User-Agent": "JARVIS-OS-local/0.4 (mapa pessoal)"})
            resp.raise_for_status()
            if len(resp.content) > MAX_BYTES:
                raise ValueError("resposta grande demais")
            fresh = convert(resp.json(), self.lat, self.lon, self.city, self.radius)
        except (httpx.HTTPError, ValueError) as exc:
            if data:   # sem internet: usa o mapa antigo e avisa
                return {"ok": True, "stale": True, **data}
            return {"ok": False, "error": f"Não consegui baixar o mapa de {self.city} do OpenStreetMap ({type(exc).__name__})."}
        finally:
            if self._client is None:
                await client.aclose()
        if not fresh["roads"]:
            return {"ok": False, "error": f"O OpenStreetMap não devolveu ruas para {self.city}; confira as coordenadas."}
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(fresh, separators=(",", ":")), encoding="utf-8")
        self._mem = fresh
        return {"ok": True, **fresh}
