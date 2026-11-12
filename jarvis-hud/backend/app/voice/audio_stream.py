"""Utilitários de áudio e de texto falado: WAV, nível, divisão em frases para TTS incremental."""
from __future__ import annotations

import array
import io
import math
import re
import wave


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_info(data: bytes) -> dict[str, float | int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        frames, rate = w.getnframes(), w.getframerate()
        return {"sample_rate": rate, "channels": w.getnchannels(), "sample_width": w.getsampwidth(), "frames": frames, "duration_s": frames / rate if rate else 0.0}


def wav_rms(data: bytes) -> float:
    """Nível RMS 0..1 de um WAV 16 bits — usado para descartar gravações em silêncio."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            return 0.0
        samples = array.array("h", w.readframes(w.getnframes()))
    if not samples:
        return 0.0
    step = max(1, len(samples) // 20000)
    picked = samples[::step]
    return math.sqrt(sum(s * s for s in picked) / len(picked)) / 32768.0


def parse_rate(mime: str, default: int = 24000) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else default


_MD = re.compile(r"(\*\*|__|\*|_|`{1,3}|^#{1,6}\s*|^\s*[-•]\s+)", re.MULTILINE)
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def speakable(text: str) -> str:
    """Remove marcações que um sintetizador leria em voz alta (markdown, URLs, emojis)."""
    text = _URL.sub("o link indicado", text)
    text = _MD.sub("", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


_UNITS = [
    (re.compile(r"(\d)\s*°\s*C\b"), r"\1 graus"), (re.compile(r"(\d)\s*°"), r"\1 graus"),
    (re.compile(r"(\d)\s*km/h\b", re.I), r"\1 quilômetros por hora"), (re.compile(r"(\d)\s*m/s\b"), r"\1 metros por segundo"),
    (re.compile(r"(\d)\s*GB\b"), r"\1 gigabytes"), (re.compile(r"(\d)\s*MB\b"), r"\1 megabytes"), (re.compile(r"(\d)\s*TB\b"), r"\1 terabytes"),
    (re.compile(r"(\d)\s*GHz\b"), r"\1 gigahertz"), (re.compile(r"(\d)\s*MHz\b"), r"\1 megahertz"),
    (re.compile(r"(\d)\s*mm\b"), r"\1 milímetros"), (re.compile(r"(\d)\s*%"), r"\1 por cento"),
]
_TIME = re.compile(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b")
_DECIMAL = re.compile(r"(\d)\.(\d)")


def _say_time(m: re.Match) -> str:
    hour, minute = int(m.group(1)), int(m.group(2))
    if minute == 0:
        return f"{hour} hora" if hour == 1 else f"{hour} horas"
    return f"{hour} e {minute}"


def normalize_for_speech(text: str) -> str:
    """Reescreve o que os sintetizadores costumam ler mal em português (unidades, horas,
    símbolos) e transforma travessões e parênteses em pausas. A legenda mantém o original."""
    text = _TIME.sub(_say_time, text)
    for pattern, repl in _UNITS:
        text = pattern.sub(repl, text)
    text = _DECIMAL.sub(r"\1,\2", text)                       # 22.5 → 22,5 (lido "vinte e dois vírgula cinco")
    text = re.sub(r"\s*[—–]\s*", ", ", text)                   # travessão vira pausa curta
    text = re.sub(r"\s*\(([^)]*)\)", r", \1,", text)           # parênteses viram um aparte entre pausas
    text = re.sub(r"\bJARVIS\b", "Jarvis", text)
    text = text.replace("&", " e ").replace("/", " por ") if re.search(r"\d\s*/\s*\d", text) is None else text.replace("&", " e ")
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceChunker:
    """Recebe o texto da IA em pedaços e devolve frases completas assim que terminam,
    para a fala começar antes de a resposta inteira chegar."""

    # ":" e ";" não encerram frase: cortar ali deixava pausas artificiais na fala
    _END = re.compile(r"(.+?[.!?…](?:[\"'”)\]]+)?)(?:\s+|$)", re.DOTALL)

    def __init__(self, min_chars: int = 28, max_chars: int = 260, first_min_chars: int = 8) -> None:
        self.min_chars, self.max_chars, self.first_min_chars = min_chars, max_chars, first_min_chars
        self._buf = ""
        self._emitted = 0  # a primeira frase pode ser curta: a fala começa antes

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            m = self._END.match(self._buf)
            if m and m.end() < len(self._buf) or (m and self._buf.endswith(("\n", " "))):
                sentence = m.group(1).strip()
                rest = self._buf[m.end():]
                # não quebra em abreviações/números ("Sr.", "3.5") nem em frases curtas demais
                floor = self.min_chars if self._emitted else self.first_min_chars
                if len(sentence) < floor and rest.strip():
                    nxt = self._END.match(rest)
                    if nxt and (nxt.end() < len(rest) or rest.endswith(("\n", " "))):
                        sentence = (sentence + " " + nxt.group(1)).strip()
                        rest = rest[nxt.end():]
                    else:
                        break
                out.append(sentence)
                self._emitted += 1
                self._buf = rest
                continue
            if len(self._buf) > self.max_chars:
                cut = self._buf.rfind(",", 0, self.max_chars)
                cut = cut if cut > self.min_chars else self._buf.rfind(" ", 0, self.max_chars)
                if cut <= 0:
                    break
                out.append(self._buf[: cut + 1].strip())
                self._buf = self._buf[cut + 1:]
                continue
            break
        return [s for s in out if s]

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []
