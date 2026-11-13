"""0.4: entrada por rosto (descritores, prova de vida, PIN, bloqueio), resumo real e sequência de entrada."""
from __future__ import annotations

import email.utils
import json
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assistant import Assistant
from app.devices.registry import DeviceRegistry
from app.main import create_app
from app.memory.store import MemoryStore
from app.security.face_gate import FaceGate, clean_descriptors, similarity
from app.services.briefing import compose, welcome_text
from app.services.news import NewsService, clean_item, default_feeds
from app.services.weather import WeatherService

from .conftest import FakeController

ORIGIN = "http://127.0.0.1:5173"
HOST = {"host": "127.0.0.1:8765"}


def face(seed: int, n: int = 1024) -> list[float]:
    rnd = random.Random(seed)
    return [rnd.random() for _ in range(n)]       # escala parecida com a dos descritores do Human (0..1)


def near(base: list[float], amount: float, seed: int = 99) -> list[float]:
    rnd = random.Random(seed)
    return [v + (rnd.random() - 0.5) * amount for v in base]


ME = face(1)
STRANGER = face(2)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- comparação (mesmo cálculo do Human)
def test_similarity_matches_the_human_library_formula():
    assert similarity(ME, ME) == 1.0
    # distância 0,0128·25 → raiz 0,566 → (1 − 0,00566 − 0,2)/0,6 > 1 → 1
    assert similarity([0.0] * 128, [0.01] * 128) == 1.0
    # distância 36·25 = 900 → raiz 30 → (1 − 0,3 − 0,2)/0,6 = 0,83
    a, b = [0.0] * 1024, [0.1875] * 1024
    assert similarity(a, b) == pytest.approx(0.83, abs=0.01)
    assert similarity(ME, near(ME, 0.6)) > similarity(ME, near(ME, 1.2)) > similarity(ME, STRANGER)
    assert similarity(ME, near(ME, 0.6)) > 0.8 and similarity(ME, STRANGER) < 0.4
    assert similarity(ME, [1.0] * 10) == 0.0
    assert clean_descriptors([[1.0] * 10]) is None and clean_descriptors([[float("nan")] * 128]) is None
    assert clean_descriptors([[0.1] * 128, [0.1] * 256]) is None and clean_descriptors([[0.1] * 128] * 11) is None


# ---------------------------------------------------------------- portão
def gate(tmp_path, **kw) -> FaceGate:
    return FaceGate(tmp_path / "rosto.json", clock=kw.pop("clock", Clock()), **kw)


def test_enrollment_needs_consistent_captures_and_a_backup_pin(tmp_path):
    g = gate(tmp_path)
    assert g.open and not g.active                                           # sem cadastro, nada bloqueia
    assert g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)]).reason == "no_pin"
    assert g.enroll([ME, near(ME, 0.5)], "1234").reason == "invalid"       # menos de 3 capturas
    assert g.enroll([ME, STRANGER, near(ME, 0.5)], "1234").reason == "invalid"   # duas pessoas
    assert g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "12a4").reason == "invalid"
    ok = g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    assert ok.ok and g.active and g.open and g.unlocked_by == "cadastro"
    stored = json.loads((tmp_path / "rosto.json").read_text())
    assert len(stored["descriptors"]) == 3 and '"4321"' not in json.dumps(stored) and len(stored["pin"]["hash"]) == 64 and stored["pin"]["iter"] == 200_000
    assert not any(k in stored for k in ("image", "foto", "jpeg"))           # só números, nunca imagem


def test_locked_gate_needs_the_face_and_a_blink(tmp_path):
    g = gate(tmp_path)
    g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    again = gate(tmp_path)                                                   # núcleo reiniciado: volta bloqueado
    assert again.active and not again.open and again.status()["unlocked"] is False
    assert again.verify([near(ME, 0.6, 7)], {"blink": False}).reason == "liveness"
    assert again.verify([STRANGER], {"blink": True}).reason == "mismatch" and not again.open
    res = again.verify([near(ME, 0.6, 7)], {"blink": True, "real": 0.9})
    assert res.ok and res.similarity >= again.threshold and again.open and again.unlocked_by == "rosto"
    again.lock()
    assert not again.open and again.verify([[0.1] * 64], {"blink": True}).reason == "invalid"
    off = gate(tmp_path, liveness="desligado")
    assert off.verify([near(ME, 0.6, 7)], {}).ok                            # prova de vida desligada pelo usuário
    strict = gate(tmp_path, antispoof_min=0.5)
    assert strict.verify([near(ME, 0.6, 7)], {"blink": True, "real": 0.1}).reason == "liveness"


