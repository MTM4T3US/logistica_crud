"""0.5: controle amplo do computador (com dublês do Windows)."""
from __future__ import annotations

import json
import subprocess
import zlib
from pathlib import Path

import pytest

from app.ai.base import ToolCall
from app.ai.pc_tools import PcTools
from app.ai.tools import ToolRegistry
from app.config import Settings
from app.devices.registry import DeviceRegistry
from app.memory.store import MemoryStore
from app.router import LocalRouter
from app.security.permissions import Permissions
from app.services.news import NewsService
from app.services.weather import WeatherService
from app.system.desktop import Desktop
from app.system.monitor import SystemMonitor
from app.system.screen_input import ScreenInput, Shot, encode_png, guard, is_terminal, normalize_combo
from app.system.win32api import Window

from .conftest import FakeController

START_APPS = [{"Name": "Calculadora", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
              {"Name": "Word", "AppID": "Microsoft.Office.WINWORD.EXE.15"},
              {"Name": "Spotify", "AppID": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
              {"Name": "Desinstalar Spotify", "AppID": "x"},
              {"Name": "Visual Studio Code", "AppID": "Microsoft.VisualStudioCode"}]


class Runner:
    def __init__(self, rc=0):
        self.calls: list[list[str]] = []
        self.rc = rc

    def __call__(self, argv):
        self.calls.append(argv)
        out = json.dumps(START_APPS) if "Get-StartApps" in " ".join(argv) else ""
        return subprocess.CompletedProcess(argv, self.rc, out, "")


class Win:
    def __init__(self, wins=None):
        self.wins = list(wins or [])
        self.closed = []
        self.appear = None     # janela que surge depois do pedido de abertura (2ª leitura em diante)
        self.reads = 0

    def list_windows(self):
        self.reads += 1
        if self.appear and self.reads >= 2:
            self.wins.append(self.appear)
            self.appear = None
        return list(self.wins)

    def post_close(self, hwnd):
        self.closed.append(hwnd)
        return True


def desktop(tmp_path, **kw):
    started, spawned = [], []
    d = Desktop(runner=kw.pop("runner", Runner()), startfile=started.append, home=tmp_path, win=kw.pop("win", None),
                spawn=spawned.append, sleep=lambda s: None, verify_s=0, **kw)
    return d, started, spawned


# ---------------------------------------------------------------- programas
def test_any_installed_program_is_found_by_spoken_name_and_opened_by_its_windows_id(tmp_path):
    win = Win([Window(1, "JARVIS OS 0.4 - Brave")])
    d, _, spawned = desktop(tmp_path, win=win)
    assert len(d.apps()) == 5
    assert d.find_app("a calculadora")[0].name == "Calculadora"
    assert d.find_app("vs code")[0].name == "Visual Studio Code"
    best, others = d.find_app("spotify")
    assert best.name == "Spotify" and all(o.name != "Desinstalar Spotify" for o in others)   # desinstalador nunca é escolhido
    assert d.find_app("programa que não existe")[0] is None
    win.appear, win.reads = Window(2, "Calculadora"), 0
    res = d.launch(d.find_app("calculadora")[0])
    assert spawned == [["explorer.exe", "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"]]
    assert res.executed and res.data["verified"] is True and "apareceu" in res.message
    ghost = d.launch(d.find_app("word")[0])
    assert ghost.data["verified"] is False and "não posso confirmar" in ghost.message


def test_sites_searches_and_settings_only_from_safe_inputs(tmp_path):
    d, started, _ = desktop(tmp_path)
    assert d.open_url("youtube.com").ok and started[-1] == "https://youtube.com"
    for bad in ("javascript:alert(1)", "file:///C:/Windows/System32/cmd.exe", "ftp://x.com", "ms-settings:privacy"):
        assert d.open_url(bad).ok is False
    assert d.web_search("clima em Itumbiara", "youtube").ok and started[-1].startswith("https://www.youtube.com/results?search_query=clima+em+Itumbiara")
    assert d.open_settings("Bluetooth").ok and started[-1] == "ms-settings:bluetooth"
    assert d.open_settings("ms-settings:qualquer").ok is False


def test_files_are_searched_in_personal_folders_and_programs_are_never_executed(tmp_path):
    (tmp_path / "Documents" / "faculdade").mkdir(parents=True)
    (tmp_path / "Documents" / "faculdade" / "Relatório Final.pdf").write_text("x")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "relatorio-instalador.exe").write_text("x")
    (tmp_path / "AppData" / "Local").mkdir(parents=True)
    (tmp_path / "AppData" / "Local" / "relatorio.txt").write_text("x")                 # fora das pastas pessoais
    d, started, _ = desktop(tmp_path)
    hits = d.search_files("relatorio")
    assert sorted(h.name for h in hits) == ["Relatório Final.pdf", "relatorio-instalador.exe"]
    pdf = 1 + [h.name for h in hits].index("Relatório Final.pdf")
    exe = 1 + [h.name for h in hits].index("relatorio-instalador.exe")
    assert d.open_file(pdf).executed and started[-1].endswith("Relatório Final.pdf")
    refused = d.open_file(exe)
    assert refused.executed is False and "não executo" in refused.message
    assert d.open_file(9).executed is False


def test_power_and_brightness_use_fixed_arguments(tmp_path):
    run = Runner()
    d, _, _ = desktop(tmp_path, runner=run)
    assert d.shutdown(False, 5).data["delay_s"] == 30                                     # nunca menos de 30 s para dar tempo de cancelar
    assert run.calls[-1][:4] == ["shutdown.exe", "/s", "/t", "30"]
    d.shutdown(True, 9999)
    assert run.calls[-1][:4] == ["shutdown.exe", "/r", "/t", "600"]
    assert d.cancel_shutdown().ok and run.calls[-1] == ["shutdown.exe", "/a"]
    d.set_brightness(250)
    assert "Brightness=[byte]100" in run.calls[-1][-1]


def test_closing_programs_spares_jarvis_and_never_kills_the_system(tmp_path, monkeypatch):
    win = Win([Window(1, "Spotify Premium"), Window(2, "JARVIS OS 0.4 - Spotify na barra"), Window(3, "Documento - Word")])
    d, _, _ = desktop(tmp_path, win=win)
    res = d.close_app("spotify")
    assert res.executed and win.closed == [1]
    import psutil

    class P:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}
            self.killed = False

        def terminate(self):
            self.killed = True

    procs = [P(10, "explorer.exe"), P(11, "chrome.exe"), P(12, "chrome.exe")]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: procs)
    assert d.kill_process("explorer").executed is False and not procs[0].killed
    assert d.kill_process("chrome").executed and procs[1].killed and procs[2].killed


