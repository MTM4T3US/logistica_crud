"""Áudio e voz: WAV, divisão em frases, palavra de ativação, motores de síntese/transcrição."""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest
from google.genai import types

from app.config import Settings
from app.voice.audio_stream import SentenceChunker, parse_rate, pcm16_to_wav, speakable, wav_info, wav_rms
from app.voice.stt import GeminiSTT, STTError, VoiceInput, WhisperSTT, clean_transcript, extract_wake_command
from app.voice.tts import STYLE_PROMPT, GeminiTTS, LocalTTS, TTSError, VoiceOutput

from .conftest import FakeSTT, FakeTTS, tone_wav
from .test_gemini_provider import api_error


def test_wav_helpers():
    wav = pcm16_to_wav(b"\x00\x00" * 24000, 24000)
    info = wav_info(wav)
    assert info["sample_rate"] == 24000 and info["channels"] == 1 and abs(info["duration_s"] - 1.0) < 1e-6
    assert wav_rms(wav) == 0.0 and 0.15 < wav_rms(tone_wav(amp=0.3)) < 0.25
    assert parse_rate("audio/L16;codec=pcm;rate=24000") == 24000 and parse_rate("audio/wav") == 24000


def test_sentence_chunker_emits_complete_sentences_while_streaming():
    c = SentenceChunker()
    out: list[str] = []
    for piece in ["Bom dia, sen", "hor. Todos os sistemas estão ", "operacionais. Em que posso", " ajudá-lo?"]:
        out += c.feed(piece)
    assert out == ["Bom dia, senhor. Todos os sistemas estão operacionais."] and c.flush() == ["Em que posso ajudá-lo?"]
    c = SentenceChunker()
    assert c.feed("A temperatura é de 22.5 graus agora em Itumbiara, senhor. ") == ["A temperatura é de 22.5 graus agora em Itumbiara, senhor."]
    long = SentenceChunker(max_chars=60)
    parts = long.feed("palavra " * 30)
    assert parts and all(len(p) <= 60 for p in parts)
    assert SentenceChunker().flush() == []
    colon = SentenceChunker()
    assert colon.feed("No modo local eu entendo apenas: hora, clima e sistema (atual: linux). ") == ["No modo local eu entendo apenas: hora, clima e sistema (atual: linux)."]


def test_speakable_strips_markup():
    assert speakable("**Pronto**, senhor! Veja https://exemplo.com/x 🚀\n- item `código`") == "Pronto, senhor! Veja o link indicado item código"


@pytest.mark.parametrize(
    "said, expected",
    [
        ("Jarvis, que horas são?", "que horas são?"),
        ("que horas são, Jarvis", "que horas são"),
        ("Járvis abre o bloco de notas", "abre o bloco de notas"),
        ("ei jarves como está o tempo", "ei como está o tempo"),
        ("Jarvis", ""),
        ("que horas são?", None),
        ("o jarvismo é curioso", None),
        ("", None),
    ],
)
def test_wake_word(said, expected):
    assert extract_wake_command(said) == expected


def test_clean_transcript():
    assert clean_transcript(' "Olá,   Jarvis" ') == "Olá, Jarvis" and clean_transcript("[silêncio]") == "" and clean_transcript("Silencio.") == "" and clean_transcript(None) == ""


def fake_provider(result=None, error=None):
    calls = []

    async def generate_content(**kw):
        calls.append(kw)
        if error:
            raise error
        return result

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    return SimpleNamespace(client=client, tts_model="tts-x", model="flash-x", settings=Settings(gemini_timeout_s=2.0)), calls


