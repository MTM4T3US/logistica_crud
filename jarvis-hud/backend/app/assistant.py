"""Orquestrador do JARVIS Core: liga IA, ferramentas, voz, memória e o canal com o HUD."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from .ai.base import AIError, AIProvider, ToolCall, ToolOutcome
from .router import Plan, _call
from .ai.gemini_provider import GeminiProvider
from .ai.local_provider import LocalProvider
from .ai.persona import build_system_prompt
from .ai.tools import ToolRegistry
from .config import Settings
from .devices.registry import DeviceRegistry
from .memory.store import MemoryStore
from .security.permissions import Permissions
from .services.local_info import local_now
from .services.briefing import compose as compose_briefing
from .services.citymap import CityMap
from .ai.pc_tools import PcTools
from .ai.agenda_tools import AgendaTools
from .ai.home_tools import HomeTools
from .devices.tuya import build_lights
from .devices.own_lock import OwnLock, load_config as load_lock_config
from .services.agenda import Agenda
from .ai.computer_agent import ComputerAgent, gemini_asker
from .system.windows import ActionResult
from .system.desktop import Desktop
from .system.screen_input import ScreenInput, get_screen_input
from .services.news import NewsService, default_feeds
from .security.face_gate import FaceGate
from .services.weather import WeatherService
from .system.monitor import SystemMonitor
from .system.windows import SystemController, get_controller
from .voice.audio_stream import SentenceChunker, normalize_for_speech, speakable, wav_info, wav_rms
from .voice.stt import GeminiSTT, STTError, VoiceInput, WhisperSTT, extract_wake_command
from .voice.wake import WakeDetector, make_wake_detector
from .router import LocalRouter

#: frases de quem diz que EXECUTOU algo (aparelho, volume, janela, app) — só valem com ferramenta
_ACTION_CLAIM = re.compile(
    r"\b(comando (foi )?enviado|enviad[oa]s? (as|às) luzes|luzes (ligadas|desligadas|acesas|apagadas)|"
    r"volume (ajustado|em \d+)|brilho (ajustado|em \d+)|(aberto|aberta|fechad[oa]|minimizad[oa]|maximizad[oa]), senhor|"
    r"rotina .{0,40} executada|mudo ativado)\b", re.IGNORECASE)


def claims_action(text: str) -> bool:
    return bool(_ACTION_CLAIM.search(text or ""))
from .voice.tts import STYLES, GeminiTTS, LocalTTS, PiperTTS, TTSEngine, TTSError, TTSResult, VoiceOutput

VERSION = "0.6.0"

SCENE_DAYS = {"todos": range(7), "dias_uteis": range(5), "fim_de_semana": (5, 6)}
MAX_TOOL_ROUNDS = 6
CONFIRM_TIMEOUT_S = 45.0
MAX_AUDIO_BYTES = 8 * 1024 * 1024
SAMPLE_TEXT = "Bom dia, senhor. Todos os sistemas estão operacionais. Em que posso ajudá-lo?"
#: erros de conteúdo — não adianta tentar o modo local
NO_FALLBACK = {"blocked", "empty", "bad_request", "tool_loop"}


class Connection:
    """Um HUD conectado por WebSocket."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.turn: asyncio.Task | None = None
        self._confirms: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self.closed = False
        #: depois de uma resposta, segue ouvindo sem exigir "Jarvis" até este instante (monotonic)
        self.window_until = 0.0
        self.listen: asyncio.Task | None = None

    async def send(self, event: dict[str, Any]) -> None:
        if self.closed:
            return
        try:
            async with self._lock:
                await self.ws.send_json(event)
        except Exception:
            self.closed = True

    async def confirm(self, text: str) -> bool:
        cid = uuid.uuid4().hex[:10]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._confirms[cid] = fut
        await self.send({"type": "confirm_request", "id": cid, "text": text, "timeout_s": CONFIRM_TIMEOUT_S})
        try:
            return bool(await asyncio.wait_for(fut, CONFIRM_TIMEOUT_S))
        except asyncio.TimeoutError:
            return False
        finally:
            self._confirms.pop(cid, None)
            await self.send({"type": "confirm_closed", "id": cid})

    def resolve_confirm(self, cid: str, approve: bool) -> None:
        fut = self._confirms.get(cid)
        if fut and not fut.done():
            fut.set_result(bool(approve))

    async def cancel_turn(self) -> bool:
        task, self.turn = self.turn, None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            return True
        return False