# ---------------------------------------------------------------- tela e teclado
class FakeScreen(ScreenInput):
    def __init__(self, title="Sem título - Bloco de Notas", exe="notepad.exe"):
        self.title, self.exe = title, exe
        self.typed, self.combos = [], []

    def foreground(self):
        return self.title, self.exe

    def type_text(self, text):
        self.typed.append(text)

    def combo(self, combo):
        self.combos.append(combo)

    def capture(self, max_w=1280):
        return Shot(encode_png(2, 1, b"\xff\x00\x00\x00\xff\x00"), 2, 1, 2, 1)


def test_keyboard_guard_blocks_terminals_and_unlisted_shortcuts():
    assert normalize_combo("Control + Shift+T") == "ctrl+shift+t" and normalize_combo("win-d") == "win+d"
    assert is_terminal("Windows PowerShell", "powershell.exe") and is_terminal("Executar", "explorer.exe")
    assert is_terminal("Prompt de Comando", "") and not is_terminal("Relatório - Word", "winword.exe")
    assert guard(FakeScreen("Administrador: Windows PowerShell", "powershell.exe"), "type") is not None
    assert guard(FakeScreen(), "combo", "win+r") is not None                               # Executar: fora da lista
    assert guard(FakeScreen(), "combo", "ctrl+c") is None and guard(FakeScreen(), "type") is None
    png = encode_png(2, 1, b"\xff\x00\x00\x00\xff\x00")
    assert png.startswith(b"\x89PNG") and zlib.decompress(png[png.index(b"IDAT") + 4:-16])[:4] == b"\x00\xff\x00\x00"


def tools_with(tmp_path, screen, answers):
    d, started, _ = desktop(tmp_path, win=Win([Window(1, "Spotify")]))
    reg = ToolRegistry(settings=Settings(), perms=Permissions(), monitor=SystemMonitor(), controller=FakeController(), devices=DeviceRegistry(simulators=False),
                       weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)
    pc = PcTools(d, screen, shots_dir=tmp_path / "caps")
    reg.extensions.append(pc.specs)
    asked = []

    async def confirm(text):
        asked.append(text)
        return answers.pop(0) if answers else False

    async def quiet(_):
        return None

    async def run(tool_name, **args):
        return await reg.execute(ToolCall("1", tool_name, args), confirm, quiet)

    return reg, run, asked, d


async def test_risky_pc_actions_need_specific_confirmation(tmp_path):
    screen = FakeScreen()
    reg, run, asked, d = tools_with(tmp_path, screen, [False, True])
    assert {"launch_app", "close_app", "kill_process", "shutdown_pc", "recycle_file", "type_text", "press_keys", "take_screenshot"} <= set(reg.specs())
    assert not any(n in reg.specs() for n in ("run_command", "shell", "terminal"))
    no = await run("close_app", name="spotify")
    assert no.executed is False and "Fechar “spotify”" in asked[-1]
    yes = await run("shutdown_pc", restart=True, delay_s=60)
    assert yes.executed and "REINICIAR" in asked[-1]
    risky = await run("press_keys", keys="alt+f4")
    assert risky.executed is False and "ALT+F4" in asked[-1] and screen.combos == []
    assert (await run("press_keys", keys="ctrl+c")).executed and screen.combos == ["ctrl+c"]
    assert (await run("press_keys", keys="win+r")).executed is False
    assert (await run("type_text", text="olá, mundo")).executed and screen.typed == ["olá, mundo"]
    screen.title, screen.exe = "Windows PowerShell", "powershell.exe"
    blocked = await run("type_text", text="Remove-Item C:\\ -Recurse")
    assert blocked.executed is False and "terminal" in blocked.summary and len(screen.typed) == 1
    shot = await run("take_screenshot")
    assert shot.executed and Path(shot.data["path"]).read_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize("text,tool,args", [
    ("desliga o computador", "shutdown_pc", {"restart": False}),
    ("reinicia o pc", "shutdown_pc", {"restart": True}),
    ("cancela o desligamento", "cancel_shutdown", {}),
    ("bloqueia o computador", "lock_windows", {}),
    ("Jarvis, bloqueia o Jarvis", "lock_hud", {}),
    ("suspende o notebook", "sleep_pc", {}),
    ("brilho da tela em 60", "set_brightness", {"percent": 60}),
    ("tira um print", "take_screenshot", {}),
    ("procura o arquivo relatório final", "find_files", {"query": "relatorio final"}),
    ("abre o 2", "open_file", {"index": 2}),
    ("manda o terceiro para a lixeira", "recycle_file", {"index": 3}),
    ("abre o site youtube.com", "open_website", {"url": "youtube.com"}),
    ("pesquisa receita de pão de queijo no youtube", "web_search", {"query": "receita de pao de queijo", "site": "youtube"}),
    ("abre as configurações de bluetooth", "open_settings", {"page": "bluetooth"}),
    ("abre o spotify", "launch_app", {"name": "spotify"}),
    ("abre o word", "launch_app", {"name": "word"}),
    ("fecha o spotify", "close_app", {"name": "spotify"}),
    ("força o fechamento do chrome", "kill_process", {"name": "chrome"}),
    ("digita: bom dia a todos", "type_text", {"text": "bom dia a todos"}),
    ("copia", "press_keys", {"keys": "ctrl+c"}),
    ("abre o mapa", "show_map", {}),
])
def test_router_runs_pc_commands_locally(text, tool, args):
    names = {"shutdown_pc", "cancel_shutdown", "lock_windows", "lock_hud", "sleep_pc", "set_brightness", "take_screenshot", "find_files", "open_file",
             "recycle_file", "show_file", "open_website", "web_search", "open_settings", "launch_app", "close_app", "kill_process", "type_text",
             "press_keys", "show_map", "set_lights", "window_control", "city_briefing"}
    plan = LocalRouter(Permissions(), lambda: names).match(text)
    assert plan is not None, text
    assert [(c.name, {k: v for k, v in c.args.items() if k in args}) for c in plan.calls] == [(tool, args)]


