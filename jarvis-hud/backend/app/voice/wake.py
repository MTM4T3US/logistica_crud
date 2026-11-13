"""Detecção LOCAL da palavra de ativação ("Jarvis") — roda no computador, antes de qualquer
envio de áudio à nuvem. Se não houver detector local, a escuta contínua fica indisponível
(nunca cai para a nuvem).

Motores:
- openWakeWord (padrão): modelo "hey_jarvis" que já vem no pacote `openwakeword`. Em teste real
  com voz natural, "Jarvis, que horas são?" pontuou 0,996 e frases sem a palavra ≤ 0,001.
- Whisper local: transcreve o trecho no computador e procura "Jarvis" no texto (mais lento).
"""
from __future__ import annotations

import asyncio
import io
import os
import threading
import wave
from dataclasses import dataclass
from typing import Any

from .stt import WhisperSTT, extract_wake_command


@dataclass
class WakeResult:
    detected: bool
    score: float
    engine: str


class WakeDetector:
    id = "base"
    label = ""

    def available(self) -> tuple[bool, str]:
        return False, "sem detector"

    async def detect(self, wav: bytes) -> WakeResult:  # pragma: no cover — interface
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        ok, reason = self.available()
        return {"id": self.id, "label": self.label, "available": ok, "reason": reason, "local": True}


def pcm16_mono_16k(wav: bytes):
    """Lê um WAV 16 bits e devolve amostras int16 a 16 kHz mono (reamostragem linear se preciso)."""
    import numpy as np

    with wave.open(io.BytesIO(wav), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("WAV precisa ser 16 bits")
    x = np.frombuffer(raw, dtype="<i2")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if rate != 16000 and len(x):
        n = int(len(x) * 16000 / rate)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)
    return x


class OpenWakeWordDetector(WakeDetector):
    id, label = "openwakeword", "openWakeWord (local)"

    def __init__(self, threshold: float = 0.5, model_path: str | None = None, factory: Any = None):
        self.threshold = threshold
        self.model_path = model_path
        self._factory = factory
        self._model: Any = None
        self._lock = threading.Lock()

    def _path(self) -> str | None:
        if self.model_path:
            return self.model_path if os.path.exists(self.model_path) else None
        try:
            import openwakeword

            path = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", "hey_jarvis_v0.1.onnx")
            return path if os.path.exists(path) else None
        except Exception:
            return None

    def available(self) -> tuple[bool, str]:
        if self._factory is not None:
            return True, ""
        try:
            import numpy  # noqa: F401
            import openwakeword  # noqa: F401
        except Exception:
            return False, "openwakeword não está instalado (rode INSTALAR_RECURSOS_LOCAIS.bat)."
        if not self._path():
            return False, "Modelo de palavra-chave não encontrado."
        return True, ""

    def _load(self) -> Any:
        if self._model is None:
            if self._factory is not None:
                self._model = self._factory()
            else:
                from importlib.metadata import version

                from openwakeword.model import Model

                # openwakeword >= 0.5 usa `wakeword_models` e, por padrão, tflite (que não existe no
                # Windows); a 0.4 usava `wakeword_model_paths` e só ONNX.
                try:
                    major, minor = (int(p) for p in version("openwakeword").split(".")[:2])
                except Exception:
                    major, minor = 0, 6
                if (major, minor) >= (0, 5):
                    self._model = Model(wakeword_models=[self._path()], inference_framework="onnx")
                else:
                    self._model = Model(wakeword_model_paths=[self._path()])
        return self._model

    def _score(self, wav: bytes) -> float:
        import numpy as np

        x = pcm16_mono_16k(wav)
        # um pouco de silêncio antes e depois: o modelo precisa de contexto nas bordas
        x = np.concatenate([np.zeros(8000, np.int16), x, np.zeros(16000, np.int16)])
        with self._lock:
            model = self._load()
            if hasattr(model, "reset"):
                model.reset()
            best = 0.0
            for i in range(0, len(x) - 1280 + 1, 1280):
                scores = model.predict(x[i:i + 1280])
                best = max(best, max(scores.values()) if scores else 0.0)
        return float(best)

    async def detect(self, wav: bytes) -> WakeResult:
        score = await asyncio.to_thread(self._score, wav)
        return WakeResult(score >= self.threshold, round(score, 3), self.id)


class WhisperWakeDetector(WakeDetector):
    id, label = "whisper", "Whisper local (transcreve e procura “Jarvis”)"

    def __init__(self, whisper: WhisperSTT, wake_word: str = "jarvis"):
        self.whisper, self.wake_word = whisper, wake_word
        self.last_text = ""

    def available(self) -> tuple[bool, str]:
        return self.whisper.available()

    async def detect(self, wav: bytes) -> WakeResult:
        result = await self.whisper.transcribe(wav)
        self.last_text = result.text
        hit = extract_wake_command(result.text, self.wake_word) is not None
        return WakeResult(hit, 1.0 if hit else 0.0, self.id)


def make_wake_detector(engine: str, threshold: float, model_path: str | None, whisper: WhisperSTT | None, wake_word: str) -> WakeDetector | None:
    """Escolhe o detector local conforme a configuração. None = escuta contínua indisponível."""
    if engine == "off":
        return None
    candidates: list[WakeDetector] = []
    if engine in ("auto", "openwakeword"):
        candidates.append(OpenWakeWordDetector(threshold, model_path))
    if engine in ("auto", "whisper") and whisper is not None:
        candidates.append(WhisperWakeDetector(whisper, wake_word))
    for det in candidates:
        if det.available()[0]:
            return det
    return candidates[0] if candidates else None
