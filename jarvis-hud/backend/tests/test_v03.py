"""Funções novas da 0.3: LEDs ELK-BLEDDM, Windows, roteador, voz/escuta locais, cotas e rede."""
from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import pytest

from app.ai.base import AIError
from app.ai.gemini_provider import GeminiProvider, map_gemini_error
from app.ai.tools import ToolRegistry
from app.config import BACKEND_DIR, Settings
from app.devices.elk_bleddm import ElkBleddmLeds, cmd_brightness, cmd_color, cmd_power
from app.devices.registry import DeviceRegistry
from app.main import check_exposure
from app.memory.store import MemoryStore
from app.router import LocalRouter
from app.security.permissions import AppEntry, Permissions, ProjectEntry, SceneEntry
from app.services.news import NewsService
from app.services.perf import summarize_fps
from app.services.weather import WeatherService
from app.system.monitor import SystemMonitor
from app.system.win32api import SW_MAXIMIZE, SW_MINIMIZE, VK, Rect, Win32Api, Window
from app.system.windows import UnsupportedController, WindowsController
from app.voice.stt import WhisperSTT
from app.voice.tts import PiperTTS, VoiceOutput
from app.voice.wake import OpenWakeWordDetector, make_wake_detector

from .conftest import FakeController, FakeTTS, call, tone_wav
from .test_gemini_provider import quota_error


# ---------------------------------------------------------------- LEDs ELK-BLEDDM (Bluetooth)
class FakeBle:
    def __init__(self, found=None, connect_fail: int = 0, write_fail: bool = False):
        self.found = found if found is not None else [{"address": "AA:BB", "name": "ELK-BLEDDM", "rssi": -50}]
        self.connect_fail, self.write_fail = connect_fail, write_fail
        self.writes: list[bytes] = []
        self.connects = 0
        self._connected = False
        self.on_disconnect = None

    async def scan(self, prefix, timeout):
        return [d for d in self.found if d["name"].startswith(prefix)]

    async def connect(self, address, on_disconnect):
        self.connects += 1
        if self.connect_fail:
            self.connect_fail -= 1
            raise TimeoutError("sem resposta")
        self._connected, self.on_disconnect = True, on_disconnect

    async def write(self, data):
        if self.write_fail:
            raise OSError("adaptador recusou")
        self.writes.append(bytes(data))

    async def disconnect(self):
        self._connected = False

    @property
    def connected(self):
        return self._connected


def leds(ble: FakeBle, address=None):
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    clock = {"t": 100.0}
    return ElkBleddmLeds(address, transport=ble, sleep=sleep, clock=lambda: clock["t"]), slept


def test_elk_bleddm_command_bytes_match_the_reference_protocol():
    assert cmd_power(True).hex(" ") == "7e 04 04 f0 00 01 ff 00 ef" and cmd_power(False).hex(" ") == "7e 04 04 00 00 00 ff 00 ef"
    assert cmd_color(0x2B, 0x9B, 0xFF).hex(" ") == "7e 00 05 03 2b 9b ff 00 ef"
    assert cmd_brightness(15).hex(" ") == "7e 04 01 0f ff 00 ff 00 ef" and cmd_brightness(250)[3] == 100


async def test_leds_scan_connect_send_and_never_claim_confirmation():
    ble = FakeBle()
    dev, slept = leds(ble)
    res = await dev.command("color", {"color": "#2B9BFF"})
    assert res.executed and res.simulated is False and dev.address == "AA:BB" and dev.link == "conectado"
    assert ble.writes == [cmd_power(True), cmd_color(0x2B, 0x9B, 0xFF)] and 0.3 in slept       # pausa de 0,3 s entre comandos
    assert "não confirma" in res.message and res.state["confirmed"] is False and dev.sent["color"] == "#2b9bff"
    off = await dev.command("off", {})
    assert off.executed and ble.writes[-1] == cmd_power(False) and dev.describe()["simulated"] is False
    bad = await dev.command("color", {"color": "azul"})
    assert bad.executed is False and len(ble.writes) == 3