def test_repeated_failures_pause_attempts_and_pin_unlocks(tmp_path):
    clock = Clock()
    g = gate(tmp_path, clock=clock)
    g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    g.lock()
    for _ in range(4):
        assert g.verify([STRANGER], {"blink": True}).retry_after_s == 0
    fifth = g.verify([STRANGER], {"blink": True})
    assert fifth.retry_after_s == 30 and "aguarde" in fifth.message.lower()
    assert g.verify([ME], {"blink": True}).reason == "cooldown"             # nem o rosto certo durante a pausa
    assert g.verify_pin("4321").reason == "cooldown"
    clock.t += 31
    assert g.verify_pin("0000").reason == "pin" and not g.open
    assert g.verify_pin("4321").ok and g.open and g.unlocked_by == "pin"


def test_changing_or_deleting_the_face_requires_being_unlocked(tmp_path):
    clock = Clock()
    g = gate(tmp_path, clock=clock)
    g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    g.lock()
    assert g.enroll([STRANGER, near(STRANGER, 0.5), near(STRANGER, 0.5, 3)], "1111").reason == "locked"
    assert g.forget().reason == "locked" and g.set_enabled(False).reason == "locked"
    g.verify_pin("4321")
    assert g.set_enabled(False).ok and not g.active and g.open
    assert g.set_enabled(True).ok and g.forget().ok and not (tmp_path / "rosto.json").exists() and not g.active


def test_reopening_the_hud_after_a_while_asks_for_the_face_again(tmp_path):
    clock = Clock()
    g = gate(tmp_path, clock=clock, relock_s=120)
    g.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    g.connection_closed(0)
    clock.t += 30
    g.connection_opened(0)
    assert g.open                                                            # recarregar a página não bloqueia
    g.connection_closed(0)
    clock.t += 200
    g.connection_opened(0)
    assert not g.open                                                        # voltou depois de 3 min: pede o rosto


# ---------------------------------------------------------------- notícias e resumo
def test_news_reads_several_feeds_drops_old_items_and_cleans_titles():
    now = datetime.now(timezone.utc)
    fresh, old = email.utils.format_datetime(now - timedelta(hours=5)), email.utils.format_datetime(now - timedelta(days=12))

    def rss(*items):
        return "<rss><channel>" + "".join(f"<item><title>{t}</title><link>https://n/{i}</link><pubDate>{d}</pubDate><source>{s}</source></item>" for i, (t, d, s) in enumerate(items)) + "</channel></rss>"

    pages = {
        "cidade": rss(("Ponte reaberta em Itumbiara - Jornal Local", fresh, "Jornal Local"), ("Notícia antiga - Jornal", old, "Jornal")),
        "brasil": rss(("Câmara aprova projeto - G1", fresh, "G1")),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages["cidade" if "Itumbiara" in str(request.url) else "brasil"])

    feeds = default_feeds("Itumbiara", "Goiás")
    assert "Itumbiara" in feeds[0][1] and "when%3A7d" in feeds[0][1] and feeds[1][0] == "Brasil"

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await NewsService(feeds=feeds, client=client).get()

    import asyncio

    data = asyncio.run(run())
    assert data["ok"] and [s["label"] for s in data["sections"]] == ["Itumbiara", "Brasil"]
    city = data["sections"][0]["items"]
    assert [i["title"] for i in city] == ["Ponte reaberta em Itumbiara"] and city[0]["source"] == "Jornal Local" and city[0]["region"] == "Itumbiara"
    assert clean_item({"title": "Sem fonte - Folha", "link": "", "published": ""})["source"] == "Folha"


