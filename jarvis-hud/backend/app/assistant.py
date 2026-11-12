"""Orquestrador do JARVIS Core: liga IA, ferramentas, voz, memória e o canal com o HUD."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import time
import uuid
from typing import Any

from fastapi import WebSocket

from .ai.base import AIError, AIProvider, ToolOutcome
from .ai.gemini_provider import GeminiProvider
from .ai.local_provider import LocalProvider
from .ai.persona import build_system_prompt
from .ai.tools import ToolRegistry
from .config import Settings
from .devices.registry import DeviceRegistry
from .memory.store import MemoryStore
from .security.permissions import Permissions
from .services.local_info import local_now
from .services.news import NewsService
from .services.weather import WeatherService
from .system.monitor import SystemMonitor
from .system.windows import SystemController, get_controller
from .voice.audio_stream import SentenceChunker, normalize_for_speech, speakable, wav_info, wav_rms
from .voice.stt import GeminiSTT, STTError, VoiceInput, WhisperSTT, extract_wake_command
from .voice.tts import STYLES, GeminiTTS, LocalTTS, TTSEngine, TTSError, TTSResult, VoiceOutput

VERSION = "0.2.1"
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
        tts: VoiceOutput | None = None, stt: VoiceInput | None = None,
    ):
        self.settings = settings
        self.memory = memory or MemoryStore(settings.db_path)
        self.perms = perms or Permissions.load(settings.permissions_path)
        self.controller = controller or get_controller()
        self.monitor = monitor or SystemMonitor()
        self.devices = devices or DeviceRegistry(simulators=settings.devices_simulators)
        self.weather = weather or WeatherService(settings.location, enabled=settings.weather_enabled)
        self.news = news or NewsService(settings.news_rss_url)
        self.gemini = gemini if gemini is not None else (GeminiProvider(settings) if settings.ai_configured else None)
        self.local = LocalProvider(self.perms)
        self.tts = tts or VoiceOutput(GeminiTTS(self.gemini, settings.tts_voice, settings.tts_style) if self.gemini else None, LocalTTS())
        self.stt = stt or VoiceInput(GeminiSTT(self.gemini, settings.gemini_stt_model) if self.gemini else None, WhisperSTT(settings.whisper_model))
        self.tools = ToolRegistry(
            settings=settings, perms=self.perms, monitor=self.monitor, controller=self.controller, devices=self.devices,
            weather=self.weather, news=self.news, memory=self.memory, memory_enabled=lambda: bool(self.runtime()["memory_enabled"]),
        )
        self.last_ai_error: dict[str, str] | None = None
        self.last_timings: dict[str, float] | None = None

    async def startup(self) -> None:
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
            "tts_engine": s.tts_engine, "tts_voice_gemini": s.tts_voice, "tts_voice_local": "", "tts_style": s.tts_style if s.tts_style in STYLES else "cinematografico",
            "stt_engine": s.stt_engine, "speak": True, "memory_enabled": s.memory_enabled, "cloud_audio_consent": False, "user_title": "senhor",
            "chat_model": "", "tts_model": "", "tts_speed": 1.0,
        }
        saved = self.memory.get_setting("runtime", {}) or {}
        return {**defaults, **{k: v for k, v in saved.items() if k in defaults}}

    def update_runtime(self, patch: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime()
        rules = {
            "tts_engine": lambda v: v in {"auto", "gemini", "local", "off"},
            "stt_engine": lambda v: v in {"auto", "gemini", "whisper", "off"},
            "tts_voice_gemini": lambda v: isinstance(v, str) and 0 < len(v) <= 40 and v.replace("-", "").replace("_", "").isalnum(),
            "tts_voice_local": lambda v: isinstance(v, str) and len(v) <= 300,
            "tts_style": lambda v: v in STYLES,
            "tts_speed": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0.8 <= float(v) <= 1.3,
            "chat_model": lambda v: isinstance(v, str) and (v == "" or (self.gemini is not None and v in self.gemini.status().get("chat_models", []))),
            "tts_model": lambda v: isinstance(v, str) and (v == "" or (self.gemini is not None and v in self.gemini.status().get("tts_models", []))),
            "speak": lambda v: isinstance(v, bool), "memory_enabled": lambda v: isinstance(v, bool),
            "cloud_audio_consent": lambda v: isinstance(v, bool),
            "user_title": lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 24,
        }
        for key, value in patch.items():
            if key in rules and rules[key](value):
                rt[key] = value.strip() if key == "user_title" else round(float(value), 2) if key == "tts_speed" else value
        self.memory.set_setting("runtime", rt)
        if "chat_model" in patch or "tts_model" in patch:
            self._apply_models(rt)
        return rt

    def _voice_for(self, engine: TTSEngine, rt: dict[str, Any]) -> str | None:
        return (rt["tts_voice_gemini"] if engine.id == "gemini" else rt["tts_voice_local"]) or None

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
            },
            "permissions": self.perms.summary(),
            "system_actions": {"platform": self.controller.platform, **self.controller.capabilities()},
            "devices": self.devices.describe(),
            "news": {"enabled": self.news.enabled},
            "weather_enabled": self.settings.weather_enabled,
        }

    async def _system_prompt(self) -> str:
        rt = self.runtime()
        facts = [f["text"] for f in await asyncio.to_thread(self.memory.facts)] if rt["memory_enabled"] else None
        return build_system_prompt(local_now(self.settings.location), title=rt["user_title"], facts=facts)

    # ------------------------------------------------------------------ conversa
    async def run_turn(self, conn: Connection, text: str, source: str = "text", stt: dict[str, Any] | None = None) -> None:
        turn = uuid.uuid4().hex[:10]
        text = text.strip()[:4000]
        marks: dict[str, float] = {"t0": time.monotonic()}
        await conn.send({"type": "transcript", "role": "user", "text": text, "source": source, **{k: v for k, v in (stt or {}).items() if k != "stt_s"}})
        await asyncio.to_thread(self.memory.add_message, "user", text, {"source": source})
        await conn.send({"type": "phase", "phase": "thinking", "turn": turn})

        rt = self.runtime()
        speak = bool(rt["speak"]) and self.tts.resolve(rt["tts_engine"]) is not None
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        speaker = asyncio.create_task(self._speak_worker(conn, turn, queue, rt, marks)) if speak else None
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
                outcomes: list[ToolOutcome] = []
                for call in calls:
                    label = self.tools.label(call.name)
                    await conn.send({"type": "tool", "stage": "start", "turn": turn, "id": call.id, "name": call.name, "label": label, "args": call.args})
                    out = await self.tools.execute(call, conn.confirm, conn.send)
                    await asyncio.to_thread(self.memory.log_action, call.name, call.args, ok=out.ok, executed=out.executed, simulated=out.simulated, summary=out.summary)
                    entry = {"id": call.id, "name": call.name, "label": label, "args": call.args, "ok": out.ok, "executed": out.executed, "simulated": out.simulated, "summary": out.summary}
                    tool_log.append(entry)
                    await conn.send({"type": "tool", "stage": "end", "turn": turn, **entry})
                    outcomes.append(out)
                stream = session.send_tool_results(outcomes)

        try:
            chain: list[tuple[AIProvider, str]] = ([(self.gemini, "ai")] if self.gemini else []) + [(self.local, "local")]
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
                    self.local.reason = f"Gemini indisponível: {err.code}"
                    await conn.send({"type": "notice", "message": "Continuando em modo local, sem IA."})
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

    async def _speak_worker(self, conn: Connection, turn: str, queue: "asyncio.Queue[str | None]", rt: dict[str, Any], marks: dict[str, float] | None = None) -> None:
        """Sintetiza as frases em paralelo (até `tts_parallel`) e entrega ao HUD na ordem.

        Motores com streaming (Gemini) mandam o áudio em pedaços assim que chegam:
        `audio_start` → `audio_chunk`… → `audio_end`. Os demais mandam um WAV inteiro (`audio`).
        Se a nuvem falhar antes do 1º pedaço, a frase sai pela voz local (modo automático)."""
        state: dict[str, Any] = {"engine": self.tts.resolve(rt["tts_engine"]), "failed": False, "switch": None}
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
                        await conn.send({"type": "audio_chunk", "turn": turn, "seq": seq, "pcm": base64.b64encode(value).decode("ascii")})
                    elif kind == "cut":
                        await conn.send({"type": "error", "scope": "tts", "code": value.code, "message": value.message})
                    elif kind == "wav":
                        first_audio()
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
        finally:
            producer.cancel()
            for task in tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.shield(conn.send({"type": "speech_done", "turn": turn, "chunks": seq, "failed": state["failed"]}))

    # ------------------------------------------------------------------ voz do usuário
    async def handle_audio(self, conn: Connection, wav: bytes, mode: str = "ptt") -> None:
        rt = self.runtime()
        engine = self.stt.resolve(rt["stt_engine"])

        async def fail(code: str, message: str) -> None:
            await conn.send({"type": "error", "scope": "stt", "code": code, "message": message})
            await conn.send({"type": "phase", "phase": "idle"})

        if engine is None:
            return await fail("stt_unavailable", "Nenhum motor de transcrição disponível. Use o modo texto, ou configure o Gemini ou o Whisper local.")
        if engine.cloud and not rt["cloud_audio_consent"]:
            return await fail("consent_required", "O áudio só é enviado à nuvem depois da sua autorização nas configurações de privacidade.")
        try:
            info = wav_info(wav)
        except Exception:
            return await fail("bad_audio", "O áudio recebido não é um WAV válido.")
        if not 0.25 <= float(info["duration_s"]) <= 60.0:
            return await fail("bad_audio", "A gravação precisa ter entre 0,25 e 60 segundos.")
        if wav_rms(wav) < 0.003:
            await conn.send({"type": "stt_empty", "reason": "silêncio"})
            return await conn.send({"type": "phase", "phase": "idle"})
        await conn.send({"type": "phase", "phase": "transcribing", "engine": engine.id, "cloud": engine.cloud})
        started = time.monotonic()
        try:
            result = await engine.transcribe(wav, self.settings.location.language)
        except STTError as err:
            return await fail(err.code, err.message)
        stt_s = round(time.monotonic() - started, 2)
        text = result.text
        if not text:
            await conn.send({"type": "stt_empty", "reason": "sem fala"})
            return await conn.send({"type": "phase", "phase": "idle"})
        source = "voice"
        if mode == "wake":
            command = extract_wake_command(text, self.settings.wake_word)
            if command is None:
                await conn.send({"type": "wake_ignored"})
                return await conn.send({"type": "phase", "phase": "idle"})
            text, source = command or "Jarvis?", "wake"
        await self.run_turn(conn, text, source, {"engine": result.engine, "cloud": result.cloud, "stt_s": stt_s})

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
