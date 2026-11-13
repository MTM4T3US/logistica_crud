"""Síntese de voz. Dois motores atrás da mesma interface:

- GeminiTTS (nuvem): vozes predefinidas com direção de estilo em linguagem natural.
- LocalTTS (offline, gratuito): SAPI5 no Windows via pyttsx3; espeak-ng em Linux/macOS.

O toque "tecnológico" e o controle de velocidade/volume são aplicados no HUD (Web Audio),
para que o timbre original do motor fique preservado e ajustável em tempo real.
"""
from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from google.genai import types

from ..ai.base import AIError
from ..ai.gemini_provider import GeminiProvider, map_gemini_error
from .audio_stream import parse_rate, pcm16_to_wav, wav_info

_BASE_STYLE = "Voz masculina adulta, registro médio-grave, timbre encorpado. Português do Brasil com dicção natural e clara. "

#: Direções de interpretação (identidade vocal original). Vão para o Gemini TTS no campo de
#: estilo de cada trecho (`speech_metadata.style`), separado do texto a ser dito. Validado na
#: API real: enviar a direção junto do texto faz o modelo LER a direção em voz alta.
STYLES: dict[str, tuple[str, str]] = {
    "cinematografico": (
        "Cinematográfica",
        _BASE_STYLE + "Interpretação de assistente de inteligência artificial sofisticado: calmo, confiante e cortês, com elegância "
        "contida e um leve toque de ironia fina. Pronúncia precisa, ritmo moderado, pausas curtas nas vírgulas e um pouco mais longas "
        "entre as frases. Sem soar robótico, teatral ou apressado.",
    ),
    "sobrio": ("Sóbria", _BASE_STYLE + "Tom sereno, profissional e discreto, quase sem ênfases. Ritmo constante, pausas regulares."),
    "caloroso": ("Calorosa", _BASE_STYLE + "Tom acolhedor e próximo, com um leve sorriso na voz, sem perder a elegância. Ritmo tranquilo."),
    "neutro": ("Neutra (sem direção)", ""),
}
STYLE_PROMPT = STYLES["cinematografico"][1]


def pace_hint(speed: float) -> str:
    """No Gemini o ritmo é pedido na direção de estilo (mudar a velocidade de reprodução
    alteraria o tom da voz)."""
    if speed <= 0.9:
        return " Ritmo bem mais lento e pausado que o normal."
    if speed < 0.97:
        return " Ritmo um pouco mais lento que o normal."
    if speed >= 1.15:
        return " Ritmo bem mais ágil que o normal, sem atropelar as palavras."
    if speed > 1.03:
        return " Ritmo um pouco mais ágil que o normal."
    return ""


def direction_for(style: str | None, default: str, speed: float = 1.0) -> str:
    base = STYLES.get(style or default, STYLES.get(default, STYLES["cinematografico"]))[1]
    hint = pace_hint(speed)
    if not base and hint:
        return hint.strip()
    return base + hint

#: Vozes predefinidas do Gemini TTS (nome → característica divulgada). A lista é a que eu
#: conhecia ao escrever e pode ter mudado; a percepção de timbre é subjetiva — compare as
#: amostras antes de escolher. As primeiras são as candidatas ao perfil médio-grave.
GEMINI_VOICES: list[tuple[str, str]] = [
    ("Charon", "informativa"), ("Orus", "firme"), ("Algieba", "suave"), ("Algenib", "grave, áspera"),
    ("Iapetus", "clara"), ("Rasalgethi", "informativa"), ("Schedar", "equilibrada"), ("Sadaltager", "culta"),
    ("Alnilam", "firme"), ("Enceladus", "soprosa"), ("Gacrux", "madura"), ("Fenrir", "enérgica"), ("Puck", "animada"),
    ("Umbriel", "tranquila"), ("Achird", "amigável"), ("Zubenelgenubi", "casual"), ("Sadachbia", "vivaz"),
    ("Zephyr", "brilhante"), ("Kore", "firme"), ("Leda", "jovem"), ("Aoede", "leve"), ("Callirrhoe", "tranquila"),
    ("Autonoe", "brilhante"), ("Despina", "suave"), ("Erinome", "clara"), ("Laomedeia", "animada"),
    ("Achernar", "suave"), ("Pulcherrima", "expressiva"), ("Vindemiatrix", "gentil"), ("Sulafat", "calorosa"),
]


