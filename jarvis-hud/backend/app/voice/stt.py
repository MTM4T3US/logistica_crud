"""Reconhecimento de fala (pt-BR) atrás de uma interface única.

- GeminiSTT: transcrição na nuvem (o HUD avisa e exige consentimento antes de enviar áudio).
- WhisperSTT: local, opcional — requer `pip install faster-whisper` e baixa o modelo no 1º uso.

Também contém a detecção da palavra de ativação ("Jarvis") sobre o texto transcrito.
"""
from __future__ import annotations

import asyncio
import io
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from google.genai import types

from ..ai.gemini_provider import GeminiProvider, map_gemini_error

TRANSCRIBE_PROMPT = (
    "Transcreva literalmente a fala deste áudio em português do Brasil. Responda somente com a transcrição, "
    "sem aspas, comentários ou descrições de ruído. Se não houver fala inteligível, responda exatamente: [silêncio]"
)


class STTError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class STTResult:
    text: str
    engine: str
    cloud: bool


class STTEngine(ABC):
    id: str
    label: str
    cloud: bool

    @abstractmethod
    def available(self) -> tuple[bool, str]: ...

    @abstractmethod
    async def transcribe(self, wav: bytes, language: str = "pt-BR") -> STTResult: ...

    def describe(self) -> dict[str, Any]:
        ok, reason = self.available()
        return {"id": self.id, "label": self.label, "cloud": self.cloud, "available": ok, "reason": reason}


def clean_transcript(text: str) -> str:
    text = (text or "").strip().strip('"“”')
    if re.fullmatch(r"\[?\s*sil[eê]ncio\s*\]?\.?", text, flags=re.IGNORECASE):
        return ""
    return re.sub(r"\s+", " ", text)


class GeminiSTT(STTEngine):
    id, label, cloud = "gemini", "Gemini (nuvem)", True

    def __init__(self, provider: GeminiProvider, model: str | None = None):
        self.p, self._model = provider, model

    def available(self) -> tuple[bool, str]:
        return True, ""

    async def transcribe(self, wav: bytes, language: str = "pt-BR") -> STTResult:
        try:
            resp = await asyncio.wait_for(
                self.p.client.aio.models.generate_content(
                    model=self._model or self.p.model,
                    contents=[types.Part.from_bytes(data=wav, mime_type="audio/wav"), TRANSCRIBE_PROMPT],
                    config=types.GenerateContentConfig(temperature=0.0),
                ),
                timeout=self.p.settings.gemini_timeout_s,
            )
            text = resp.text or ""
        except Exception as exc:
            err = map_gemini_error(exc)
            raise STTError(err.code, err.message) from None
        return STTResult(clean_transcript(text), self.id, True)


class WhisperSTT(STTEngine):
    id, label, cloud = "whisper", "Whisper local (offline)", False

    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self._model: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False, "faster-whisper não está instalado (pip install faster-whisper)."
        return True, ""

    def _transcribe_blocking(self, wav: bytes) -> str:
        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(self.model_size, device="auto", compute_type="auto")
        segments, _ = self._model.transcribe(io.BytesIO(wav), language="pt", vad_filter=True)
        return " ".join(s.text.strip() for s in segments)

    async def transcribe(self, wav: bytes, language: str = "pt-BR") -> STTResult:
        ok, reason = self.available()
        if not ok:
            raise STTError("unavailable", reason)
        try:
            text = await asyncio.to_thread(self._transcribe_blocking, wav)
        except Exception as exc:
            raise STTError("local_failed", f"A transcrição local falhou ({type(exc).__name__}).") from None
        return STTResult(clean_transcript(text), self.id, False)


class VoiceInput:
    def __init__(self, gemini: GeminiSTT | None, whisper: WhisperSTT | None):
        self.engines: dict[str, STTEngine] = {}
        if whisper:
            self.engines["whisper"] = whisper
        if gemini:
            self.engines["gemini"] = gemini

    def resolve(self, preference: str) -> STTEngine | None:
        if preference == "off":
            return None
        if preference in self.engines and self.engines[preference].available()[0]:
            return self.engines[preference]
        if preference == "auto":
            for key in ("gemini", "whisper"):
                if key in self.engines and self.engines[key].available()[0]:
                    return self.engines[key]
        return None

    def describe(self) -> list[dict[str, Any]]:
        return [e.describe() for e in self.engines.values()]


# ------------------------------------------------------------------ palavra de ativação
def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


#: como reconhecedores costumam grafar "Jarvis" em português
_WAKE_VARIANTS = {"jarvis": r"(?:d?jarv[ie]s|jarvi[sz]|jarves|jarbas|jarvys|jar vis|charvis|javis)"}


def extract_wake_command(text: str, wake: str = "jarvis") -> str | None:
    """Se a frase contém a palavra de ativação, devolve o comando sem ela; senão, None.

    "Jarvis, que horas são?" → "que horas são?"   |   "que horas são, Jarvis" → "que horas são"
    "Jarvis" → "" (só chamou)                     |   "que horas são" → None (ignorar)
    """
    folded = _fold(text)
    pattern = _WAKE_VARIANTS.get(_fold(wake), re.escape(_fold(wake)))
    m = re.search(rf"(?<![a-z]){pattern}(?![a-z])", folded)
    if not m:
        return None
    # _fold preserva o comprimento para caracteres pré-compostos comuns; se não bater, usa o texto dobrado
    src = text if len(text) == len(folded) else folded
    rest = (src[: m.start()] + " " + src[m.end():]).strip()
    rest = re.sub(r"^[\s,.:;!?-]+|[\s,;:-]+$", "", rest)
    rest = re.sub(r"\s+,", ",", re.sub(r"\s{2,}", " ", rest))
    return rest
