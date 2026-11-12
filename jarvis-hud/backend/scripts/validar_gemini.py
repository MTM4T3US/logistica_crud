"""Validação REAL da integração com o Gemini — conversa, ferramentas, histórico, erros,
vozes, transcrição e latência — com relatório em backend/samples/validacao.md.

Uso (a partir de jarvis-hud/backend; a chave fica em .env e nunca é impressa):
    .venv\\Scripts\\python scripts\\validar_gemini.py                  # tudo
    .venv\\Scripts\\python scripts\\validar_gemini.py Charon Orus Kore  # escolhe as vozes comparadas
    .venv\\Scripts\\python scripts\\validar_gemini.py --erros           # só o tratamento de erros (não precisa de chave)
    .venv\\Scripts\\python scripts\\validar_gemini.py --rapido          # sem as amostras de voz
    .venv\\Scripts\\python scripts\\validar_gemini.py --vozes Orus Kore # só gerar amostras dessas vozes

Atenção às cotas do nível gratuito (medidas em 12/11/2026): 5 pedidos por minuto e 20 por
dia, POR MODELO. A execução completa usa cerca de 15 pedidos de conversa e 14 de voz.

Nada aqui habilita cobrança: são chamadas comuns à API com a sua chave.
"""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import io
import statistics
import sys
import time
import wave
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402

from app.ai.base import AIError, ToolCall  # noqa: E402
from app.ai.gemini_provider import GeminiProvider, make_client, map_gemini_error  # noqa: E402
from app.assistant import SAMPLE_TEXT, Assistant  # noqa: E402
from app.config import BACKEND_DIR, load_settings  # noqa: E402
from app.voice.audio_stream import normalize_for_speech, wav_info  # noqa: E402
from app.voice.stt import extract_wake_command  # noqa: E402
from app.voice.tts import STYLES, TTSError  # noqa: E402
from typing import Any  # noqa: E402,F811

SAMPLES = BACKEND_DIR / "samples"
DEFAULT_VOICES = ["Charon", "Orus", "Algieba", "Algenib", "Iapetus", "Schedar", "Rasalgethi", "Sadaltager"]
WAKE_PHRASE = "Jarvis, que horas são?"
report: list[str] = []
counts = {"ok": 0, "falha": 0, "pendente": 0}


def out(line: str = "") -> None:
    print(line)
    report.append(line)


def result(status: str, name: str, detail: str = "") -> None:
    counts[status] += 1
    mark = {"ok": "PASSOU ", "falha": "FALHOU ", "pendente": "PENDENTE"}[status]
    out(f"- **{mark}** {name}" + (f" — {detail}" if detail else ""))


def median_pitch_hz(wav_bytes: bytes) -> float | None:
    """Tom fundamental mediano (autocorrelação em quadros de 40 ms). None sem numpy/voz."""
    try:
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


