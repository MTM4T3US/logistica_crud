"""Ferramentas: validação estrita, permissões, confirmação e leituras reais do sistema."""
from __future__ import annotations

import pytest

from app.ai.tools import ToolRegistry, validate_args
from app.devices.registry import DeviceRegistry
from app.memory.store import MemoryStore
from app.security.permissions import AppEntry, Permissions
from app.services.news import NewsService
from app.services.weather import WeatherService
from app.system.monitor import SystemMonitor
from app.system.windows import UnsupportedController, WindowsController

from .conftest import FakeController, call


def make(settings, perms, controller=None, memory_on=False):
    return ToolRegistry(
        settings=settings, perms=perms, monitor=SystemMonitor(), controller=controller or FakeController(), devices=DeviceRegistry(),
        weather=WeatherService(settings.location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"),
        memory_enabled=lambda: memory_on,
    )


async def yes(_: str) -> bool:
    return True


async def no(_: str) -> bool:
    return False


async def quiet(_: dict) -> None:
    return None


def test_validate_args_is_strict():
    schema = {"type": "object", "properties": {"app_id": {"type": "string", "enum": ["a"]}, "n": {"type": "integer", "minimum": 0, "maximum": 100}, "m": {"type": "boolean"}}, "required": ["app_id"]}
    assert validate_args(schema, {"app_id": "a", "n": 5}) is None
    assert validate_args(schema, {"app_id": "a", "n": 5.0}) is None
    assert "lista autorizada" in validate_args(schema, {"app_id": "cmd.exe /c calc"})
    assert "desconhecido" in validate_args(schema, {"app_id": "a", "command": "rm -rf /"})
    assert "faltou" in validate_args(schema, {})
    assert "intervalo" in validate_args(schema, {"app_id": "a", "n": 500})
    assert "inteiro" in validate_args(schema, {"app_id": "a", "n": "5"}) and "inteiro" in validate_args(schema, {"app_id": "a", "n": True})
    assert "verdadeiro" in validate_args(schema, {"app_id": "a", "m": "sim"})
    assert validate_args(schema, "open notepad") == "os argumentos não são um objeto"


def test_catalog_only_exposes_what_is_authorized(settings, perms):
    names = set(make(settings, perms).specs())
    assert {"open_app", "open_folder", "run_routine", "set_volume", "get_system_status", "get_weather", "control_device"} <= names
    assert not {"remember", "recall_memory"} & names and not any("shell" in n or "exec" in n or "file" in n for n in names)
    empty = Permissions(volume_control=False, process_list=False)
    bare = set(make(settings, empty).specs())
    assert not {"open_app", "open_folder", "run_routine", "set_volume", "get_volume", "list_processes"} & bare
    assert {"remember", "recall_memory"} <= set(make(settings, perms, memory_on=True).specs())
    decl = {d["name"]: d for d in make(settings, perms).declarations()}
    assert decl["open_app"]["parameters"]["properties"]["app_id"]["enum"] == ["notas", "editor"]


async def test_open_app_only_from_allowlist_and_reports_execution(settings, perms):
    ctl = FakeController()
    reg = make(settings, perms, ctl)
    ok = await reg.execute(call("open_app", app_id="notas"), yes, quiet)
    assert ok.ok and ok.executed and ctl.opened == ["notas"]
    bad = await reg.execute(call("open_app", app_id="powershell"), yes, quiet)
    assert not bad.executed and "lista autorizada" in bad.summary and ctl.opened == ["notas"]
    unknown = await reg.execute(call("run_shell", command="dir"), yes, quiet)
    assert not unknown.executed and "não existe" in unknown.summary


async def test_confirmation_is_required_and_respected(settings, perms):
    ctl = FakeController()
    reg = make(settings, perms, ctl)
    asked: list[str] = []

    async def deny(text: str) -> bool:
        asked.append(text)
        return False

    denied = await reg.execute(call("open_app", app_id="editor"), deny, quiet)
    assert not denied.executed and "não autorizou" in denied.summary and ctl.opened == [] and asked == ["Abrir o aplicativo Editor?"]
    routine = await reg.execute(call("run_routine", routine_id="programar"), deny, quiet)
    assert not routine.executed and ctl.opened == []
    done = await reg.execute(call("run_routine", routine_id="programar"), yes, quiet)
    assert done.ok and done.executed and ctl.opened == ["notas", "docs"]
    assert [s["executed"] for s in done.data["steps"]] == [True, True] and "2 de 2" in done.summary


async def test_actions_fail_honestly_off_windows(settings, perms):
    reg = make(settings, perms, UnsupportedController())
    for c in (call("open_app", app_id="notas"), call("open_folder", folder_id="docs"), call("set_volume", percent=30), call("get_volume")):
        out = await reg.execute(c, yes, quiet)
        assert out.ok is False and out.executed is False and "Windows" in out.summary
    routine = await reg.execute(call("run_routine", routine_id="programar"), yes, quiet)
    assert routine.ok is False and routine.executed is False and "0 de 2" in routine.summary
    assert (await reg.execute(call("set_volume"), yes, quiet)).executed is False


def test_windows_controller_never_uses_a_shell(tmp_path):
    spawned, started = [], []
    ctl = WindowsController(spawn=spawned.append, startfile=started.append, which=lambda name: f"C:/bin/{name}" if name == "notepad.exe" else None, verify_s=0)
    assert ctl.open_app(AppEntry("n", "Notas", ("notepad.exe", "--novo"))).executed and spawned == [["C:/bin/notepad.exe", "--novo"]]
    assert ctl.open_app(AppEntry("e", "Edge", ("msedge.exe",))).executed and started == ["msedge.exe"]
    missing = ctl.open_app(AppEntry("x", "Sumido", ("sumido.exe", "arg")))
    assert missing.executed is False and "não encontrado" in missing.message
    from app.security.permissions import FolderEntry

    assert ctl.open_folder(FolderEntry("d", "Docs", str(tmp_path))).executed and started[-1] == str(tmp_path)
    assert ctl.open_folder(FolderEntry("d", "Docs", str(tmp_path / "nao-existe"))).executed is False

    def boom(_):
        raise OSError(5, "Acesso negado")

    assert WindowsController(spawn=boom, startfile=boom, which=lambda n: n, verify_s=0).open_app(AppEntry("n", "Notas", ("notepad.exe",))).executed is False


async def test_system_readings_are_real(settings, perms):
    reg = make(settings, perms)
    out = await reg.execute(call("get_system_status"), yes, quiet)
    d = out.data
    assert out.executed and 0 <= d["cpu_percent"] <= 100 and 0 < d["ram_percent"] <= 100 and d["ram_total_gb"] > 0 and d["disk_total_gb"] > 0 and d["uptime_hours"] >= 0
    procs = (await reg.execute(call("list_processes", top=3, sort_by="ram"), yes, quiet)).data["processes"]
    assert 1 <= len(procs) <= 3 and procs == sorted(procs, key=lambda r: r["ram_mb"], reverse=True) and all(p["pid"] >= 0 for p in procs)
    t = await reg.execute(call("get_local_time"), yes, quiet)
    assert t.data["city"] == "Itumbiara" and t.data["timezone"] == "America/Sao_Paulo"


async def test_unavailable_sources_are_reported_not_invented(settings, perms):
    reg = make(settings, perms)
    weather = await reg.execute(call("get_weather"), yes, quiet)
    assert weather.ok is False and weather.executed is False and "temperature_c" not in weather.data
    news = await reg.execute(call("get_news"), yes, quiet)
    assert news.ok is False and news.data == {"items": []} and "Nenhuma fonte" in news.summary


async def test_devices_flagged_simulated_and_lock_refused(settings, perms):
    reg = make(settings, perms)
    seen: list[dict] = []

    async def note(ev: dict) -> None:
        seen.append(ev)

    led = await reg.execute(call("control_device", device_id="leds", action="on"), yes, note)
    assert led.executed and led.simulated and seen[0]["type"] == "devices"
    lock = await reg.execute(call("control_device", device_id="fechadura", action="unlock"), yes, note)
    assert lock.ok is False and lock.executed is False and "RECUSADO" in lock.summary
    assert lock.for_model()["executed"] is False and lock.for_model()["simulated"] is True
    ui: list[dict] = []

    async def cap(ev: dict) -> None:
        ui.append(ev)

    m = await reg.execute(call("show_map"), yes, cap)
    assert ui == [{"type": "ui", "action": "show_map"}] and m.data == {"demo_scene": True, "real_map": False}


async def test_memory_tools_only_when_enabled(settings, perms):
    off = make(settings, perms)
    assert (await off.execute(call("remember", fact="x"), yes, quiet)).executed is False
    on = make(settings, perms, memory_on=True)
    assert (await on.execute(call("remember", fact="gosta de jazz"), yes, quiet)).executed
    assert (await on.execute(call("recall_memory"), yes, quiet)).data == {"facts": ["gosta de jazz"]}