# ---------------------------------------------------------------- modo computer use
class AgentScreen(FakeScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pos = (500, 500)
        self.clicks, self.scrolls, self.hidden, self.restored, self.shots = [], [], [], [], 0
        self.user_moves_after: int | None = None

    def cursor(self):
        if self.user_moves_after is not None and len(self.clicks) >= self.user_moves_after:
            return (self.pos[0] + 300, self.pos[1])                       # o usuário pegou o mouse
        return self.pos

    def capture(self, max_w=1280):
        self.shots += 1
        return Shot(b"\x89PNG-fake", 1280, 720, 1920, 1080)

    def click(self, x, y, button="left", double=False):
        self.pos = (x, y)
        self.clicks.append((x, y, button, double))

    def scroll(self, x, y, clicks):
        self.pos = (x, y)
        self.scrolls.append(clicks)

    def minimize_titled(self, needle):
        self.hidden.append(needle)
        return [77]

    def restore(self, handles):
        self.restored.append(handles)


def scripted(*actions):
    seen = []

    async def ask(prompt, png):
        seen.append((prompt, png))
        return actions[len(seen) - 1] if len(seen) <= len(actions) else {"action": "done", "description": "", "risk": "baixo", "thought": ""}

    return ask, seen


def act(action, risk="baixo", **kw):
    return {"thought": "...", "action": action, "description": kw.pop("description", action), "risk": risk, **kw}


async def run_agent(screen, ask, answers=(), **kw):
    from app.ai.computer_agent import ComputerAgent

    asked, events = [], []
    replies = list(answers)

    async def confirm(text):
        asked.append(text)
        return replies.pop(0) if replies else False

    async def notify(ev):
        events.append(ev)

    async def nosleep(_):
        return None

    agent = ComputerAgent(screen, ask, open_url=lambda u: type("R", (), {"message": f"abrindo {u}"})(), sleep=nosleep, **kw)
    return await agent.run("abrir o último e-mail da faculdade", confirm, notify), asked, events


async def test_agent_clicks_on_real_screen_coordinates_and_finishes():
    screen = AgentScreen()
    ask, seen = scripted(act("open_url", url="mail.google.com"), act("click", x=500, y=250, description="e-mail da faculdade"),
                         act("scroll", x=500, y=500, direction="down", amount=3), act("done", summary="Abri o e-mail da faculdade."))
    res, asked, events = await run_agent(screen, ask)
    assert res["ok"] and res["steps"] == 4 and res["message"] == "Abri o e-mail da faculdade."
    assert screen.clicks == [(960, 270, "left", False)]                        # 0-1000 → pixels da tela real (1920×1080)
    assert screen.scrolls == [-3] and asked == []
    assert screen.hidden == ["JARVIS OS"] and screen.restored == [[77]]      # o HUD sai da frente e volta
    assert seen[0][1] == b"\x89PNG-fake" and "Tarefa do dono" in seen[0][0] and "1. open_url" in seen[2][0]
    assert [e["stage"] for e in events] == ["start", "step", "step", "step", "step", "end"]


async def test_agent_asks_before_sending_and_never_types_secrets():
    screen = AgentScreen()
    ask, _ = scripted(act("click", x=100, y=100, description="botão Enviar do Gmail"))
    res, asked, _ = await run_agent(screen, ask, answers=[False])
    assert res["reason"] == "denied" and screen.clicks == [] and "Enviar" in asked[0]
    ask, _ = scripted(act("type_text", text="M1nh@Senha!", description="campo de texto"))
    res, _, _ = await run_agent(AgentScreen(), ask)
    assert res["reason"] == "need_user" and "senha" in res["message"].lower()
    ask, _ = scripted(act("press_keys", keys="alt+f4", description="fechar janela"))
    res, asked, _ = await run_agent(AgentScreen(), ask, answers=[False])
    assert res["reason"] == "denied" and "Passo 1" in asked[0]


async def test_agent_refuses_terminals_and_stops_when_the_user_takes_the_mouse():
    term = AgentScreen(title="Windows PowerShell", exe="powershell.exe")
    ask, seen = scripted(act("type_text", text="Get-ChildItem", description="digitar comando"), act("done", summary="ok"))
    res, _, _ = await run_agent(term, ask)
    assert term.typed == [] and "RECUSADO" in seen[1][0]
    screen = AgentScreen()
    screen.user_moves_after = 1
    ask, _ = scripted(act("click", x=10, y=10), act("click", x=20, y=20), act("click", x=30, y=30))
    res, _, _ = await run_agent(screen, ask)
    assert res["reason"] == "stopped" and len(screen.clicks) == 1 and "mexeu no mouse" in res["message"]


async def test_agent_respects_the_step_limit_and_ai_failures():
    ask, _ = scripted(*[act("wait", seconds=1)] * 10)
    res, _, _ = await run_agent(AgentScreen(), ask, max_steps=3)
    assert res["reason"] == "limit" and res["steps"] == 3

    async def broken(prompt, png):
        from app.ai.base import AIError
        raise AIError("rate_limit", "Cota do Gemini esgotada.")

    res, _, events = await run_agent(AgentScreen(), broken)
    assert res["reason"] == "ai" and "Cota" in res["message"] and events[-1]["stage"] == "end"


async def test_gemini_asker_sends_one_screenshot_with_a_strict_json_schema():
    from app.ai.computer_agent import SCHEMA, gemini_asker

    calls = []

    class Models:
        async def generate_content(self, model, contents, config):
            calls.append((model, contents, config))
            return type("R", (), {"text": json.dumps(act("done", summary="feito"))})()

    class Provider:
        client = type("C", (), {"aio": type("A", (), {"models": Models()})()})()
        counted = []

        def failover_chain(self):
            return ["gemini-x-flash"]

        def count(self, m):
            self.counted.append(m)

    prov = Provider()
    out = await gemini_asker(prov)("tarefa", b"\x89PNGdata")
    model, contents, config = calls[0]
    parts = contents[0].parts
    assert out["action"] == "done" and model == "gemini-x-flash" and prov.counted == ["gemini-x-flash"]
    assert parts[1].inline_data.mime_type == "image/png" and parts[1].inline_data.data == b"\x89PNGdata"
    assert config.response_mime_type == "application/json" and config.response_schema == SCHEMA


async def test_computer_task_tool_requires_authorization_every_time(tmp_path):
    screen = AgentScreen()
    ask, _ = scripted(act("done", summary="Pronto."))
    from app.ai.computer_agent import ComputerAgent

    d, _, _ = desktop(tmp_path)
    reg = ToolRegistry(settings=Settings(), perms=Permissions(), monitor=SystemMonitor(), controller=FakeController(), devices=DeviceRegistry(simulators=False),
                       weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)

    async def nosleep(_):
        return None

    reg.extensions.append(PcTools(d, screen, agent=lambda: ComputerAgent(screen, ask, sleep=nosleep)).specs)
    answers = [False, True]
    asked = []

    async def confirm(text):
        asked.append(text)
        return answers.pop(0)

    async def quiet(_):
        return None

    no = await reg.execute(ToolCall("1", "computer_task", {"task": "abrir o Gmail"}), confirm, quiet)
    assert no.executed is False and "Gemini (Google)" in asked[0] and screen.shots == 0
    yes = await reg.execute(ToolCall("2", "computer_task", {"task": "abrir o Gmail"}), confirm, quiet)
    assert yes.ok and "Pronto." in yes.summary and screen.shots == 1
    plan = LocalRouter(Permissions(), lambda: {"computer_task"}).match("Jarvis, usa o computador para abrir meu último e-mail")
    assert plan and plan.calls[0].name == "computer_task" and plan.calls[0].args["task"] == "abrir meu ultimo e-mail"


# ---------------------------------------------------------------- agenda pessoal
from datetime import date as _date, datetime as _dt, timedelta as _td  # noqa: E402

from app.services.agenda import Agenda, parse_event  # noqa: E402

FRIDAY_10H = _dt(2026, 11, 13, 10, 0)


@pytest.mark.parametrize("phrase,title,start,all_day,repeat", [
    ("dentista amanhã às 15h", "Dentista", _dt(2026, 11, 14, 15, 0), False, ""),
    ("reunião com o João na sexta às 14h", "Reunião com o João", _dt(2026, 11, 13, 14, 0), False, ""),
    ("pagar a conta de luz dia 20 às 9h", "Pagar a conta de luz", _dt(2026, 11, 20, 9, 0), False, ""),
    ("aniversário da Mãe dia 20/11", "Aniversário da Mãe", _dt(2026, 11, 20), True, ""),
    ("academia toda segunda às 8h", "Academia", _dt(2026, 11, 16, 8, 0), False, "semanal"),
    ("tomar remédio todos os dias às 22h", "Tomar remédio", _dt(2026, 11, 13, 22, 0), False, "diario"),
    ("buscar as crianças às 5 da tarde", "Buscar as crianças", _dt(2026, 11, 13, 17, 0), False, ""),
    ("almoço com a Ana meio-dia", "Almoço com a Ana", _dt(2026, 11, 13, 12, 0), False, ""),
    ("prova de Cálculo 2 de dezembro às 19h30", "Prova de Cálculo", _dt(2026, 12, 2, 19, 30), False, ""),
    ("café às 9h", "Café", _dt(2026, 11, 14, 9, 0), False, ""),                       # 9h já passou hoje → amanhã
])
def test_agenda_understands_portuguese_phrases(phrase, title, start, all_day, repeat):
    ev = parse_event(phrase, FRIDAY_10H)
    assert (ev["title"], ev["start"], ev["all_day"], ev["repeat"]) == (title, start, all_day, repeat)


def test_agenda_without_a_date_or_time_is_not_an_event():
    assert parse_event("ligar pro banco", FRIDAY_10H) is None and parse_event("que meu carro é prata", FRIDAY_10H) is None


def test_agenda_repeats_today_list_and_reminders_once():
    clock = {"now": FRIDAY_10H}
    a = Agenda(":memory:", clock=lambda: clock["now"])
    a.add("Academia", _dt(2026, 11, 16, 8, 0), repeat="semanal")
    a.add("Remédio", _dt(2026, 11, 13, 22, 0), repeat="diario", remind_min=10)
    a.add("Dentista", _dt(2026, 11, 13, 15, 0), remind_min=15)
    a.add("Reunião antiga", _dt(2026, 11, 13, 8, 0))
    week = a.occurrences(_date(2026, 11, 13), _date(2026, 11, 23))
    assert [e["start"].date() for e in week if e["title"] == "Academia"] == [_date(2026, 11, 16), _date(2026, 11, 23)]
    assert len([e for e in week if e["title"] == "Remédio"]) == 11
    assert [e["title"] for e in a.today(remaining=True)] == ["Dentista", "Remédio"]           # a das 8h já passou
    assert a.say_day(a.today(remaining=True)) == "Hoje você tem 2 compromissos: Dentista às 15 horas e Remédio às 22 horas."
    assert a.say_day([]) == "Sua agenda de hoje está livre."
    clock["now"] = _dt(2026, 11, 13, 14, 46)
    due = a.due_reminders()
    assert [e["title"] for e in due] == ["Dentista"] and a.due_reminders() == []              # avisa uma vez só
    assert a.find("dentista")[0]["title"] == "Dentista" and a.find("xyz") == []


async def test_agenda_tools_add_list_and_remove_with_confirmation():
    from app.ai.agenda_tools import AgendaTools

    a = Agenda(":memory:", clock=lambda: FRIDAY_10H)
    reg = ToolRegistry(settings=Settings(), perms=Permissions(), monitor=SystemMonitor(), controller=FakeController(), devices=DeviceRegistry(simulators=False),
                       weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)
    reg.extensions.append(AgendaTools(a).specs)
    answers, asked, events = [False, True], [], []

    async def confirm(text):
        asked.append(text)
        return answers.pop(0)

    async def notify(ev):
        events.append(ev)

    async def run(tool, **args):
        return await reg.execute(ToolCall("1", tool, args), confirm, notify)

    added = await run("agenda_add", phrase="dentista amanhã às 15h")
    assert added.executed and added.summary == "Marcado: Dentista, amanhã às 15 horas." and events[-1]["type"] == "agenda"
    assert (await run("agenda_add", title="Reunião", date="2026-11-13", time="08:00")).summary == "Essa data e hora já passaram."
    assert (await run("agenda_add", phrase="ligar pro banco")).executed is False
    assert (await run("agenda_list", day="amanha")).summary == "Amanhã você tem 1 compromisso: Dentista às 15 horas."
    assert (await run("agenda_remove", query="dentista")).executed is False and "Desmarcar “Dentista, amanhã às 15 horas”" in asked[0]
    assert (await run("agenda_remove", query="dentista")).summary == "Desmarcado: Dentista." and a.all() == []


@pytest.mark.parametrize("text,tool,args", [
    ("marca dentista amanhã às 15h", "agenda_add", {"phrase": "dentista amanhã às 15h"}),
    ("me lembra de pagar a conta dia 20 às 9h", "agenda_add", {"phrase": "pagar a conta dia 20 às 9h"}),
    ("o que eu tenho hoje", "agenda_list", {"day": "hoje"}),
    ("minha agenda de amanhã", "agenda_list", {"day": "amanha"}),
    ("meus compromissos da semana", "agenda_list", {"days": 7}),
    ("desmarca o dentista", "agenda_remove", {"query": "dentista"}),
])
def test_router_handles_the_agenda_locally(text, tool, args):
    names = {"agenda_add", "agenda_list", "agenda_remove", "cancel_shutdown", "set_lights"}
    plan = LocalRouter(Permissions(), lambda: names).match(text)
    assert plan is not None and [(c.name, c.args) for c in plan.calls] == [(tool, args)]


def test_router_leaves_non_agenda_reminders_to_the_ai():
    names = {"agenda_add", "agenda_list", "agenda_remove", "cancel_shutdown"}
    assert LocalRouter(Permissions(), lambda: names).match("lembra que meu carro é prata") is None
    assert LocalRouter(Permissions(), lambda: names).match("cancela o desligamento").calls[0].name == "cancel_shutdown"


def test_welcome_mentions_todays_appointments_and_locked_state_hides_the_agenda(settings, perms):
    import asyncio

    from app.assistant import Assistant

    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    later = core.agenda.now() + _td(hours=2)
    core.agenda.add("Dentista", later.replace(second=0, microsecond=0))
    b = asyncio.run(core.briefing())
    assert "Bem-vindo de volta" in b["welcome"] and "você tem 1 compromisso: Dentista às" in b["welcome"] and b["agenda"][0]["title"] == "Dentista"
    state = asyncio.run(core.state())
    assert state["agenda"]["today"][0]["title"] == "Dentista"
    from .test_v04 import ME, near

    core.gate.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
    core.gate.lock()
    assert asyncio.run(core.state())["agenda"] is None                                      # bloqueado: nada da agenda sai do núcleo


def test_agenda_api_for_the_settings_panel(settings, perms):
    from fastapi.testclient import TestClient

    from app.assistant import Assistant
    from app.main import create_app

    settings.local_token = "token-de-teste"
    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    h = {"host": "127.0.0.1:8765", "x-jarvis-token": "token-de-teste"}
    with TestClient(create_app(settings, core), base_url="http://127.0.0.1:8765") as c:
        tomorrow = (core.agenda.now() + _td(days=1)).date().isoformat()
        r = c.post("/api/agenda", headers=h, json={"title": "Prova", "date": tomorrow, "time": "19:30", "repeat": ""})
        assert r.status_code == 200 and r.json()["message"].startswith("Marcado: Prova, amanhã às 19 horas e 30")
        assert c.post("/api/agenda", headers=h, json={"title": "Sem data", "date": "ontem"}).status_code == 400
        listed = c.get("/api/agenda", headers=h).json()
        assert [e["title"] for e in listed["events"]] == ["Prova"]
        assert c.delete(f"/api/agenda/{listed['all'][0]['id']}", headers=h).json()["ok"] and c.get("/api/agenda", headers=h).json()["all"] == []
        from .test_v04 import ME, near

        core.gate.enroll([ME, near(ME, 0.5), near(ME, 0.5, 3)], "4321")
        core.gate.lock()
        assert c.get("/api/agenda", headers=h).status_code == 423


# ---------------------------------------------------------------- luzes de casa (Smart Life / Tuya, rede local)
from app.ai.home_tools import HomeTools  # noqa: E402
from app.devices.tuya import TuyaLight, build_lights, load_devices  # noqa: E402

WIZARD = [
    {"name": "Luz Sala", "id": "eb01", "key": "chave-secreta-1", "ip": "192.168.0.31", "version": "3.3", "category": "dj"},
    {"name": "Quarto", "id": "eb02", "key": "chave-secreta-2", "ip": "", "version": "3.4", "category": "dj"},
    {"name": "Tomada Abajur", "id": "eb03", "key": "chave-secreta-3", "ip": "192.168.0.33", "version": "3.3", "category": "cz"},
    {"name": "Câmera", "id": "eb04", "key": "k", "category": "sp"},                 # não é luz
    {"name": "Sem chave", "id": "eb05", "key": "", "category": "dj"},
]


class FakeBulb:
    def __init__(self, info, offline=False):
        self.info, self.offline, self.calls = info, offline, []

    def _r(self, name, *a):
        self.calls.append((name, *a))
        if self.offline:
            raise ConnectionError("Network Error: Device Unreachable")
        return {"dps": {"20": name != "turn_off"}}

    def turn_on(self):
        return self._r("turn_on")

    def turn_off(self):
        return self._r("turn_off")

    def set_colour(self, r, g, b):
        return self._r("set_colour", r, g, b)

    def set_brightness_percentage(self, v):
        return self._r("set_brightness_percentage", v)

    def set_white_percentage(self, v, t):
        return self._r("set_white_percentage", v, t)

    def status(self):
        return self._r("status")


def test_tuya_wizard_file_keeps_only_lights_and_switches(tmp_path):
    f = tmp_path / "devices.json"
    f.write_text(json.dumps(WIZARD), encoding="utf-8")
    infos = load_devices(f)
    assert [i["name"] for i in infos] == ["Luz Sala", "Quarto", "Tomada Abajur"]
    built = {}
    lights, note = build_lights(f, factory=lambda info: built.setdefault(info["id"], FakeBulb(info)))
    assert [d.id for d in lights] == ["luz_luz_sala", "luz_quarto", "luz_tomada_abajur"] and "3 aparelho" in note
    assert lights[2].actions == ("status", "on", "off") and "chave" not in json.dumps([d.describe() for d in lights])   # a chave nunca sai
    assert build_lights(tmp_path / "nao-existe.json")[0] == []


async def test_tuya_light_reports_confirmation_from_the_device_and_honest_failures(tmp_path):
    bulbs = {}
    sala = TuyaLight(WIZARD[0], lambda info: bulbs.setdefault("sala", FakeBulb(info)))
    res = await sala.command("color", {"color": "#0000ff"})
    assert res.executed and "confirmado pelo aparelho" in res.message and res.state["confirmed"] and bulbs["sala"].calls == [("set_colour", 0, 0, 255)]
    off = TuyaLight(WIZARD[1], lambda info: FakeBulb(info, offline=True))
    bad = await off.command("on", {})
    assert bad.executed is False and "não respondeu" in bad.message and off.status()["reachable"] is False


async def test_house_lights_all_include_the_led_strip_and_say_what_is_confirmed(tmp_path):
    reg = DeviceRegistry(simulators=True)
    for info in WIZARD[:3]:
        reg.register(TuyaLight(info, lambda i: FakeBulb(i)))
    home = HomeTools(reg)
    spec = {s.name: s for s in home.specs()}["house_lights"]
    assert "todas" in spec.parameters["properties"]["target"]["enum"]
    events = []

    async def notify(ev):
        events.append(ev)

    run = type("Run", (), {"call": ToolCall("1", "house_lights", {}), "notify": staticmethod(notify)})
    out = await home._run({"target": "todas", "power": "off"}, run)
    assert out.executed and "Luz Sala, Quarto, Tomada Abajur: feito (confirmado pelos aparelhos)" in out.summary
    assert "Fita de LED" in out.summary and events[-1]["type"] == "devices"
    room = await home._run({"target": "luz_quarto", "color": "#ff0000", "brightness": 40}, run)
    assert room.executed and room.data["confirmed"] is True


@pytest.mark.parametrize("text,args", [
    ("apaga as luzes", {"target": "todas", "power": "off"}),
    ("acende a luz da sala", {"target": "luz_luz_sala", "power": "on"}),
    ("luz do quarto em azul", {"target": "luz_quarto", "color": "#2b6bff"}),
    ("luzes a 30%", {"target": "todas", "brightness": 30}),
    ("liga o abajur", {"target": "luz_tomada_abajur", "power": "on"}),
    ("luz da sala branca", {"target": "luz_luz_sala", "white": True}),
])
def test_router_speaks_to_house_lights_by_room(text, args):
    from app.router import COLORS

    if "color" in args:
        args = {**args, "color": COLORS["azul"]}
    lights = lambda: [("luz_luz_sala", "Luz Sala"), ("luz_quarto", "Quarto"), ("luz_tomada_abajur", "Tomada Abajur")]  # noqa: E731
    plan = LocalRouter(Permissions(), lambda: {"house_lights", "set_lights"}, lights=lights).match(text)
    assert plan is not None and plan.calls[0].name == "house_lights" and plan.calls[0].args == args


def test_leds_still_go_only_to_the_strip_when_house_lights_exist():
    plan = LocalRouter(Permissions(), lambda: {"house_lights", "set_lights"}, lights=lambda: [("luz_quarto", "Quarto")]).match("coloque os leds em azul")
    assert plan.calls[0].name == "set_lights"


# ---------------------------------------------------------------- fechadura do usuário (só trancar e ver)
import httpx  # noqa: E402

from app.devices.own_lock import OwnLock, load_config, new_config, sign  # noqa: E402

SECRET = bytes(range(32))


def fake_lock(state, *, forge=False, seen=None):
    def handler(req: httpx.Request) -> httpx.Response:
        ts, nonce = req.headers["X-Jarvis-Time"], req.headers["X-Jarvis-Nonce"]
        good = sign(SECRET, f"{req.method}\n{req.url.path}\n{ts}\n{nonce}\n")
        if req.headers["X-Jarvis-Sig"] != good:
            return httpx.Response(401, text='{"error":"assinatura"}')
        if seen is not None:
            seen.append((req.method, req.url.path))
        if req.url.path == "/lock" and not state["door_open"]:
            state["locked"] = True
        body = json.dumps({**state, "event": "porta aberta" if req.url.path == "/lock" and state["door_open"] else None})
        sig = "falsa" if forge else sign(SECRET, f"RESP\n{nonce}\n{body}")
        return httpx.Response(200, text=body, headers={"X-Lock-Sig": sig})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_own_lock_locks_and_reads_with_signed_messages_only():
    seen = []
    state = {"locked": False, "door_open": False, "battery": 87}
    lock = OwnLock("http://192.168.0.50", SECRET, client=fake_lock(state, seen=seen))
    st = await lock.command("status", {})
    assert st.executed and st.message.startswith("Fechadura ABRINDO (solenoide energizado). Porta fechada.")
    ok = await lock.command("lock", {})
    assert ok.executed and "circuito confirmou" in ok.message and state["locked"] and seen == [("GET", "/status"), ("POST", "/lock")]
    no = await lock.command("unlock", {})
    assert no.executed is False and "não existe" in no.message and seen[-1] == ("POST", "/lock")      # nada foi enviado
    assert "unlock" not in lock.actions
    open_door = OwnLock("http://192.168.0.50", SECRET, client=fake_lock({"locked": False, "door_open": True, "battery": 50}))
    refused = await open_door.command("lock", {})
    assert refused.executed is False and "porta aberta" in refused.message
    forged = OwnLock("http://192.168.0.50", SECRET, client=fake_lock({"locked": True, "door_open": False, "battery": 50}, forge=True))
    bad = await forged.command("status", {})
    assert bad.executed is False and "assinada" in bad.message and forged.status()["locked"] is None   # não acredita em "trancada" forjado


def test_lock_pairing_config_and_voice_never_unlocks(tmp_path):
    cfg = new_config("http://192.168.0.50/")
    assert cfg["url"] == "http://192.168.0.50" and len(bytes.fromhex(cfg["secret"])) == 32
    (tmp_path / "fechadura.json").write_text(json.dumps(cfg))
    assert load_config(tmp_path / "fechadura.json")["url"] == "http://192.168.0.50"
    (tmp_path / "ruim.json").write_text(json.dumps({"url": "192.168.0.50", "secret": "12"}))
    assert load_config(tmp_path / "ruim.json") is None
    r = LocalRouter(Permissions(), lambda: {"control_device"})
    assert r.match("tranca a porta").calls[0].args == {"device_id": "fechadura", "action": "lock"}
    assert r.match("a porta está trancada?").calls[0].args == {"device_id": "fechadura", "action": "status"}
    unlock = r.match("Jarvis, destranca a porta")
    assert unlock.calls == [] and "não é permitido" in unlock.render([], "senhor")



# ---------------------------------------------------------------- firmware real da fechadura (C++ compilado no PC)
import shutil  # noqa: E402
import subprocess as _sp  # noqa: E402

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


@pytest.fixture(scope="module")
def firmware_bins(tmp_path_factory):
    """Compila o protocolo e o módulo JarvisLock.h + exemplo_integracao.ino com Arduino simulado (OpenSSL no lugar do mbedtls)."""
    if not shutil.which("g++") or not Path("/usr/include/openssl/hmac.h").exists():
        pytest.skip("sem g++/OpenSSL para compilar o firmware no PC")
    out = tmp_path_factory.mktemp("fw")
    test_dir = FIRMWARE / "teste_nativo"
    (out / "secrets.h").write_text('#pragma once\n#define WIFI_SSID "x"\n#define WIFI_PASS "x"\n#define JARVIS_SECRET_HEX "' + SECRET.hex() + '"\n')
    flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", f"-I{test_dir / 'stubs'}", f"-I{out}", f"-I{FIRMWARE / 'fechadura_jarvis'}"]
    for name in ("teste_protocolo", "teste_modulo"):
        r = _sp.run(["g++", *flags, "-x", "c++", "-o", str(out / name), str(test_dir / f"{name}.cpp"), "-lcrypto"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    return out


def test_firmware_protocol_matches_the_python_side(firmware_bins):
    ts, now = "1763000000", 1763000005
    nonce = "a" * 24
    good = sign(SECRET, f"POST\n/lock\n{ts}\n{nonce}\n")
    lines = [f"init\t{SECRET.hex()}",
             "\t".join(["check", "POST", "/lock", ts, nonce, "-", good, str(now)]),               # válido
             "\t".join(["check", "POST", "/lock", ts, nonce, "-", good, str(now)]),               # mesmo nonce de novo
             "\t".join(["check", "POST", "/lock", ts, "b" * 24, "-", sign(SECRET, f"POST\n/lock\n{ts}\n{'b' * 24}\n"), str(now + 40)]),
             "\t".join(["check", "POST", "/lock", ts, "c" * 24, "-", "0" * 64, str(now)]),
             "\t".join(["check", "GET", "/status", ts, "d" * 24, "-", sign(SECRET, f"GET\n/status\n{ts}\n{'d' * 24}\n"), "0"]),
             f"resp\t{nonce}\t{{\"locked\":true}}", "init\tcurto"]
    r = _sp.run([str(firmware_bins / "teste_protocolo")], input="\n".join(lines) + "\n", capture_output=True, text=True)
    assert r.stdout.split("\n")[:8] == ["ok", "ok", "pedido repetido", "horario fora da janela", "assinatura invalida", "fechadura sem hora (NTP)",
                                         sign(SECRET, f"RESP\n{nonce}\n" + '{"locked":true}'), "segredo invalido"]


class FirmwareProcess:
    """O módulo compilado rodando como processo; o JARVIS conversa com ele por um transporte httpx."""

    def __init__(self, binary):
        self.p = _sp.Popen([str(binary)], stdin=_sp.PIPE, stdout=_sp.PIPE, text=True, bufsize=1)
        self.now = 1763000000

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return self.p.stdout.readline().rstrip("\n")

    def transport(self):
        def handler(req: httpx.Request) -> httpx.Response:
            out = self.cmd("\t".join(["req", req.method, req.url.path, req.headers["X-Jarvis-Time"], req.headers["X-Jarvis-Nonce"],
                                      req.headers["X-Jarvis-Sig"], str(self.now)]))
            code, sig, body = out.split("\t", 2)
            return httpx.Response(int(code), text=body, headers={"X-Lock-Sig": sig} if sig else {})

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


async def test_jarvis_talks_to_the_real_firmware_module_end_to_end(firmware_bins):
    fw = FirmwareProcess(firmware_bins / "teste_modulo")
    try:
        lock = OwnLock("http://192.168.0.50:8080", SECRET, client=fw.transport(), clock=lambda: fw.now)
        st = await lock.command("status", {})
        assert st.executed and "Fechadura travada" in st.message and "Sem sensor de porta" in st.message
        assert fw.cmd("abrir\tapp") == "solenoide=1"                                         # o app abre (caminho do TCC)
        cut = await lock.command("lock", {})
        assert cut.executed and "circuito confirmou" in cut.message and lock.events[0]["src"] == "jarvis" and lock.events[1]["src"] == "app"
        down = await lock.command("lockdown", {})
        assert down.executed and "Modo trancado ligado" in down.message and lock.status()["lockdown"] is True
        assert fw.cmd("abrir\tapp") == "solenoide=0"                                         # modo trancado: app não abre
        assert fw.cmd("abrir\trosto") == "solenoide=0"
        assert fw.cmd("abrir\tteclado") == "solenoide=1"                                     # teclado continua abrindo
        assert fw.cmd("passa\t3100") == "solenoide=0"                                        # e trava sozinho depois de 3 s
        for _ in range(3):
            fw.cmd("errado")
        st = await lock.command("status", {})
        assert "3 código(s) errado(s)" in st.message and lock.events[0] == {"t": fw.now, "src": "teclado", "ok": False}
        assert fw.cmd("mestre") == "ok"
        assert (await lock.command("status", {})).state["lockdown"] is False                  # só o teclado desliga o modo
        assert fw.cmd("\t".join(["req", "POST", "/unlock", "1", "x" * 24, "0" * 64, str(fw.now)])).startswith("404")   # não existe destrancar
        fw.now += 120                                                                        # relógio do PC adiantado 2 min
        late = OwnLock("http://192.168.0.50:8080", SECRET, client=fw.transport(), clock=lambda: fw.now - 120)
        assert (await late.command("status", {})).executed is False
        wrong = OwnLock("http://192.168.0.50:8080", bytes(32), client=fw.transport(), clock=lambda: fw.now)
        assert (await wrong.command("lock", {})).executed is False                           # segredo errado: recusado
    finally:
        fw.close()


def test_lockdown_voice_command():
    r = LocalRouter(Permissions(), lambda: {"control_device"})
    for text in ("ativa o modo trancado", "ninguém entra hoje", "bloqueia a fechadura"):
        assert r.match(text).calls[0].args == {"device_id": "fechadura", "action": "lockdown"}, text


async def test_lock_events_become_hud_alerts(firmware_bins, settings, perms):
    from app.assistant import Assistant

    core = Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None)
    fw = FirmwareProcess(firmware_bins / "teste_modulo")
    try:
        fw.now = int(_dt.now().timestamp())
        core.devices.register(OwnLock("http://192.168.0.50:8080", SECRET, client=fw.transport(), clock=lambda: fw.now))
        fw.cmd("abrir\tteclado")
        assert await core.check_lock() == []                                   # 1ª leitura: não repete o histórico
        fw.now += 1
        fw.cmd("passa\t3100")
        fw.cmd("abrir\tapp")
        notes = await core.check_lock()
        assert len(notes) == 1 and notes[0].startswith("Porta aberta pelo app às")
        for _ in range(3):
            fw.cmd("errado")
        assert await core.check_lock() == ["Atenção: 3 códigos errados seguidos no teclado da fechadura."]
        assert await core.check_lock() == []                                   # não repete o mesmo alerta
    finally:
        fw.close()


@pytest.mark.parametrize("text,tool", [
    ("brilho em 30%", "set_lights"),                      # correção do teste no Windows: brilho sozinho = luzes
    ("brilho da tela em 60", "set_brightness"),
    ("brilho do notebook em 60", "set_brightness"),       # 0.5: tela do notebook, não os LEDs
])
def test_brightness_goes_to_the_right_place_after_the_windows_merge(text, tool):
    plan = LocalRouter(Permissions(), lambda: {"set_lights", "set_brightness"}).match(text)
    assert plan is not None and plan.calls[0].name == tool


async def test_leds_bluetooth_radio_off_gives_clear_message_without_retries():
    """Visto no Windows (0.5.2): com o Bluetooth desligado, 3 tentativas e a mensagem
    "BleakBluetoothNotAvailableError: ('Bluetooth radio is not powered on…')"."""
    from app.devices.elk_bleddm import ElkBleddmLeds

    class RadioOff:
        connects = 0

        async def connect(self, address, on_disconnect):
            self.connects += 1
            raise type("BleakBluetoothNotAvailableError", (Exception,), {})("Bluetooth radio is not powered on. Turn on Bluetooth and try again.")

        @property
        def connected(self):
            return False

    async def nosleep(_s):
        return None

    ble = RadioOff()
    res = await ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep).command("color", {"color": "#0000ff"})
    assert res.executed is False and ble.connects == 1
    assert "Bluetooth do Windows está desligado" in res.message and "Bleak" not in res.message


def test_router_launch_reply_uses_the_real_program_name():
    """Visto no Windows (0.5.2): "abre o Word" respondia "senhor, word aberto."."""
    from app.ai.base import ToolCall, ToolOutcome
    from app.router import _launched

    ok = ToolOutcome(ToolCall("1", "launch_app", {"name": "word"}), True, True, "Word aberto — janela “Word” apareceu.")
    assert _launched("word")([ok], "senhor") == "Word aberto, senhor."
    fail = ToolOutcome(ToolCall("1", "launch_app", {"name": "{x}"}), False, False, "Não encontrei “{x}” no Menu Iniciar.")
    assert _launched("{x}")([fail], "senhor").startswith("Não consegui, senhor")


def test_typing_and_shortcuts_refused_in_sensitive_windows():
    """Visto no Windows (0.5.2): "digita / seleciona tudo / copia" atuou na aba ".env" do Bloco de Notas."""
    from app.system.screen_input import guard, is_sensitive

    class Si:
        def __init__(self, title, exe="notepad.exe"):
            self.t, self.e = title, exe

        def foreground(self):
            return self.t, self.e

    for title in (" .env - Bloco de notas", "*.env - Bloco de notas", "secrets.h - Arduino IDE", r"C:\pasta\.env.local - Notepad++",
                  "chave.pem - Bloco de notas", "Senhas.kdbx - KeePass", "tinytuya.json - Bloco de notas"):
        assert is_sensitive(title, "notepad.exe"), title
        assert "Recusado" in (guard(Si(title), "type") or "") and "Recusado" in (guard(Si(title), "combo", "ctrl+a") or "")
    for title in ("Sem título - Bloco de notas", "relatorio.docx - Word", "environment notes - Bloco de notas", "YouTube - Brave"):
        assert not is_sensitive(title, "notepad.exe"), title
    assert guard(Si("Sem título - Bloco de notas"), "type") is None


def test_router_types_text_with_original_case(perms):
    from app.router import LocalRouter

    r = LocalRouter(perms, lambda: {"type_text"}, "jarvis")
    plan = r.match("Jarvis, digita: teste do JARVIS")
    assert plan is not None and plan.calls[0].args == {"text": "teste do JARVIS"}



# ---------------------------------------------------------------- correções depois do teste da 0.5.2 no Windows
def test_letter_shortcuts_use_the_windows_virtual_key_of_the_capital_letter():
    """Visto no Windows: "seleciona tudo"/"copia" não copiavam. As letras iam como 0x61/0x63 (Num1/Num3)."""
    from app.system.screen_input import VK

    assert (VK["a"], VK["c"], VK["v"], VK["x"], VK["z"], VK["s"]) == (0x41, 0x43, 0x56, 0x58, 0x5A, 0x53)
    assert all(0x41 <= VK[chr(c)] <= 0x5A for c in range(ord("a"), ord("z") + 1)) and VK["0"] == 0x30


async def test_agenda_keeps_the_capitals_and_accents_the_user_said():
    from app.ai.agenda_tools import AgendaTools

    plan = LocalRouter(Permissions(), lambda: {"agenda_add"}).match("Jarvis, marca Teste de lembrete do JARVIS amanhã às 9h")
    assert plan.calls[0].args == {"phrase": "Teste de lembrete do JARVIS amanhã às 9h"}
    a = Agenda(":memory:", clock=lambda: FRIDAY_10H)
    reg = ToolRegistry(settings=Settings(), perms=Permissions(), monitor=SystemMonitor(), controller=FakeController(), devices=DeviceRegistry(simulators=False),
                       weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)
    reg.extensions.append(AgendaTools(a).specs)

    async def quiet(_):
        return None

    out = await reg.execute(plan.calls[0], quiet, quiet)
    assert out.summary == "Marcado: Teste de lembrete do JARVIS, amanhã às 9 horas." and a.all()[0]["title"] == "Teste de lembrete do JARVIS"


@pytest.mark.parametrize("text,phrase", [
    ("academia toda segunda às 8h", "academia toda segunda às 8h"),
    ("Jarvis, dentista amanhã às 15h", "dentista amanhã às 15h"),
    ("Reunião com o João sexta às 14h", "Reunião com o João sexta às 14h"),
])
def test_appointments_without_a_verb_are_understood_locally(text, phrase):
    plan = LocalRouter(Permissions(), lambda: {"agenda_add", "agenda_list", "shutdown_pc", "get_local_time"}).match(text)
    assert plan is not None and plan.calls[0].name == "agenda_add" and plan.calls[0].args == {"phrase": phrase}


@pytest.mark.parametrize("text", ["que horas são", "e amanhã às 10h?", "desliga o computador às 22h", "o que eu tenho amanhã às 9h",
                                  "aniversário da mãe dia 20/11", "volume 30", "abre o 2"])
def test_not_everything_with_a_time_becomes_an_appointment(text):
    plan = LocalRouter(Permissions(), lambda: {"agenda_add", "agenda_list", "shutdown_pc", "get_local_time", "set_volume", "open_file"}).match(text)
    assert plan is None or plan.calls[0].name != "agenda_add" or "marca" in text, text


def test_social_media_posts_are_not_headlines():
    import asyncio

    now = _dt.now(__import__("datetime").timezone.utc)
    fresh = __import__("email.utils").utils.format_datetime(now - _td(hours=2))
    rss = ("<rss><channel>" + "".join(f"<item><title>{t} - {s}</title><link>https://n/{i}</link><pubDate>{fresh}</pubDate><source>{s}</source></item>"
                                    for i, (t, s) in enumerate([("Vote no candidato X para prefeito", "Instagram"), ("Ponte reaberta", "Jornal Local"),
                                                                 ("Post da campanha", "Facebook")])) + "</channel></rss>")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=rss))) as client:
            return await NewsService("https://news.example/rss", client=client).get()

    data = asyncio.run(run())
    assert [i["title"] for i in data["items"]] == ["Ponte reaberta"]