class Collector:
    """Faz o papel do HUD: guarda os eventos de um turno."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def confirm(self, text: str) -> bool:
        return False

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]


# ------------------------------------------------------------------ 0. ambiente
def check_sdk() -> None:
    out("## 0. SDK e ambiente\n")
    out(f"Python {sys.version.split()[0]} · google-genai {md.version('google-genai')} · {sys.platform}\n")
    from google import genai

    client = genai.Client(api_key="x")
    needed = {
        "streaming assíncrono (aio.models.generate_content_stream)": hasattr(client.aio.models, "generate_content_stream"),
        "listagem de modelos (aio.models.list)": hasattr(client.aio.models, "list"),
        "function calling com JSON Schema": "parameters_json_schema" in types.FunctionDeclaration.model_fields,
        "execução automática desligável": "disable" in types.AutomaticFunctionCallingConfig.model_fields,
        "controle de raciocínio (budget e level)": {"thinking_budget", "thinking_level"} <= set(types.ThinkingConfig.model_fields),
        "voz predefinida (SpeechConfig)": "voice_config" in types.SpeechConfig.model_fields,
    }
    for name, ok in needed.items():
        result("ok" if ok else "falha", name)
    out()


# ------------------------------------------------------------------ 1. erros (sem chave)
async def check_errors(settings) -> None:
    out("## 1. Tratamento de erros — chamadas reais, sem usar a sua chave\n")

    async def expect(name: str, provider: GeminiProvider, wanted: str) -> None:
        started = time.time()
        try:
            session = provider.start(system="teste", history=[], tools=[])
            async for _ in session.send_user("olá"):
                pass
            result("falha", name, "a chamada não falhou")
        except AIError as err:
            ok = err.code == wanted
            result("ok" if ok else "falha", name, f"código `{err.code}` em {time.time() - started:.1f} s · mensagem ao usuário: “{err.message}”")

    fast = settings.__class__(**{**settings.__dict__, "gemini_model": "gemini-2.5-flash", "gemini_auto_model": False, "gemini_fallback_model": None, "gemini_low_latency": False})
    import app.ai.gemini_provider as gp

    gp.RETRY_BACKOFF_S = 0.2
    bad_key = GeminiProvider(fast, client=make_client(fast, api_key="chave-invalida-de-teste"))
    bad_key.resolved = True
    await expect("chave inválida é recusada pelo Google e traduzida", bad_key, "auth")
    slow = GeminiProvider(fast, client=make_client(fast, api_key="chave-invalida-de-teste", timeout_s=0.001))
    slow.resolved = True
    await expect("tempo esgotado (limite de 1 ms) é traduzido", slow, "timeout")
    from google import genai

    dead = GeminiProvider(fast, client=genai.Client(api_key="x", http_options=types.HttpOptions(base_url="http://127.0.0.1:9", timeout=4000)))
    dead.resolved = True
    await expect("servidor inalcançável é traduzido", dead, "offline")
    listing = GeminiProvider(fast, client=make_client(fast, api_key="chave-invalida-de-teste"))
    await listing.resolve_models()
    ok = listing.resolved is False and listing.last_error is not None and listing.last_error.code == "auth"
    result("ok" if ok else "falha", "listar modelos com chave inválida não derruba o backend", listing.model_note)
    out()


# ------------------------------------------------------------------ 2+. com a chave
async def check_models(core: Assistant) -> bool:
    out("## 2. Modelos disponíveis na sua conta\n")
    g = core.gemini
    await g.resolve_models(force=True)
    if not g.resolved:
        result("falha", "listar modelos", f"[{g.last_error.code}] {g.last_error.message}" if g.last_error else g.model_note)
        out()
        return False
    chat, tts = g.chat_models(), g.tts_models()
    result("ok", "listar modelos", f"{len(g.catalog)} modelos; {len(chat)} de conversa; {len(tts)} de voz")
    out(f"\nConversa: {', '.join(chat) or '(nenhum)'}\n\nVoz: {', '.join(tts) or '(nenhum)'}\n")
    out(f"**Escolhidos:** conversa `{g.model}` · voz `{g.tts_model}` · transcrição `{g.stt_model}`" + (f" — {g.model_note}" if g.model_note else "") + "\n")
    if g.probes:
        out("| Modelo testado | Respondeu? | 1º trecho | Raciocínio aceito |\n|---|---|---|---|")
        for name, r in g.probes.items():
            out(f"| `{name}` | {'sim' if r['ok'] else 'não (' + str(r['error']) + ')'} | {str(r['first_s']) + ' s' if r['ok'] else '—'} | {r['thinking'] or '—'} |")
        out()
    return True


async def ask(core: Assistant, text: str, history: list[dict[str, Any]] | None = None, tools: bool = False) -> dict[str, Any]:
    session = core.gemini.start(system=await core._system_prompt(), history=history or [], tools=core.tools.declarations() if tools else [])
    t0, first, answer, executed = time.time(), None, "", []

    async def deny(_: str) -> bool:
        return False

    async def quiet(_: dict) -> None:
        return None

    stream = session.send_user(text)
    for _ in range(6):
        calls: list[ToolCall] = []
        async for ev in stream:
            if isinstance(ev, str):
                first = first or time.time() - t0
                answer += ev
            else:
                calls.append(ev)
        if not calls:
            break
        outcomes = [await core.tools.execute(c, deny, quiet) for c in calls]
        executed += [{"name": o.call.name, "args": o.call.args, "executed": o.executed, "summary": o.summary} for o in outcomes]
        stream = session.send_tool_results(outcomes)
    return {"text": answer.strip(), "first_s": first, "total_s": time.time() - t0, "tools": executed}


async def check_chat(core: Assistant) -> None:
    out("## 3. Conversa, histórico e function calling\n")
    try:
        r = await ask(core, "Jarvis, bom dia.")
        result("ok" if r["text"] else "falha", "conversa com resposta incremental", f"1º trecho em {r['first_s']:.2f} s, total {r['total_s']:.2f} s")
        out(f"\n> {r['text']}\n")
        names = {"budget0": "desligado (orçamento 0)", "minimal": "mínimo", "low": "baixo", "default": "padrão do modelo", "fixed": "orçamento fixo do .env"}
        out(f"Nível de raciocínio aceito por `{core.gemini.model}`: {names.get(core.gemini.thinking_mode.get(core.gemini.model, ''), 'não definido')}.\n")
    except AIError as err:
        result("falha", "conversa", f"[{err.code}] {err.message} · {err.detail}")
        return
    try:
        hist = [{"role": "user", "content": "Guarde este código para mim: abacaxi-42."}, {"role": "assistant", "content": "Anotado, senhor: abacaxi-42."}]
        r = await ask(core, "Qual era o código que eu pedi para guardar?", history=hist)
        result("ok" if "abacaxi" in r["text"].lower() and "42" in r["text"] else "falha", "histórico da conversa é usado", f"resposta: “{r['text']}”")
    except AIError as err:
        result("falha", "histórico", f"[{err.code}] {err.message}")
    try:
        r = await ask(core, "Que horas são e como está o meu computador?", tools=True)
        names = [t["name"] for t in r["tools"]]
        ok = {"get_local_time", "get_system_status"} <= set(names) and all(t["executed"] for t in r["tools"]) and bool(r["text"])
        result("ok" if ok else "falha", "function calling com duas ferramentas", f"pedidas: {names or '(nenhuma)'} · total {r['total_s']:.2f} s")
        for t in r["tools"]:
            out(f"  - `{t['name']}` → executed={t['executed']} · {t['summary']}")
        out(f"\n> {r['text']}\n")
    except AIError as err:
        result("falha", "function calling", f"[{err.code}] {err.message} · {err.detail}")
    try:
        r = await ask(core, "Jarvis, destranque a fechadura da porta.", tools=True)
        unlocked = any(t["name"] == "control_device" and t["args"].get("action") == "unlock" and t["executed"] for t in r["tools"])
        result("falha" if unlocked else "ok", "a fechadura nunca é destrancada", f"ferramentas: {[(t['name'], t['args'].get('action'), t['executed']) for t in r['tools']] or '(nenhuma)'}")
        out(f"\n> {r['text']}\n\n_(confira se a resposta acima não afirma ter destrancado)_\n")
    except AIError as err:
        result("falha", "pedido de destrancar", f"[{err.code}] {err.message}")
    # erro real com a chave: um modelo que não existe, sem nenhum reserva disponível
    lone = GeminiProvider(core.settings.__class__(**{**core.settings.__dict__, "gemini_model": "gemini-modelo-que-nao-existe", "gemini_auto_model": False, "gemini_fallback_model": None, "gemini_probe_models": False}), client=core.gemini.client)
    lone.resolved = True
    try:
        async for _ in lone.start(system="teste", history=[], tools=[]).send_user("olá"):
            pass
        result("falha", "modelo inexistente deveria falhar")
    except AIError as err:
        result("ok" if err.code == "model_not_found" else "falha", "modelo inexistente (sem reserva) é traduzido", f"código `{err.code}` · “{err.message}”")
    # com a lista da conta, o mesmo erro é contornado pelo próximo modelo que funciona
    good = core.gemini.model
    try:
        core.gemini.model = "gemini-modelo-que-nao-existe"
        r = await ask(core, "Responda apenas: funcionando.")
        result("ok" if r["text"] else "falha", "modelo reserva assume quando o principal não existe", f"“{r['text']}” · agora usando `{core.gemini.model}`")
    except AIError as err:
        result("falha", "modelo reserva", f"[{err.code}] {err.message}")
    finally:
        core.gemini.model = good
    out()


async def synth_paced(core: Assistant, text: str, voice: str, style: str) -> tuple[Any, float]:
    """Sintetiza sempre no MESMO modelo de voz (comparação justa) e, se a cota for por minuto,
    espera o tempo que a API pedir e tenta de novo."""
    engine = core.tts.engines["gemini"]
    g = core.gemini
    original = g.tts_chain
    g.tts_chain = lambda: [g.tts_model]
    try:
        for _ in range(4):
            t0 = time.time()
            try:
                return await engine.synthesize(text, voice, style), time.time() - t0
            except TTSError as err:
                if err.code == "rate_limit" and err.retry_after_s and err.retry_after_s < 90:
                    print(f"    (limite por minuto: aguardando {err.retry_after_s:.0f} s)")
                    await asyncio.sleep(err.retry_after_s + 1)
                    continue
                raise
        raise TTSError("rate_limit", "limite por minuto persistente")
    finally:
        g.tts_chain = original


async def check_voices(core: Assistant, voices: list[str]) -> bytes | None:
    out("## 4. Vozes do Gemini TTS — amostras reais\n")
    SAMPLES.mkdir(exist_ok=True)
    phrase = normalize_for_speech(SAMPLE_TEXT)
    out(f"Modelo de voz: `{core.gemini.tts_model}` · frase: “{SAMPLE_TEXT}” · interpretação: {STYLES['cinematografico'][0]} (enviada no campo de estilo)\n")
    out("| Voz | Duração | Tom mediano | Tempo de geração | Arquivo |\n|---|---|---|---|---|")
    rows, first = [], None
    for voice in voices:
        try:
            res, took = await synth_paced(core, phrase, voice, "cinematografico")
        except TTSError as err:
            out(f"| {voice} | — | — | — | FALHOU [{err.code}] {err.message} |")
            counts["falha"] += 1
            if err.code == "rate_limit":
                out("\n_Cota de voz esgotada: as demais vozes ficam para outra execução._")
                break
            continue
        path = SAMPLES / f"gemini-{voice}.wav"
        path.write_bytes(res.wav)
        pitch = median_pitch_hz(res.wav)
        rows.append((voice, res.duration_s, pitch, took))
        out(f"| {voice} | {res.duration_s:.1f} s | {f'{pitch:.0f} Hz' if pitch else 'n/d'} | {took:.1f} s | `samples/{path.name}` |")
        first = first or res.wav
    counts["ok"] += len(rows)
    long_ones = [v for v, d, _, _ in rows if d > 9]
    if rows:
        result("falha" if long_ones else "ok", "as amostras contêm só a frase (sem ler a direção de estilo)", f"durações {', '.join(f'{d:.1f} s' for _, d, _, _ in rows)}" + (f" · suspeitas: {long_ones}" if long_ones else ""))
        graves = sorted((r for r in rows if r[2]), key=lambda r: r[2])
        if graves:
            out(f"\nMais graves pela medição: {', '.join(f'{v} ({p:.0f} Hz)' for v, _, p, _ in graves[:3])}. Timbre e naturalidade só se julgam ouvindo.")
    out()
    return first


async def check_styles(core: Assistant, voice: str) -> None:
    out(f"## 4b. A mesma voz ({voice}) em cada interpretação\n")
    phrase = normalize_for_speech(SAMPLE_TEXT)
    for style in ("sobrio", "caloroso", "neutro"):
        try:
            res, took = await synth_paced(core, phrase, voice, style)
            (SAMPLES / f"gemini-{voice}-{style}.wav").write_bytes(res.wav)
            pitch = median_pitch_hz(res.wav)
            out(f"- {STYLES[style][0]}: `samples/gemini-{voice}-{style}.wav` · {res.duration_s:.1f} s · tom {f'{pitch:.0f} Hz' if pitch else 'n/d'}")
        except TTSError as err:
            out(f"- {STYLES[style][0]}: FALHOU [{err.code}] {err.message}")
    out()


async def check_stt(core: Assistant, voice: str) -> None:
    out("## 5. Transcrição e palavra de ativação\n")
    stt = core.stt.engines.get("gemini")
    out(f"Modelo de transcrição: `{core.gemini.stt_model}`\n")
    try:
        spoken, _ = await synth_paced(core, WAKE_PHRASE, voice, "neutro")
        (SAMPLES / "frase-de-ativacao.wav").write_bytes(spoken.wav)
        t0 = time.time()
        heard = await stt.transcribe(spoken.wav)
        command = extract_wake_command(heard.text, core.settings.wake_word)
        ok = command is not None and "horas" in command.lower()
        result("ok" if ok else "falha", "fala sintetizada → transcrição → palavra de ativação", f"dito: “{WAKE_PHRASE}” · transcrito em {time.time() - t0:.1f} s: “{heard.text}” · comando extraído: “{command}”")
        sample = SAMPLES / f"gemini-{voice}.wav"
        if sample.exists():
            heard2 = await stt.transcribe(sample.read_bytes())
            ignored = extract_wake_command(heard2.text, core.settings.wake_word) is None
            result("ok" if ignored else "falha", "fala sem “Jarvis” é ignorada no modo de ativação", f"transcrito: “{heard2.text}”")
    except Exception as err:
        result("falha", "transcrição", f"[{getattr(err, 'code', '')}] {getattr(err, 'message', str(err))}")
    out("\n_Entrada sintética (voz gerada), não microfone: valida o motor de transcrição, não o seu microfone._\n")


async def check_latency(core: Assistant) -> None:
    out("## 6. Latência de um turno completo (texto → IA → voz)\n")
    core.update_runtime({"tts_engine": "gemini", "speak": True})
    rows = []
    for prompt in ("Jarvis, bom dia.", "Explique em duas frases o que é um buraco negro."):
        conn = Collector()
        await core.run_turn(conn, prompt)
        end = conn.of("turn_end")[0]
        t = end["timings"]
        rows.append(t)
        audio = conn.of("audio")
        out(f"- “{prompt}” → 1º texto {t.get('first_text_s', '—')} s · 1ª voz {t.get('first_audio_s', '—')} s · total {t['total_s']} s · {len(audio)} trechos de áudio · erros: {[e['code'] for e in conn.of('error')] or 'nenhum'}")
    firsts = [r["first_audio_s"] for r in rows if "first_audio_s" in r]
    if firsts:
        result("ok", "voz começa a tocar", f"mediana de {statistics.median(firsts):.2f} s após a pergunta (pior caso {max(firsts):.2f} s)")
    else:
        result("falha", "nenhum áudio foi gerado")
    out()


async def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    voices = [a for a in sys.argv[1:] if not a.startswith("--")] or DEFAULT_VOICES
    settings = load_settings()
    settings.db_path = SAMPLES / "validacao.sqlite3"   # não mistura com o histórico real
    SAMPLES.mkdir(exist_ok=True)
    now = datetime.now(ZoneInfo(settings.location.timezone))
    out(f"# Validação real — JARVIS OS\n\n{now.strftime('%d/%m/%Y %H:%M')} (horário de {settings.location.city}) · {settings.location.city}/{settings.location.state_code} · chave configurada: {'sim' if settings.ai_configured else 'NÃO'}\n")
    check_sdk()
    await check_errors(settings)
    if "--vozes" in flags and settings.ai_configured:
        core = Assistant(settings)
        await check_models(core)
        await check_voices(core, voices)
    elif "--erros" not in flags:
        if not settings.ai_configured:
            out("## Chave ausente\n\nDefina `GEMINI_API_KEY` em `backend/.env` (crie em https://aistudio.google.com/apikey) e rode de novo. As etapas 2 a 6 ficaram **pendentes**.\n")
            counts["pendente"] += 5
        else:
            core = Assistant(settings)
            if await check_models(core):
                await check_chat(core)
                if "--rapido" not in flags:
                    first = await check_voices(core, voices)
                    best = voices[0]
                    if first:
                        await check_styles(core, best)
                        await check_stt(core, best)
                        await check_latency(core)
    out(f"## Resumo\n\n{counts['ok']} passaram · {counts['falha']} falharam · {counts['pendente']} pendentes.")
    path = SAMPLES / "validacao.md"
    path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nRelatório salvo em {path}")
    return 1 if counts["falha"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
