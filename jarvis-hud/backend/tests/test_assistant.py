"""Orquestração ponta a ponta com provedor roteirizado: eventos do HUD, registro e falhas."""
from __future__ import annotations

import asyncio
import base64

import pytest

from app.ai.base import AIError
from app.assistant import Assistant
from app.devices.registry import DeviceRegistry
from app.memory.store import MemoryStore
from app.services.weather import WeatherService
from app.voice.audio_stream import pcm16_to_wav
from app.voice.stt import STTError, VoiceInput
from app.voice.tts import VoiceOutput

from .conftest import FakeConn, FakeController, FakeSTT, FakeTTS, ScriptedProvider, call, tone_wav


def build(settings, perms, script=None, *, tts=None, stt=None, runtime=None, gemini="scripted"):
    provider = ScriptedProvider(script or []) if gemini == "scripted" else gemini
    out = VoiceOutput(None, None)
    out.engines = tts if tts is not None else {}
    vin = VoiceInput(None, None)
    vin.engines = stt if stt is not None else {}
    core = Assistant(
        settings, gemini=provider, memory=MemoryStore(":memory:"), perms=perms, controller=FakeController(), devices=DeviceRegistry(),
        weather=WeatherService(settings.location, enabled=False), tts=out, stt=vin,
    )
    core.update_runtime({"tts_engine": "auto", "stt_engine": "auto", **(runtime or {})})
    return core, provider


async def test_text_turn_streams_deltas_and_stores_history(settings, perms):
    core, provider = build(settings, perms, [["Bom dia, senhor. ", "Todos os sistemas estão operacionais."]])
    conn = FakeConn()
    await core.run_turn(conn, "Jarvis, bom dia.")
    assert conn.kinds() == ["transcript", "phase", "delta", "delta", "turn_end"]
    assert conn.of("transcript")[0] == {"type": "transcript", "role": "user", "text": "Jarvis, bom dia.", "source": "text"}
    end = conn.of("turn_end")[0]
    assert end["text"] == "Bom dia, senhor. Todos os sistemas estão operacionais." and end["mode"] == "ai" and end["error"] is None and end["spoken"] is False
    msgs = core.memory.recent_messages()
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "Jarvis, bom dia."), ("assistant", end["text"])]
    started = provider.started[0]
    assert "Itumbiara" in started["system"] and 'executed": true' in started["system"] and started["history"] == []
    await core.run_turn(FakeConn(), "e agora?")
    assert [m["content"] for m in provider.started[1]["history"]] == ["Jarvis, bom dia.", end["text"]]


async def test_tool_call_is_executed_logged_and_reported(settings, perms):
    script = [["Vou preparar seu ambiente. ", call("open_app", app_id="notas"), call("open_app", app_id="powershell")], ["O Bloco de Notas está aberto."]]
    core, provider = build(settings, perms, script)
    conn = FakeConn()
    await core.run_turn(conn, "abre o bloco de notas e o powershell")
    tools = conn.of("tool")
    assert [(t["stage"], t["name"]) for t in tools] == [("start", "open_app"), ("end", "open_app"), ("start", "open_app"), ("end", "open_app")]
    assert tools[1]["executed"] is True and tools[1]["label"] == "Abrir aplicativo" and tools[3]["executed"] is False and "lista autorizada" in tools[3]["summary"]
    assert core.controller.opened == ["notas"]
    back = provider.seen_results[0]
    assert [o.for_model()["executed"] for o in back] == [True, False]
    actions = core.memory.recent_actions()
    assert [(a["tool"], a["executed"]) for a in actions] == [("open_app", True), ("open_app", False)]
    assert core.memory.recent_messages()[-1]["meta"]["tools"][0]["summary"] == "Bloco de Notas aberto."


async def test_confirmation_goes_to_the_user(settings, perms):
    core, _ = build(settings, perms, [[call("run_routine", routine_id="programar")], ["Não autorizado, senhor."]])
    conn = FakeConn(approve=False)
    await core.run_turn(conn, "prepara tudo para programar")
    assert conn.confirm_texts == ["Executar a rotina “Programar” (2 etapas)?"] and core.controller.opened == []
    assert conn.of("tool")[1]["executed"] is False