def test_briefing_uses_only_real_data_and_says_when_a_source_failed():
    now = {"time": "19:40", "date": "quinta-feira, 12 de novembro de 2026", "greeting": "Boa noite"}
    assert welcome_text(now, "senhor") == "Boa noite, senhor. Bem-vindo de volta. São 19 horas e 40, quinta-feira, 12 de novembro."
    assert "É 1 hora" in welcome_text({**now, "time": "01:00"}, "senhor")
    weather = {"ok": True, "temperature_c": 31.4, "condition": "Parcialmente nublado", "today": {"max_c": 34.2, "min_c": 21.6, "rain_probability": 40}}
    news = {"enabled": True, "sections": [
        {"label": "Itumbiara", "items": [{"title": "Ponte reaberta", "source": "Jornal", "region": "Itumbiara"}, {"title": "Feira no sábado.", "source": "Rádio", "region": "Itumbiara"}], "error": None},
        {"label": "Brasil", "items": [{"title": "Câmara aprova projeto", "source": "G1", "region": "Brasil"}], "error": None}]}
    b = compose(now, "Itumbiara", "senhor", weather, news)
    assert b["briefing"].startswith("Itumbiara agora: 31 graus, parcialmente nublado. Hoje, máxima de 34 e mínima de 22 graus, com 40 por cento de chance de chuva.")
    assert "Nas notícias de Itumbiara: Ponte reaberta; Feira no sábado." in b["briefing"] and "No Brasil: Câmara aprova projeto." in b["briefing"]
    assert b["briefing"].endswith("Em que posso ajudar, senhor?") and len(b["headlines"]) == 3
    bad = compose(now, "Itumbiara", "senhor", {"ok": False}, {"enabled": True, "sections": [{"label": "Itumbiara", "items": [], "error": "x"}, {"label": "Brasil", "items": [], "error": None}]})
    assert "Não consegui o clima de Itumbiara agora." in bad["briefing"] and "Não consegui ler as notícias de Itumbiara" in bad["briefing"]
    assert "Não encontrei notícias recentes do Brasil." in bad["briefing"] and bad["weather"] is None and bad["headlines"] == []
    assert "notícias" not in compose(now, "Itumbiara", "senhor", weather, {"enabled": False})["briefing"].lower()


# ---------------------------------------------------------------- servidor: bloqueio, entrada e música
@pytest.fixture
def client(settings, perms):
    settings.local_token = "token-de-teste"
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False))
    core.update_runtime({"speak": False})
    with TestClient(create_app(settings, core), base_url="http://127.0.0.1:8765") as c:
        c.core = core
        yield c


def auth() -> dict:
    return {**HOST, "x-jarvis-token": "token-de-teste"}


def until(ws, kind: str, limit: int = 40) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"sem evento {kind}")


def test_server_blocks_everything_until_the_face_is_confirmed(client):
    core = client.core
    core.gate.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    core.gate.lock()
    assert client.post("/api/settings", headers=auth(), json={"speak": True}).status_code == 423
    assert client.get("/api/intro/music", headers=auth()).status_code == 423
    st = client.get("/api/state", headers=auth()).json()
    assert st["face"]["active"] and st["face"]["unlocked"] is False and st["face"]["pin_set"]
    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        assert ws.receive_json()["state"]["face"]["unlocked"] is False
        ws.send_json({"type": "user_text", "text": "que horas são"})
        assert until(ws, "locked")["message"].startswith("Confirme seu rosto")
        ws.send_json({"type": "face_verify", "descriptors": [STRANGER], "liveness": {"blink": True}})
        bad = until(ws, "face_result")
        assert bad["ok"] is False and bad["reason"] == "mismatch"
        ws.send_json({"type": "face_verify", "descriptors": [near(ME, 0.6, 7)], "liveness": {"blink": True}})
        good = until(ws, "face_result")
        assert good["ok"] and good["similarity"] >= 0.62
        assert until(ws, "state")["state"]["face"]["unlocked"] is True
        ws.send_json({"type": "lock"})
        assert until(ws, "state")["state"]["face"]["unlocked"] is False
        ws.send_json({"type": "pin_verify", "pin": "4321"})
        assert until(ws, "face_result")["ok"]
    assert client.post("/api/settings", headers=auth(), json={"intro_voice_delay_s": 3}).json()["runtime"]["intro_voice_delay_s"] == 3


def test_intro_speaks_welcome_then_flies_to_the_city_with_the_real_briefing(client):
    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json({"type": "intro"})
        seen = []
        for _ in range(30):
            msg = ws.receive_json()
            if msg["type"] in ("ui", "delta", "turn_end"):
                seen.append(msg)
            if msg["type"] == "ui" and msg["action"] == "intro_done":
                break
    kinds = [(m["type"], m.get("action")) for m in seen]
    assert kinds == [("ui", "intro"), ("delta", None), ("turn_end", None), ("ui", "show_map"), ("delta", None), ("turn_end", None), ("ui", "intro_done")]
    welcome, brief = seen[1]["text"], seen[4]["text"]
    assert "Bem-vindo de volta" in welcome and seen[3]["at_turn"] == seen[4]["turn"] and seen[3]["at_turn"].startswith("intro-b-")
    # sem clima e sem notícias configurados no teste: ele diz isso, não inventa
    assert brief.startswith("Não consegui o clima de Itumbiara agora.") and "graus" not in brief
    assert seen[5]["mode"] == "intro" and seen[5]["ai"]["mode"] == "local"