async def test_leds_controlled_reconnection_and_honest_failures():
    dev, slept = leds(FakeBle(connect_fail=2), address="AA:BB")
    res = await dev.command("on", {})
    assert res.executed and dev._ensure and slept[:2] == [1.5, 4.0]                          # 3 tentativas espaçadas
    dead, _ = leds(FakeBle(connect_fail=9), address="AA:BB")
    fail = await dead.command("on", {})
    assert fail.executed is False and dead.link == "falha" and "3 tentativas" in fail.message
    none, _ = leds(FakeBle(found=[]))
    miss = await none.command("on", {})
    assert miss.executed is False and "Nenhuma fita" in miss.message
    broken, _ = leds(FakeBle(write_fail=True), address="AA:BB")
    w = await broken.command("on", {})
    assert w.executed is False and "Falha ao enviar" in w.message
    ble = FakeBle()
    dev, _ = leds(ble, address="AA:BB")
    await dev.command("on", {})
    ble._connected = False
    ble.on_disconnect()
    assert dev.link == "desconectado" and "encerrou" in dev.last_error
    again = await dev.command("brightness", {"value": 40})
    assert again.executed and ble.connects == 2                                               # reconecta sob demanda


async def test_registry_uses_the_real_driver_and_tool_sends_scenes():
    ble = FakeBle()
    dev, _ = leds(ble, address="AA:BB")
    reg = DeviceRegistry(simulators=True, leds=dev)
    assert reg.get("leds") is dev and [d["simulated"] for d in reg.describe() if d["id"] == "leds"] == [False]
    perms = Permissions(scenes={"cinema": SceneEntry("cinema", "Modo cinema", True, "#1030ff", 15), "apagar": SceneEntry("apagar", "Apagar", False)})
    tools = ToolRegistry(settings=Settings(), perms=perms, monitor=SystemMonitor(), controller=FakeController(), devices=reg,
                         weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)

    async def yes(_):
        return True

    async def quiet(_):
        return None

    out = await tools.execute(call("set_lights", scene_id="cinema"), yes, quiet)
    assert out.executed and out.simulated is False and out.data["confirmed"] is False
    # brilho 15 % feito escurecendo a cor (só comandos validados na fita), num envio só
    assert ble.writes == [cmd_power(True), cmd_color(2, 7, 38)] and out.data["state"]["sent"]["brightness"] == 15
    await tools.execute(call("set_lights", scene_id="apagar"), yes, quiet)
    assert ble.writes[-1] == cmd_power(False)
    assert (await tools.execute(call("set_lights"), yes, quiet)).executed is False
    assert "fita REAL por Bluetooth" in tools.specs()["set_lights"].description


async def test_leds_follow_the_validated_scripts_and_emulate_brightness():
    ble = FakeBle()
    dev, slept = leds(ble, address="BE:27:53:00:BC:1B")
    await dev.command("color", {"color": "#0000ff"})
    assert slept[0] == 0.5 and ble.writes == [cmd_power(True), cmd_color(0, 0, 255)]          # espera 0,5 s após conectar
    dim = await dev.command("brightness", {"value": 50})
    assert ble.writes[-1] == cmd_color(0, 0, 128) and cmd_brightness(50) not in ble.writes     # sem o comando não validado
    assert "escurecida" in dim.message and dev.status()["brightness_mode"] == "cor"
    await dev.command("color", {"color": "#ff0000"})
    assert ble.writes[-1] == cmd_color(128, 0, 0)                                              # o brilho escolhido continua valendo
    exp_ble = FakeBle()
    exp = ElkBleddmLeds("AA:BB", transport=exp_ble, sleep=leds(exp_ble)[0]._sleep, brightness_mode="comando")
    res = await exp.command("brightness", {"value": 30})
    assert exp_ble.writes == [cmd_brightness(30)] and "não validado" in res.message