async def test_runaway_tool_loop_is_stopped(settings, perms):
    core, _ = build(settings, perms, [[call("get_local_time")] for _ in range(20)])
    conn = FakeConn()
    await core.run_turn(conn, "loop")
    assert conn.of("error")[0]["code"] == "tool_loop" and len([t for t in conn.of("tool") if t["stage"] == "end"]) == 6
    assert conn.of("turn_end")[0]["error"]["code"] == "tool_loop"


async def test_ai_failure_falls_back_to_local_mode_with_real_data(settings, perms):
    core, _ = build(settings, perms, [AIError("offline", "Sem conexão com o Gemini. Verifique a internet.", retryable=True)])
    conn = FakeConn()
    await core.run_turn(conn, "como está meu computador?")
    assert conn.of("error")[0] == {"type": "error", "scope": "ai", "code": "offline", "message": "Sem conexão com o Gemini. Verifique a internet."}
    assert conn.of("notice")[0]["message"] == "Continuando em modo local, sem IA."
    end = conn.of("turn_end")[0]
    assert end["mode"] == "local" and end["provider"] == "local" and "processador está em" in end["text"] and end["error"] is None
    assert conn.of("tool")[1]["name"] == "get_system_status" and conn.of("tool")[1]["executed"] is True
    assert core.ai_status()["last_error"]["code"] == "offline"


async def test_no_local_fallback_after_partial_answer_or_content_error(settings, perms):
    core, _ = build(settings, perms, [["Metade da resposta ", AIError("unavailable", "O Gemini está indisponível.", retryable=True)]])
    conn = FakeConn()
    await core.run_turn(conn, "x")
    end = conn.of("turn_end")[0]
    assert end["mode"] == "ai" and end["text"] == "Metade da resposta" and end["error"]["code"] == "unavailable" and conn.of("notice") == []
    core, _ = build(settings, perms, [AIError("blocked", "Bloqueado.")])
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert conn.of("turn_end")[0]["mode"] == "ai" and conn.of("turn_end")[0]["text"] == ""


async def test_without_key_the_system_stays_usable_and_says_it_is_not_ai(settings, perms):
    core, _ = build(settings, perms, gemini=None)
    assert core.gemini is None and core.ai_status()["configured"] is False and core.ai_status()["mode"] == "local"
    conn = FakeConn()
    await core.run_turn(conn, "que horas são?")
    assert "em Itumbiara" in conn.of("turn_end")[0]["text"] and conn.of("tool")[1]["name"] == "get_local_time"
    conn = FakeConn()
    await core.run_turn(conn, "escreva um poema")
    text = conn.of("turn_end")[0]["text"]
    assert "sem inteligência artificial" in text and conn.of("tool") == []


async def test_speech_is_synthesized_per_sentence_with_real_text(settings, perms):
    tts = FakeTTS("local")
    core, _ = build(settings, perms, [["**Bom dia**, senhor. Todos os sistemas ", "estão operacionais. Em que posso ajudá-lo?"]], tts={"local": tts}, runtime={"tts_voice_local": "v9"})
    conn = FakeConn()
    await core.run_turn(conn, "bom dia")
    audio = conn.of("audio")
    # modo econômico (padrão): 1ª frase sozinha para a voz começar logo; o resto em UM pedido
    assert [a["seq"] for a in audio] == [0, 1] and [a["text"] for a in audio] == ["**Bom dia**, senhor.", "Todos os sistemas estão operacionais. Em que posso ajudá-lo?"]
    assert tts.spoken == [("Bom dia, senhor.", "v9"), ("Todos os sistemas estão operacionais. Em que posso ajudá-lo?", "v9")]
    assert set(tts.styles_seen) == {"cinematografico"}
    assert base64.b64decode(audio[0]["wav"])[:4] == b"RIFF" and audio[0]["duration"] == 0.2 and audio[0]["cloud"] is False
    assert conn.of("speech_done")[0] == {"type": "speech_done", "turn": audio[0]["turn"], "chunks": 2, "failed": False}
    timings = conn.of("turn_end")[0]["timings"]
    assert 0 <= timings["first_text_s"] <= timings["first_audio_s"] <= timings["total_s"] and core.last_timings["mode"] == "ai"
    assert conn.kinds().index("speech_done") < conn.kinds().index("turn_end") and conn.of("turn_end")[0]["spoken"] is True


