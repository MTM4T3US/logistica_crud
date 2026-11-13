"""Reconhecimento de fala (pt-BR) atrás de uma interface única.

- GeminiSTT: transcrição na nuvem (o HUD avisa e exige consentimento antes de enviar áudio).
- WhisperSTT: local, opcional — requer `pip install faster-whisper` e baixa o modelo no 1º uso.

Também contém a detecção da palavra de ativação ("Jarvis") sobre o texto transcrito.
"""
from __future__ import annotations

import asyncio
import io
import sys
import threading
from pathlib import Path
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


def response_text(resp: Any) -> str:
    """Texto de uma resposta de transcrição. Os modelos dedicados devolvem o resultado em
    partes `audio_transcription` (não em `text`) — descoberto na validação com a API real."""
    out: list[str] = []
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            heard = getattr(part, "audio_transcription", None)
            if heard is not None and getattr(heard, "text", None):
                out.append(heard.text)
            elif getattr(part, "text", None) and not getattr(part, "thought", False):
                out.append(part.text)
    return " ".join(out)


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
        if hasattr(self.p, "resolve_models"):
            await self.p.resolve_models()
        first = self._model or getattr(self.p, "stt_model", None) or self.p.model
        others = [m for m in (self.p.failover_chain() if hasattr(self.p, "failover_chain") else []) if m != first]
        cooling = getattr(self.p, "cooling", lambda _m: False)
        chain = [m for m in [first, *others] if not cooling(m)] or [first]
        last = STTError("unavailable", "Nenhum modelo do Gemini transcreveu o áudio.")
        audio = types.Part.from_bytes(data=wav, mime_type="audio/wav")
        for model in chain[:3]:
            # modelos dedicados ("transcribe") recebem só o áudio; os de conversa, áudio + instrução
            contents = [audio] if "transcribe" in model else [audio, TRANSCRIBE_PROMPT]
            try:
                resp = await asyncio.wait_for(
                    self.p.client.aio.models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(temperature=0.0)),
                    timeout=self.p.settings.gemini_timeout_s,
                )
                if hasattr(self.p, "count"):
                    self.p.count(model)
                return STTResult(clean_transcript(response_text(resp)), self.id, True)
            except Exception as exc:
                err = map_gemini_error(exc)
                last = STTError(err.code, err.message)
                if err.code == "rate_limit" and hasattr(self.p, "note_limit"):
                    self.p.note_limit(model, err)
                if err.code not in ("rate_limit", "unavailable", "timeout", "model_not_found"):
                    break
        raise last


def _cuda_libs_ok() -> bool:
    """No Windows, a GPU só serve ao faster-whisper se as DLLs do CUDA 12 (cuBLAS) e do cuDNN 9
    estiverem acessíveis. Sem elas o modelo carrega na GPU mas a transcrição falha ou trava."""
    if sys.platform != "win32":
        return True
    import ctypes

    for dll in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(dll)
        except OSError:
            return False
    return True


class WhisperSTT(STTEngine):
    """Transcrição 100% local com faster-whisper. O modelo fica em backend/models/whisper
    (baixado pelo INSTALAR_RECURSOS_LOCAIS.bat ou no 1º uso). Tenta a GPU (CUDA) quando pedido e
    volta para a CPU (int8) se as bibliotecas da NVIDIA não estiverem presentes."""

    id, label, cloud = "whisper", "Whisper local (offline)", False

    def __init__(self, model_size: str = "small", models_dir: Path | None = None, device: str = "auto", compute: str = "int8", factory: Any = None):
        self.model_size, self.device, self.compute = model_size, device, compute
        self.root = Path(models_dir) / "whisper" if models_dir else None
        self._factory = factory
        self._model: Any = None
        self.loaded_on: str | None = None
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if self._factory is not None:
            return True, ""
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False, "faster-whisper não está instalado (rode INSTALAR_RECURSOS_LOCAIS.bat)."
        return True, ""

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        make = self._factory
        if make is None:
            from faster_whisper import WhisperModel

            def make(size: str, device: str, compute: str) -> Any:
                return WhisperModel(size, device=device, compute_type=compute, download_root=str(self.root) if self.root else None)

        want_cuda = self.device == "cuda" or (self.device == "auto" and (self._factory is not None or _cuda_libs_ok()))
        attempts = [("cuda", "float16"), ("cpu", self.compute)] if want_cuda else [("cpu", self.compute)]
        last: Exception | None = None
        for device, compute in attempts:
            try:
                self._model = make(self.model_size, device, compute)
                self.loaded_on = f"{device}/{compute}"
                return self._model
            except Exception as exc:  # sem CUDA/cuDNN: segue para a CPU
                last = exc
        raise last or RuntimeError("faster-whisper não carregou")

    @staticmethod
    def _audio(wav: bytes) -> Any:
        """WAV 16 bits -> float32 mono 16 kHz (o que o faster-whisper espera), sem passar pelo PyAV.
        O faster-whisper 1.2 chama av.open(..., metadata_errors=...), que o PyAV 15+ não aceita mais
        (TypeError no Windows com av 19). Outros formatos seguem para o decodificador dele."""
        try:
            from .wake import pcm16_mono_16k

            return pcm16_mono_16k(wav).astype("float32") / 32768.0
        except Exception:
            return io.BytesIO(wav)

    def _run(self, model: Any, wav: bytes) -> str:
        segments, _ = model.transcribe(
            self._audio(wav), language="pt", beam_size=1, vad_filter=True, condition_on_previous_text=False,
            initial_prompt="Jarvis, assistente pessoal.",
        )
        return " ".join(s.text.strip() for s in segments)

    def _transcribe_blocking(self, wav: bytes) -> str:
        with self._lock:
            model = self._load()
            try:
                return self._run(model, wav)
            except Exception:
                # o modelo pode CARREGAR na GPU e só falhar ao transcrever (ex.: Windows sem
                # cublas64_12.dll). Volta para a CPU uma vez, com um modelo novo, e fica nela.
                if not (self.loaded_on or "").startswith("cuda"):
                    raise
                self._model, self.device = None, "cpu"
                return self._run(self._load(), wav)

    async def transcribe(self, wav: bytes, language: str = "pt-BR") -> STTResult:
        ok, reason = self.available()
        if not ok:
            raise STTError("unavailable", reason)
        try:
            text = await asyncio.to_thread(self._transcribe_blocking, wav)
        except Exception as exc:
            raise STTError("local_failed", f"A transcrição local falhou ({type(exc).__name__}: {str(exc)[:120]}).") from None
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
            # local primeiro: privacidade e nenhuma cota gasta
            for key in ("whisper", "gemini"):
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