async def test_bluetooth_runs_on_its_own_thread():
    """No Windows o bleak exige MTA; o volume (comtypes) e a voz SAPI deixam a thread principal em STA."""
    import threading

    from app.devices.elk_bleddm import _BleLoop

    async def where():
        return threading.current_thread().name

    assert await _BleLoop.shared().run(where()) == "jarvis-bluetooth"


# ---------------------------------------------------------------- Windows: janelas, mídia, projetos
class FakeWin(Win32Api):
    def __init__(self):
        self.wins = [Window(1, "Documento - Bloco de Notas"), Window(2, "JARVIS OS 0.3 - Google Chrome"), Window(3, "main.py - jarvis - Visual Studio Code")]
        self.pressed, self.shown, self.moved, self.closed, self.focused = [], [], [], [], []

    def list_windows(self):
        return list(self.wins)

    def show(self, hwnd, cmd):
        self.shown.append((hwnd, cmd))
        return True

    def focus(self, hwnd):
        self.focused.append(hwnd)
        return True

    def move(self, hwnd, rect):
        self.moved.append((hwnd, rect))
        return True

    def work_area(self, hwnd):
        return Rect(0, 0, 1920, 1040)

    def post_close(self, hwnd):
        self.closed.append(hwnd)
        return True

    def press(self, *keys):
        self.pressed.append(keys)


def test_windows_controller_manages_windows_and_media_keys(tmp_path):
    win = FakeWin()
    ctl = WindowsController(spawn=lambda a: None, startfile=lambda p: None, which=lambda n: n, win=win, volume_endpoint=lambda: None)
    assert ctl.media("next").executed and win.pressed[-1] == (VK["next"],) and ctl.media("next").data["confirmed"] is False
    assert ctl.media("explodir").executed is False
    assert ctl.windows("maximize", "codigo").executed and win.shown[-1] == (3, SW_MAXIMIZE)            # apelido "código" → VS Code
    assert ctl.windows("minimize", "navegador").executed and win.shown[-1] == (2, SW_MINIMIZE)
    snap = ctl.windows("snap_left", "bloco de notas")
    assert snap.executed and win.moved[-1] == (1, Rect(0, 0, 960, 1040))
    side = ctl.windows("arrange", "chrome", "vscode")
    assert side.executed and win.moved[-2:] == [(2, Rect(0, 0, 960, 1040)), (3, Rect(960, 0, 1920, 1040))]
    assert ctl.windows("focus", "inexistente").executed is False
    assert ctl.windows("close", "bloco").executed and win.closed == [1]
    assert ctl.windows("minimize_all").executed and win.pressed[-1] == (VK["lwin"], VK["d"])
    assert ctl.step_volume(10).executed and win.pressed[-1] == (VK["volume_up"],)                  # sem pycaw: teclas de volume
    proj = ProjectEntry("jarvis", "JARVIS", str(tmp_path))
    spawned = []
    ctl2 = WindowsController(spawn=spawned.append, startfile=lambda p: None, which=lambda n: f"C:/bin/{n}", win=win)
    assert ctl2.open_project(proj, AppEntry("vscode", "VS Code", ("code",))).executed and spawned == [["C:/bin/code", str(tmp_path)]]
    assert ctl2.open_project(ProjectEntry("x", "X", str(tmp_path / "nao")), None).executed is False
    off = UnsupportedController()
    assert all(not r.executed for r in (off.media("next"), off.windows("list"), off.step_volume(5), off.open_project(proj, None)))


class ClockedWin(FakeWin):
    """Uma janela nova aparece só depois de `after` segundos."""

    def __init__(self, clock, title=None, after=1.0):
        super().__init__()
        self.clock, self.title, self.after = clock, title, after

    def list_windows(self):
        extra = [Window(9, self.title)] if self.title and self.clock["t"] >= self.after else []
        return list(self.wins) + extra