async def test_gemini_tts_wraps_pcm_and_sends_voice_and_style():
    pcm = b"\x10\x00" * 12000
    resp = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(inline_data=types.Blob(data=pcm, mime_type="audio/L16;codec=pcm;rate=24000"))]))])
    p, calls = fake_provider(resp)
    out = await GeminiTTS(p, "Charon").synthesize("Boa noite, senhor.", "Orus")
    assert out.wav[:4] == b"RIFF" and abs(out.duration_s - 0.5) < 1e-6 and (out.engine, out.voice, out.cloud) == ("gemini", "Orus", True)
    cfg = calls[0]["config"]
    assert calls[0]["model"] == "tts-x" and cfg.response_modalities == ["AUDIO"] and cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Orus"
    assert calls[0]["contents"].startswith(STYLE_PROMPT) and calls[0]["contents"].endswith("Boa noite, senhor.")
    assert "português do Brasil" in STYLE_PROMPT and "médio-grave" in STYLE_PROMPT
    assert {v["id"] for v in GeminiTTS(p).voices()} >= {"Charon", "Orus"}


async def test_gemini_tts_errors_are_translated():
    p, _ = fake_provider(error=api_error(429, "RESOURCE_EXHAUSTED"))
    with pytest.raises(TTSError) as e:
        await GeminiTTS(p).synthesize("oi")
    assert e.value.code == "rate_limit"
    p, _ = fake_provider(types.GenerateContentResponse(candidates=[]))
    with pytest.raises(TTSError) as e:
        await GeminiTTS(p).synthesize("oi")
    assert e.value.code == "empty"


async def test_gemini_stt_sends_wav_and_cleans_text():
    resp = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part.from_text(text=' "Jarvis, bom dia." ')]))])
    p, calls = fake_provider(resp)
    out = await GeminiSTT(p).transcribe(tone_wav())
    assert (out.text, out.engine, out.cloud) == ("Jarvis, bom dia.", "gemini", True)
    part = calls[0]["contents"][0]
    assert part.inline_data.mime_type == "audio/wav" and part.inline_data.data[:4] == b"RIFF" and calls[0]["model"] == "flash-x"
    p, _ = fake_provider(error=api_error(503, "UNAVAILABLE"))
    with pytest.raises(STTError) as e:
        await GeminiSTT(p).transcribe(tone_wav())
    assert e.value.code == "unavailable"


def test_engine_selection_and_fallback():
    cloud, local = FakeTTS("gemini", cloud=True), FakeTTS("local")
    out = VoiceOutput(None, None)
    out.engines = {"gemini": cloud, "local": local}
    assert out.resolve("auto") is cloud and out.resolve("local") is local and out.resolve("off") is None and out.resolve("inexistente") is None
    assert out.fallback_for(cloud, "auto") is local and out.fallback_for(cloud, "gemini") is None and out.fallback_for(local, "auto") is None
    only_local = VoiceOutput(None, None)
    only_local.engines = {"local": local}
    assert only_local.resolve("auto") is local and only_local.resolve("gemini") is None
    vin = VoiceInput(None, None)
    vin.engines = {"whisper": FakeSTT(engine_id="whisper"), "gemini": FakeSTT(engine_id="gemini", cloud=True)}
    assert vin.resolve("auto").id == "gemini" and vin.resolve("whisper").id == "whisper" and vin.resolve("off") is None
    assert VoiceInput(None, None).resolve("auto") is None


def test_whisper_reports_unavailable_when_not_installed():
    ok, reason = WhisperSTT().available()
    if not ok:
        assert "faster-whisper" in reason


@pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")), reason="espeak-ng não instalado")
async def test_local_tts_generates_real_speech_audio():
    tts = LocalTTS()
    assert tts.available() == (True, "") and tts.voices()
    out = await tts.synthesize("Bom dia, senhor. Todos os sistemas estão operacionais.")
    info = wav_info(out.wav)
    assert out.engine == "local" and out.cloud is False and info["duration_s"] > 1.5 and wav_rms(out.wav) > 0.01
    other = await tts.synthesize("Teste.", "voz-que-nao-existe; rm -rf /")
    assert other.voice == "pt-br+m3"
