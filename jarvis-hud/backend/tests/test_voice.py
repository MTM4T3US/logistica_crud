"""Áudio e voz: WAV, divisão em frases, palavra de ativação, motores de síntese/transcrição."""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest
from google.genai import types

from app.config import Settings
from app.voice.audio_stream import SentenceChunker, normalize_for_speech, parse_rate, pcm16_to_wav, speakable, wav_info, wav_rms
from app.voice.stt import GeminiSTT, STTError, VoiceInput, WhisperSTT, clean_transcript, extract_wake_command
from app.voice.tts import STYLE_PROMPT, STYLES, GeminiTTS, LocalTTS, TTSError, VoiceOutput

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
    # a primeira frase sai sozinha (a voz começa antes); as curtas seguintes são agrupadas
    assert out == ["Bom dia, senhor.", "Todos os sistemas estão operacionais."] and c.flush() == ["Em que posso ajudá-lo?"]
    grouped = SentenceChunker()
    assert grouped.feed("Certo. Sim. Feito, senhor, sem problemas. ") == ["Certo. Sim.", "Feito, senhor, sem problemas."]
    c = SentenceChunker()
    assert c.feed("A temperatura é de 22.5 graus agora em Itumbiara, senhor. ") == ["A temperatura é de 22.5 graus agora em Itumbiara, senhor."]
    long = SentenceChunker(max_chars=60)
    parts = long.feed("palavra " * 30)
    assert parts and all(len(p) <= 60 for p in parts)
    assert SentenceChunker().flush() == []
    colon = SentenceChunker()
    assert colon.feed("No modo local eu entendo apenas: hora, clima e sistema (atual: linux). ") == ["No modo local eu entendo apenas: hora, clima e sistema (atual: linux)."]


@pytest.mark.parametrize(
    "written, spoken",
    [
        ("São 07:18 em Itumbiara.", "São 7 e 18 em Itumbiara."),
        ("A reunião é às 14:00 e termina 1:00.", "A reunião é às 14 horas e termina 1 hora."),
        ("Faz 22.5°C, umidade de 87%.", "Faz 22,5 graus, umidade de 87 por cento."),
        ("Vento a 10 km/h; 29 GB livres.", "Vento a 10 quilômetros por hora; 29 gigabytes livres."),
        ("O JARVIS avisa — sem falta (prometo).", "O Jarvis avisa, sem falta, prometo."),
        ("Tudo certo, senhor.", "Tudo certo, senhor."),
    ],
)
def test_normalize_for_speech(written, spoken):
    assert normalize_for_speech(written) == spoken


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

    async def resolve_models(force: bool = False):
        return None

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    return SimpleNamespace(client=client, tts_model="tts-x", model="flash-x", settings=Settings(gemini_timeout_s=2.0), resolve_models=resolve_models), calls


def _audio_resp(pcm: bytes = b"\x10\x00" * 12000) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(inline_data=types.Blob(data=pcm, mime_type="audio/L16;codec=pcm;rate=24000"))]))])


async def test_gemini_tts_wraps_pcm_and_sends_voice_and_style():
    p, calls = fake_provider(_audio_resp())
    out = await GeminiTTS(p, "Charon").synthesize("Boa noite, senhor.", "Orus")
    assert out.wav[:4] == b"RIFF" and abs(out.duration_s - 0.5) < 1e-6 and (out.engine, out.voice, out.cloud, out.model) == ("gemini", "Orus", True, "tts-x")
    cfg = calls[0]["config"]
    assert calls[0]["model"] == "tts-x" and cfg.response_modalities == ["AUDIO"] and cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Orus"
    # a direção vai no campo de estilo; o texto a ser DITO é só a frase (defeito real corrigido:
    # com a direção junto do texto, o modelo lia a direção em voz alta — 33 s de instrução falada)
    part = calls[0]["contents"][0].parts[0]
    assert part.text == "Boa noite, senhor." and part.speech_metadata.style == STYLE_PROMPT
    assert "português do brasil" in STYLE_PROMPT.lower() and "médio-grave" in STYLE_PROMPT and "pausas" in STYLE_PROMPT
    await GeminiTTS(p).synthesize("Texto.", style="sobrio")
    assert calls[1]["contents"][0].parts[0].speech_metadata.style == STYLES["sobrio"][1]
    await GeminiTTS(p).synthesize("Texto puro.", style="neutro")
    assert calls[2]["contents"] == "Texto puro."
    await GeminiTTS(p, default_style="inexistente").synthesize("Texto.", style="também-não")
    assert calls[3]["contents"][0].parts[0].speech_metadata.style == STYLE_PROMPT
    assert [s["id"] for s in GeminiTTS(p).styles()] == ["cinematografico", "sobrio", "caloroso", "neutro"] and len(GeminiTTS(p).voices()) == 30


