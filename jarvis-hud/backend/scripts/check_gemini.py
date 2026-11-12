"""Verificação rápida da integração com o Gemini e comparação de vozes.

Uso (a partir de jarvis-hud/backend, com a chave em .env):
    .venv/Scripts/python scripts/check_gemini.py                 # conversa, ferramentas, TTS e STT
    .venv/Scripts/python scripts/check_gemini.py Charon Orus Algieba   # compara estas vozes
    .venv/Scripts/python scripts/check_gemini.py --local          # só a voz local (sem chave)

As amostras ficam em backend/samples/<voz>.wav para você OUVIR e escolher: a estimativa de
tom (Hz) ajuda a comparar o registro grave/agudo, mas timbre e naturalidade são subjetivos.
"""
from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.base import AIError, ToolCall  # noqa: E402
from app.assistant import SAMPLE_TEXT, Assistant  # noqa: E402
from app.config import BACKEND_DIR, load_settings  # noqa: E402
from app.voice.audio_stream import wav_info  # noqa: E402
from app.voice.tts import TTSError  # noqa: E402

SAMPLES = BACKEND_DIR / "samples"


def median_pitch_hz(wav_bytes: bytes) -> float | None:
    """Tom fundamental mediano (autocorrelação em quadros de 40 ms). None sem numpy/voz."""
    try:
        import io

        import numpy as np
    except ImportError:
        return None
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    frame, hop = int(rate * 0.04), int(rate * 0.02)
    lo, hi = int(rate / 320), int(rate / 60)
    pitches = []
    for start in range(0, len(data) - frame, hop):
        x = data[start:start + frame]
        if np.sqrt(np.mean(x * x)) < 0.02:
            continue
        x = x - x.mean()
        ac = np.correlate(x, x, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.4:
            pitches.append(rate / lag)
    return float(np.median(pitches)) if len(pitches) >= 5 else None


async def sample_voices(core: Assistant, engine_id: str, voices: list[str | None]) -> bytes | None:
    engine = core.tts.engines.get(engine_id)
    if engine is None or not engine.available()[0]:
        print(f"  motor '{engine_id}' indisponível: {engine.available()[1] if engine else 'não configurado'}")
        return None
    SAMPLES.mkdir(exist_ok=True)
    first = None
    for voice in voices:
        t0 = time.time()
        try:
            res = await engine.synthesize(SAMPLE_TEXT, voice)
        except TTSError as err:
            print(f"  {voice or 'padrão':<12} FALHOU [{err.code}] {err.message}")
            continue
        path = SAMPLES / f"{engine_id}-{(res.voice or 'padrao').replace('+', '_')}.wav"
        path.write_bytes(res.wav)
        pitch = median_pitch_hz(res.wav)
        info = wav_info(res.wav)
        print(f"  {res.voice:<12} {res.duration_s:5.1f} s · {info['sample_rate']} Hz · tom mediano {f'{pitch:.0f} Hz' if pitch else 'n/d'} · gerado em {time.time() - t0:.1f} s → {path.relative_to(BACKEND_DIR)}")
        first = first or res.wav
    return first


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    local_only = "--local" in sys.argv
    settings = load_settings()
    core = Assistant(settings)
    print(f"Local: {settings.location.city}/{settings.location.state_code} · IA configurada: {settings.ai_configured}")

    print("\n[voz local]")
    await sample_voices(core, "local", [None])
    if local_only:
        return 0
    if not core.gemini:
        print("\nGEMINI_API_KEY não definida em backend/.env — nada mais a testar. (Use --local para testar só a voz local.)")
        return 1

    print("\n[1] modelos disponíveis na conta")
    await core.gemini.resolve_models()
    print(f"  conversa: {core.gemini.model} · voz: {core.gemini.tts_model} · {len(core.gemini.available_models)} modelos listados")
    if core.gemini.model_note:
        print(f"  nota: {core.gemini.model_note}")

    print("\n[2] conversa com resposta incremental")
    session = core.gemini.start(system=await core._system_prompt(), history=[], tools=[])
    t0, first, text = time.time(), None, ""
    try:
        async for ev in session.send_user("Jarvis, bom dia."):
            if isinstance(ev, str):
                first = first or time.time() - t0
                text += ev
        print(f"  primeiro trecho em {first:.2f} s, total {time.time() - t0:.2f} s\n  « {text.strip()} »")
    except AIError as err:
        print(f"  FALHOU [{err.code}] {err.message}\n  detalhe: {err.detail}")
        return 2

    print("\n[3] function calling (a IA pede; o backend executa)")
    session = core.gemini.start(system=await core._system_prompt(), history=[], tools=core.tools.declarations())

    async def deny(_: str) -> bool:
        return False

    async def quiet(_: dict) -> None:
        return None

    try:
        stream, answer = session.send_user("Que horas são e como está o meu computador?"), ""
        for _ in range(4):
            calls: list[ToolCall] = []
            async for ev in stream:
                if isinstance(ev, str):
                    answer += ev
                else:
                    calls.append(ev)
            if not calls:
                break
            outcomes = [await core.tools.execute(c, deny, quiet) for c in calls]
            for o in outcomes:
                print(f"  ferramenta {o.call.name}({o.call.args}) → executed={o.executed} · {o.summary}")
            stream = session.send_tool_results(outcomes)
        print(f"  « {answer.strip()} »")
    except AIError as err:
        print(f"  FALHOU [{err.code}] {err.message}\n  detalhe: {err.detail}")

    print("\n[4] vozes do Gemini TTS (mesma frase, estilo do JARVIS)")
    first_wav = await sample_voices(core, "gemini", args or ["Charon", "Orus", "Algieba", "Algenib", "Iapetus", "Schedar"])

    print("\n[5] transcrição (envia a primeira amostra de volta para o Gemini)")
    if first_wav:
        try:
            res = await core.stt.engines["gemini"].transcribe(first_wav)
            print(f"  esperado : {SAMPLE_TEXT}\n  transcrito: {res.text}")
        except Exception as err:  # STTError
            print(f"  FALHOU: {getattr(err, 'message', err)}")
    else:
        print("  sem amostra para transcrever.")
    print(f"\nOuça os arquivos em {SAMPLES} e escolha a voz em Configurações → Áudio (ou JARVIS_TTS_VOICE).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