def test_open_app_only_claims_success_when_a_window_appears():
    clock = {"t": 0.0}

    def sleep(s):
        clock["t"] += s

    def ctl(win):
        return WindowsController(spawn=lambda a: None, startfile=lambda p: None, which=lambda n: n, win=win,
                                 sleep=sleep, clock=lambda: clock["t"], verify_s=6.0)

    calc = AppEntry("calculadora", "Calculadora", ("calc.exe",))
    ok = ctl(ClockedWin(clock, "Calculadora", after=1.0)).open_app(calc)
    assert ok.executed and ok.data["verified"] is True and "apareceu" in ok.message and clock["t"] >= 1.0
    clock["t"] = 0.0
    ghost = ctl(ClockedWin(clock, None)).open_app(calc)
    assert ghost.executed and ghost.data["verified"] is False and "não posso confirmar" in ghost.message and clock["t"] >= 6.0
    clock["t"] = 0.0
    again = ctl(FakeWin()).open_app(AppEntry("bloco_de_notas", "Bloco de Notas", ("notepad.exe",)))
    assert again.data["verified"] is True and again.data["new_window"] is False and "já havia" in again.message
    clock["t"] = 0.0
    edge = ctl(ClockedWin(clock, "Nova guia - Microsoft\u200b Edge", after=0.5)).open_app(AppEntry("navegador", "Navegador", ("msedge.exe",)))
    assert edge.data["verified"] is True                                                       # título com caractere invisível
    custom = AppEntry("jogo", "Meu Jogo", ("jogo.exe",), window=("Steam",))
    clock["t"] = 0.0
    assert ctl(ClockedWin(clock, "Steam", after=0.2)).open_app(custom).data["verified"] is True


def test_router_repeats_an_unverified_launch_instead_of_saying_opened():
    from app.ai.base import ToolCall, ToolOutcome
    from app.router import _report

    render = _report("{title}, aberto.")
    c = ToolCall("1", "open_app", {"app_id": "calculadora"})
    unverified = ToolOutcome(c, True, True, "Calculadora: o programa foi iniciado, mas nenhuma janela apareceu em 6 s — não posso confirmar que abriu.", data={"verified": False})
    assert render([unverified], "senhor").startswith("Calculadora: o programa foi iniciado")
    assert render([ToolOutcome(c, True, True, "ok", data={"verified": True})], "senhor") == "senhor, aberto."


async def test_closing_a_window_needs_specific_confirmation():
    win = FakeWin()
    ctl = WindowsController(spawn=lambda a: None, startfile=lambda p: None, which=lambda n: n, win=win, volume_endpoint=lambda: None)
    perms = Permissions(close_windows=True)
    tools = ToolRegistry(settings=Settings(), perms=perms, monitor=SystemMonitor(), controller=ctl, devices=DeviceRegistry(simulators=False),
                         weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)
    asked = []

    async def deny(text):
        asked.append(text)
        return False

    async def quiet(_):
        return None

    out = await tools.execute(call("window_control", action="close", query="bloco"), deny, quiet)
    assert out.executed is False and win.closed == [] and asked == ["Fechar a janela “Documento - Bloco de Notas”? Trabalho não salvo pode ser perdido."]
    without = ToolRegistry(settings=Settings(), perms=Permissions(), monitor=SystemMonitor(), controller=ctl, devices=DeviceRegistry(simulators=False),
                           weather=WeatherService(Settings().location, enabled=False), news=NewsService(None), memory=MemoryStore(":memory:"), memory_enabled=lambda: False)
    assert "close" not in without.specs()["window_control"].parameters["properties"]["action"]["enum"]   # desligado por padrão