async def test_cloud_voice_failure_continues_with_local_voice_or_text(settings, perms):
    local = FakeTTS("local")
    core, _ = build(settings, perms, [["Primeira frase completa aqui. Segunda frase completa aqui."]], tts={"gemini": FakeTTS("gemini", cloud=True, fail=True), "local": local})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert len(conn.of("notice")) == 1 and "Continuando com a voz local" in conn.of("notice")[0]["message"] and [a["engine"] for a in conn.of("audio")] == ["local", "local"]
    core, _ = build(settings, perms, [["Uma frase completa aqui."]], tts={"gemini": FakeTTS("gemini", cloud=True, fail=True)}, runtime={"tts_engine": "gemini"})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert conn.of("audio") == [] and conn.of("error")[0]["scope"] == "tts" and conn.of("speech_done")[0]["failed"] is True
    assert conn.of("turn_end")[0]["text"] == "Uma frase completa aqui."
    core, _ = build(settings, perms, [["Sem voz."]], tts={"local": local}, runtime={"speak": False})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert conn.of("audio") == [] and conn.of("speech_done") == []


async def test_interrupt_stops_generation_and_speech(settings, perms):
    gate = asyncio.Event()

    async def wait_forever():
        await gate.wait()

    core, _ = build(settings, perms, [["Uma frase completa para falar. ", wait_forever, "nunca chega"]], tts={"local": FakeTTS("local")})
    conn = FakeConn()
    task = asyncio.create_task(core.run_turn(conn, "fale bastante"))
    for _ in range(200):
        await asyncio.sleep(0.005)
        if conn.of("audio"):
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    end = conn.of("turn_end")[0]
    assert end["interrupted"] is True and end["text"] == "Uma frase completa para falar." and "nunca chega" not in end["text"]
    assert conn.of("speech_done") and core.memory.recent_messages()[-1]["meta"]["interrupted"] is True
    n = len(conn.events)
    await asyncio.sleep(0.05)
    assert len(conn.events) == n


async def test_voice_input_requires_consent_for_cloud_and_handles_silence(settings, perms):
    cloud = FakeSTT("Jarvis, que horas são?", engine_id="gemini", cloud=True)
    core, _ = build(settings, perms, [["São dez horas."]], stt={"gemini": cloud})
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav())
    assert conn.of("error")[0]["code"] == "consent_required" and cloud.calls == 0 and conn.of("transcript") == []
    core.update_runtime({"cloud_audio_consent": True})
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav())
    assert conn.of("phase")[0] == {"type": "phase", "phase": "transcribing", "engine": "gemini", "cloud": True}
    assert conn.of("transcript")[0] == {"type": "transcript", "role": "user", "text": "Jarvis, que horas são?", "source": "voice", "engine": "gemini", "cloud": True}
    assert conn.of("turn_end")[0]["text"] == "São dez horas."
    conn = FakeConn()
    await core.handle_audio(conn, pcm16_to_wav(b"\x00\x00" * 16000, 16000))
    assert conn.of("stt_empty")[0]["reason"] == "silêncio" and cloud.calls == 1
    for bad in (b"isto nao e wav", tone_wav(0.05)):
        conn = FakeConn()
        await core.handle_audio(conn, bad)
        assert conn.of("error")[0]["code"] == "bad_audio"


async def test_wake_word_mode_ignores_speech_not_addressed_to_jarvis(settings, perms):
    local = FakeSTT("vou sair para almoçar", engine_id="whisper")
    core, provider = build(settings, perms, [["Às ordens."], ["Às ordens, senhor."]], stt={"whisper": local})
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav(), "wake")
    assert conn.of("wake_ignored") and conn.of("transcript") == [] and provider.seen_user == []
    local.text = "Jarvis, abre o editor"
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav(), "wake")
    assert conn.of("transcript")[0]["text"] == "abre o editor" and conn.of("transcript")[0]["source"] == "wake" and provider.seen_user == ["abre o editor"]
    local.text = "Jarvis"
    await core.handle_audio(FakeConn(), tone_wav(), "wake")
    assert provider.seen_user[-1] == "Jarvis?"