def test_intro_music_is_the_users_own_file_kept_on_this_pc(client, settings):
    up = lambda data, name: client.post("/api/intro/music", headers={**auth(), "x-file-name": name, "content-type": "application/octet-stream"}, content=data)
    assert client.get("/api/intro/music", headers=auth()).status_code == 404
    assert up(b"ID3" + b"\x00" * 64, "virus.exe").status_code == 400
    assert up(b"<html>nao sou audio</html>", "musica.mp3").status_code == 400
    mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" * 500
    ok = up(mp3, "Minha%20m%C3%BAsica.mp3")
    assert ok.status_code == 200 and ok.json()["name"] == "Minha música.mp3"
    got = client.get("/api/intro/music", headers=auth())
    assert got.status_code == 200 and got.content == mp3 and got.headers["content-type"] == "audio/mpeg"
    assert (settings.db_path.parent / "entrada" / "musica.mp3").read_bytes() == mp3
    state = client.get("/api/state", headers=auth()).json()
    assert state["intro"] == {"music": True, "music_name": "Minha música.mp3"}
    assert client.delete("/api/intro/music", headers=auth()).json()["ok"] and client.get("/api/intro/music", headers=auth()).status_code == 404


# ---------------------------------------------------------------- mapa real (OpenStreetMap)
OVERPASS = {"elements": [
    {"type": "way", "tags": {"highway": "primary", "name": "Av. Afonso Pena"}, "geometry": [{"lat": -18.4192, "lon": -49.2163}, {"lat": -18.4192, "lon": -49.2143}]},
    {"type": "way", "tags": {"highway": "residential"}, "geometry": [{"lat": -18.4182, "lon": -49.2153}, {"lat": -18.4202, "lon": -49.2153}]},
    {"type": "way", "tags": {"highway": "footway"}, "geometry": [{"lat": -18.4182, "lon": -49.2150}, {"lat": -18.4183, "lon": -49.2150}]},
    {"type": "way", "tags": {"building": "yes", "building:levels": "4"}, "geometry": [
        {"lat": -18.4190, "lon": -49.2150}, {"lat": -18.4190, "lon": -49.2148}, {"lat": -18.4188, "lon": -49.2148}, {"lat": -18.4188, "lon": -49.2150}, {"lat": -18.4190, "lon": -49.2150}]},
    {"type": "way", "tags": {"building": "house"}, "geometry": [
        {"lat": -18.4195, "lon": -49.2156}, {"lat": -18.4195, "lon": -49.21555}, {"lat": -18.41945, "lon": -49.21555}, {"lat": -18.41945, "lon": -49.2156}, {"lat": -18.4195, "lon": -49.2156}]},
    {"type": "way", "tags": {"waterway": "river", "name": "Rio Paranaíba"}, "geometry": [{"lat": -18.43, "lon": -49.23}, {"lat": -18.432, "lon": -49.20}]},
    {"type": "way", "tags": {"leisure": "park"}, "geometry": [{"lat": -18.418, "lon": -49.214}, {"lat": -18.418, "lon": -49.213}, {"lat": -18.417, "lon": -49.213}, {"lat": -18.418, "lon": -49.214}]},
    {"type": "node", "lat": -18.4185, "lon": -49.2160, "tags": {"amenity": "townhall", "name": "Prefeitura de Itumbiara"}},
]}


def test_city_map_converts_openstreetmap_to_local_meters_and_caches(tmp_path):
    from app.services.citymap import CityMap, Projector, convert, overpass_query

    p = Projector(-18.4192, -49.2153)
    x, z = p(-18.4192, -49.2143)                     # 0,001° a leste ≈ 105,6 m nessa latitude
    assert 105 < x < 106 and abs(z) < 1e-6 and p(-18.4182, -49.2153)[1] < -110   # norte = z negativo
    data = convert(OVERPASS, -18.4192, -49.2153, "Itumbiara", 1800)
    assert data["counts"] == {"roads": 2, "buildings": 2, "buildings_with_height": 1, "water": 1, "parks": 1, "pois": 1}
    assert data["buildings"][0][0] == 13.0 and len(data["buildings"][0][1]) == 8      # 4 andares → 13 m; anel sem repetir o 1º ponto
    assert data["buildings"][1][0] == 4.0                                                 # casa sem altura no mapa: 4 m estimados
    assert data["roads"][0][0] == 0 and data["pois"][0][:2] == ["Prefeitura de Itumbiara", "prefeitura"]
    assert "ODbL" in data["attribution"] and 'around:1800,-18.4192,-49.2153' in overpass_query(-18.4192, -49.2153, 1800)

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=OVERPASS)

    import asyncio

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cm = CityMap(tmp_path / "mapa", "Itumbiara", -18.4192, -49.2153, 1800, "https://overpass.example/api/interpreter", client=client)
            first = await cm.get()
            second = await cm.get()
            fresh = CityMap(tmp_path / "mapa", "Itumbiara", -18.4192, -49.2153, 1800, "https://overpass.example/api/interpreter", client=client)
            return first, second, fresh.status()

    first, second, status = asyncio.run(run())
    assert first["ok"] and second["ok"] and len(calls) == 1                             # 2ª vez vem do arquivo
    assert status["ready"] and status["counts"]["roads"] == 2 and (tmp_path / "mapa" / "itumbiara-1800m.json").exists()

    async def offline():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
            return await CityMap(tmp_path / "vazio", "Itumbiara", -18.4192, -49.2153, 1800, "https://x/api", client=client).get()

    bad = asyncio.run(offline())
    assert bad["ok"] is False and "OpenStreetMap" in bad["error"]