# ---------------------------------------------------------------- roteador local
@pytest.fixture
def router():
    perms = Permissions.load(BACKEND_DIR / "config" / "permissions.example.json")
    names = {"set_lights", "run_routine", "media_control", "set_volume", "change_volume", "get_volume", "window_control", "open_project",
             "open_folder", "open_app", "get_weather", "get_local_time", "list_processes", "get_system_status", "list_devices"}
    return LocalRouter(perms, lambda: names)


@pytest.mark.parametrize("said, calls", [
    ("Jarvis, coloque os LEDs em azul.", [("set_lights", {"color": "#0050ff"})]),
    ("Jarvis, desligue as luzes.", [("set_lights", {"power": "off"})]),
    ("Jarvis, ativar modo cinema.", [("run_routine", {"routine_id": "cinema"})]),
    ("brilho das luzes em 40%", [("set_lights", {"brightness": 40})]),
    ("abra o VS Code", [("open_app", {"app_id": "vscode"})]),
    ("abre o projeto jarvis", [("open_project", {"project_id": "jarvis"})]),
    ("prepara tudo para programar", [("run_routine", {"routine_id": "programar"})]),
    ("próxima música", [("media_control", {"action": "next"})]),
    ("volume 30", [("set_volume", {"percent": 30})]),
    ("abaixa o volume", [("change_volume", {"delta": -10})]),
    ("organiza as janelas lado a lado", [("window_control", {"action": "arrange"})]),
    ("abra o navegador e coloque os leds em roxo", [("open_app", {"app_id": "navegador"}), ("set_lights", {"color": "#8000ff"})]),
    ("que horas são", [("get_local_time", {})]),
])
def test_router_recognizes_everyday_commands(router, said, calls):
    plan = router.match(said)
    assert plan is not None and [(c.name, c.args) for c in plan.calls] == calls


@pytest.mark.parametrize("said", ["por que o céu é azul?", "me conte uma piada", "abre o spotify e me explica o que é um quasar", "bom dia", "o que você acha disso?"])
def test_router_sends_conversation_to_the_ai(router, said):
    assert router.match(said) is None


def test_router_stop_and_offline_chat(router):
    assert router.match("Jarvis, pare").kind == "stop" and router.match("bom dia", allow_chat=True).kind == "chat"


# ---------------------------------------------------------------- voz e escuta locais
def test_piper_engine_and_fallback_order(tmp_path):
    (tmp_path / "piper").mkdir()
    (tmp_path / "piper" / "pt_BR-faber-medium.onnx").write_bytes(b"x")
    (tmp_path / "piper" / "pt_BR-faber-medium.onnx.json").write_text("{}")

    class FakeVoice:
        def synthesize_wav(self, text, w, syn_config=None):
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\x01\x00" * 22050)

    piper = PiperTTS(tmp_path, loader=lambda path: FakeVoice())
    assert piper.available() == (True, "") and piper.voices()[0]["id"] == "pt_BR-faber-medium"
    res = asyncio.run(piper.synthesize("Olá", speed=1.2))
    assert res.engine == "piper" and res.cloud is False and abs(res.duration_s - 1.0) < 1e-3
    assert PiperTTS(tmp_path / "vazio", loader=lambda p: None).available()[0] is False
    cloud, local = FakeTTS("gemini", cloud=True), FakeTTS("local")
    out = VoiceOutput(None, None)
    out.engines = {"gemini": cloud, "piper": piper, "local": local}
    assert out.resolve("auto") is cloud and out.fallback_for(cloud, "auto") is piper and out.fallback_for(piper, "auto") is local
    assert out.fallback_for(cloud, "gemini") is None and out.resolve("piper") is piper


def test_whisper_tries_gpu_then_falls_back_to_cpu():
    tried = []

    class FakeSeg:
        text = " Jarvis, que horas são? "

    class FakeModel:
        def transcribe(self, audio, **kw):
            assert kw["language"] == "pt" and kw["vad_filter"] is True
            return [FakeSeg()], None

    def factory(size, device, compute):
        tried.append((device, compute))
        if device == "cuda":
            raise RuntimeError("cublas64_12.dll não encontrada")
        return FakeModel()

    w = WhisperSTT("small", device="auto", factory=factory)
    res = asyncio.run(w.transcribe(tone_wav()))
    assert res.text == "Jarvis, que horas são?" and tried == [("cuda", "float16"), ("cpu", "int8")] and w.loaded_on == "cpu/int8"