async def test_stt_unavailable_or_failing_is_reported(settings, perms):
    core, _ = build(settings, perms)
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav())
    assert conn.of("error")[0]["code"] == "stt_unavailable" and "modo texto" in conn.of("error")[0]["message"]
    core, _ = build(settings, perms, stt={"whisper": FakeSTT(error=STTError("local_failed", "A transcrição local falhou."))})
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav())
    assert conn.of("error")[0]["code"] == "local_failed" and conn.of("phase")[-1]["phase"] == "idle"


async def test_runtime_settings_are_validated_and_persisted(settings, perms):
    core, _ = build(settings, perms)
    rt = core.update_runtime({"tts_engine": "hackear", "tts_voice_gemini": "Orus", "speak": "sim", "user_title": "  chefe ", "desconhecido": 1, "memory_enabled": True, "tts_style": "gritando"})
    assert rt["tts_engine"] == "auto" and rt["tts_voice_gemini"] == "Orus" and rt["speak"] is True and rt["user_title"] == "chefe" and "desconhecido" not in rt
    assert rt["tts_style"] == "cinematografico" and core.update_runtime({"tts_style": "sobrio"})["tts_style"] == "sobrio"
    # modelo: só entre os que a conta listou
    assert core.update_runtime({"chat_model": "modelo-inventado"})["chat_model"] == "" and core.gemini.model == "gemini-teste"
    assert core.update_runtime({"chat_model": "gemini-outro"})["chat_model"] == "gemini-outro" and core.gemini.model == "gemini-outro"
    assert core.runtime()["memory_enabled"] is True and "remember" in core.tools.specs()
    assert core.update_runtime({"tts_voice_gemini": "Orus; drop table"})["tts_voice_gemini"] == "Orus"
    state = await core.state()
    assert state["location"]["city"] == "Itumbiara" and state["ai"]["configured"] is True and state["voice"]["wake_word"] == "jarvis"
    assert all(d["simulated"] for d in state["devices"]) and state["news"] == {"enabled": False}
    engine = FakeTTS("local")
    sampler = build(settings, perms, tts={"local": engine})[0]
    sample = await sampler.voice_sample("local", "v1")
    assert base64.b64decode(sample["wav"])[:4] == b"RIFF" and "Bom dia, senhor" in sample["text"] and sample["cached"] is False
    again = await sampler.voice_sample("local", "v1")
    assert again["cached"] is True and again["wav"] == sample["wav"] and len(engine.spoken) == 1   # repetir não sintetiza de novo
    other = await sampler.voice_sample("local", "v1", style="sobrio")
    assert other["cached"] is False and other["style"] == "sobrio" and len(engine.spoken) == 2


async def test_sentences_are_synthesized_in_parallel_but_delivered_in_order(settings, perms):
    # a 1ª frase demora mais que as outras: mesmo assim a ordem de entrega é a do texto
    tts = FakeTTS("local", delays=[0.12, 0.0, 0.03, 0.0])
    text = "Primeira frase bem completa aqui. Segunda frase bem completa aqui. Terceira frase bem completa aqui. Quarta frase bem completa aqui."
    settings.tts_chunking = "frase"   # um pedido de voz por frase (para quem tem cota folgada)
    core, _ = build(settings, perms, [[text]], tts={"local": tts})
    conn = FakeConn()
    started = asyncio.get_running_loop().time()
    await core.run_turn(conn, "x")
    elapsed = asyncio.get_running_loop().time() - started
    audio = conn.of("audio")
    assert [a["seq"] for a in audio] == [0, 1, 2, 3] and [a["text"].split()[0] for a in audio] == ["Primeira", "Segunda", "Terceira", "Quarta"]
    assert 2 <= tts.max_running <= settings.tts_parallel and elapsed < 0.14   # em série levaria 0,15 s


async def test_speech_text_is_normalized_but_subtitle_keeps_original(settings, perms):
    tts = FakeTTS("local")
    core, _ = build(settings, perms, [["Agora são 07:18 em Itumbiara — 22.5°C e umidade de 87%."]], tts={"local": tts})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert conn.of("audio")[0]["text"] == "Agora são 07:18 em Itumbiara — 22.5°C e umidade de 87%."
    assert tts.spoken[0][0] == "Agora são 7 e 18 em Itumbiara, 22,5 graus e umidade de 87 por cento."


