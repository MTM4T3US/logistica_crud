"""Baixa (ou atualiza) o mapa real da cidade do OpenStreetMap para a cena 3D do HUD.

Uso:  .venv\\Scripts\\python scripts\\baixar_mapa.py [--forcar]
O núcleo também baixa sozinho na primeira vez que o mapa é aberto; este script serve para
adiantar o download e conferir o que veio. Dados © colaboradores do OpenStreetMap (ODbL).
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.services.citymap import CityMap  # noqa: E402


async def main() -> int:
    s = load_settings()
    loc = s.location
    cm = CityMap(s.db_path.parent / "mapa", loc.city, loc.latitude, loc.longitude, s.map_radius_m, s.overpass_url)
    print(f"Mapa de {loc.city} ({loc.latitude}, {loc.longitude}), raio {s.map_radius_m} m — fonte: {s.overpass_url}")
    t0 = time.perf_counter()
    data = await cm.get(force="--forcar" in sys.argv)
    if not data.get("ok"):
        print("FALHA:", data["error"])
        return 1
    c = data["counts"]
    print(f"OK em {time.perf_counter() - t0:.1f} s{' (arquivo antigo: sem internet)' if data.get('stale') else ''}: "
          f"{c['roads']} ruas, {c['buildings']} prédios ({c['buildings_with_height']} com altura no mapa), "
          f"{c['water']} trechos de água, {c['parks']} parques, {c['pois']} pontos de referência.")
    print(f"Salvo em {cm.path}")
    if c["buildings"] < 200:
        print("Aviso: poucos prédios mapeados no OpenStreetMap nesta região; o HUD mostra só o que existe no mapa.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
