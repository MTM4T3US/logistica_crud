"""Síntese de voz. Dois motores atrás da mesma interface:

- GeminiTTS (nuvem): vozes predefinidas com direção de estilo em linguagem natural.
- LocalTTS (offline, gratuito): SAPI5 no Windows via pyttsx3; espeak-ng em Linux/macOS.

O toque "tecnológico" e o controle de velocidade/volume são aplicados no HUD (Web Audio),
para que o timbre original do motor fique preservado e ajustável em tempo real.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from google.genai import types

from ..ai.base import AIError
from ..ai.gemini_provider import GeminiProvider, map_gemini_error
from .audio_stream import parse_rate, pcm16_to_wav, wav_info

#: Direção de voz enviada ao Gemini TTS junto com o texto (identidade vocal original).
STYLE_PROMPT = (
    "Leia o texto a seguir em português do Brasil, com dicção brasileira natural e perfeitamente compreensível. "
    "Voz masculina adulta, registro médio-grave, timbre encorpado e elegante. Tom calmo, confiante e cortês, "
    "como um assistente sofisticado: pronúncia clara e precisa, ritmo moderado com pausas naturais, "
    "sem soar robótico nem teatral. Diga somente o texto, sem acrescentar nada:"
)

#: Vozes predefinidas do Gemini TTS sugeridas para o perfil pedido. A percepção de timbre
#: é subjetiva — compare as amostras (scripts/voice_samples.py) antes de escolher.
GEMINI_VOICES: list[tuple[str, str]] = [
    ("Charon", "informativa"), ("Orus", "firme"), ("Algieba", "suave"), ("Algenib", "grave, áspera"),
    ("Iapetus", "clara"), ("Rasalgethi", "informativa"), ("Schedar", "equilibrada"), ("Sadaltager", "culta"),
    ("Alnilam", "firme"), ("Enceladus", "soprosa"), ("Gacrux", "madura"), ("Fenrir", "enérgica"), ("Puck", "animada"),
]


class TTSError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class TTSResult:
    wav: bytes
    duration_s: float
    engine: str
    voice: str
    cloud: bool


class TTSEngine(ABC):
    id: str
    label: str
    cloud: bool

    @abstractmethod
    def available(self) -> tuple[bool, str]: ...

    @abstractmethod
    def voices(self) -> list[dict[str, str]]: ...

    @abstractmethod
    async def synthesize(self, text: str, voice: str | None = None) -> TTSResult: ...

    def describe(self) -> dict[str, Any]:
        ok, reason = self.available()
        return {"id": self.id, "label": self.label, "cloud": self.cloud, "available": ok, "reason": reason, "voices": self.voices() if ok else []}


class GeminiTTS(TTSEngine):
    id, label, cloud = "gemini", "Gemini TTS (nuvem)", True

    def __init__(self, provider: GeminiProvider, default_voice: str = "Charon", style: str = STYLE_PROMPT):
        self.p, self.default_voice, self.style = provider, default_voice, style

    def available(self) -> tuple[bool, str]:
        return True, ""

    def voices(self) -> list[dict[str, str]]:
        return [{"id": v, "label": f"{v} — {note}"} for v, note in GEMINI_VOICES]

    async def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        voice = voice or self.default_voice
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        )
        try:
            resp = await asyncio.wait_for(
                self.p.client.aio.models.generate_content(model=self.p.tts_model, contents=f"{self.style}\n\n{text}", config=config),
                timeout=self.p.settings.gemini_timeout_s,
            )
            part = resp.candidates[0].content.parts[0]
            pcm, mime = part.inline_data.data, part.inline_data.mime_type or ""
        except (AttributeError, IndexError, TypeError):
            raise TTSError("empty", "O Gemini TTS não devolveu áudio.") from None
        except Exception as exc:
            err: AIError = map_gemini_error(exc)
            raise TTSError(err.code, err.message.replace("O Gemini", "O Gemini TTS", 1)) from None
        if not pcm:
            raise TTSError("empty", "O Gemini TTS não devolveu áudio.")
        wav = pcm if pcm[:4] == b"RIFF" else pcm16_to_wav(pcm, parse_rate(mime))
        return TTSResult(wav, float(wav_info(wav)["duration_s"]), self.id, voice, True)


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

    async def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        ok, reason = self.available()
        if not ok:
            raise TTSError("unavailable", reason)
        wav, used = await asyncio.to_thread(self._synth_blocking, text, voice)
        return TTSResult(wav, float(wav_info(wav)["duration_s"]), self.id, used, False)

    def _synth_blocking(self, text: str, voice: str | None) -> tuple[bytes, str]:
        with self._lock, tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fala.wav")
            if self._backend == "espeak":
                allowed = {v for v, _ in ESPEAK_VOICES}
                used = voice if voice in allowed else "pt-br+m3"
                try:
                    subprocess.run([self._espeak, "-v", used, "-s", "150", "-p", "38", "-w", path, "--stdin"], input=text.encode("utf-8"), check=True, timeout=30, capture_output=True)
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
                    engine.setProperty("rate", 172)
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


class VoiceOutput:
    """Escolhe o motor conforme a preferência ('auto' | 'gemini' | 'local' | 'off')."""

    def __init__(self, gemini: GeminiTTS | None, local: LocalTTS | None):
        self.engines: dict[str, TTSEngine] = {}
        if gemini:
            self.engines["gemini"] = gemini
        if local:
            self.engines["local"] = local

    def resolve(self, preference: str) -> TTSEngine | None:
        if preference == "off":
            return None
        if preference in self.engines and self.engines[preference].available()[0]:
            return self.engines[preference]
        if preference == "auto":
            for key in ("gemini", "local"):
                if key in self.engines and self.engines[key].available()[0]:
                    return self.engines[key]
        return None

    def fallback_for(self, engine: TTSEngine, preference: str) -> TTSEngine | None:
        """No modo 'auto', se a nuvem falhar, a fala continua pela voz local."""
        if preference == "auto" and engine.id == "gemini":
            local = self.engines.get("local")
            if local and local.available()[0]:
                return local
        return None

    def describe(self) -> list[dict[str, Any]]:
        return [e.describe() for e in self.engines.values()]
