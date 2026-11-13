"""0.6: o JARVIS como programa do Windows (peças puras) e as cenas da casa."""
from __future__ import annotations

from pathlib import Path

import sys

import pytest
from fastapi.testclient import TestClient

from app.assistant import Assistant
from app.desktop_app import browser_args, find_browser, is_autostart, parse_hotkey, set_autostart, startup_command
from app.devices.registry import DeviceRegistry
from app.main import create_app
from app.memory.store import MemoryStore
from app.services.weather import WeatherService

from .conftest import FakeController

ORIGIN = "http://127.0.0.1:5173"
HOST = {"host": "127.0.0.1:8765"}


# ---------------------------------------------------------------- app de bandeja
def test_hotkeys_are_parsed_for_register_hotkey():
    assert parse_hotkey("ctrl+alt+j") == (0x0002 | 0x0001 | 0x4000, ord("J"))
    assert parse_hotkey("Ctrl + Alt + Space") == (0x0002 | 0x0001 | 0x4000, 0x20)
    assert parse_hotkey("win+shift+f12") == (0x0008 | 0x0004 | 0x4000, 0x7B)
    for bad in ("j", "ctrl+alt", "ctrl+alt+ç", ""):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_hud_window_uses_edge_chrome_or_brave_in_app_mode_with_its_own_profile(tmp_path):
    env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86", "LOCALAPPDATA": r"C:\U\AppData\Local"}
    have = {r"C:\PF\Google\Chrome\Application\chrome.exe", r"C:\U\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"}
    assert find_browser(env, have.__contains__) == r"C:\PF\Google\Chrome\Application\chrome.exe"
    assert find_browser(env, {r"C:\PF86\Microsoft\Edge\Application\msedge.exe", *have}.__contains__).endswith("msedge.exe")   # Edge primeiro
    assert find_browser(env, lambda p: p == r"D:\meu\brave.exe", preferred=r"D:\meu\brave.exe") == r"D:\meu\brave.exe"
    assert find_browser(env, lambda p: False) is None
    args = browser_args("msedge.exe", "http://127.0.0.1:8765/", tmp_path / "perfil")
    assert args[1] == "--app=http://127.0.0.1:8765/" and f"--user-data-dir={tmp_path / 'perfil'}" in args
    assert "--autoplay-policy=no-user-gesture-required" in args                          # a música da entrada toca sem clique


class FakeWinreg:
    HKEY_CURRENT_USER, KEY_SET_VALUE, KEY_QUERY_VALUE, REG_SZ = 1, 2, 4, 1

    def __init__(self):
        self.values: dict[str, str] = {}

    def OpenKey(self, root, path, reserved, access):
        assert root == 1 and path.endswith(r"CurrentVersion\Run")
        return "chave"

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        del self.values[name]

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        return self.values[name], 1

    def CloseKey(self, key):
        pass


def test_start_with_windows_writes_only_the_current_users_run_key(tmp_path):
    exe = tmp_path / "python.exe"
    (tmp_path / "pythonw.exe").write_text("")
    cmd = startup_command(str(exe), Path(r"C:\JARVIS\backend\jarvis_app.pyw"))
    assert cmd == f'"{tmp_path / "pythonw.exe"}" "C:\\JARVIS\\backend\\jarvis_app.pyw" --minimizado'   # sem console, só na bandeja
    reg = FakeWinreg()
    assert is_autostart(reg) is False
    set_autostart(True, reg, cmd)
    assert reg.values["JARVIS"] == cmd and is_autostart(reg) is True
    set_autostart(False, reg)
    set_autostart(False, reg)                                                             # desligar duas vezes não quebra
    assert reg.values == {} and is_autostart(reg) is False


def test_entry_point_finds_its_own_folder():
    text = (Path(__file__).resolve().parents[1] / "jarvis_app.pyw").read_text(encoding="utf-8")
    assert "os.chdir(HERE)" in text and "from app.desktop_app import main" in text


@pytest.fixture
def client(settings, perms):
    settings.local_token = "token-de-teste"
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    with TestClient(create_app(settings, core), base_url="http://127.0.0.1:8765") as c:
        c.core = core
        yield c


def auth() -> dict:
    return {**HOST, "x-jarvis-token": "token-de-teste"}


def test_tray_shortcuts_reach_the_open_hud(client):
    assert client.post("/api/hud/talk", headers=HOST).status_code == 401                 # sem token, nada
    assert client.post("/api/hud/talk", headers=auth()).json() == {"ok": False, "hud": 0}  # nenhum HUD aberto
    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        ws.receive_json()
        assert client.post("/api/hud/talk", headers=auth()).json() == {"ok": True, "hud": 1}
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "ui":
                assert msg["action"] == "talk"
                break
        else:
            raise AssertionError("o HUD não recebeu o atalho")
        assert client.post("/api/hud/lock", headers=auth()).json()["ok"] is False          # sem rosto cadastrado não bloqueia
        from .test_v04 import ME, near

        client.core.gate.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
        assert client.post("/api/hud/lock", headers=auth()).json() == {"ok": True} and not client.core.gate.open
        assert client.post("/api/hud/talk", headers=auth()).status_code == 423              # bloqueado: falar não passa
    assert client.post("/api/hud/explodir", headers=auth()).status_code in (400, 423)


# ---------------------------------------------------------------- cenas da casa
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from app.ai.base import ToolCall  # noqa: E402
from app.router import LocalRouter  # noqa: E402
from app.security.permissions import DEFAULT_SCENES, Permissions  # noqa: E402


def load_perms(tmp_path, raw):
    f = tmp_path / "permissions.json"
    f.write_text(json.dumps(raw), encoding="utf-8")
    return Permissions.load(f)


def test_ready_made_scenes_load_can_be_replaced_and_never_unlock(tmp_path):
    p = load_perms(tmp_path, {})
    assert list(p.routines) == ["bom_dia", "cinema", "foco", "boa_noite", "saindo"]
    assert p.routines["saindo"].confirm and p.routines["bom_dia"].exact and p.routines["bom_dia"].icon == "sol"
    mine = load_perms(tmp_path, {"routines": [{"id": "cinema", "name": "Meu cinema", "steps": [{"tool": "set_volume", "args": {"percent": 10}}]}]})
    assert mine.routines["cinema"].name == "Meu cinema" and len(mine.routines) == 5
    assert load_perms(tmp_path, {"cenas_padrao": False}).routines == {}
    evil = load_perms(tmp_path, {"cenas_padrao": False, "routines": [
        {"id": "abre", "steps": [{"tool": "control_device", "args": {"device_id": "fechadura", "action": "unlock"}}]},
        {"id": "ok", "steps": [{"tool": "control_device", "args": {"device_id": "fechadura", "action": "lock"}}]}]})
    assert list(evil.routines) == ["ok"]                                                   # destrancar nunca entra numa cena
    assert all(st["tool"] != "control_device" or st["args"]["action"] in ("lock", "lockdown") for d in DEFAULT_SCENES for st in d["steps"])


@pytest.mark.parametrize("text,scene", [
    ("bom dia", "bom_dia"), ("Jarvis, bom dia", "bom_dia"), ("bom dia, senhor", "bom_dia"), ("boa noite jarvis", "boa_noite"),
    ("modo cinema", "cinema"), ("hora do filme", "cinema"), ("modo foco", "foco"), ("vamos trabalhar", "foco"),
    ("estou saindo", "saindo"), ("saindo de casa", "saindo"),
])
def test_scenes_are_triggered_by_their_phrases(tmp_path, text, scene):
    p = load_perms(tmp_path, {})
    plan = LocalRouter(p, lambda: {"run_routine", "get_local_time"}).match(text)
    assert plan is not None and plan.calls[0].args == {"routine_id": scene}


def test_greeting_scenes_only_fire_on_the_whole_phrase(tmp_path):
    p = load_perms(tmp_path, {})
    r = LocalRouter(p, lambda: {"run_routine", "get_local_time"})
    plan = r.match("bom dia, que horas são?")
    assert plan is not None and [c.name for c in plan.calls] == ["get_local_time"]
    assert r.match("bom dia, liga a luz") is None or all(c.name != "run_routine" for c in r.match("bom dia, liga a luz").calls)


async def test_scene_skips_missing_devices_and_speaks_the_briefing(settings, tmp_path):
    from .conftest import FakeController

    settings.permissions_path = tmp_path / "permissions.json"
    settings.permissions_path.write_text("{}", encoding="utf-8")
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    asked = []

    async def yes(text):
        asked.append(text)
        return True

    async def quiet(_):
        return None

    out = await core.tools.execute(ToolCall("1", "run_routine", {"routine_id": "bom_dia"}), yes, quiet)
    steps = out.data["steps"]
    assert steps[0]["skipped"] and "não está disponível" in steps[0]["message"]                 # sem luzes Tuya neste PC
    assert steps[1]["executed"] and "SIMULADOR" in steps[1]["message"].upper()                  # fita (simulador no teste)
    assert out.data["speech"][0].startswith("Não consegui o clima de Itumbiara")                # resumo real (sem clima no teste)
    assert out.summary == "Bom dia: 2 de 2 etapas feitas (1 pulada(s): recurso ausente)." and asked == []
    plan = core.router.match("bom dia")
    text = plan.render([out], "senhor")
    assert text.startswith("Bom dia, senhor. Não consegui o clima")
    leaving = await core.tools.execute(ToolCall("2", "run_routine", {"routine_id": "saindo"}), yes, quiet)
    assert asked == ["Executar a rotina “Saindo de casa” (2 etapas)?"] and leaving.executed       # pede confirmação (conta só o que existe aqui)