async def test_gemini_tts_without_style_support_speaks_only_the_text():
    seen = []

    async def generate_content(**kw):
        seen.append(kw["contents"])
        if not isinstance(kw["contents"], str):
            raise api_error(400, "INVALID_ARGUMENT", "speech_metadata is not supported")
        return _audio_resp()

    p, _ = fake_provider()
    p.client.aio.models.generate_content = generate_content
    p.tts_style_mode = {}
    out = await GeminiTTS(p).synthesize("Olá, senhor.")
    assert out.wav[:4] == b"RIFF" and seen[-1] == "Olá, senhor." and p.tts_style_mode == {"tts-x": "plain"}
    assert all(STYLE_PROMPT not in str(c) for c in seen if isinstance(c, str))   # a direção nunca vira fala
    seen.clear()
    await GeminiTTS(p).synthesize("De novo.")
    assert seen == ["De novo."]                                                    # lembrou: não tenta o estilo de novo


async def test_gemini_tts_moves_to_another_voice_model_when_quota_runs_out():
    used = []

    async def generate_content(**kw):
        used.append(kw["model"])
        if kw["model"] == "tts-novo":
            raise api_error(429, "RESOURCE_EXHAUSTED")
        return _audio_resp()

    p, _ = fake_provider()
    p.client.aio.models.generate_content = generate_content
    limited = []
    p.tts_chain = lambda: ["tts-novo", "tts-antigo"]
    p.note_limit = lambda model, err: limited.append((model, err.code))
    out = await GeminiTTS(p).synthesize("Olá.")
    assert used == ["tts-novo", "tts-antigo"] and out.model == "tts-antigo" and limited == [("tts-novo", "rate_limit")]


async def test_gemini_tts_errors_are_translated():
    p, _ = fake_provider(error=api_error(429, "RESOURCE_EXHAUSTED"))
    with pytest.raises(TTSError) as e:
        await GeminiTTS(p).synthesize("oi")
    assert e.value.code == "rate_limit"
    p, _ = fake_provider(types.GenerateContentResponse(candidates=[]))
    with pytest.raises(TTSError) as e:
        await GeminiTTS(p).synthesize("oi")
    assert e.value.code == "empty"


async def test_dedicated_transcription_model_answer_is_read():
    # formato real devolvido pelo gemini-3.5-transcribe: a fala vem em `audio_transcription`, não em `text`
    resp = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(audio_transcription=types.Transcription(text="Jarvis, que horas são?"))]))])
    p, calls = fake_provider(resp)
    p.stt_model = "transcritor-x"
    out = await GeminiSTT(p).transcribe(tone_wav())
    assert out.text == "Jarvis, que horas são?" and calls[0]["model"] == "transcritor-x" and len(calls[0]["contents"]) == 2
    p.stt_model = "gemini-3.5-transcribe"
    await GeminiSTT(p).transcribe(tone_wav())
    assert len(calls[1]["contents"]) == 1     # modelo dedicado recebe só o áudio


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
    # local primeiro: privacidade e nenhuma cota gasta
    assert vin.resolve("auto").id == "whisper" and vin.resolve("gemini").id == "gemini" and vin.resolve("off") is None
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


def test_speech_rate_goes_into_the_direction_not_the_text():
    from app.voice.tts import direction_for

    assert direction_for("cinematografico", "cinematografico", 1.0) == STYLE_PROMPT
    assert direction_for("cinematografico", "cinematografico", 0.85).endswith("Ritmo bem mais lento e pausado que o normal.")
    assert direction_for("neutro", "cinematografico", 1.2) == "Ritmo bem mais ágil que o normal, sem atropelar as palavras."
    assert direction_for("neutro", "cinematografico", 1.0) == ""


def _stream_chunk(data: bytes, mime: str = "audio/l16; rate=24000; channels=1") -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(inline_data=types.Blob(data=data, mime_type=mime))]))])


async def test_gemini_tts_streams_audio_pieces():
    p, _ = fake_provider()
    sent = []

    async def generate_content_stream(**kw):
        sent.append(kw)

        async def gen():
            for i in range(3):
                yield _stream_chunk(bytes([i, 0]) * 100)

        return gen()

    p.client.aio.models.generate_content_stream = generate_content_stream
    stream = await GeminiTTS(p).open_stream("Bom dia, senhor.", "Orus", speed=1.2)
    pieces = [c async for c in stream.chunks()]
    assert [x[:2] for x in pieces] == [bytes([0, 0]), bytes([1, 0]), bytes([2, 0])] and stream.rate == 24000 and stream.model == "tts-x"
    part = sent[0]["contents"][0].parts[0]
    assert part.text == "Bom dia, senhor." and "Ritmo bem mais ágil" in part.speech_metadata.style


async def test_gemini_tts_stream_falls_to_next_model_before_first_audio():
    p, _ = fake_provider()
    used = []

    async def generate_content_stream(**kw):
        used.append(kw["model"])
        if kw["model"] == "tts-novo":
            raise api_error(429, "RESOURCE_EXHAUSTED")

        async def gen():
            yield _stream_chunk(b"\x01\x00" * 50)

        return gen()

    p.client.aio.models.generate_content_stream = generate_content_stream
    p.tts_chain = lambda: ["tts-novo", "tts-antigo"]
    p.note_limit = lambda model, err: None
    stream = await GeminiTTS(p).open_stream("Olá.")
    assert used == ["tts-novo", "tts-antigo"] and stream.model == "tts-antigo"