# ---------------------------------------------------------------- comandos locais da 0.4
@pytest.mark.parametrize("text,tool", [
    ("Jarvis, mostra o mapa", "show_map"), ("abre o mapa da cidade", "show_map"),
    ("quais as novidades", "city_briefing"), ("Jarvis, como está a cidade?", "city_briefing"), ("me dá as notícias", "city_briefing"),
    ("bloqueia o jarvis", "lock_hud"), ("Jarvis, trava a tela", "lock_hud"),
])
def test_router_handles_map_news_and_lock_without_gemini(text, tool):
    from app.router import LocalRouter
    from app.security.permissions import Permissions

    names = {"show_map", "city_briefing", "lock_hud", "get_weather", "get_time", "control_device", "set_lights"}
    plan = LocalRouter(Permissions(), lambda: names).match(text)
    assert plan is not None and [c.name for c in plan.calls] == [tool]


def test_locking_by_voice_works_but_nothing_unlocks_by_voice(settings, perms):
    from app.router import LocalRouter

    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False))
    names = set(core.tools.specs())
    assert {"lock_hud", "city_briefing", "show_map"} <= names and not any("unlock" in n for n in names)
    plan = LocalRouter(perms, lambda: names).match("tranca a porta")
    assert plan is None or "lock_hud" not in [c.name for c in plan.calls]     # porta ≠ JARVIS
    assert core._lock_from_tool() is False                                     # sem rosto cadastrado não bloqueia
    core.gate.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    assert core._lock_from_tool() is True and not core.gate.open


def test_map_route_reports_missing_map_without_an_http_error(client, monkeypatch):
    async def offline(force=False):
        return {"ok": False, "error": "Não consegui baixar o mapa de Itumbiara do OpenStreetMap (ConnectError)."}

    monkeypatch.setattr(client.core.citymap, "get", offline)
    r = client.get("/api/map", headers=auth())
    assert r.status_code == 200 and r.json()["ok"] is False and "OpenStreetMap" in r.json()["error"]
    assert client.get("/api/state", headers=auth()).json()["map"] == {"ready": False, "city": "Itumbiara"}


def test_briefing_skips_duplicate_story_and_cut_captions():
    """Visto no Windows: o mesmo fato veio do Instagram (legenda cortada "…a expectativa d") e do
    Rota Jurídica; o resumo falava os dois, o primeiro cortado no meio da palavra."""
    from app.services.briefing import _news_text

    caption = ("O atendimento do Cejusc de Itumbiara, antes restrito a três municípios, foi ampliado para abranger também "
               "as jurisdições das Varas do Trabalho de Goiatuba e Quirinópolis, alcançando 23 municípios da região Sul de Goiás. "
               "Com a mudança, a expectativa d")
    news = {"enabled": True, "sections": [
        {"label": "Itumbiara", "items": [
            {"title": caption, "source": "Instagram"},
            {"title": "TRT-GO amplia atendimento do Cejusc de Itumbiara para 23 municípios da região Sul de Goiás", "source": "Rota Jurídica"},
            {"title": "Prefeitura inaugura nova praça no centro", "source": "Jornal"}]},
        {"label": "Brasil", "items": [{"title": "Senado aprova texto-base de pacote", "source": "Agência Brasil"}]}]}
    text, used = _news_text(news, "Itumbiara")
    assert "expectativa d" not in text and text.count("Cejusc") == 1 and "TRT-GO amplia" in text
    assert "nova praça" in text and "Senado aprova" in text and len(used) == 3