async def test_scheduled_scenes_run_once_in_their_window_and_never_confirm_alone(settings, tmp_path):
    from .conftest import FakeController

    settings.permissions_path = tmp_path / "permissions.json"
    settings.permissions_path.write_text("{}", encoding="utf-8")
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    rt = core.update_runtime({"scene_schedules": {"bom_dia": {"at": "07:00", "days": "dias_uteis", "on": True},
                                                  "saindo": {"at": "07:30", "days": "todos", "on": True}}})
    assert rt["scene_schedules"]["bom_dia"]["at"] == "07:00"
    assert core.update_runtime({"scene_schedules": {"bom_dia": {"at": "25:00"}}})["scene_schedules"]["bom_dia"]["at"] == "07:00"   # inválido: ignora
    events = []

    async def capture(ev):
        events.append(ev)
        return 1

    core.broadcast = capture
    friday = datetime(2026, 11, 13, 7, 1)
    assert await core.run_scheduled_scenes(friday) == ["bom_dia"]
    assert await core.run_scheduled_scenes(friday + timedelta(minutes=1)) == []                  # uma vez por dia
    assert await core.run_scheduled_scenes(datetime(2026, 11, 14, 7, 1)) == []                   # sábado: só dias úteis
    assert await core.run_scheduled_scenes(datetime(2026, 11, 13, 7, 31)) == ["saindo"]
    assert any("pede confirmação" in e.get("text", "") for e in events if e.get("type") == "reminder")
    scenes = {s["id"]: s for s in (await core.state())["scenes"]}
    assert scenes["bom_dia"]["schedule"] == {"at": "07:00", "days": "dias_uteis", "on": True} and scenes["cinema"]["schedule"] is None


async def test_scheduled_scene_while_locked_speaks_only_the_greeting(settings, tmp_path, monkeypatch):
    import asyncio

    from .conftest import FakeController

    settings.permissions_path = tmp_path / "permissions.json"
    settings.permissions_path.write_text("{}", encoding="utf-8")
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    core.update_runtime({"scene_schedules": {"bom_dia": {"at": "07:00", "days": "todos", "on": True}}})
    spoken = []

    async def speak(conn, tid, text, mode="chat"):
        spoken.append(text)

    class Conn:
        turn = None

        async def send(self, ev):
            return None

    monkeypatch.setattr(core, "speak_text", speak)
    core.conns.add(Conn())
    monkeypatch.setattr(type(core.gate), "open", property(lambda self: False))      # rosto cadastrado, ainda não entrou
    assert await core.run_scheduled_scenes(datetime(2026, 11, 13, 7, 0)) == ["bom_dia"]
    await asyncio.sleep(0)
    assert spoken == ["Bom dia, senhor."]                                               # nada do clima, notícias ou agenda
    monkeypatch.setattr(type(core.gate), "open", property(lambda self: True))
    assert await core.run_scheduled_scenes(datetime(2026, 11, 14, 7, 0)) == ["bom_dia"]
    await asyncio.sleep(0)
    assert spoken[1].startswith("Bom dia, senhor. Não consegui o clima")


# ---------------------------------------------------------------- botões rápidos do HUD
def test_hud_buttons_run_fixed_plans_without_ai_and_never_unlock(client):
    def until_kind(ws, kind):
        for _ in range(60):
            msg = ws.receive_json()
            if msg["type"] == kind:
                return msg
        raise AssertionError(kind)

    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        st = ws.receive_json()["state"]
        assert st["quick"] == {"lights": True, "house": False, "leds": True, "door": True}   # sem Tuya: "luzes" vira a fita
        scene = st["scenes"][0]
        ws.send_json({"type": "quick", "action": f"cena:{scene['id']}"})
        shown = until_kind(ws, "transcript")
        assert shown["text"] == f"Cena: {scene['name']}" and shown["source"] == "botão"
        ask = until_kind(ws, "confirm_request")                                            # botão também pede o "sim"
        assert ask["text"].startswith(f"Executar a rotina “{scene['name']}”")
        ws.send_json({"type": "confirm", "id": ask["id"], "approve": True})
        end = until_kind(ws, "turn_end")
        assert end["mode"] == "router" and end["text"].startswith(scene["name"])
        ws.send_json({"type": "quick", "action": "luzes:off"})
        tool = until_kind(ws, "tool")
        assert tool["name"] == "control_device" and tool["args"] == {"device_id": "leds", "action": "off"}
        until_kind(ws, "turn_end")
        for bad in ("porta:unlock", "cena:nao_existe", "shell:rm", ""):
            ws.send_json({"type": "quick", "action": bad})
            assert "não está disponível" in until_kind(ws, "notice")["message"]


