"""Configuração, permissões, memória, clima, hora local, notícias e dispositivos."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import email.utils
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import BACKEND_DIR, Settings, load_settings
from app.devices.registry import DeviceRegistry, SimRobot
from app.memory.store import MemoryStore
from app.security.permissions import LocalAuth, Permissions
from app.services.local_info import local_now
from app.services.news import NewsService, parse_feed
from app.services.weather import WeatherService, describe

OPEN_METEO = {
    "current": {"time": "2026-11-11T22:00", "temperature_2m": 22.3, "relative_humidity_2m": 96, "apparent_temperature": 26.1, "is_day": 0, "precipitation": 0.0, "weather_code": 0, "cloud_cover": 12, "wind_speed_10m": 6.0},
    "daily": {"time": ["2026-11-11", "2026-11-12"], "weather_code": [95, 80], "temperature_2m_max": [30.3, 29.6], "temperature_2m_min": [22.1, 21.5], "precipitation_probability_max": [99, 86], "sunrise": ["2026-11-11T05:38", "2026-11-12T05:38"], "sunset": ["2026-11-11T18:36", "2026-11-12T18:37"]},
}


# ---------------------------------------------------------------- configuração
def test_default_location_is_itumbiara():
    loc = Settings().location
    assert (loc.city, loc.state, loc.country, loc.timezone, loc.language) == ("Itumbiara", "Goiás", "Brasil", "America/Sao_Paulo", "pt-BR")


def test_ai_disabled_without_key_and_key_never_in_repr(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_settings(tmp_path / "ausente.env").ai_configured is False
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=segredo-de-teste-123\nGEMINI_MODEL=gemini-x-flash\n", encoding="utf-8")
    s = load_settings(env)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert s.ai_configured and s.gemini_model == "gemini-x-flash"
    assert "segredo-de-teste-123" not in repr(s) and s.local_token not in repr(s)


def test_env_example_has_no_credentials_and_env_is_gitignored():
    example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    line = next(l for l in example.splitlines() if l.startswith("GEMINI_API_KEY"))
    assert line.strip() == "GEMINI_API_KEY="
    ignore = (BACKEND_DIR.parent / ".gitignore").read_text(encoding="utf-8")
    assert "backend/.env" in ignore and "backend/data/" in ignore and "backend/config/permissions.json" in ignore


def test_frontend_source_never_mentions_the_api_key():
    src = BACKEND_DIR.parent / "src"
    for path in src.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in text and "generativelanguage" not in text, path


# ---------------------------------------------------------------- permissões
def test_permissions_example_loads_and_rejects_unsafe_entries(tmp_path: Path):
    example = Permissions.load(BACKEND_DIR / "config" / "permissions.example.json")
    assert "vscode" in example.apps and "programar" in example.routines and example.routines["programar"].confirm
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({
        "apps": [{"id": "ok", "command": ["notepad.exe"]}, {"id": "shell", "command": ["cmd.exe", "/c del *.* & echo"]}, {"id": "vazio", "command": []}],
        "routines": [{"id": "ruim", "steps": [{"tool": "open_app", "args": {}}, {"tool": "run_shell", "args": {}}]}],
    }), encoding="utf-8")
    p = Permissions.load(bad)
    assert list(p.apps) == ["ok"] and p.routines == {}
    assert Permissions.load(tmp_path / "nao-existe.json").apps == {}


def test_local_auth_checks_host_origin_and_token():
    auth = LocalAuth("tok", ("http://127.0.0.1:5173",), 8765)
    assert auth.host_ok("127.0.0.1:8765") and auth.host_ok("127.0.0.1:5173") and not auth.host_ok("evil.example:8765") and not auth.host_ok(None)
    assert auth.origin_ok("http://127.0.0.1:5173", required=True) and not auth.origin_ok("https://evil.example", required=False)
    assert auth.origin_ok(None, required=False) and not auth.origin_ok(None, required=True)
    assert auth.token_ok("tok") and not auth.token_ok("tok2") and not auth.token_ok(None)


# ---------------------------------------------------------------- memória
def test_memory_store_roundtrip(tmp_path: Path):
    m = MemoryStore(tmp_path / "a" / "m.db")
    m.add_message("user", "olá", {"source": "text"})
    m.add_message("assistant", "Bom dia, senhor.")
    assert [x["role"] for x in m.recent_messages()] == ["user", "assistant"]
    fid = m.add_fact("prefere café sem açúcar")
    assert m.facts()[0]["text"] == "prefere café sem açúcar" and m.delete_fact(fid) and m.facts() == []
    m.log_action("open_app", {"app_id": "x"}, ok=True, executed=True, simulated=False, summary="aberto")
    a = m.recent_actions()[0]
    assert a["tool"] == "open_app" and a["executed"] is True and a["simulated"] is False
    m.set_setting("runtime", {"speak": False})
    assert m.get_setting("runtime") == {"speak": False} and m.get_setting("nada", 7) == 7
    m.clear_messages()
    assert m.recent_messages() == []


# ---------------------------------------------------------------- clima (Open-Meteo)
async def test_weather_parses_real_payload_and_caches():
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(request)
        return httpx.Response(200, json=OPEN_METEO)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = WeatherService(Settings().location, client=client)
        data = await svc.get()
        again = await svc.get()
    assert data["ok"] and data["source"] == "Open-Meteo" and data["city"] == "Itumbiara"
    assert data["temperature_c"] == 22.3 and data["condition"] == "Céu limpo" and data["today"]["max_c"] == 30.3
    assert data["forecast"][0]["condition"] == "Trovoadas" and "CC BY" in data["attribution"]
    assert again is data and len(hits) == 1
    q = dict(hits[0].url.params)
    assert q["latitude"] == "-18.4192" and q["longitude"] == "-49.2153" and q["timezone"] == "America/Sao_Paulo"


async def test_weather_never_invents_data_on_failure():
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(200, json=OPEN_METEO)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = WeatherService(Settings().location, client=client, ttl_s=0)
        svc.retry_delay_s = 0
        down = await svc.get()
        assert down["ok"] is False and "temperature_c" not in down and "sem conexão" in down["error"]
        state["fail"] = False
        assert (await svc.get())["ok"]
        state["fail"] = True
        stale = await svc.get()
        assert stale["ok"] and stale["stale"] is True and stale["temperature_c"] == 22.3
    off = await WeatherService(Settings().location, enabled=False).get()
    assert off["ok"] is False and "desativado" in off["error"]
    assert describe(63) == "Chuva" and describe(None) == "Sem informação"


async def test_weather_retries_transient_provider_errors():
    replies = [httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."}), httpx.Response(503), httpx.Response(200, json=OPEN_METEO)]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return replies[len(seen) - 1] if len(seen) <= 3 else httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = WeatherService(Settings().location, client=client, ttl_s=0)
        svc.retry_delay_s = 0
        assert (await svc.get())["temperature_c"] == 22.3 and len(seen) == 3
        svc._cache = None
        limited = await svc.get()
        assert limited["ok"] is False and "limite de consultas" in limited["error"] and len(seen) == 6
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400))) as client:
        bad = await WeatherService(Settings().location, client=client).get()
        assert bad["ok"] is False and "HTTP 400" in bad["error"]


# ---------------------------------------------------------------- hora local
def test_local_time_uses_city_timezone():
    now = local_now(Settings().location, datetime(2026, 11, 12, 3, 5, tzinfo=timezone.utc))
    assert now["time"] == "00:05" and now["utc_offset"] == "UTC-3" and now["part_of_day"] == "madrugada"
    assert now["date"] == "quinta-feira, 12 de novembro de 2026" and now["city"] == "Itumbiara"
    assert local_now(Settings().location, datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc))["greeting"] == "Bom dia"


# ---------------------------------------------------------------- notícias
async def test_news_is_off_without_source_and_parses_feeds():
    off = await NewsService(None).get()
    assert off["ok"] is False and off["enabled"] is False and off["items"] == [] and "desligadas" in off["error"]
    rss = "<rss><channel><item><title>Obra na ponte</title><link>https://ex.org/1</link><pubDate>Thu, 12 Nov 2026</pubDate></item></channel></rss>"
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Feira</title><link href="https://ex.org/2"/><updated>2026-11-12</updated></entry></feed>'
    assert parse_feed(rss) == [{"title": "Obra na ponte", "link": "https://ex.org/1", "published": "Thu, 12 Nov 2026", "source": ""}]
    assert parse_feed(atom)[0] == {"title": "Feira", "link": "https://ex.org/2", "published": "2026-11-12", "source": ""}
    fresh = email.utils.format_datetime(datetime.now(timezone.utc) - timedelta(hours=3))
    rss_now = rss.replace("Thu, 12 Nov 2026", fresh)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=rss_now))) as client:
        data = await NewsService("https://jornal.example/rss", client=client).get()
    assert data["ok"] and data["source"] == "jornal.example" and data["items"][0]["link"] == "https://ex.org/1"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<quebrado"))) as client:
        assert (await NewsService("https://jornal.example/rss", client=client).get())["ok"] is False


# ---------------------------------------------------------------- dispositivos (simuladores)
async def test_devices_are_simulated_and_lock_never_unlocks():
    reg = DeviceRegistry()
    assert sorted(reg.ids()) == ["fechadura", "leds", "persiana", "robo"]
    assert all(d["simulated"] and d["connected"] is False for d in reg.describe())
    on = await reg.command("leds", "color", {"color": "#FF8800"})
    assert on.ok and on.simulated and on.state == {"on": True, "color": "#ff8800", "brightness": 80} and "SIMULADOR" in on.message
    assert (await reg.command("leds", "color", {"color": "vermelho"})).executed is False
    assert (await reg.command("persiana", "position", {"value": 250})).state["position"] == 100
    unlock = await reg.command("fechadura", "unlock")
    assert unlock.ok is False and unlock.executed is False and reg.get("fechadura").status()["locked"] is True and "autenticação forte" in unlock.message
    assert reg.get("fechadura").events[-1] == {**reg.get("fechadura").events[-1], "action": "unlock", "allowed": False}
    assert (await reg.command("leds", "explodir")).executed is False and (await reg.command("torradeira", "on")).ok is False
    assert DeviceRegistry(simulators=False).ids() == []


def test_robot_emergency_stop_and_watchdog():
    t = {"now": 0.0}
    robot = SimRobot(clock=lambda: t["now"])
    assert robot.command("move", {"direction": "forward", "speed": 40}).state["moving"] is True
    t["now"] = 1.0
    robot.command("heartbeat", {})
    t["now"] = 2.0
    assert robot.status()["moving"] is True
    t["now"] = 4.0  # 2 s sem heartbeat > 1,5 s
    s = robot.status()
    assert s["moving"] is False and s["stop_reason"] == "perda de comunicação"
    robot.command("move", {"direction": "left"})
    assert robot.command("emergency_stop", {}).state == {"moving": False, "direction": None, "speed": 0, "emergency": True, "stop_reason": "parada de emergência"}
    assert robot.command("move", {"direction": "forward"}).executed is False
    robot.command("reset_emergency", {})
    assert robot.command("move", {"direction": "sideways"}).executed is False
    assert robot.command("move", {"direction": "forward"}).executed is True


def test_empty_env_values_fall_back_to_defaults(tmp_path, monkeypatch):
    """O .env.example traz `JARVIS_MODELS_DIR=` vazio. No Windows isso virava Path("") = pasta atual
    e o núcleo não achava a voz Piper nem o Whisper em backend/models."""
    for name in ("JARVIS_MODELS_DIR", "JARVIS_HOST", "JARVIS_DB_PATH", "JARVIS_PERMISSIONS_FILE", "JARVIS_WHISPER_MODEL"):
        monkeypatch.setenv(name, "")
    s = load_settings(tmp_path / "ausente.env")
    assert s.models_dir == BACKEND_DIR / "models"
    assert s.host == "127.0.0.1" and s.whisper_model == "small"
    assert s.db_path == BACKEND_DIR / "data" / "jarvis.sqlite3"
    assert s.permissions_path == BACKEND_DIR / "config" / "permissions.json"


def test_permissions_file_saved_with_bom_still_loads(tmp_path):
    """Visto no Windows: permissions.json salvo pelo PowerShell 5.1 (UTF-8 com BOM) derrubava o núcleo."""
    src = (BACKEND_DIR / "config" / "permissions.example.json").read_text(encoding="utf-8")
    path = tmp_path / "permissions.json"
    path.write_bytes(b"\xef\xbb\xbf" + src.encode("utf-8"))
    assert Permissions.load(path).apps