class TTSError(Exception):
    def __init__(self, code: str, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.code, self.message, self.retry_after_s = code, message, retry_after_s


class TTSStream:
    """Fala em streaming: PCM 16 bits mono, entregue em pedaços conforme o modelo gera."""

    def __init__(self, first: bytes, rest: AsyncIterator[bytes], rate: int, engine: str, voice: str, model: str, cloud: bool):
        self._first, self._rest = first, rest
        self.rate, self.engine, self.voice, self.model, self.cloud = rate, engine, voice, model, cloud

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self._first
        async for piece in self._rest:
            if piece:
                yield piece


@dataclass
class TTSResult:
    wav: bytes
    duration_s: float
    engine: str
    voice: str
    cloud: bool
    model: str = ""


class TTSEngine(ABC):
    id: str
    label: str
    cloud: bool

    @abstractmethod
    def available(self) -> tuple[bool, str]: ...

    @abstractmethod
    def voices(self) -> list[dict[str, str]]: ...

    @abstractmethod
    async def synthesize(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSResult: ...

    #: motores que entregam áudio em partes implementam open_stream()
    streams = False

    async def open_stream(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSStream:
        raise TTSError("unsupported", "Este motor não faz streaming.")

    def styles(self) -> list[dict[str, str]]:
        return []

    def describe(self) -> dict[str, Any]:
        ok, reason = self.available()
        return {"id": self.id, "label": self.label, "cloud": self.cloud, "available": ok, "reason": reason, "voices": self.voices() if ok else [], "styles": self.styles()}


class GeminiTTS(TTSEngine):
    id, label, cloud = "gemini", "Gemini TTS (nuvem)", True

    def __init__(self, provider: GeminiProvider, default_voice: str = "Charon", default_style: str = "cinematografico"):
        self.p, self.default_voice, self.default_style = provider, default_voice, default_style if default_style in STYLES else "cinematografico"

    def styles(self) -> list[dict[str, str]]:
        return [{"id": key, "label": label} for key, (label, _) in STYLES.items()]

    def available(self) -> tuple[bool, str]:
        return True, ""

    def voices(self) -> list[dict[str, str]]:
        return [{"id": v, "label": f"{v} — {note}"} for v, note in GEMINI_VOICES]

    streams = True

    def _config(self, voice: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        )

    @staticmethod
    def _contents(text: str, direction: str, mode: str) -> Any:
        if mode == "metadata":
            return [types.Content(role="user", parts=[types.Part(text=text, speech_metadata=types.SpeechMetadata(style=direction))])]
        return text  # só o texto: nunca misturamos a direção com o que deve ser dito

    def _fail(self, err: AIError) -> TTSError:
        msg = err.message.replace("O Gemini", "O Gemini TTS", 1).replace("deste modelo Gemini", "do modelo de voz")
        return TTSError(err.code, msg, err.retry_after_s)

    async def _attempts(self, text: str, voice: str, style: str | None, speed: float, call):
        """Percorre os modelos de voz da conta e os modos de estilo até um responder.
        `call(model, contents)` faz a requisição; cotas e indisponibilidade passam ao próximo modelo."""
        direction = direction_for(style, self.default_style, speed)
        await self.p.resolve_models()
        chain = self.p.tts_chain() if hasattr(self.p, "tts_chain") else [self.p.tts_model]
        modes: dict[str, str] = getattr(self.p, "tts_style_mode", {})
        last = TTSError("unavailable", "Nenhum modelo de voz do Gemini respondeu.")
        for model in chain[:3]:
            mode = modes.get(model, "metadata") if direction else "plain"
            while True:
                try:
                    result = await call(model, self._contents(text, direction, mode))
                except TTSError as err:   # resposta sem áudio
                    last = err
                    break
                except Exception as exc:
                    err = map_gemini_error(exc)
                    if err.code == "bad_request" and mode == "metadata":
                        mode = modes[model] = "plain"   # este modelo não aceita o campo de estilo
                        continue
                    last = self._fail(err)
                    if err.code == "rate_limit" and hasattr(self.p, "note_limit"):
                        self.p.note_limit(model, err)
                    if err.code in ("rate_limit", "unavailable", "timeout", "model_not_found"):
                        break   # cota e disponibilidade são por modelo: tenta o próximo modelo de voz
                    raise last from None
                if direction and modes.get(model) != mode:
                    modes[model] = mode
                if hasattr(self.p, "count"):
                    self.p.count(model)
                return model, result
        raise last

    async def synthesize(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSResult:
        voice = voice or self.default_voice

        async def call(model: str, contents: Any) -> tuple[bytes, str]:
            resp = await asyncio.wait_for(self.p.client.aio.models.generate_content(model=model, contents=contents, config=self._config(voice)), timeout=self.p.settings.gemini_timeout_s)
            try:
                part = resp.candidates[0].content.parts[0]
                pcm, mime = part.inline_data.data, part.inline_data.mime_type or ""
            except (AttributeError, IndexError, TypeError):
                raise TTSError("empty", "O Gemini TTS não devolveu áudio.") from None
            if not pcm:
                raise TTSError("empty", "O Gemini TTS não devolveu áudio.")
            return pcm, mime

        model, (pcm, mime) = await self._attempts(text, voice, style, speed, call)
        wav = pcm if pcm[:4] == b"RIFF" else pcm16_to_wav(pcm, parse_rate(mime))
        return TTSResult(wav, float(wav_info(wav)["duration_s"]), self.id, voice, True, model)

    async def open_stream(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSStream:
        """Abre a síntese em streaming e só retorna quando o 1º pedaço de áudio chegou — assim
        uma falha antes do áudio ainda pode cair para outro modelo (ou para a voz local)."""
        voice = voice or self.default_voice
        limit = self.p.settings.gemini_first_token_timeout_s

        async def call(model: str, contents: Any) -> tuple[bytes, Any, int]:
            stream = await asyncio.wait_for(self.p.client.aio.models.generate_content_stream(model=model, contents=contents, config=self._config(voice)), limit)
            it = stream.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(it.__anext__(), limit)
                except StopAsyncIteration:
                    raise TTSError("empty", "O Gemini TTS não devolveu áudio.") from None
                data, mime = _audio_of(chunk)
                if data:
                    rate = parse_rate(mime)
                    if data[:4] == b"RIFF":   # alguns modelos mandam o 1º pedaço com cabeçalho WAV
                        rate = int(wav_info(data)["sample_rate"])
                        data = data[44:]
                    return data, it, rate

        model, (first, it, rate) = await self._attempts(text, voice, style, speed, call)
        timeout = self.p.settings.gemini_timeout_s

        async def rest() -> AsyncIterator[bytes]:
            while True:
                try:
                    chunk = await asyncio.wait_for(it.__anext__(), timeout)
                except StopAsyncIteration:
                    return
                except Exception as exc:
                    raise self._fail(map_gemini_error(exc)) from None
                data, _ = _audio_of(chunk)
                if data:
                    yield data

        return TTSStream(first, rest(), rate, self.id, voice, model, True)


def _audio_of(chunk: Any) -> tuple[bytes, str]:
    for cand in getattr(chunk, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            blob = getattr(part, "inline_data", None)
            if blob is not None and blob.data:
                return blob.data, blob.mime_type or ""
    return b"", ""


ESPEAK_VOICES = [("pt-br", "Português (Brasil) — padrão"), ("pt-br+m3", "Português (Brasil) — grave"), ("pt-br+m7", "Português (Brasil) — encorpada")]


class LocalTTS(TTSEngine):
    id, label, cloud = "local", "Voz local (offline)", False

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self._sapi_voices: list[dict[str, str]] | None = None
        self._backend = "sapi" if sys.platform == "win32" else ("espeak" if self._espeak else "none")

    def available(self) -> tuple[bool, str]:
        if self._backend == "sapi":
            try:
                import pyttsx3  # noqa: F401
            except Exception:
                return False, "pyttsx3 não está instalado."
            return True, ""
        if self._backend == "espeak":
            return True, ""
        return False, "Nenhum sintetizador local encontrado (instale espeak-ng neste sistema)."

    def voices(self) -> list[dict[str, str]]:
        if self._backend == "espeak":
            return [{"id": v, "label": label} for v, label in ESPEAK_VOICES]
        if self._backend == "sapi":
            if self._sapi_voices is None:
                self._sapi_voices = self._list_sapi()
            return self._sapi_voices
        return []

    @staticmethod
    def _list_sapi() -> list[dict[str, str]]:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            out = []
            for v in engine.getProperty("voices"):
                tag = f"{v.name} {getattr(v, 'languages', '')} {v.id}".lower()
                pt = any(k in tag for k in ("portug", "pt-br", "pt_br", "brazil", "brasil", "0416"))
                out.append({"id": v.id, "label": v.name + (" — pt-BR" if pt else ""), "pt": "1" if pt else "0"})
            out.sort(key=lambda v: v["pt"], reverse=True)
            return [{"id": v["id"], "label": v["label"]} for v in out]
        except Exception:
            return []

    async def synthesize(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSResult:
        ok, reason = self.available()
        if not ok:
            raise TTSError("unavailable", reason)
        wav, used = await asyncio.to_thread(self._synth_blocking, text, voice, speed)
        return TTSResult(wav, float(wav_info(wav)["duration_s"]), self.id, used, False)

    def _synth_blocking(self, text: str, voice: str | None, speed: float = 1.0) -> tuple[bytes, str]:
        speed = max(0.7, min(1.4, float(speed or 1.0)))
        with self._lock, tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fala.wav")
            if self._backend == "espeak":
                allowed = {v for v, _ in ESPEAK_VOICES}
                used = voice if voice in allowed else "pt-br+m3"
                try:
                    subprocess.run([self._espeak, "-v", used, "-s", str(round(150 * speed)), "-p", "38", "-w", path, "--stdin"], input=text.encode("utf-8"), check=True, timeout=30, capture_output=True)
                except (subprocess.SubprocessError, OSError) as exc:
                    raise TTSError("local_failed", f"O sintetizador local falhou ({type(exc).__name__}).") from None
            else:
                try:
                    import pyttsx3

                    engine = pyttsx3.init()
                    known = {v["id"] for v in self.voices()}
                    used = voice if voice in known else (self.voices()[0]["id"] if self.voices() else "")
                    if used:
                        engine.setProperty("voice", used)
                    engine.setProperty("rate", round(172 * speed))
                    engine.save_to_file(text, path)
                    engine.runAndWait()
                    engine.stop()
                except Exception as exc:
                    raise TTSError("local_failed", f"A voz do Windows falhou ({type(exc).__name__}).") from None
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                raise TTSError("local_failed", "O sintetizador local não gerou áudio.") from None
        if len(data) < 100:
            raise TTSError("local_failed", "O sintetizador local não gerou áudio.")
        return data, used


class PiperTTS(TTSEngine):
    """Voz neural local (Piper, offline e gratuita). Reserva quando o Gemini TTS não responde ou
    está sem cota. Modelos .onnx (+ .onnx.json) em backend/models/piper — baixados pelo
    INSTALAR_RECURSOS_LOCAIS.bat. Padrão: pt_BR-faber-medium (masculina)."""

    id, label, cloud = "piper", "Piper (voz neural local)", False
    DEFAULT = "pt_BR-faber-medium"

    def __init__(self, models_dir: Path, model_path: Path | None = None, loader: Any = None):
        self.dir = Path(models_dir) / "piper"
        self.model_path = Path(model_path) if model_path else None
        self._loader = loader
        self._voices: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _models(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        if self.model_path and self.model_path.exists():
            found[self.model_path.stem] = self.model_path
        if self.dir.is_dir():
            for onnx in sorted(self.dir.glob("*.onnx")):
                if Path(str(onnx) + ".json").exists():
                    found.setdefault(onnx.stem, onnx)
        return found

    def available(self) -> tuple[bool, str]:
        if self._loader is None:
            try:
                import piper  # noqa: F401
            except Exception:
                return False, "piper-tts não está instalado (rode INSTALAR_RECURSOS_LOCAIS.bat)."
        if not self._models():
            return False, f"Nenhuma voz Piper em {self.dir} (rode INSTALAR_RECURSOS_LOCAIS.bat)."
        return True, ""

    def voices(self) -> list[dict[str, str]]:
        return [{"id": k, "label": k + (" — padrão" if k == self.DEFAULT else "")} for k in self._models()]

    def _voice(self, name: str) -> Any:
        if name not in self._voices:
            path = self._models()[name]
            if self._loader is not None:
                self._voices[name] = self._loader(path)
            else:
                from piper import PiperVoice

                self._voices[name] = PiperVoice.load(path)
        return self._voices[name]

    async def synthesize(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> TTSResult:
        ok, reason = self.available()
        if not ok:
            raise TTSError("unavailable", reason)
        models = self._models()
        name = voice if voice in models else (self.DEFAULT if self.DEFAULT in models else next(iter(models)))

        def run() -> bytes:
            with self._lock:
                engine = self._voice(name)
                try:
                    from piper import SynthesisConfig

                    cfg = SynthesisConfig(length_scale=1.0 / max(0.7, min(1.4, speed)))
                except Exception:
                    cfg = None
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    engine.synthesize_wav(text, w, syn_config=cfg)
                return buf.getvalue()

        try:
            wav = await asyncio.to_thread(run)
        except Exception as exc:
            raise TTSError("local_failed", f"A voz Piper falhou ({type(exc).__name__}).") from None
        return TTSResult(wav, float(wav_info(wav)["duration_s"]), self.id, name, False, "piper")


class VoiceOutput:
    """Escolhe o motor conforme a preferência ('auto' | 'gemini' | 'piper' | 'local' | 'off').

    Ordem no automático: Gemini (nuvem) → Piper (neural local) → voz do sistema (SAPI/espeak)."""

    ORDER = ("gemini", "piper", "local")

    def __init__(self, gemini: GeminiTTS | None, local: LocalTTS | None, piper: PiperTTS | None = None):
        self.engines: dict[str, TTSEngine] = {}
        if gemini:
            self.engines["gemini"] = gemini
        if piper:
            self.engines["piper"] = piper
        if local:
            self.engines["local"] = local

    def resolve(self, preference: str) -> TTSEngine | None:
        if preference == "off":
            return None
        if preference in self.engines and self.engines[preference].available()[0]:
            return self.engines[preference]
        if preference == "auto":
            for key in self.ORDER:
                if key in self.engines and self.engines[key].available()[0]:
                    return self.engines[key]
        return None

    def resolve_offline(self) -> TTSEngine | None:
        """Primeiro motor LOCAL disponível na ordem (Piper → voz do sistema). Usado nas respostas
        de comandos do roteador no modo automático, para não gastar a cota do Gemini TTS."""
        for key in self.ORDER:
            engine = self.engines.get(key)
            if engine and not engine.cloud and engine.available()[0]:
                return engine
        return None

    def fallback_for(self, engine: TTSEngine, preference: str) -> TTSEngine | None:
        """No modo automático, se um motor falhar, a fala continua pelo próximo da ordem."""
        if preference != "auto" or engine.id not in self.ORDER:
            return None
        for key in self.ORDER[self.ORDER.index(engine.id) + 1:]:
            nxt = self.engines.get(key)
            if nxt and nxt.available()[0]:
                return nxt
        return None

    def describe(self) -> list[dict[str, Any]]:
        return [e.describe() for e in self.engines.values()]