def test_whisper_falls_back_to_cpu_when_gpu_loads_but_transcription_fails():
    """Visto no Windows (RTX 2050 sem CUDA Toolkit): o modelo carrega na GPU e só a transcrição
    falha com "cublas64_12.dll is not found". Deve recarregar na CPU e responder."""
    tried = []

    class FakeSeg:
        text = " volume vinte "

    class GpuModel:
        def transcribe(self, audio, **kw):
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    class CpuModel:
        def transcribe(self, audio, **kw):
            assert getattr(audio, "dtype", None) is not None   # WAV decodificado aqui, sem PyAV
            return [FakeSeg()], None

    def factory(size, device, compute):
        tried.append(device)
        return GpuModel() if device == "cuda" else CpuModel()

    w = WhisperSTT("small", device="auto", factory=factory)
    assert asyncio.run(w.transcribe(tone_wav())).text == "volume vinte"
    assert asyncio.run(w.transcribe(tone_wav())).text == "volume vinte"
    assert tried == ["cuda", "cpu"] and w.loaded_on == "cpu/int8"


SAMPLE = BACKEND_DIR / "samples" / "frase-de-ativacao.wav"


@pytest.mark.skipif(not SAMPLE.exists() or not OpenWakeWordDetector().available()[0], reason="openwakeword ou amostra real ausente")
async def test_real_openwakeword_detects_jarvis_in_natural_speech():
    det = OpenWakeWordDetector(threshold=0.5)
    hit = await det.detect(SAMPLE.read_bytes())                                   # "Jarvis, que horas são?" (voz Gemini, 24 kHz)
    miss = await det.detect((BACKEND_DIR / "samples" / "gemini-Charon.wav").read_bytes())   # frase sem a palavra
    assert hit.detected and hit.score > 0.9 and not miss.detected and miss.score < 0.1


def test_wake_detector_selection_is_always_local():
    assert make_wake_detector("off", 0.5, None, None, "jarvis") is None
    det = make_wake_detector("auto", 0.5, None, WhisperSTT(factory=lambda *a: None), "jarvis")
    assert det is not None and det.describe()["local"] is True


# ---------------------------------------------------------------- cotas, conexão e rede
def test_quota_usage_is_counted_and_limits_learned(tmp_path):
    p = GeminiProvider(Settings(gemini_api_key="x", db_path=tmp_path / "j.db"), client=object())
    p.count("gemini-3.6-flash"); p.count("gemini-3.6-flash")
    err = map_gemini_error(quota_error(True, "58754s"))
    p.note_limit("gemini-3.6-flash", err)
    rep = p.usage_report()["models"]["gemini-3.6-flash"]
    assert rep == {"today": 2, "day_limit": 20, "minute_limit": None, "exhausted": True}
    p.note_network(AIError("offline", "Sem conexão"))
    assert p.status()["connection"]["state"] == "offline"
    again = GeminiProvider(Settings(gemini_api_key="x", db_path=tmp_path / "j.db"), client=object())
    assert again.usage_report()["models"]["gemini-3.6-flash"]["today"] == 2 and again.limits["gemini-3.6-flash"]["day"] == 20


def test_network_exposure_requires_explicit_authorization(monkeypatch):
    assert check_exposure(Settings(host="127.0.0.1")) is None
    assert "JARVIS_ALLOW_LAN" in check_exposure(Settings(host="0.0.0.0"))
    monkeypatch.setenv("JARVIS_LOCAL_TOKEN", "curto")
    assert "24 caracteres" in check_exposure(Settings(host="0.0.0.0", allow_lan=True))
    monkeypatch.setenv("JARVIS_LOCAL_TOKEN", "x" * 32)
    assert "JARVIS_ALLOWED_ORIGINS" in check_exposure(Settings(host="0.0.0.0", allow_lan=True))
    assert check_exposure(Settings(host="192.168.0.10", allow_lan=True, allowed_origins=("http://192.168.0.10:8765",))) is None


