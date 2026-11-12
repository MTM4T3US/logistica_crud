"""Provedor Gemini com um cliente falso (mesmos tipos do SDK): streaming, ferramentas e falhas."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors, types

from app.ai import gemini_provider as gp
from app.ai.base import AIError, ToolCall, ToolOutcome
from app.ai.gemini_provider import GeminiProvider, map_gemini_error, pick_chat_model, pick_tts_model
from app.config import Settings

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
        async def pager():
            for n in self.names:
                yield SimpleNamespace(name=n)

        return pager()


def provider(script: list[Any], **kw: Any) -> tuple[GeminiProvider, FakeModels]:
    models = FakeModels(script, kw.pop("names", None))
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    settings = Settings(gemini_api_key="teste", gemini_timeout_s=kw.pop("timeout", 2.0), **kw)
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
    p, models = provider([api_error(404, "NOT_FOUND"), api_error(404, "NOT_FOUND"), [chunk(text("ok"))]], gemini_model="gemini-a", gemini_fallback_model="gemini-b")
    assert await collect(p.start(system="s", history=[], tools=[]).send_user("x")) == ["ok"]
    assert [c["model"] for c in models.calls] == ["gemini-a", "gemini-a", "gemini-b"]


async def test_non_retryable_and_exhausted_errors_surface():
    p, models = provider([api_error(429, "RESOURCE_EXHAUSTED")])
    with pytest.raises(AIError) as e:
        await collect(p.start(system="s", history=[], tools=[]).send_user("x"))
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


def test_model_selection_prefers_configured_then_newest_stable_flash():
    names = ["models/gemini-2.0-flash", "models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-2.5-pro", "models/gemini-3-flash-preview", "models/gemini-2.5-flash-preview-tts", "models/gemini-2.5-pro-preview-tts", "models/gemini-2.5-flash-image"]
    assert pick_chat_model(names, "gemini-2.0-flash") == "gemini-2.0-flash"
    assert pick_chat_model(names, "gemini-9-flash") == "gemini-2.5-flash"
    assert pick_chat_model(["models/gemini-3-flash-preview", "models/gemini-3-pro"], "x") == "gemini-3-flash-preview"
    assert pick_chat_model(["models/text-embedding-004"], "x") is None
    assert pick_tts_model(names, "nao-existe") == "gemini-2.5-flash-preview-tts" and pick_tts_model(["models/gemini-2.5-flash"], "x") is None


async def test_resolve_models_adjusts_to_account_and_survives_failure():
    p, _ = provider([], names=["models/gemini-3.5-flash", "models/gemini-3.5-flash-tts"], gemini_model="gemini-antigo-flash")
    await p.resolve_models()
    assert p.model == "gemini-3.5-flash" and p.tts_model == "gemini-3.5-flash-tts" and "não está disponível" in p.model_note
    locked, _ = provider([], names=["models/gemini-3.5-flash"], gemini_model="gemini-antigo-flash", gemini_auto_model=False)
    await locked.resolve_models()
    assert locked.model == "gemini-antigo-flash"

    async def boom():
        raise httpx.ConnectError("sem rede")

    p.client.aio.models.list = boom
    p.model_note = ""
    await p.resolve_models()
    assert p.last_error.code == "offline" and "offline" in p.model_note
