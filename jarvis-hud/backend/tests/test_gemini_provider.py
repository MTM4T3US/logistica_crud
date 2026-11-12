"""Provedor Gemini com um cliente falso (mesmos tipos do SDK): streaming, ferramentas e falhas."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors, types

from app.ai import gemini_provider as gp
from app.ai.base import AIError, ToolCall, ToolOutcome
from app.ai.gemini_provider import GeminiProvider, is_chat_model, map_gemini_error, pick_chat_model, pick_tts_model
from app.config import Settings

def _foreign(name: str, *bases: str) -> Exception:
    """Exceção de outra biblioteca HTTP (ex.: httpx2), reconhecível só pelos nomes das classes."""
    cls: type = Exception
    for base in reversed(bases):
        cls = type(base, (cls,), {})
    return type(name, (cls,), {})("falha de transporte")


TOOLS = [{"name": "get_weather", "description": "clima", "parameters": {"type": "object", "properties": {}}}]


def chunk(*parts: types.Part, finish: Any = None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)])


def text(t: str) -> types.Part:
    return types.Part.from_text(text=t)


def api_error(code: int, status: str, message: str = "x") -> errors.APIError:
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": message, "status": status}})


class FakeModels:
    def __init__(self, script: list[Any], names: list[str] | None = None):
        self.script, self.calls, self.names = script, [], names or []

    async def generate_content_stream(self, *, model: str, contents: list, config: Any):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step

        async def gen():
            for item in step:
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, (int, float)):
                    await asyncio.sleep(item)
                    continue
                yield item

        return gen()

    async def list(self):
        self.listed = getattr(self, "listed", 0) + 1

        async def pager():
            for n in self.names:
                yield SimpleNamespace(name=n, display_name=n.split("/")[-1].title(), supported_actions=["generateContent"])

        return pager()


def provider(script: list[Any], **kw: Any) -> tuple[GeminiProvider, FakeModels]:
    models = FakeModels(script, kw.pop("names", None))
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    kw.setdefault("gemini_model", "gemini-2.5-flash")
    kw.setdefault("gemini_low_latency", False)
    kw.setdefault("gemini_probe_models", False)
    timeout = kw.pop("timeout", 2.0)
    kw.setdefault("gemini_first_token_timeout_s", timeout)
    kw.setdefault("db_path", Path(":memory:"))  # não grava o estado aprendido no diretório real
    settings = Settings(gemini_api_key="teste", gemini_timeout_s=timeout, **kw)
    return GeminiProvider(settings, client=client), models


async def collect(stream) -> list[Any]:
    return [ev async for ev in stream]


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(gp, "RETRY_BACKOFF_S", 0.0)


async def test_streams_text_incrementally_with_history_and_system():
    p, models = provider([[chunk(text("Bom dia, ")), chunk(text("senhor."))]])
    session = p.start(system="persona", history=[{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}], tools=TOOLS)
    assert await collect(session.send_user("bom dia")) == ["Bom dia, ", "senhor."]
    sent = models.calls[0]
    assert [c.role for c in sent["contents"]] == ["user", "model", "user"] and sent["contents"][-1].parts[0].text == "bom dia"
    assert sent["config"].system_instruction == "persona" and sent["config"].automatic_function_calling.disable is True
    assert sent["config"].tools[0].function_declarations[0].name == "get_weather"
    assert session.contents[-1].role == "model"


async def test_function_call_round_trip_keeps_model_parts():
    fc = types.Part.from_function_call(name="get_weather", args={})
    fc.thought_signature = b"assinatura"
    p, models = provider([[chunk(text("Vou verificar. ")), chunk(fc)], [chunk(text("Faz 22 graus."))]])
    session = p.start(system="s", history=[], tools=TOOLS)
    first = await collect(session.send_user("clima?"))
    assert first[0] == "Vou verificar. " and isinstance(first[1], ToolCall) and first[1].name == "get_weather"
    outcome = ToolOutcome(first[1], True, True, "22°C", data={"temperature_c": 22.3})
    assert await collect(session.send_tool_results([outcome])) == ["Faz 22 graus."]
    second = models.calls[1]["contents"]
    assert second[-2].role == "model" and second[-2].parts[-1].thought_signature == b"assinatura"
    resp = second[-1].parts[0].function_response
    assert resp.name == "get_weather" and resp.response["executed"] is True and resp.response["temperature_c"] == 22.3


async def test_thought_parts_are_not_spoken():
    thought = types.Part(text="raciocínio interno", thought=True)
    p, _ = provider([[chunk(thought), chunk(text("Pronto."))]])
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["Pronto."]


@pytest.mark.parametrize(
    "exc, code, retryable",
    [
        (api_error(429, "RESOURCE_EXHAUSTED"), "rate_limit", False),
        (api_error(403, "PERMISSION_DENIED"), "auth", False),
        (api_error(400, "INVALID_ARGUMENT", "API key not valid"), "auth", False),
        (api_error(404, "NOT_FOUND"), "model_not_found", False),
        (api_error(503, "UNAVAILABLE"), "unavailable", True),
        (api_error(400, "INVALID_ARGUMENT"), "bad_request", False),
        (asyncio.TimeoutError(), "timeout", True),
        (httpx.ReadTimeout("lento"), "timeout", True),
        (httpx.ConnectError("sem rede"), "offline", True),
        # o SDK 3.x usa httpx2: mesmas classes, outro módulo (defeito achado na validação real)
        (_foreign("ReadTimeout", "TimeoutException", "TransportError"), "timeout", True),
        (_foreign("ConnectError", "NetworkError", "TransportError"), "offline", True),
        (_foreign("ProxyError", "TransportError"), "offline", True),
        (RuntimeError("?"), "unknown", False),
    ],
)
def test_error_mapping(exc, code, retryable):
    err = map_gemini_error(exc)
    assert (err.code, err.retryable) == (code, retryable) and err.message and "Traceback" not in err.message


async def test_retries_transient_failure_then_succeeds():
    p, models = provider([api_error(503, "UNAVAILABLE"), [chunk(text("ok"))]])
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["ok"]
    assert len(models.calls) == 2 and p.last_error is None


async def test_falls_back_to_second_model_when_primary_missing():
    p, models = provider([api_error(404, "NOT_FOUND"), [chunk(text("ok"))]], gemini_model="gemini-a", gemini_fallback_model="gemini-b", gemini_auto_model=False)
    p.resolved = True
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["ok"]
    # com um reserva disponível não insiste no modelo que falhou — e o que respondeu vira o principal
    assert [c["model"] for c in models.calls] == ["gemini-a", "gemini-b"] and p.model == "gemini-b" and "gemini-a" in p.model_note


async def test_non_retryable_and_exhausted_errors_surface():
    p, models = provider([api_error(429, "RESOURCE_EXHAUSTED")])
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
    # sem outro modelo disponível, a cota esgotada NÃO é repetida no mesmo modelo
    assert e.value.code == "rate_limit" and len(models.calls) == 1 and p.last_error.code == "rate_limit"
    p, models = provider([httpx.ConnectError("x"), httpx.ConnectError("x")])
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
    assert e.value.code == "offline" and len(models.calls) == 2


async def test_no_retry_after_text_was_already_emitted():
    p, models = provider([[chunk(text("Metade da ")), api_error(503, "UNAVAILABLE")], [chunk(text("nunca"))]])
    got: list[Any] = []
    with pytest.raises(AIError) as e:
        async for ev in p.start(system="s", history=[], tools=[]).send_user("x"):
            got.append(ev)
    assert got == ["Metade da "] and e.value.code == "unavailable" and len(models.calls) == 1


async def test_stalled_stream_times_out():
    p, _ = provider([[5.0, chunk(text("tarde demais"))], [5.0]], timeout=0.05)
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
    assert e.value.code == "timeout"


async def test_empty_or_blocked_response_is_an_error():
    p, _ = provider([[chunk()]])
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
    assert e.value.code == "empty"
    p, _ = provider([[chunk(finish=types.FinishReason.SAFETY)]])
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
    assert e.value.code == "blocked"


NAMES = ["models/gemini-2.0-flash", "models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-2.5-pro", "models/gemini-3-flash-preview",
         "models/gemini-2.5-flash-preview-tts", "models/gemini-2.5-pro-preview-tts", "models/gemini-2.5-flash-image", "models/text-embedding-004"]


def test_selection_against_the_real_account_listing():
    # nomes reais devolvidos pela conta do usuário em 12/11/2026 (v1beta)
    real = ["gemini-2.5-flash", "gemini-2.5-flash-image", "gemini-2.5-flash-lite", "gemini-2.5-flash-native-audio-latest", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro",
            "gemini-2.5-pro-preview-tts", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-3.1-flash-live-preview", "gemini-3.1-flash-tts-preview", "gemini-3.5-flash",
            "gemini-3.5-live-translate-preview", "gemini-3.5-transcribe", "gemini-3.5-transcribe-live", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash",
            "gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts", "gemini-3.8-live", "gemini-4-argon", "gemini-flash-latest", "gemini-nano-banana-2.1", "gemini-omni-1.2-flash",
            "gemini-2.5-computer-use-preview-10-2025", "gemini-robotics-er-2-preview", "gemini-embedding-2", "gemma-4-31b-it", "lyria-3.5"]
    from app.ai.gemini_provider import pick_stt_model

    assert pick_chat_model(real, "auto") == "gemini-3.8-flash" and pick_tts_model(real, "auto") == "gemini-3.8-flash-tts"
    assert pick_stt_model(real, None, "gemini-3.8-flash") == "gemini-3.5-transcribe" and pick_stt_model(["gemini-2.5-flash"], None, "gemini-2.5-flash") == "gemini-2.5-flash"
    assert pick_stt_model(real, "gemini-2.5-flash", "x") == "gemini-2.5-flash"
    chat = [n for n in real if is_chat_model(n)]
    assert chat == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-4-argon", "gemini-flash-latest"]


def test_model_selection_never_assumes_a_name():
    assert pick_chat_model(NAMES, "gemini-2.0-flash") == "gemini-2.0-flash"
    assert pick_chat_model(NAMES, "auto") == "gemini-2.5-flash"                       # estável antes de prévia; nunca o "lite"
    assert pick_chat_model(NAMES, "gemini-9-flash") == "gemini-2.5-flash"
    assert pick_chat_model(["models/gemini-3-flash-preview", "models/gemini-3-pro"], "auto") == "gemini-3-flash-preview"
    assert pick_chat_model(["models/gemini-4-flash", "models/gemini-3.5-flash"], "auto") == "gemini-4-flash"
    assert pick_chat_model(["models/gemini-3-flash-lite"], "auto") == "gemini-3-flash-lite"   # só há lite: usa
    assert pick_chat_model(["models/text-embedding-004"], "auto") is None
    assert pick_tts_model(NAMES, "auto") == "gemini-2.5-flash-preview-tts" and pick_tts_model(["models/gemini-2.5-flash"], "auto") is None
    assert is_chat_model("gemini-2.5-flash", ["generateContent"]) and not is_chat_model("gemini-2.5-flash-preview-tts") and not is_chat_model("gemini-2.5-flash", ["embedContent"])


async def test_auto_mode_picks_models_from_the_account_list():
    p, models = provider([[chunk(text("ok"))]], names=["models/gemini-3.5-flash", "models/gemini-3.5-flash-lite", "models/gemini-3.5-flash-tts", "models/gemini-3.5-pro"], gemini_model="auto", gemini_tts_model="auto")
    assert p.resolved is False and "não conferidos" in p.model_note
    # a primeira conversa já resolve os modelos, mesmo que a inicialização não o tenha feito
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["ok"]
    assert models.calls[0]["model"] == "gemini-3.5-flash" and p.tts_model == "gemini-3.5-flash-tts" and p.resolved and models.listed == 1
    assert p.stt_model == "gemini-3.5-flash"   # sem modelo dedicado de transcrição, usa o de conversa
    st = p.status()
    assert st["chat_models"] == ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-3.5-flash-lite"] and st["tts_models"] == ["gemini-3.5-flash-tts"] and "automaticamente" in st["note"]
    p.set_models(chat="modelo-inventado")
    assert p.model == "gemini-3.5-flash"
    p.set_models(chat="gemini-3.5-pro", tts="gemini-3.5-flash-tts")
    assert p.model == "gemini-3.5-pro" and p.model_note == ""


async def test_configured_model_is_checked_against_the_account():
    p, _ = provider([], names=["models/gemini-3.5-flash", "models/gemini-3.5-flash-tts"], gemini_model="gemini-antigo-flash")
    await p.resolve_models()
    assert p.model == "gemini-3.5-flash" and "não está disponível" in p.model_note
    locked, _ = provider([], names=["models/gemini-3.5-flash"], gemini_model="gemini-antigo-flash", gemini_auto_model=False)
    await locked.resolve_models()
    assert locked.model == "gemini-antigo-flash" and "não aparece na lista" in locked.model_note


async def test_model_listing_failure_keeps_working_and_retries_later():
    p, models = provider([], names=["models/gemini-3.5-flash"], gemini_model="auto")

    async def boom():
        raise httpx.ConnectError("sem rede")

    real_list, models.list = models.list, boom
    await p.resolve_models()
    assert p.resolved is False and p.last_error.code == "offline" and "sem confirmação" in p.model_note and p.model   # segue com um palpite declarado
    models.list = real_list
    await p.resolve_models()                      # dentro do intervalo de espera: não insiste
    assert p.resolved is False
    await p.resolve_models(force=True)
    assert p.resolved and p.model == "gemini-3.5-flash"


async def test_reasoning_level_steps_down_until_the_model_accepts_it():
    # 2.5 Flash: tenta raciocínio desligado; recusado → padrão do modelo, e lembra disso
    p, models = provider([api_error(400, "INVALID_ARGUMENT", "thinking is not supported"), [chunk(text("ok"))], [chunk(text("de novo"))]], gemini_low_latency=True)
    p.resolved = True
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["ok"]
    assert models.calls[0]["config"].thinking_config.thinking_budget == 0 and models.calls[1]["config"].thinking_config is None
    assert p.thinking_mode == {"gemini-2.5-flash": "default"}
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("y")) == ["de novo"]
    assert models.calls[2]["config"].thinking_config is None and len(models.calls) == 3
    # geração 3: MINIMAL recusado (caso real do 3.7/3.8 Flash) → LOW aceito
    p3, m3 = provider([api_error(400, "INVALID_ARGUMENT", "Thinking level MINIMAL is not supported for this model."), [chunk(text("ok"))]], gemini_low_latency=True, gemini_model="gemini-3.7-flash")
    p3.resolved = True
    await collect(p3.start(system="s", history=[], tools=[]).send_user("x"))
    levels = [c["config"].thinking_config.thinking_level for c in m3.calls]
    assert levels == [types.ThinkingLevel.MINIMAL, types.ThinkingLevel.LOW] and p3.thinking_mode["gemini-3.7-flash"] == "low"
    fixed, mf = provider([api_error(400, "INVALID_ARGUMENT")], gemini_thinking_budget=128)
    fixed.resolved = True
    with pytest.raises(AIError) as e:
        await collect(fixed.start(system="s", history=[], tools=[]).send_user("x"))
    assert e.value.code == "bad_request" and len(mf.calls) == 1        # orçamento explícito do usuário não é alterado
    off, mo = provider([[chunk(text("ok"))]], gemini_low_latency=False)
    off.resolved = True
    await collect(off.start(system="s", history=[], tools=[]).send_user("x"))
    assert mo.calls[0]["config"].thinking_config is None


class ByModel:
    """API falsa em que cada modelo se comporta de um jeito (como na conta real: uns sobrecarregados, outros lentos)."""

    def __init__(self, behaviors: dict[str, Any]):
        self.behaviors, self.calls = behaviors, []

    async def generate_content_stream(self, *, model: str, contents: Any, config: Any):
        self.calls.append({"model": model, "config": config})
        how = self.behaviors[model]
        if callable(how):
            how = how(config)
        if isinstance(how, Exception):
            raise how

        async def gen():
            await asyncio.sleep(how)
            yield chunk(text("pronto"))

        return gen()

    async def list(self):
        async def pager():
            for name in self.behaviors:
                yield SimpleNamespace(name="models/" + name, display_name=name, supported_actions=["generateContent"])

        return pager()


def probing(behaviors: dict[str, Any], **kw: Any) -> tuple[GeminiProvider, ByModel]:
    models = ByModel(behaviors)
    kw.setdefault("db_path", Path(":memory:"))
    kw.setdefault("gemini_probe_models", True)
    settings = Settings(gemini_api_key="teste", gemini_model="auto", gemini_timeout_s=1.0, gemini_first_token_timeout_s=1.0, gemini_probe_timeout_s=0.25, **kw)
    return GeminiProvider(settings, client=SimpleNamespace(aio=SimpleNamespace(models=models))), models


REAL_WORLD = {
    "gemini-3.8-flash": api_error(503, "UNAVAILABLE", "high demand"),      # o mais novo, sobrecarregado
    "gemini-3.7-flash": 5.0,                                              # não responde a tempo
    "gemini-3.6-flash": 0.12,                                             # responde, mas devagar
    "gemini-2.5-flash": 0.0,                                              # responde na hora
    "gemini-2.5-flash-lite": 0.0,
    "gemini-3.8-flash-tts": api_error(400, "INVALID_ARGUMENT"),
}


async def test_startup_probe_picks_a_model_that_actually_answers_fast():
    p, models = probing(dict(REAL_WORLD), gemini_max_first_token_s=0.05)
    await p.resolve_models()
    assert p.model == "gemini-2.5-flash" and p.tts_model == "gemini-3.8-flash-tts"
    # testa um por vez, do mais novo ao mais antigo, e para no primeiro rápido o bastante (poupa cota)
    assert list(p.probes) == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-flash"]
    assert p.probes["gemini-3.8-flash"] == {"ok": False, "first_s": None, "thinking": None, "error": "unavailable"}
    assert p.probes["gemini-3.7-flash"]["error"] == "timeout" and p.probes["gemini-3.6-flash"]["ok"] and "gemini-3.8-flash-tts" not in p.probes
    assert "teste real" in p.model_note and "gemini-3.8-flash (unavailable)" in p.model_note and "gemini-3.6-flash" in p.model_note
    assert p.failover_chain() == ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash-lite"]
    # com um tempo-alvo folgado, para no mais novo que respondeu
    patient, _ = probing(dict(REAL_WORLD), gemini_max_first_token_s=5.0)
    await patient.resolve_models()
    assert patient.model == "gemini-3.6-flash" and "gemini-2.5-flash" not in patient.probes
    # ninguém dentro do alvo: fica com o mais rápido entre os vivos
    slow = {"gemini-3.6-flash": 0.15, "gemini-3.5-flash": 0.05}
    hurry, _ = probing(slow, gemini_max_first_token_s=0.001)
    await hurry.resolve_models()
    assert hurry.model == "gemini-3.5-flash"
    dead, _ = probing({"gemini-3.8-flash": api_error(503, "UNAVAILABLE")})
    await dead.resolve_models()
    assert dead.model == "gemini-3.8-flash" and "Nenhum modelo" in dead.model_note
    off, m_off = probing(dict(REAL_WORLD), gemini_probe_models=False)
    await off.resolve_models()
    assert off.model == "gemini-3.8-flash" and off.probes == {} and m_off.calls == []


def quota_error(per_day: bool, delay: str) -> errors.APIError:
    """429 com os detalhes que a API real envia (formato capturado na validação de 12/11/2026)."""
    quota = "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if per_day else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": f"You exceeded your current quota. Please retry in {delay}.", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota, "quotaValue": "20" if per_day else "5"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}
    return errors.ClientError(429, body)


def test_quota_errors_tell_minute_from_day():
    minute = map_gemini_error(quota_error(False, "21s"))
    assert (minute.code, minute.scope, minute.retry_after_s) == ("rate_limit", "minute", 21.0) and "aguarde 21 s" in minute.message
    day = map_gemini_error(quota_error(True, "58754s"))
    assert (day.code, day.scope) == ("rate_limit", "day") and "diária" in day.message and "16 h" in day.message


async def test_exhausted_quota_moves_to_another_model_and_is_remembered(tmp_path):
    behaviors = {"gemini-3.5-flash": quota_error(True, "58754s"), "gemini-2.5-flash": 0.0}
    p, models = probing(behaviors, db_path=tmp_path / "jarvis.sqlite3", gemini_probe_models=False)
    await p.resolve_models()
    assert p.model == "gemini-3.5-flash"
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["pronto"]
    assert [c["model"] for c in models.calls] == ["gemini-3.5-flash", "gemini-2.5-flash"]      # sem repetir o esgotado
    assert p.model == "gemini-2.5-flash" and "cota esgotada" in p.model_note and p.cooling("gemini-3.5-flash")
    # outra execução do backend lembra da cota esgotada e do modelo que funcionou
    again, m2 = probing(behaviors, db_path=tmp_path / "jarvis.sqlite3", gemini_probe_models=True)
    await again.resolve_models()
    assert again.model == "gemini-2.5-flash" and again.cooling("gemini-3.5-flash") and m2.calls == [] and "reaproveitado" in again.model_note
    assert again.status()["limited"] == ["gemini-3.5-flash"]


async def test_probe_discovers_the_reasoning_level_each_model_accepts():
    def picky(config):  # aceita LOW, recusa MINIMAL — como o 3.7/3.8 Flash reais
        level = config.thinking_config.thinking_level if config.thinking_config else None
        return api_error(400, "INVALID_ARGUMENT", "Thinking level MINIMAL is not supported") if level == types.ThinkingLevel.MINIMAL else 0.0

    def picky_slow(config):
        out = picky(config)
        return out if isinstance(out, Exception) else 0.05

    # alvo de 10 ms: o 3.7 responde (com LOW) mas devagar, então o 2.5 também é testado
    p, models = probing({"gemini-3.7-flash": picky_slow, "gemini-2.5-flash": 0.0}, gemini_max_first_token_s=0.01)
    await p.resolve_models()
    assert p.thinking_mode == {"gemini-3.7-flash": "low", "gemini-2.5-flash": "budget0"} and p.probes["gemini-3.7-flash"]["thinking"] == "low"
    assert p.status()["thinking"] == p.thinking_mode[p.model]


async def test_runtime_failover_promotes_the_next_working_model():
    state = {"down": False}

    def flaky(config):
        return api_error(503, "UNAVAILABLE", "high demand") if state["down"] else 0.0

    p, models = probing({"gemini-3.6-flash": flaky, "gemini-2.5-flash": 0.0}, gemini_max_first_token_s=5.0)
    await p.resolve_models()
    assert p.model == "gemini-3.6-flash"
    state["down"] = True
    models.calls.clear()
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["pronto"]
    assert [c["model"] for c in models.calls] == ["gemini-3.6-flash", "gemini-2.5-flash"]
    assert p.model == "gemini-2.5-flash" and "falhou (unavailable)" in p.model_note and p.last_error is None
