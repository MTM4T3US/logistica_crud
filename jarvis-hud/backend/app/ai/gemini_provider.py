"""Provedor Google Gemini (SDK oficial google-genai): respostas incrementais, function
calling manual (a execução é sempre do backend) e tratamento de falhas.

A chave vem só de GEMINI_API_KEY no backend. Este módulo nunca a registra em log.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, AsyncIterator

import httpx
from google import genai
from google.genai import errors, types

from ..config import Settings
from .base import AIError, AIProvider, ChatSession, ProviderEvent, ToolCall, ToolOutcome

RETRY_BACKOFF_S = 1.2


def make_client(settings: Settings) -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)))


def map_gemini_error(exc: BaseException) -> AIError:
    """Traduz qualquer falha do SDK/rede em um AIError com mensagem para o usuário."""
    if isinstance(exc, AIError):
        return exc
    detail = f"{type(exc).__name__}: {str(exc)[:300]}"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return AIError("timeout", "O Gemini demorou demais para responder. Tente de novo em instantes.", retryable=True, detail=detail)
    if isinstance(exc, (httpx.TransportError, ConnectionError)) or type(exc).__name__ in {"ClientConnectorError", "ClientOSError", "ServerDisconnectedError"}:
        return AIError("offline", "Sem conexão com o Gemini. Verifique a internet.", retryable=True, detail=detail)
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", "") or "").upper()
        msg = (getattr(exc, "message", "") or "").lower()
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return AIError("rate_limit", "O limite de uso da API Gemini foi atingido. Aguarde um pouco ou confira a cota da sua chave.", detail=detail)
        if code in (401, 403) or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"} or "api key" in msg:
            return AIError("auth", "A chave da API Gemini foi recusada. Confira GEMINI_API_KEY em backend/.env.", detail=detail)
        if code == 404 or status == "NOT_FOUND":
            return AIError("model_not_found", "O modelo Gemini configurado não está disponível nesta conta. Ajuste GEMINI_MODEL.", detail=detail)
        if code in (500, 502, 503, 504) or status in {"UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}:
            return AIError("unavailable", "O Gemini está indisponível ou sobrecarregado no momento.", retryable=True, detail=detail)
        return AIError("bad_request", "O Gemini recusou a solicitação.", detail=detail)
    return AIError("unknown", "Falha inesperada ao falar com o Gemini.", detail=detail)


def _version_key(name: str) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", name.split("flash")[0])][:2]
    return tuple(nums + [0] * (2 - len(nums)))


def pick_chat_model(names: list[str], wanted: str) -> str | None:
    """Escolhe o modelo de conversa: o configurado, se existir; senão o Flash estável mais novo."""
    short = [n.split("/")[-1] for n in names]
    if wanted in short:
        return wanted
    flash = [n for n in short if n.startswith("gemini-") and "flash" in n and not any(x in n for x in ("tts", "image", "audio", "live", "embedding", "lite"))]
    if not flash:
        return None
    stable = [n for n in flash if "preview" not in n and "exp" not in n]
    return sorted(stable or flash, key=lambda n: (_version_key(n), -len(n)))[-1]


def pick_tts_model(names: list[str], wanted: str) -> str | None:
    short = [n.split("/")[-1] for n in names]
    if wanted in short:
        return wanted
    tts = [n for n in short if "tts" in n]
    flash = [n for n in tts if "flash" in n]
    pool = flash or tts
    return sorted(pool, key=_version_key)[-1] if pool else None


class GeminiProvider(AIProvider):
    name = "gemini"
    cloud = True

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client or make_client(settings)
        self.model = settings.gemini_model
        self.fallback = settings.gemini_fallback_model
        self.tts_model = settings.gemini_tts_model
        self.available_models: list[str] = []
        self.model_note = ""
        self.last_error: AIError | None = None

    async def resolve_models(self) -> None:
        """Confere na conta quais modelos existem e ajusta os configurados (se permitido)."""
        try:
            pager = await asyncio.wait_for(self.client.aio.models.list(), timeout=self.settings.gemini_timeout_s)
            names = [m.name async for m in pager if getattr(m, "name", None)]
        except Exception as exc:  # sem rede/chave inválida: mantém o configurado e registra o motivo
            self.last_error = map_gemini_error(exc)
            self.model_note = f"Não foi possível listar os modelos ({self.last_error.code})."
            return
        self.available_models = sorted(n.split("/")[-1] for n in names)
        if not self.settings.gemini_auto_model:
            return
        chat = pick_chat_model(names, self.model)
        if chat and chat != self.model:
            self.model_note = f"'{self.model}' não está disponível na conta; usando '{chat}'."
            self.model = chat
        tts = pick_tts_model(names, self.tts_model)
        if tts:
            self.tts_model = tts

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name, "model": self.model, "fallback_model": self.fallback, "tts_model": self.tts_model, "cloud": True,
            "note": self.model_note, "last_error": self.last_error.code if self.last_error else None,
        }

    def start(self, *, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatSession:
        return GeminiSession(self, system, history, tools)


class GeminiSession(ChatSession):
    def __init__(self, provider: GeminiProvider, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]):
        self.p = provider
        self.contents: list[types.Content] = []
        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            if msg.get("content"):
                self.contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
        cfg: dict[str, Any] = {"system_instruction": system, "temperature": 0.7}
        if tools:
            decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]) for t in tools]
            cfg["tools"] = [types.Tool(function_declarations=decls)]
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        if provider.settings.gemini_thinking_budget is not None:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=provider.settings.gemini_thinking_budget)
        self.config = types.GenerateContentConfig(**cfg)

    def send_user(self, text: str) -> AsyncIterator[ProviderEvent]:
        self.contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        return self._generate()

    def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]:
        parts = [types.Part.from_function_response(name=o.call.name, response=o.for_model()) for o in outcomes]
        self.contents.append(types.Content(role="user", parts=parts))
        return self._generate()

    async def _generate(self) -> AsyncIterator[ProviderEvent]:
        timeout = self.p.settings.gemini_timeout_s
        plan = [self.p.model, self.p.model] + ([self.p.fallback] if self.p.fallback and self.p.fallback != self.p.model else [])
        last: AIError | None = None
        for attempt, model in enumerate(plan):
            emitted = False
            parts: list[types.Part] = []
            calls: list[ToolCall] = []
            finish = None
            try:
                stream = await asyncio.wait_for(self.p.client.aio.models.generate_content_stream(model=model, contents=self.contents, config=self.config), timeout)
                it = stream.__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(it.__anext__(), timeout)
                    except StopAsyncIteration:
                        break
                    if getattr(chunk, "prompt_feedback", None) and getattr(chunk.prompt_feedback, "block_reason", None):
                        raise AIError("blocked", "O Gemini bloqueou este pedido pelas políticas de segurança.")
                    for cand in chunk.candidates or []:
                        finish = getattr(cand, "finish_reason", None) or finish
                        for part in (cand.content.parts if cand.content and cand.content.parts else []):
                            parts.append(part)
                            if part.function_call is not None:
                                fc = part.function_call
                                calls.append(ToolCall(id=fc.id or uuid.uuid4().hex[:12], name=fc.name or "", args=dict(fc.args or {})))
                            elif part.text and not getattr(part, "thought", False):
                                emitted = True
                                yield part.text
            except Exception as exc:
                last = map_gemini_error(exc)
                self.p.last_error = last
                is_last = attempt == len(plan) - 1
                # depois de emitir texto não há como "desdizer": não repete a chamada
                can_retry = last.retryable or (last.code == "model_not_found" and not is_last)
                if emitted or is_last or not can_retry:
                    raise last from None
                if model == plan[attempt + 1]:
                    await asyncio.sleep(RETRY_BACKOFF_S)
                continue
            if not emitted and not calls:
                reason = str(getattr(finish, "name", finish) or "")
                if "SAFETY" in reason or "PROHIBITED" in reason:
                    raise AIError("blocked", "O Gemini bloqueou a resposta pelas políticas de segurança.")
                raise AIError("empty", "O Gemini não devolveu conteúdo para este pedido.", detail=f"finish_reason={reason}")
            self.contents.append(types.Content(role="model", parts=parts))
            self.p.last_error = None
            for call in calls:
                yield call
            return
        raise last or AIError("unknown", "Falha inesperada ao falar com o Gemini.")