class Assistant:
    def __init__(
        self, settings: Settings, *, gemini: GeminiProvider | None = None, memory: MemoryStore | None = None,
        perms: Permissions | None = None, controller: SystemController | None = None, monitor: SystemMonitor | None = None,
        devices: DeviceRegistry | None = None, weather: WeatherService | None = None, news: NewsService | None = None,
        tts: VoiceOutput | None = None, stt: VoiceInput | None = None, wake: WakeDetector | None | bool = True,
        desktop: Desktop | None = None, screen: ScreenInput | None = None,
    ):
        self.settings = settings
        self.data_dir = settings.db_path.parent
        self.gate = FaceGate(self.data_dir / "rosto.json", settings.face_threshold, settings.face_liveness,
                             settings.face_relock_min * 60, settings.face_antispoof_min)
        loc = settings.location
        self.citymap = CityMap(self.data_dir / "mapa", loc.city, loc.latitude, loc.longitude, settings.map_radius_m, settings.overpass_url)
        self.memory = memory or MemoryStore(settings.db_path)
        self.perms = perms or Permissions.load(settings.permissions_path)
        self.controller = controller or get_controller()
        self.monitor = monitor or SystemMonitor()
        self.devices = devices or self._make_devices(settings)
        self.weather = weather or WeatherService(settings.location, enabled=settings.weather_enabled)
        self.news = news or self._make_news(settings)
        self.gemini = gemini if gemini is not None else (GeminiProvider(settings) if settings.ai_configured else None)
        self.tts = tts or VoiceOutput(GeminiTTS(self.gemini, settings.tts_voice, settings.tts_style) if self.gemini else None, LocalTTS(),
                                      PiperTTS(settings.models_dir, settings.piper_model))
        self.whisper = WhisperSTT(settings.whisper_model, settings.models_dir, settings.whisper_device, settings.whisper_compute)
        self.stt = stt or VoiceInput(GeminiSTT(self.gemini, settings.gemini_stt_model) if self.gemini else None, self.whisper)
        if wake is True:
            whisper = self.stt.engines.get("whisper") if hasattr(self.stt, "engines") else None
            self.wake = make_wake_detector(settings.wake_engine, settings.wake_threshold, settings.wake_model, whisper, settings.wake_word)
        else:
            self.wake = wake or None
        self.tools = ToolRegistry(
            settings=settings, perms=self.perms, monitor=self.monitor, controller=self.controller, devices=self.devices,
            weather=self.weather, news=self.news, memory=self.memory, memory_enabled=lambda: bool(self.runtime()["memory_enabled"]),
            briefing=self.briefing, lock=self._lock_from_tool, map_status=lambda: self.citymap.status(),
        )
        # 0.5: controle amplo do computador (só existe de fato no Windows)
        self.screen = screen if screen is not None else get_screen_input()
        self.desktop = desktop if desktop is not None else Desktop(win=getattr(self.controller, "win", None))
        self.pc_tools = PcTools(self.desktop, self.screen, lambda k: bool(self.perms.pc.get(k, False)), agent=self._computer_agent)
        self.tools.extensions.append(self.pc_tools.specs)
        # 0.5: agenda pessoal (local)
        self.agenda = Agenda(self.data_dir / "agenda.sqlite3" if str(settings.db_path) != ":memory:" else ":memory:", settings.location.timezone)
        self.tools.extensions.append(AgendaTools(self.agenda).specs)
        self.conns: set[Connection] = set()
        self._reminders: asyncio.Task | None = None
        self._lock_seen: set[str] = set()
        self._scenes_done: set[str] = set()
        self._lock_wrong = 0
        # 0.5: luzes de casa Smart Life/Tuya (rede local)
        lights, self.home_note = build_lights(settings.tuya_devices or self.data_dir / "tuya" / "devices.json")
        # 0.5: fechadura do usuário (só trancar e ver), quando pareada com scripts/parear_fechadura.py
        lock_cfg = load_lock_config(self.data_dir / "fechadura.json")
        if lock_cfg:
            self.devices.register(OwnLock(lock_cfg["url"], bytes.fromhex(lock_cfg["secret"])))
        for light in lights:
            self.devices.register(light)
        self.home = HomeTools(self.devices)
        self.tools.extensions.append(self.home.specs)
        self.router = LocalRouter(self.perms, lambda: set(self.tools.specs()), settings.wake_word,
                                  lights=lambda: [(d.id, d.name) for d in self.home.lights()])
        self.local = LocalProvider(self.router)
        self.last_ai_error: dict[str, str] | None = None
        self.last_timings: dict[str, float] | None = None
        self.led_fx = self._make_led_effects(settings)
        self._intro_task: asyncio.Task | None = None

    def _make_led_effects(self, settings: Settings):
        """Efeitos de luz só na fita REAL (JARVIS_LEDS=bluetooth); o simulador não pisca nada."""
        from .devices.elk_bleddm import ElkBleddmLeds
        from .devices.led_effects import VoiceLights, parse_effects

        dev = self.devices.get("leds")
        wanted = parse_effects(settings.led_effects)
        if not isinstance(dev, ElkBleddmLeds) or not wanted:
            return None
        return VoiceLights(dev, voice="voz" in wanted, intro="inicio" in wanted)

    def _computer_agent(self) -> ComputerAgent | None:
        if self.gemini is None or self.screen is None:
            return None

        def open_by_name(name: str) -> Any:
            app, _ = self.desktop.find_app(name)
            return self.desktop.launch(app) if app else ActionResult(False, False, f"Não encontrei “{name}”.")

        return ComputerAgent(self.screen, gemini_asker(self.gemini), open_app=open_by_name, open_url=self.desktop.open_url)

    def _lock_from_tool(self) -> bool:
        if not self.gate.active:
            return False
        self.gate.lock()
        return True

    @staticmethod
    def _make_news(settings: Settings) -> NewsService:
        if settings.news_rss_url:                       # compatibilidade com a 0.3
            return NewsService(settings.news_rss_url)
        if settings.news_feeds is not None:
            return NewsService(feeds=list(settings.news_feeds))
        return NewsService(feeds=default_feeds(settings.location.city, settings.location.state))

    @staticmethod
    def _make_devices(settings: Settings) -> DeviceRegistry:
        if settings.leds_mode == "bluetooth":
            from .devices.elk_bleddm import ElkBleddmLeds

            return DeviceRegistry(simulators=settings.devices_simulators, leds=ElkBleddmLeds(settings.led_address, settings.led_name_prefix, brightness_mode=settings.led_brightness))
        return DeviceRegistry(simulators=settings.devices_simulators, leds_off=settings.leds_mode == "off")

    async def shutdown(self) -> None:
        for task in (self._reminders, self._intro_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def startup(self) -> None:
        self._reminders = asyncio.create_task(self._reminder_loop())
        if self.led_fx is not None and self.led_fx.intro_enabled and not self.gate.active:
            # sem entrada por rosto: o efeito de abertura roda ao iniciar. Com ela, roda ao entrar (on_entry)
            self._intro_task = asyncio.create_task(self.led_fx.intro())   # em segundo plano: não atrasa o núcleo
        if self.gemini:
            await self.gemini.resolve_models()
            self._apply_models(self.runtime())

    def _apply_models(self, rt: dict[str, Any]) -> None:
        """Reaplica a escolha de modelo feita no painel (só vale se a conta lista o modelo)."""
        if self.gemini and hasattr(self.gemini, "set_models"):
            self.gemini.set_models(rt.get("chat_model") or None, rt.get("tts_model") or None)

    # ------------------------------------------------------------------ ajustes
    def runtime(self) -> dict[str, Any]:
        s = self.settings
        defaults = {
            "tts_engine": s.tts_engine, "tts_voice_gemini": s.tts_voice, "tts_voice_local": "", "tts_voice_piper": "", "tts_style": s.tts_style if s.tts_style in STYLES else "cinematografico",
            "stt_engine": s.stt_engine, "speak": True, "memory_enabled": s.memory_enabled, "cloud_audio_consent": False, "user_title": "senhor",
            "chat_model": "", "tts_model": "", "tts_speed": 1.0, "router_mode": s.router_mode if s.router_mode in ("local_first", "ai_first") else "local_first",
            "continuous_consent": False, "barge_in": True,
            "intro_enabled": True, "intro_music_volume": 0.7, "intro_voice_delay_s": 5.0,
            "scene_schedules": {},
        }
        saved = self.memory.get_setting("runtime", {}) or {}
        return {**defaults, **{k: v for k, v in saved.items() if k in defaults}}

    def update_runtime(self, patch: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime()
        rules = {
            "tts_engine": lambda v: v in {"auto", "gemini", "piper", "local", "off"},
            "stt_engine": lambda v: v in {"auto", "gemini", "whisper", "off"},
            "tts_voice_gemini": lambda v: isinstance(v, str) and 0 < len(v) <= 40 and v.replace("-", "").replace("_", "").isalnum(),
            "tts_voice_local": lambda v: isinstance(v, str) and len(v) <= 300,
            "tts_voice_piper": lambda v: isinstance(v, str) and len(v) <= 120,
            "tts_style": lambda v: v in STYLES,
            "tts_speed": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0.8 <= float(v) <= 1.3,
            "router_mode": lambda v: v in ("local_first", "ai_first"),
            "continuous_consent": lambda v: isinstance(v, bool), "barge_in": lambda v: isinstance(v, bool),
            "chat_model": lambda v: isinstance(v, str) and (v == "" or (self.gemini is not None and v in self.gemini.status().get("chat_models", []))),
            "tts_model": lambda v: isinstance(v, str) and (v == "" or (self.gemini is not None and v in self.gemini.status().get("tts_models", []))),
            "speak": lambda v: isinstance(v, bool), "memory_enabled": lambda v: isinstance(v, bool),
            "cloud_audio_consent": lambda v: isinstance(v, bool),
            "user_title": lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 24,
            "intro_enabled": lambda v: isinstance(v, bool),
            "scene_schedules": lambda v: isinstance(v, dict) and len(v) <= 20 and all(
                isinstance(k, str) and isinstance(x, dict) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(x.get("at", "")))
                and x.get("days", "todos") in SCENE_DAYS and isinstance(x.get("on", True), bool) for k, x in v.items()),
            "intro_music_volume": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= float(v) <= 1,
            "intro_voice_delay_s": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= float(v) <= 30,
        }
        for key, value in patch.items():
            if key in rules and rules[key](value):
                rt[key] = value.strip() if key == "user_title" else round(float(value), 2) if key in ("tts_speed", "intro_music_volume", "intro_voice_delay_s") else value
        self.memory.set_setting("runtime", rt)
        if "chat_model" in patch or "tts_model" in patch:
            self._apply_models(rt)
        return rt

    def _voice_for(self, engine: TTSEngine, rt: dict[str, Any]) -> str | None:
        if engine.id == "gemini":
            return rt["tts_voice_gemini"] or None
        if engine.id == "piper":
            return rt.get("tts_voice_piper") or None
        return rt["tts_voice_local"] or None

    # ------------------------------------------------------------------ estado para o HUD
    def ai_status(self) -> dict[str, Any]:
        if self.gemini:
            st = self.gemini.status()
            st.update(configured=True, mode="ai", last_error=self.last_ai_error or ({"code": st["last_error"]} if st["last_error"] else None))
            return st
        return {"configured": False, "mode": "local", "provider": "local", "model": self.local.model, "cloud": False, "note": "Defina GEMINI_API_KEY em backend/.env para ativar a IA.", "last_error": None}

    async def state(self) -> dict[str, Any]:
        rt = self.runtime()
        tts_engine = self.tts.resolve(rt["tts_engine"])
        stt_engine = self.stt.resolve(rt["stt_engine"])
        loc = self.settings.location
        return {
            "version": VERSION,
            "ai": self.ai_status(),
            "timings": self.last_timings,
            "location": {"city": loc.city, "state": loc.state, "state_code": loc.state_code, "country": loc.country, "timezone": loc.timezone, "language": loc.language, "latitude": loc.latitude, "longitude": loc.longitude},
            "runtime": rt,
            "voice": {
                "tts_engines": self.tts.describe(), "stt_engines": self.stt.describe(),
                "tts_active": tts_engine.id if tts_engine else None, "tts_cloud": bool(tts_engine and tts_engine.cloud),
                "stt_active": stt_engine.id if stt_engine else None, "stt_cloud": bool(stt_engine and stt_engine.cloud),
                "wake_word": self.settings.wake_word,
                "wake": self.wake.describe() if self.wake else {"id": None, "available": False, "reason": "detecção local desligada (JARVIS_WAKE_ENGINE=off)", "local": True},
                "conversation_window_s": self.settings.conversation_window_s,
            },
            "permissions": self.perms.summary(),
            "system_actions": {"platform": self.controller.platform, **self.controller.capabilities()},
            "devices": self.devices.describe(),
            "news": {"enabled": self.news.enabled, "feeds": [label for label, _ in self.news.feeds]},
            "weather_enabled": self.settings.weather_enabled,
            "face": self.gate.status(),
            "map": self.citymap.status(),
            # com o JARVIS bloqueado, a agenda não sai do núcleo
            "agenda": self.agenda_state() if self.gate.open else None,
            "scenes": self.scenes_state(),
            # botões rápidos que existem neste PC (luzes = casa e/ou fita; house = há lâmpadas Tuya)
            "quick": {"lights": self.quick_plan("luzes:on") is not None, "house": bool(self.home.lights()),
                      "leds": self.quick_plan("fita:on") is not None, "door": self.quick_plan("porta:status") is not None},
            "home": {"note": self.home_note, "lights": [{"id": d.id, "name": d.name} for d in self.home.lights()]},
            "intro": {"music": self.intro_music() is not None, "music_name": (self.memory.get_setting("intro_music", {}) or {}).get("name", "")},
        }

    async def _system_prompt(self) -> str:
        rt = self.runtime()
        facts = [f["text"] for f in await asyncio.to_thread(self.memory.facts)] if rt["memory_enabled"] else None
        return build_system_prompt(local_now(self.settings.location), title=rt["user_title"], facts=facts)

    # ------------------------------------------------------------------ conversa
    # ------------------------------------------------------------------ botões rápidos do HUD (0.6)
    def quick_plan(self, action: str) -> tuple[str, Plan] | None:
        """Botões do HUD viram um plano FIXO (lista fechada, sem IA): cena, luzes, fita e porta. Passam pelas
        mesmas ferramentas, confirmações e registros de um comando falado. Destrancar não existe aqui."""
        tools = set(self.tools.specs())
        first = lambda o, title: o[0].summary if o else "Sem resposta."   # noqa: E731
        kind, _, arg = str(action or "").partition(":")
        if kind == "cena" and arg in self.perms.routines and "run_routine" in tools:
            r = self.perms.routines[arg]
            return f"Cena: {r.name}", Plan("routine", [_call("run_routine", routine_id=arg)], self.router._say_routine(r.name))
        if kind == "luzes" and arg in ("on", "off"):
            if "house_lights" in tools:
                return ("Acender as luzes" if arg == "on" else "Apagar as luzes"), Plan("lights", [_call("house_lights", target="todas", power=arg)], first)
            kind = "fita"
        if kind == "fita" and arg in ("on", "off") and "control_device" in tools and self.devices.get("leds") is not None:
            return ("Ligar a fita de LED" if arg == "on" else "Desligar a fita de LED"), Plan("leds", [_call("control_device", device_id="leds", action=arg)], first)
        if kind == "porta" and arg in ("status", "lock", "lockdown") and "control_device" in tools and self.devices.get("fechadura") is not None:
            label = {"status": "Ver a porta", "lock": "Trancar a porta", "lockdown": "Modo trancado"}[arg]
            return label, Plan("lock", [_call("control_device", device_id="fechadura", action=arg)], first)
        return None

    async def run_turn(self, conn: Connection, text: str, source: str = "text", stt: dict[str, Any] | None = None, plan: Plan | None = None) -> None:
        turn = uuid.uuid4().hex[:10]
        text = text.strip()[:4000]
        shown = text or "Jarvis"
        marks: dict[str, float] = {"t0": time.monotonic()}
        await conn.send({"type": "transcript", "role": "user", "text": shown, "source": source, **{k: v for k, v in (stt or {}).items() if k not in ("stt_s", "wake_score")}})
        await asyncio.to_thread(self.memory.add_message, "user", shown, {"source": source})
        await conn.send({"type": "phase", "phase": "thinking", "turn": turn})

        rt = self.runtime()
        # o roteador decide ANTES da voz começar: resposta de comando local (no modo automático)
        # sai por uma voz local e não gasta pedidos do Gemini TTS
        if plan is not None:
            pass                                                                  # botão do HUD: plano fixo
        elif not text.strip():
            plan = Plan("ack", render=lambda _o, title: f"Pois não, {title}?")   # disse só "Jarvis"
        elif rt.get("router_mode", "local_first") == "local_first":
            plan = self.router.match(text)
        speak = bool(rt["speak"]) and self.tts.resolve(rt["tts_engine"]) is not None
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        speaker = asyncio.create_task(self._speak_worker(conn, turn, queue, rt, marks, prefer_local=plan is not None)) if speak else None
        chunker = SentenceChunker()
        # modo econômico (padrão): a 1ª frase é sintetizada na hora e TODO o restante vira um
        # único pedido de voz ao final — no máximo 2 requisições por resposta, por causa das cotas
        economy = self.settings.tts_chunking != "frase"
        held: list[str] = []
        spoken_first = False

        def queue_speech(sentence: str) -> None:
            nonlocal spoken_first
            if not economy or not spoken_first:
                spoken_first = True
                queue.put_nowait(sentence)
            else:
                held.append(sentence)

        said: list[str] = []
        tool_log: list[dict[str, Any]] = []
        used: dict[str, str] = {"provider": "", "model": "", "mode": ""}
        error: AIError | None = None
        interrupted = False

        async def converse(provider: AIProvider, mode: str) -> None:
            used.update(provider=provider.name, model=provider.model, mode=mode)
            history = await asyncio.to_thread(self.memory.recent_messages, self.settings.history_turns * 2)
            history = [m for m in history if m["role"] in ("user", "assistant")][:-1]  # sem a fala atual
            session = provider.start(system=await self._system_prompt(), history=history, tools=self.tools.declarations())
            stream = session.send_user(text)
            for round_no in range(MAX_TOOL_ROUNDS + 1):
                calls = []
                async for ev in stream:
                    if isinstance(ev, str):
                        marks.setdefault("first_text", time.monotonic())
                        said.append(ev)
                        await conn.send({"type": "delta", "turn": turn, "text": ev})
                        for sentence in chunker.feed(ev):
                            queue_speech(sentence)
                    else:
                        calls.append(ev)
                if not calls:
                    return
                if round_no == MAX_TOOL_ROUNDS:
                    raise AIError("tool_loop", "O pedido exigiu etapas demais e foi interrompido por segurança.")
                outcomes = [await execute(call) for call in calls]
                stream = session.send_tool_results(outcomes)

        async def execute(call: ToolCall) -> ToolOutcome:
            label = self.tools.label(call.name)
            await conn.send({"type": "tool", "stage": "start", "turn": turn, "id": call.id, "name": call.name, "label": label, "args": call.args})
            out = await self.tools.execute(call, conn.confirm, conn.send)
            await asyncio.to_thread(self.memory.log_action, call.name, call.args, ok=out.ok, executed=out.executed, simulated=out.simulated, summary=out.summary)
            entry = {"id": call.id, "name": call.name, "label": label, "args": call.args, "ok": out.ok, "executed": out.executed, "simulated": out.simulated, "summary": out.summary}
            tool_log.append(entry)
            await conn.send({"type": "tool", "stage": "end", "turn": turn, **entry})
            return out

        async def say(reply: str) -> None:
            if not reply:
                return
            marks.setdefault("first_text", time.monotonic())
            said.append(reply)
            await conn.send({"type": "delta", "turn": turn, "text": reply})
            for sentence in chunker.feed(reply + " "):
                queue_speech(sentence)

        async def route_local(plan: Plan) -> None:
            """Comando reconhecido localmente: executa sem gastar a cota do Gemini."""
            used.update(provider="roteador", model="comandos locais", mode="router")
            outcomes = [await execute(call) for call in plan.calls]
            await say(plan.render(outcomes, rt["user_title"]))

        try:
            chain: list[tuple[AIProvider, str]] = [] if plan is not None else ([(self.gemini, "ai")] if self.gemini else []) + [(self.local, "local")]
            if plan is not None:
                await route_local(plan)
            for provider, mode in chain:
                try:
                    await converse(provider, mode)
                    error = None
                    if mode == "ai":
                        self.last_ai_error = None
                    break
                except AIError as err:
                    error = err
                    if mode == "ai":
                        self.last_ai_error = {"code": err.code, "message": err.message}
                    await conn.send({"type": "error", "scope": "ai", "code": err.code, "message": err.message})
                    # só cai para o modo local se nada foi dito/feito e o problema é de disponibilidade
                    if said or tool_log or mode == "local" or err.code in NO_FALLBACK:
                        break
                    self.local.reason = {"rate_limit": "cota do Gemini esgotada", "offline": "sem internet", "timeout": "o Gemini não respondeu a tempo",
                                         "unavailable": "Gemini sobrecarregado", "auth": "chave do Gemini recusada"}.get(err.code, f"Gemini indisponível: {err.code}")
                    self.local.title = rt["user_title"]
                    await conn.send({"type": "notice", "message": "Continuando em modo local, sem IA."})
            if used["mode"] == "ai" and not tool_log and claims_action("".join(said)):
                # a IA afirmou ter feito algo sem chamar ferramenta (visto no Windows: "Brilho em 30 por
                # cento: comando enviado." sem nenhuma ação). O prompt proíbe; aqui o HUD avisa a verdade.
                await conn.send({"type": "notice", "message": "Atenção: a IA disse que fez algo, mas nenhuma ação foi executada. Repita o pedido de outro jeito."})
            for sentence in chunker.flush():
                queue_speech(sentence)
            if held:
                queue.put_nowait(" ".join(held))
            queue.put_nowait(None)
            if speaker:
                await speaker
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            if speaker and not speaker.done():
                speaker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await speaker
            reply = "".join(said).strip()
            t0 = marks["t0"]
            timings = {k: round(marks[src] - t0, 2) for k, src in (("first_text_s", "first_text"), ("first_audio_s", "first_audio")) if src in marks}
            timings["total_s"] = round(time.monotonic() - t0, 2)
            if stt and "stt_s" in stt:
                timings["stt_s"] = stt["stt_s"]
            if not interrupted and reply:
                self.last_timings = {**timings, "mode": used["mode"]}
            if reply or tool_log:
                meta = {"provider": used["provider"], "model": used["model"], "tools": tool_log, "interrupted": interrupted, "timings": timings}
                with contextlib.suppress(Exception):
                    await asyncio.shield(asyncio.to_thread(self.memory.add_message, "assistant", reply, meta))
            with contextlib.suppress(Exception):
                await asyncio.shield(conn.send({
                    "type": "turn_end", "turn": turn, "text": reply, "provider": used["provider"], "model": used["model"], "mode": used["mode"],
                    "spoken": speak, "interrupted": interrupted, "error": {"code": error.code, "message": error.message} if error else None,
                    "ai": self.ai_status(), "timings": timings,
                }))

    async def _speak_worker(self, conn: Connection, turn: str, queue: "asyncio.Queue[str | None]", rt: dict[str, Any], marks: dict[str, float] | None = None,
                            prefer_local: bool = False) -> None:
        """Sintetiza as frases em paralelo (até `tts_parallel`) e entrega ao HUD na ordem.

        Motores com streaming (Gemini) mandam o áudio em pedaços assim que chegam:
        `audio_start` → `audio_chunk`… → `audio_end`. Os demais mandam um WAV inteiro (`audio`).
        Se a nuvem falhar antes do 1º pedaço, a frase sai pela voz local (modo automático)."""
        engine0 = self.tts.resolve(rt["tts_engine"])
        if prefer_local and rt["tts_engine"] == "auto":
            engine0 = self.tts.resolve_offline() or engine0   # comando local: voz local, sem cota
        state: dict[str, Any] = {"engine": engine0, "failed": False, "switch": None}
        limit = asyncio.Semaphore(max(1, self.settings.tts_parallel))
        ordered: asyncio.Queue[tuple[str, asyncio.Queue] | None] = asyncio.Queue()
        tasks: list[asyncio.Task] = []
        style, speed = rt.get("tts_style"), float(rt.get("tts_speed", 1.0))

        async def whole(engine: TTSEngine, spoken: str) -> TTSResult:
            try:
                return await engine.synthesize(spoken, self._voice_for(engine, rt), style, speed)
            except TTSError as err:
                fallback = self.tts.fallback_for(engine, rt["tts_engine"])
                if fallback is None:
                    raise
                if state["engine"] is engine:  # a 1ª falha troca o motor das próximas frases
                    state["engine"], state["switch"] = fallback, err
                return await fallback.synthesize(spoken, self._voice_for(fallback, rt), style, speed)

        async def job(spoken: str, out: asyncio.Queue) -> None:
            try:
                async with limit:
                    engine: TTSEngine | None = state["engine"]
                    if engine is None or state["failed"]:
                        return
                    if not engine.streams:
                        await out.put(("wav", await whole(engine, spoken)))
                        return
                    try:
                        stream = await engine.open_stream(spoken, self._voice_for(engine, rt), style, speed)
                    except TTSError as err:
                        fallback = self.tts.fallback_for(engine, rt["tts_engine"])
                        if fallback is None:
                            raise
                        if state["engine"] is engine:
                            state["engine"], state["switch"] = fallback, err
                        await out.put(("wav", await whole(fallback, spoken)))
                        return
                    await out.put(("start", stream))
                    try:
                        async for pcm in stream.chunks():
                            await out.put(("chunk", pcm))
                    except TTSError as err:
                        await out.put(("cut", err))   # o áudio já começou: encerra a frase onde parou
            except TTSError as err:
                await out.put(("error", err))
            finally:
                await out.put(("end", None))

        async def produce() -> None:
            while True:
                sentence = await queue.get()
                if sentence is None:
                    break
                spoken = normalize_for_speech(speakable(sentence))
                if spoken:
                    out: asyncio.Queue = asyncio.Queue()
                    tasks.append(asyncio.create_task(job(spoken, out)))
                    await ordered.put((sentence, out))
            await ordered.put(None)

        def first_audio() -> None:
            if marks is not None:
                marks.setdefault("first_audio", time.monotonic())

        producer = asyncio.create_task(produce())
        seq = 0
        fx = self.led_fx if self.led_fx is not None and self.led_fx.voice else None
        if fx:
            fx.begin()
        interrupted = False
        try:
            while True:
                item = await ordered.get()
                if item is None:
                    break
                sentence, out = item
                live: dict[str, Any] | None = None
                while True:
                    kind, value = await out.get()
                    if state["switch"] is not None:
                        err, state["switch"] = state["switch"], None
                        await conn.send({"type": "notice", "message": f"{err.message} Continuando com a voz local."})
                    if kind == "end":
                        break
                    if kind == "start":
                        live = {"rate": value.rate, "bytes": 0}
                        await conn.send({"type": "audio_start", "turn": turn, "seq": seq, "text": sentence, "rate": value.rate, "engine": value.engine,
                                         "voice": value.voice, "model": value.model, "cloud": value.cloud})
                    elif kind == "chunk" and live is not None:
                        first_audio()
                        live["bytes"] += len(value)
                        if fx:
                            fx.feed_pcm(value, live["rate"])
                        await conn.send({"type": "audio_chunk", "turn": turn, "seq": seq, "pcm": base64.b64encode(value).decode("ascii")})
                    elif kind == "cut":
                        await conn.send({"type": "error", "scope": "tts", "code": value.code, "message": value.message})
                    elif kind == "wav":
                        first_audio()
                        if fx:
                            fx.feed_wav(value.wav)
                        await conn.send({
                            "type": "audio", "turn": turn, "seq": seq, "text": sentence, "duration": round(value.duration_s, 3),
                            "engine": value.engine, "voice": value.voice, "model": value.model, "cloud": value.cloud, "wav": base64.b64encode(value.wav).decode("ascii"),
                        })
                        seq += 1
                    elif kind == "error" and not state["failed"]:
                        state["failed"] = True
                        await conn.send({"type": "error", "scope": "tts", "code": value.code, "message": value.message})
                if live is not None:
                    await conn.send({"type": "audio_end", "turn": turn, "seq": seq, "duration": round(live["bytes"] / 2 / live["rate"], 3)})
                    seq += 1
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            if fx:
                fx.end(interrupted=interrupted)
            producer.cancel()
            for task in tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.shield(conn.send({"type": "speech_done", "turn": turn, "chunks": seq, "failed": state["failed"]}))

    # ------------------------------------------------------------------ entrada: rosto → música → boas-vindas → cidade
    MUSIC_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".opus": "audio/ogg",
                   ".wav": "audio/wav", ".flac": "audio/flac", ".webm": "audio/webm"}
    MUSIC_MAX_BYTES = 40 * 1024 * 1024

    def intro_music(self) -> Path | None:
        """A música de entrada é um arquivo do próprio usuário, guardado só neste computador."""
        folder = self.data_dir / "entrada"
        for ext in self.MUSIC_TYPES:
            path = folder / f"musica{ext}"
            if path.is_file():
                return path
        return None

    @staticmethod
    def _looks_like_audio(data: bytes) -> bool:
        head = data[:12]
        return (head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0) or head[:4] in (b"OggS", b"RIFF", b"fLaC", b"\x1aE\xdf\xa3")
                or head[4:8] == b"ftyp")

    def save_intro_music(self, data: bytes, filename: str) -> dict[str, Any]:
        ext = Path(filename).suffix.lower()
        if ext not in self.MUSIC_TYPES:
            raise ValueError("Formato não aceito. Use MP3, M4A, AAC, OGG, OPUS, WAV, FLAC ou WEBM.")
        if not data or len(data) > self.MUSIC_MAX_BYTES:
            raise ValueError("Arquivo vazio ou maior que 40 MB.")
        if not self._looks_like_audio(data):
            raise ValueError("O arquivo não parece ser de áudio.")
        folder = self.data_dir / "entrada"
        folder.mkdir(parents=True, exist_ok=True)
        old = self.intro_music()
        if old:
            old.unlink()
        (folder / f"musica{ext}").write_bytes(data)
        name = Path(filename).name[:120]
        self.memory.set_setting("intro_music", {"name": name, "bytes": len(data)})
        return {"name": name, "bytes": len(data)}

    def delete_intro_music(self) -> None:
        old = self.intro_music()
        if old:
            old.unlink()
        self.memory.set_setting("intro_music", {})

    async def briefing(self) -> dict[str, Any]:
        """Clima, notícias reais da cidade e os compromissos de hoje, em texto pronto para falar."""
        async def nothing() -> None:
            return None

        rt = self.runtime()
        weather, news = await asyncio.gather(self.weather.get(), self.news.get() if self.news.enabled else nothing())
        today = await asyncio.to_thread(self.agenda.today, True)
        return compose_briefing(local_now(self.settings.location), self.settings.location.city, rt["user_title"], weather, news,
                                agenda_text=self.agenda.say_day(today), agenda=[Agenda.public(e) for e in today])

    # ------------------------------------------------------------------ cenas (0.6)
    def scene_schedules(self) -> dict[str, dict[str, Any]]:
        """Horário de cada cena: o padrão do permissions.json, trocado pelo que foi ajustado no painel."""
        out: dict[str, dict[str, Any]] = {}
        for rid, r in self.perms.routines.items():
            if r.schedule and r.schedule.get("at"):
                out[rid] = {"at": str(r.schedule["at"]), "days": r.schedule.get("days", "todos"), "on": bool(r.schedule.get("on", True))}
        for rid, sch in (self.runtime().get("scene_schedules") or {}).items():
            if rid in self.perms.routines:
                out[rid] = {"at": sch["at"], "days": sch.get("days", "todos"), "on": bool(sch.get("on", True))}
        return out

    def scenes_state(self) -> list[dict[str, Any]]:
        sch = self.scene_schedules()
        return [{"id": rid, "name": r.name, "icon": r.icon, "words": list(r.words), "exact": r.exact, "confirm": r.confirm,
                 "steps": [st["tool"] for st in r.steps], "schedule": sch.get(rid)} for rid, r in self.perms.routines.items()]

    async def run_scheduled_scenes(self, now: datetime | None = None) -> list[str]:
        """Roda as cenas cujo horário chegou (janela de 3 min, uma vez por dia). Cenas que pedem confirmação
        só avisam: sem ninguém olhando, nada que precise de "sim" acontece sozinho."""
        now = now or self.agenda.now()
        ran: list[str] = []
        title = self.runtime()["user_title"]
        for rid, sch in self.scene_schedules().items():
            if not sch.get("on") or now.weekday() not in SCENE_DAYS.get(sch.get("days", "todos"), SCENE_DAYS["todos"]):
                continue
            hh, mm = (int(x) for x in sch["at"].split(":"))
            start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            key = f"{rid}@{now.date()}"
            if not (start <= now < start + timedelta(minutes=3)) or key in self._scenes_done:
                continue
            self._scenes_done.add(key)
            routine = self.perms.routines[rid]
            ran.append(rid)
            if routine.confirm:
                await self.broadcast({"type": "reminder", "text": f"Hora da cena “{routine.name}”. Ela pede confirmação: diga “{routine.name.lower()}”."})
                continue

            async def deny(_text: str) -> bool:
                return False

            out = await self.tools.execute(ToolCall(f"cena-{rid}", "run_routine", {"routine_id": rid}), deny, self.broadcast)
            await self.broadcast({"type": "reminder", "text": f"Cena agendada — {out.summary}"})
            # bloqueado: só o cumprimento; o resumo (com a agenda) fica para depois da entrada
            speech = " ".join(out.data.get("speech", [])) if self.gate.open else ""
            conn = next((c for c in self.conns if c.turn is None or c.turn.done()), None)
            if conn is not None and out.executed:
                conn.turn = asyncio.create_task(self.speak_text(conn, f"cena-{uuid.uuid4().hex[:6]}", f"{routine.name}, {title}. {speech}".strip(), mode="cena"))
        return ran

    async def broadcast(self, event: dict[str, Any]) -> int:
        """Manda um evento para todos os HUDs abertos. Devolve quantos receberam."""
        sent = 0
        for conn in list(self.conns):
            with contextlib.suppress(Exception):
                await conn.send(event)
                sent += 1
        return sent

    def agenda_state(self) -> dict[str, Any]:
        return {"today": [Agenda.public(e) for e in self.agenda.today()], "upcoming": [Agenda.public(e) for e in self.agenda.upcoming(14)]}

    async def check_lock(self) -> list[str]:
        """Novos eventos da fechadura real (aberturas, códigos errados) viram avisos. Devolve os textos."""
        lock = self.devices.get("fechadura")
        if not isinstance(lock, OwnLock):
            return []
        res = await self.devices.command("fechadura", "status", {})
        if not res.executed:
            return []
        seen = self._lock_seen
        first = not seen
        notes = []
        names = {"teclado": "pelo teclado", "app": "pelo app", "rosto": "pelo reconhecimento facial", "painel": "pelo painel", "jarvis": "pelo JARVIS"}
        for ev in reversed(lock.events):
            key = f"{ev.get('t')}-{ev.get('src')}-{ev.get('ok')}"
            if key in seen:
                continue
            seen.add(key)
            if first or ev.get("src") in ("jarvis", "trancado", "liberado"):
                continue                                  # na 1ª leitura não repete o histórico antigo
            when = datetime.fromtimestamp(int(ev.get("t", 0)), ZoneInfo(self.settings.location.timezone)).strftime("%H:%M") if ev.get("t") else ""
            if ev.get("ok"):
                notes.append(f"Porta aberta {names.get(ev.get('src'), ev.get('src'))} às {when}.")
            elif ev.get("src") != "teclado":
                notes.append(f"Tentativa de abrir {names.get(ev.get('src'), ev.get('src'))} recusada (modo trancado) às {when}.")
        wrong = int(lock.status().get("wrong_codes") or 0)
        if wrong >= 3 and wrong != self._lock_wrong:
            notes.append(f"Atenção: {wrong} códigos errados seguidos no teclado da fechadura.")
        self._lock_wrong = wrong
        return notes

    async def _reminder_loop(self) -> None:
        """A cada 30 s: lembretes vencidos e eventos da fechadura viram aviso no HUD e fala."""
        while True:
            await asyncio.sleep(30)
            with contextlib.suppress(Exception):
                await self.run_scheduled_scenes()
            with contextlib.suppress(Exception):
                for text in await self.check_lock():
                    for conn in list(self.conns):
                        with contextlib.suppress(Exception):
                            await conn.send({"type": "reminder", "text": text, "event": None})
                            if "Atenção" in text and (conn.turn is None or conn.turn.done()):
                                conn.turn = asyncio.create_task(self.speak_text(conn, f"fechadura-{uuid.uuid4().hex[:6]}", text, mode="alerta"))
            try:
                due = await asyncio.to_thread(self.agenda.due_reminders)
            except Exception:
                continue
            for ev in due:
                mins = max(1, round((ev["start"] - self.agenda.now()).total_seconds() / 60))
                private = not self.gate.open
                title = self.runtime()["user_title"]
                text = (f"{title.capitalize()}, você tem um lembrete." if private
                        else f"Lembrete, {title}: {ev['title']}, em {mins} minuto{'s' if mins > 1 else ''}.")
                for conn in list(self.conns):
                    with contextlib.suppress(Exception):
                        await conn.send({"type": "reminder", "text": text, "event": None if private else Agenda.public(ev)})
                        if conn.turn is None or conn.turn.done():
                            conn.turn = asyncio.create_task(self.speak_text(conn, f"lembrete-{uuid.uuid4().hex[:6]}", text, mode="lembrete"))

    async def speak_text(self, conn: Connection, turn: str, text: str, mode: str = "intro") -> None:
        """Fala um texto pronto (sem IA), pela mesma cadeia de voz das respostas: 1 pedido de voz por bloco."""
        rt = self.runtime()
        await conn.send({"type": "delta", "turn": turn, "text": text})
        speak = bool(rt["speak"]) and self.tts.resolve(rt["tts_engine"]) is not None
        if speak:
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            queue.put_nowait(text)
            queue.put_nowait(None)
            await self._speak_worker(conn, turn, queue, rt)
        await conn.send({"type": "turn_end", "turn": turn, "text": text, "provider": "roteador", "model": "texto local", "mode": mode,
                         "spoken": speak, "interrupted": False, "error": None, "ai": self.ai_status(), "timings": {}})

    def on_entry(self) -> None:
        """Rosto ou PIN aceito: a fita faz a apresentação de entrada junto com a música."""
        if self.led_fx is not None:
            self.led_fx.start_entry()

    async def intro(self, conn: Connection) -> None:
        """Depois do rosto confirmado: boas-vindas e, já sobre a cidade, clima e notícias."""
        b = await self.briefing()
        tag = uuid.uuid4().hex[:6]
        welcome, city = f"intro-a-{tag}", f"intro-b-{tag}"
        await conn.send({"type": "ui", "action": "intro", "briefing": b, "welcome_turn": welcome, "map_turn": city})
        await self.speak_text(conn, welcome, b["welcome"])
        # o HUD só voa para a cidade quando o áudio deste trecho começa a tocar
        await conn.send({"type": "ui", "action": "show_map", "briefing": b, "at_turn": city})
        await self.speak_text(conn, city, b["briefing"])
        await conn.send({"type": "ui", "action": "intro_done"})

    # ------------------------------------------------------------------ voz do usuário
    async def handle_audio(self, conn: Connection, wav: bytes, mode: str = "ptt") -> None:
        """Fala do usuário. Modos:
        - ptt: botão de falar (intenção explícita);
        - wake: escuta contínua — só segue se o detector LOCAL ouvir "Jarvis";
        - followup: logo depois de uma resposta, dentro da janela de conversa (sem exigir "Jarvis");
        - barge: o usuário falou enquanto o JARVIS falava — interrompe só se ouvir "Jarvis".
        Nada sai do computador antes de passar pelo detector local (wake/barge)."""
        rt = self.runtime()

        async def fail(code: str, message: str) -> None:
            await conn.send({"type": "error", "scope": "stt", "code": code, "message": message})
            await conn.send({"type": "phase", "phase": "idle"})

        async def ignore(reason: str, score: float | None = None) -> None:
            await conn.send({"type": "wake_ignored", "mode": mode, "reason": reason, "score": score})

        try:
            info = wav_info(wav)
        except Exception:
            return await fail("bad_audio", "O áudio recebido não é um WAV válido.")
        if not 0.25 <= float(info["duration_s"]) <= 60.0:
            return await fail("bad_audio", "A gravação precisa ter entre 0,25 e 60 segundos.")
        if wav_rms(wav) < 0.003:
            if mode in ("wake", "barge", "followup"):
                return await ignore("silêncio")
            await conn.send({"type": "stt_empty", "reason": "silêncio"})
            return await conn.send({"type": "phase", "phase": "idle"})
        if mode in ("wake", "barge", "followup") and not rt["continuous_consent"]:
            return await fail("consent_required", "A escuta contínua só funciona depois da sua autorização em Configurações → Microfone.")

        detected_score: float | None = None
        if mode in ("wake", "barge"):
            if self.wake is None or not self.wake.available()[0]:
                reason = self.wake.available()[1] if self.wake else "nenhum detector local configurado"
                return await fail("wake_unavailable", f"Detecção local de “Jarvis” indisponível: {reason}")
            try:
                found = await self.wake.detect(wav)
            except Exception as exc:
                return await fail("wake_failed", f"O detector local falhou ({type(exc).__name__}).")
            if not found.detected:
                return await ignore("sem a palavra-chave", found.score)   # descartado no próprio computador
            detected_score = found.score
            if mode == "barge":
                await conn.send({"type": "barge_accept", "score": found.score})

        engine = self.stt.resolve(rt["stt_engine"])
        if engine is None:
            return await fail("stt_unavailable", "Nenhum motor de transcrição disponível. Use o modo texto, ou instale o Whisper local / configure o Gemini.")
        if engine.cloud and not rt["cloud_audio_consent"]:
            return await fail("consent_required", "O áudio só é enviado à nuvem depois da sua autorização nas configurações de privacidade.")
        if mode in ("wake", "barge"):
            # a palavra-chave foi confirmada: interrompe o que estiver em andamento e assume
            if conn.turn is not None and conn.turn is not asyncio.current_task():
                await conn.cancel_turn()
            conn.turn = asyncio.current_task()
        await conn.send({"type": "phase", "phase": "transcribing", "engine": engine.id, "cloud": engine.cloud})
        started = time.monotonic()
        try:
            result = await engine.transcribe(wav, self.settings.location.language)
        except STTError as err:
            return await fail(err.code, err.message)
        stt_s = round(time.monotonic() - started, 2)
        text = result.text
        if not text and mode == "ptt":
            await conn.send({"type": "stt_empty", "reason": "sem fala"})
            return await conn.send({"type": "phase", "phase": "idle"})
        source = {"ptt": "voice", "followup": "voice", "wake": "wake", "barge": "wake"}.get(mode, "voice")
        if mode in ("wake", "barge"):
            command = extract_wake_command(text, self.settings.wake_word)
            # o detector local já confirmou a palavra; se a transcrição não a trouxer, usa o texto todo
            text = command if command is not None else text
        elif mode == "followup" and not text:
            return await ignore("sem fala")
        info = {"engine": result.engine, "cloud": result.cloud, "stt_s": stt_s}
        if detected_score is not None:
            info["wake_score"] = detected_score
        await self.run_turn(conn, text, source, info)

    async def voice_sample(self, engine_id: str, voice: str | None, text: str | None = None, style: str | None = None) -> dict[str, Any]:
        """Amostra para ouvir e comparar no painel. Fica em cache local: ouvir de novo a mesma
        combinação não gasta outra chamada à nuvem."""
        engine = self.tts.engines.get(engine_id)
        if engine is None or not engine.available()[0]:
            raise TTSError("unavailable", "Este motor de voz não está disponível.")
        phrase = speakable(text or SAMPLE_TEXT)[:300]
        style = style if style in STYLES else self.runtime()["tts_style"]
        speed = float(self.runtime().get("tts_speed", 1.0))
        model = getattr(self.gemini, "tts_model", "") if engine_id == "gemini" else ""
        key = hashlib.sha1(f"{engine_id}|{model}|{voice}|{style}|{speed}|{phrase}".encode()).hexdigest()[:20]
        cache = self.settings.db_path.parent / "voice_cache" if str(self.settings.db_path) != ":memory:" else None
        path = cache / f"{key}.wav" if cache else None
        cached = bool(path and path.exists())
        if cached:
            wav = await asyncio.to_thread(path.read_bytes)
            used, duration = voice or "", float(wav_info(wav)["duration_s"])
        else:
            result = await engine.synthesize(normalize_for_speech(phrase), voice or None, style, speed)
            wav, used, duration = result.wav, result.voice, result.duration_s
            if path:
                with contextlib.suppress(OSError):
                    cache.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(path.write_bytes, wav)
        return {"engine": engine_id, "voice": used, "style": style, "cloud": engine.cloud, "cached": cached, "duration": round(duration, 3), "text": phrase, "wav": base64.b64encode(wav).decode("ascii")}