def test_hud_buttons_are_blocked_while_locked(client):
    core = client.core
    me = [0.1] * 1024
    core.gate.enroll([me, me, me], "4321")
    core.gate.lock()
    with client.websocket_connect("/ws?token=token-de-teste", headers={**HOST, "origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json({"type": "quick", "action": "porta:lock"})
        for _ in range(20):
            msg = ws.receive_json()
            assert msg["type"] not in ("tool", "transcript")
            if msg["type"] == "locked":
                break
        else:
            raise AssertionError("sem aviso de bloqueio")


def test_hud_turns_start_with_windows_on_and_off(client, monkeypatch):
    monkeypatch.delenv("JARVIS_HOTKEY_OPEN", raising=False)
    monkeypatch.setenv("JARVIS_HOTKEY_TALK", "ctrl+shift+f9")
    assert client.get("/api/app", headers=HOST).status_code == 401
    if sys.platform != "win32":
        info = client.get("/api/app", headers=auth()).json()
        assert info["windows"] is False and info["autostart"] is None
        assert client.post("/api/app/autostart", headers=auth(), json={"on": True}).status_code == 400
    reg = FakeWinreg()
    client.app.state.winreg = reg
    info = client.get("/api/app", headers=auth()).json()
    assert info == {"windows": True, "autostart": False, "hotkeys": {"open": "ctrl+alt+j", "talk": "ctrl+shift+f9"}, "in_app": False}
    assert client.post("/api/app/autostart", headers=auth(), json={"on": "sim"}).status_code == 400
    assert client.post("/api/app/autostart", headers=auth(), json={"on": True, "command": "calc.exe"}).json() == {"ok": True, "autostart": True}
    assert reg.values["JARVIS"].endswith('jarvis_app.pyw" --minimizado') and "calc" not in reg.values["JARVIS"]   # comando fixo
    assert client.post("/api/app/autostart", headers=auth(), json={"on": False}).json() == {"ok": True, "autostart": False}
    assert reg.values == {}


@pytest.mark.parametrize("text,args,said", [
    ("desliga o computador", {"restart": False}, "Desligando em um minuto"),
    ("desliga o PC em 10 minutos", {"restart": False, "delay_s": 600}, "Desligando em 10 minutos"),
    ("reinicia o pc daqui a 5 min", {"restart": True, "delay_s": 300}, "Reiniciando em 5 minutos"),
    ("desliga o computador em 10 segundos", {"restart": False, "delay_s": 30}, "Desligando em 30 segundos"),
    ("desliga o computador em meia hora", None, "no máximo 10 minutos"),
    ("desliga o pc em 2 horas", None, "no máximo 10 minutos"),
])
def test_spoken_shutdown_delay_is_respected_or_refused(text, args, said):
    from app.ai.base import ToolOutcome as Out

    plan = LocalRouter(Permissions(), lambda: {"shutdown_pc"}).match(text)
    assert plan is not None
    if args is None:
        assert plan.calls == [] and said in plan.render([], "senhor")                      # nunca desliga antes do pedido
    else:
        assert plan.calls[0].args == args
        assert plan.render([Out(plan.calls[0], True, True, "ok")], "senhor").startswith(said)


# ---------------------------------------------------------------- 0.6.1: entrar só pelo rosto
def test_face_entry_needs_no_blink_by_default_and_blink_is_a_hud_choice(client):
    core = client.core
    me = [0.1] * 1024
    core.gate.enroll([me, me, me], "4321")
    core.gate.lock()
    assert core.gate.liveness == "desligado" and core.runtime()["face_blink"] is False and core.runtime()["face_auto"] is False
    assert core.gate.verify([me], {"blink": False}).ok                                   # só o rosto: entra
    core.gate.lock()
    core.update_runtime({"face_blink": True, "face_auto": True})
    assert core.gate.liveness == "piscar" and core.runtime()["face_auto"] is True
    assert core.gate.verify([me], {"blink": False}).reason == "liveness"                  # religada no HUD: pede piscada
    assert core.gate.verify([me], {"blink": True}).ok
    core.update_runtime({"face_blink": "sim"})                                             # valor inválido: ignora
    assert core.gate.liveness == "piscar"
    core.update_runtime({"face_blink": False})
    assert core.gate.status()["liveness"] == "desligado"