async def test_voice_turn_reports_transcription_time(settings, perms):
    core, _ = build(settings, perms, [["Pronto, senhor."]], stt={"whisper": FakeSTT("Jarvis, acenda a luz", engine_id="whisper")})
    conn = FakeConn()
    await core.handle_audio(conn, tone_wav())
    assert "stt_s" in conn.of("turn_end")[0]["timings"] and "stt_s" not in conn.of("transcript")[0]


async def test_economy_mode_caps_voice_requests_per_reply(settings, perms):
    tts = FakeTTS("local")
    long = " ".join(f"Esta é a frase número {i} da resposta longa." for i in range(1, 9))
    core, _ = build(settings, perms, [[long]], tts={"local": tts})
    conn = FakeConn()
    await core.run_turn(conn, "explique")
    assert len(tts.spoken) == 2 and tts.spoken[0][0].startswith("Esta é a frase número 1") and "número 8" in tts.spoken[1][0]
    assert "".join(a["text"] for a in conn.of("audio")).replace(" ", "") == long.replace(" ", "")


async def test_streamed_speech_is_sent_in_pieces_and_in_order(settings, perms):
    # a 1ª frase demora mais para começar; mesmo assim os pedaços chegam ao HUD na ordem do texto
    tts = FakeTTS("gemini", cloud=True, stream=True, delays=[0.09, 0.0])
    core, _ = build(settings, perms, [["Bom dia, senhor. Todos os sistemas estão operacionais."]], tts={"gemini": tts}, runtime={"tts_speed": 1.2})
    conn = FakeConn()
    await core.run_turn(conn, "bom dia")
    kinds = [(e["type"], e.get("seq")) for e in conn.events if e["type"].startswith("audio")]
    assert kinds == [("audio_start", 0), ("audio_chunk", 0), ("audio_chunk", 0), ("audio_chunk", 0), ("audio_end", 0),
                     ("audio_start", 1), ("audio_chunk", 1), ("audio_chunk", 1), ("audio_chunk", 1), ("audio_end", 1)]
    first = conn.of("audio_start")[0]
    assert first["text"] == "Bom dia, senhor." and first["rate"] == 24000 and first["cloud"] is True and first["model"] == "modelo-falso"
    pcm = base64.b64decode(conn.of("audio_chunk")[0]["pcm"])
    assert pcm[:2] == bytes([1, 0]) and conn.of("audio_end")[0]["duration"] == 0.3
    assert tts.speeds == [1.2, 1.2] and conn.of("speech_done")[0]["chunks"] == 2
    assert 0 < conn.of("turn_end")[0]["timings"]["first_audio_s"]


async def test_stream_failing_before_audio_falls_back_to_local_voice(settings, perms):
    cloud, local = FakeTTS("gemini", cloud=True, stream=True, fail=True), FakeTTS("local")
    core, _ = build(settings, perms, [["Uma frase completa aqui. Outra frase completa aqui."]], tts={"gemini": cloud, "local": local})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert [e["type"] for e in conn.events if e["type"].startswith("audio")] == ["audio", "audio"]
    assert len(conn.of("notice")) == 1 and "voz local" in conn.of("notice")[0]["message"] and len(local.spoken) == 2


async def test_stream_cut_midway_ends_the_sentence_and_reports(settings, perms):
    tts = FakeTTS("gemini", cloud=True, stream=True, fail_stream_after=2)
    core, _ = build(settings, perms, [["Uma frase completa aqui."]], tts={"gemini": tts})
    conn = FakeConn()
    await core.run_turn(conn, "x")
    assert [e["type"] for e in conn.events if e["type"].startswith("audio")] == ["audio_start", "audio_chunk", "audio_chunk", "audio_end"]
    assert conn.of("error")[0]["scope"] == "tts" and conn.of("audio_end")[0]["duration"] == 0.2
    assert conn.of("turn_end")[0]["text"] == "Uma frase completa aqui."


async def test_speech_rate_is_validated(settings, perms):
    core, _ = build(settings, perms)
    assert core.update_runtime({"tts_speed": 1.15})["tts_speed"] == 1.15
    assert core.update_runtime({"tts_speed": 3})["tts_speed"] == 1.15 and core.update_runtime({"tts_speed": "rápido"})["tts_speed"] == 1.15
