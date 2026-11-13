"""Servidor: autenticação local (Host, Origin, token) e conversa real pelo WebSocket."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.assistant import Assistant
from app.devices.registry import DeviceRegistry
from app.main import create_app
from app.memory.store import MemoryStore
from app.services.weather import WeatherService

from .conftest import FakeController

ORIGIN = "http://127.0.0.1:5173"
HOST = {"host": "127.0.0.1:8765"}


@pytest.fixture
def client(settings, perms):
    settings.local_token = "token-de-teste"
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(), weather=WeatherService(settings.location, enabled=False))
    with TestClient(create_app(settings, core), base_url="http://127.0.0.1:8765") as c:
        yield c


def _keys(obj) -> list[str]:
    if isinstance(obj, dict):
        return [str(k) for k in obj] + [k for v in obj.values() for k in _keys(v)]
    if isinstance(obj, list):
        return [k for v in obj for k in _keys(v)]
    return []


def auth(extra: dict | None = None) -> dict:
    return {**HOST, "x-jarvis-token": "token-de-teste", **(extra or {})}


def test_health_is_open_but_everything_else_needs_the_token(client):
    assert client.get("/api/health", headers=HOST).json()["ok"] is True
    assert client.get("/api/state", headers=HOST).status_code == 401
    assert client.get("/api/state", headers={**HOST, "x-jarvis-token": "errado"}).status_code == 401
    state = client.get("/api/state", headers=auth()).json()
    assert state["version"] == "0.5.1" and state["ai"]["configured"] is False and state["location"]["city"] == "Itumbiara"
    # o estado público não carrega o token de sessão nem qualquer valor de chave
    assert "token-de-teste" not in str(state)
    assert not any("key" in k.lower() or "token" in k.lower() for k in _keys(state))


def test_session_token_only_for_allowed_origins_and_hosts(client):
    assert client.post("/api/session", headers=HOST).status_code == 403
    assert client.post("/api/session", headers={**HOST, "origin": "https://site-malicioso.example"}).status_code == 403
    ok = client.post("/api/session", headers={**HOST, "origin": ORIGIN})
    assert ok.status_code == 200 and ok.json()["token"] == "token-de-teste" and ok.headers["access-control-allow-origin"] == ORIGIN
    assert client.get("/api/state", headers={"host": "atacante.example", "x-jarvis-token": "token-de-teste"}).status_code == 403
    assert client.get("/api/state", headers=auth({"origin": "https://site-malicioso.example"})).status_code == 403
    pre = client.options("/api/state", headers={**HOST, "origin": ORIGIN, "access-control-request-method": "GET"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == ORIGIN


def test_settings_history_and_system_endpoints(client):
    state = client.post("/api/settings", headers=auth(), json={"tts_engine": "off", "user_title": "chefe"}).json()
    assert state["runtime"]["tts_engine"] == "off" and state["runtime"]["user_title"] == "chefe"
    sysinfo = client.get("/api/system", headers=auth()).json()
    assert 0 <= sysinfo["cpu_percent"] <= 100 and sysinfo["ram_total_gb"] > 0
    assert client.get("/api/weather", headers=auth()).json()["ok"] is False
    assert client.get("/api/history", headers=auth()).json() == {"messages": []}
    assert client.get("/api/memory", headers=auth()).json() == {"enabled": False, "facts": []}
    assert client.post("/api/voice/sample", headers=auth(), json={"engine": "nenhum"}).status_code == 503


@pytest.mark.parametrize("path, headers", [
    ("/ws", {"origin": ORIGIN}),
    ("/ws?token=errado", {"origin": ORIGIN}),
    ("/ws?token=token-de-teste", {}),
    ("/ws?token=token-de-teste", {"origin": "https://site-malicioso.example"}),
])
def test_websocket_rejects_unauthenticated_clients(client, path, headers):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(path, headers={**HOST, **headers}):
            pass
    assert e.value.code == 4403


def read_until(ws, kind: str, limit: int = 60) -> list[dict]:
    seen = []
    for _ in range(limit):
        ev = ws.receive_json()
        seen.append(ev)
        if ev["type"] == kind:
            return seen
    raise AssertionError(f"evento {kind} não chegou: {[e['type'] for e in seen]}")


def test_websocket_conversation_runs_real_tools(client):
    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["state"]["ai"]["mode"] == "local"
        ws.send_json({"type": "user_text", "text": "Jarvis, como está meu computador?"})
        events = read_until(ws, "turn_end")
        kinds = [e["type"] for e in events]
        assert "transcript" in kinds and "tool" in kinds and "delta" in kinds
        tool = [e for e in events if e["type"] == "tool" and e["stage"] == "end"][0]
        assert tool["name"] == "get_system_status" and tool["executed"] is True and "CPU" in tool["summary"]
        assert "Processador em" in events[-1]["text"] and events[-1]["mode"] == "router"
        ws.send_json({"type": "user_text", "text": "abra o bloco de notas"})
        events = read_until(ws, "turn_end")
        assert [e for e in events if e["type"] == "tool" and e["stage"] == "end"][0]["executed"] is True
        ws.send_json({"type": "user_audio", "wav": "@@@não-é-base64@@@"})
        assert read_until(ws, "error")[-1]["code"] == "bad_audio"
        ws.send_json({"type": "refresh"})
        assert read_until(ws, "state")[-1]["state"]["version"] == "0.5.1"
    actions = client.get("/api/actions", headers=auth()).json()["actions"]
    assert [a["tool"] for a in actions] == ["get_system_status", "open_app"] and all(a["executed"] for a in actions)
    history = client.get("/api/history", headers=auth()).json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