def test_performance_summary():
    assert summarize_fps([60, 58, 0, None, "x", 30]) == {"avg": 49.3, "min": 30.0, "p05": 30.0, "max": 60.0, "n": 3}
    assert summarize_fps([])["avg"] is None


async def test_router_reply_never_presents_a_simulator_as_real(router):
    from app.ai.base import ToolOutcome

    plan = router.match("coloque os leds em azul")
    sim = ToolOutcome(plan.calls[0], True, True, "ok", simulated=True)
    real = ToolOutcome(plan.calls[0], True, True, "ok", simulated=False)
    assert "simulador" in plan.render([sim], "senhor") and "simulador" not in plan.render([real], "senhor")


def test_router_never_says_done_when_a_routine_only_partly_ran():
    """Visto no Windows: "ativar modo cinema" com a fita fora de alcance → 1 de 2 etapas, e o JARVIS
    dizia "Rotina executada". Tem de dizer que foi só em parte e qual etapa falhou."""
    from app.ai.base import ToolCall, ToolOutcome
    from app.router import _report

    steps = [{"tool": "set_lights", "executed": False, "message": "Não consegui conectar à fita."},
             {"tool": "set_volume", "executed": True, "message": "Volume em 35%."}]
    out = ToolOutcome(ToolCall("1", "run_routine", {"routine_id": "cinema"}), False, True, "Rotina Modo cinema: 1 de 2 etapas executadas.", data={"steps": steps})
    text = _report("Rotina “Modo cinema” executada, {title}.")([out], "senhor")
    assert "executada, senhor" not in text and "1 de 2" in text and "Não consegui conectar à fita." in text


def test_router_handles_brightness_alone_as_lights(perms):
    """Visto no Windows: "brilho em 30%" ia para o Gemini, que disse "comando enviado" sem ferramenta."""
    from app.router import LocalRouter

    r = LocalRouter(perms, lambda: {"set_lights"}, "jarvis")
    for text in ("brilho em 30%", "Jarvis, brilho 30", "coloque o brilho em trinta"):
        plan = r.match(text)
        assert plan is not None and plan.calls[0].args == {"brightness": 30}, text
    assert r.match("aumenta o brilho da tela") is None


async def test_leds_unplugged_strip_fails_within_the_connect_budget(monkeypatch):
    """Medido no Windows com a fita fora da tomada: 82 s até falhar. Agora há um prazo total
    (CONNECT_BUDGET_S = 25 s; aqui reduzido para o teste) e a mensagem é em português claro."""
    import time

    from app.devices import elk_bleddm

    monkeypatch.setattr(elk_bleddm, "CONNECT_BUDGET_S", 1.5)

    class HangingBle(FakeBle):            # o bleak procurando um aparelho que não está lá
        async def connect(self, address, on_disconnect):
            self.connects += 1
            await asyncio.sleep(60)

    class GoneBle(FakeBle):
        async def connect(self, address, on_disconnect):
            self.connects += 1
            await asyncio.sleep(0.4)
            raise type("BleakDeviceNotFoundError", (Exception,), {})("Device with address AA:BB was not found.")

    for ble in (HangingBle(), GoneBle()):
        dev = ElkBleddmLeds("AA:BB", transport=ble)
        t0 = time.monotonic()
        res = await dev.command("color", {"color": "#0000ff"})
        assert res.executed is False and time.monotonic() - t0 < 2.0, type(ble).__name__
        assert "não respondeu" in res.message and "tomada" in res.message and "Bleak" not in res.message
