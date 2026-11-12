"""Provedor Google Gemini (SDK oficial google-genai): respostas incrementais, function
calling manual (a execução é sempre do backend) e tratamento de falhas.

Os modelos NÃO são presumidos: com GEMINI_MODEL=auto (padrão) o backend lista o que a
conta oferece e escolhe. A chave vem só de GEMINI_API_KEY e nunca é registrada em log.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, AsyncIterator

import httpx
from google import genai
from google.genai import errors, types

from ..config import Settings
from .base import AIError, AIProvider, ChatSession, ProviderEvent, ToolCall, ToolOutcome

RETRY_BACKOFF_S = 1.2
#: último recurso se a conta não puder ser consultada (sem rede na inicialização)
GUESS_CHAT_MODEL = "gemini-2.5-flash"
GUESS_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_NETWORK_ERRORS = {"TransportError", "NetworkError", "ConnectError", "ProxyError", "ClientConnectionError", "ClientConnectorError", "ClientOSError", "ServerDisconnectedError"}
_NOT_CHAT = ("tts", "image", "audio", "live", "embedding", "aqa", "learnlm", "robotics", "computer-use", "transcribe", "translate", "banana", "omni", "decision", "customtools")


def make_client(settings: Settings, api_key: str | None = None, timeout_s: float | None = None) -> genai.Client:
    ms = int((timeout_s or settings.gemini_timeout_s) * 1000)
    return genai.Client(api_key=api_key or settings.gemini_api_key, http_options=types.HttpOptions(api_version=settings.gemini_api_version, timeout=max(1, ms)))


def map_gemini_error(exc: BaseException) -> AIError:
    """Traduz qualquer falha do SDK/rede em um AIError com mensagem para o usuário."""
    if isinstance(exc, AIError):
        return exc
    detail = f"{type(exc).__name__}: {str(exc)[:300]}"
    # O SDK pode usar httpx, httpx2 ou aiohttp por baixo: reconhecemos a falha pelo nome das
    # classes na hierarquia da exceção, não pelo módulo de onde ela veio.
    kinds = {c.__name__ for c in type(exc).__mro__}
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)) or "TimeoutException" in kinds or "ServerTimeoutError" in kinds:
        return AIError("timeout", "O Gemini demorou demais para responder. Tente de novo em instantes.", retryable=True, detail=detail)
    if isinstance(exc, (httpx.TransportError, ConnectionError)) or kinds & _NETWORK_ERRORS:
        return AIError("offline", "Sem conexão com o Gemini. Verifique a internet.", retryable=True, detail=detail)
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", "") or "").upper()
        msg = (getattr(exc, "message", "") or "").lower()
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            wait, scope, limit = quota_details(exc)
            if scope == "day":
                text = "A cota diária gratuita deste modelo Gemini acabou" + (f" (volta em cerca de {max(1, round(wait / 3600))} h)." if wait else ".")
            else:
                text = "O limite por minuto da API Gemini foi atingido" + (f"; aguarde {round(wait)} s." if wait else ". Aguarde um instante.")
            err = AIError("rate_limit", text, detail=detail, retry_after_s=wait, scope=scope)
            err.limit = limit
            return err
        if code in (401, 403) or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"} or "api key" in msg:
            return AIError("auth", "A chave da API Gemini foi recusada. Confira GEMINI_API_KEY em backend/.env.", detail=detail)
        if code == 404 or status == "NOT_FOUND":
            return AIError("model_not_found", "O modelo Gemini configurado não está disponível nesta conta. Ajuste GEMINI_MODEL.", detail=detail)
        if code in (500, 502, 503, 504) or status in {"UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}:
            return AIError("unavailable", "O Gemini está indisponível ou sobrecarregado no momento.", retryable=True, detail=detail)
        return AIError("bad_request", "O Gemini recusou a solicitação.", detail=detail)
    return AIError("unknown", "Falha inesperada ao falar com o Gemini.", detail=detail)


def quota_info(exc: BaseException) -> tuple[float | None, str]:
    """Lê do erro 429 quanto esperar (RetryInfo) e se a cota estourada é por minuto ou por dia."""
    wait, scope, _ = quota_details(exc)
    return wait, scope


def quota_details(exc: BaseException) -> tuple[float | None, str, int | None]:
    """Como quota_info, mais o limite informado pelo Google (quotaValue), quando vier."""
    wait: float | None = None
    scope = "minute"
    limit: int | None = None
    body = getattr(exc, "details", None)
    items = (body.get("error", {}) if isinstance(body, dict) else {}).get("details", []) or []
    for item in items:
        kind = str(item.get("@type", "")).rsplit(".", 1)[-1]
        if kind == "RetryInfo":
            m = re.match(r"([\d.]+)s", str(item.get("retryDelay", "")))
            wait = float(m.group(1)) if m else wait
        elif kind == "QuotaFailure":
            for v in item.get("violations", []):
                if "PerDay" in str(v.get("quotaId", "")):
                    scope = "day"
                try:
                    limit = int(v.get("quotaValue"))
                except (TypeError, ValueError):
                    pass
    if wait is None:
        m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", str(getattr(exc, "message", "") or ""))
        if m:
            wait = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))
    if wait and wait > 600:
        scope = "day"
    return wait, scope, limit


PACIFIC = ZoneInfo("America/Los_Angeles")   # as cotas diárias do Gemini viram à meia-noite do Pacífico


def quota_day() -> str:
    return datetime.now(PACIFIC).strftime("%Y-%m-%d")


def model_version(name: str) -> tuple[int, int]:
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def is_chat_model(name: str, actions: list[str] | None = None) -> bool:
    short = name.split("/")[-1]
    if not short.startswith("gemini-") or any(x in short for x in _NOT_CHAT):
        return False
    return not actions or "generateContent" in actions


def _rank(name: str) -> tuple:
    """Maior é melhor: estável antes de prévia, Flash comum antes de Lite, versão mais nova."""
    preview = any(x in name for x in ("preview", "exp", "latest"))
    return (not preview, "lite" not in name, model_version(name), -len(name))


def pick_chat_model(names: list[str], wanted: str) -> str | None:
    """O modelo pedido, se a conta o oferece; senão o melhor Flash disponível."""
    short = [n.split("/")[-1] for n in names]
    if wanted and wanted != "auto" and wanted in short:
        return wanted
    flash = [n for n in short if is_chat_model(n) and "flash" in n]
    pool = [n for n in flash if "lite" not in n] or flash
    return sorted(pool, key=_rank)[-1] if pool else None


def pick_tts_model(names: list[str], wanted: str) -> str | None:
    short = [n.split("/")[-1] for n in names]
    if wanted and wanted != "auto" and wanted in short:
        return wanted
    tts = [n for n in short if "tts" in n]
    pool = [n for n in tts if "flash" in n] or tts
    return sorted(pool, key=_rank)[-1] if pool else None


def pick_stt_model(names: list[str], wanted: str | None, chat: str) -> str:
    """Modelo de transcrição: o pedido; senão um dedicado ("transcribe", não ao vivo); senão o de conversa."""
    short = [n.split("/")[-1] for n in names]
    if wanted and wanted != "auto" and wanted in short:
        return wanted
    dedicated = [n for n in short if "transcribe" in n and "live" not in n]
    return sorted(dedicated, key=_rank)[-1] if dedicated else chat


class GeminiProvider(AIProvider):
    name = "gemini"
    cloud = True

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client or make_client(settings)
        self.wanted_model = settings.gemini_model or "auto"
        self.wanted_tts = settings.gemini_tts_model or "auto"
        self.model = self.wanted_model if self.wanted_model != "auto" else GUESS_CHAT_MODEL
        self.tts_model = self.wanted_tts if self.wanted_tts != "auto" else GUESS_TTS_MODEL
        self.stt_model = settings.gemini_stt_model or self.model
        self.fallback = settings.gemini_fallback_model
        self.catalog: list[dict[str, Any]] = []
        self.model_note = "Modelos ainda não conferidos na conta."
        self.resolved = False
        self._last_try = 0.0
        self.last_error: AIError | None = None
        #: nível de raciocínio aceito por modelo ("minimal" | "low" | "budget0" | "default"), descoberto na prática
        self.thinking_mode: dict[str, str] = {}
        #: resultado do teste de resposta de cada candidato: {modelo: {ok, first_s, error}}
        self.probes: dict[str, dict[str, Any]] = {}
        #: modelos com cota estourada: {modelo: instante (epoch) em que a cota volta}
        self.cooldowns: dict[str, float] = {}
        #: como cada modelo de voz aceita a direção de estilo ("metadata" | "plain")
        self.tts_style_mode: dict[str, str] = {}
        self._state_path: Path | None = None if str(settings.db_path) == ":memory:" else settings.db_path.parent / "gemini_state.json"
        self._chosen_at = 0.0
        #: pedidos contados por este computador no dia (fuso do Pacífico) e limites informados pela API
        self.usage: dict[str, Any] = {"day": quota_day(), "counts": {}}
        self.limits: dict[str, dict[str, int]] = {}
        self.connection: dict[str, Any] = {"state": "desconhecida", "at": None, "detail": ""}
        self._saved_at = 0.0
        self._load_state()

    # ------------------------------------------------------------------ memória entre execuções
    def _load_state(self) -> None:
        """Reaproveita o que já se aprendeu sobre a conta (modelo que respondeu, cotas estouradas):
        com 20 requisições por dia no nível gratuito, não dá para redescobrir a cada inicialização."""
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        now = time.time()
        self.cooldowns = {m: t for m, t in data.get("cooldowns", {}).items() if isinstance(t, (int, float)) and t > now}
        self.thinking_mode = {m: v for m, v in data.get("thinking_mode", {}).items() if isinstance(v, str)}
        self.tts_style_mode = {m: v for m, v in data.get("tts_style_mode", {}).items() if isinstance(v, str)}
        usage = data.get("usage", {})
        if isinstance(usage, dict) and usage.get("day") == quota_day() and isinstance(usage.get("counts"), dict):
            self.usage = {"day": usage["day"], "counts": {k: int(v) for k, v in usage["counts"].items() if isinstance(v, int)}}
        self.limits = {m: {k: int(v) for k, v in d.items() if isinstance(v, int)} for m, d in data.get("limits", {}).items() if isinstance(d, dict)}
        if self.wanted_model == "auto" and isinstance(data.get("chosen"), str) and now - float(data.get("chosen_at", 0)) < self.settings.gemini_probe_ttl_s:
            self.model, self._chosen_at = data["chosen"], float(data.get("chosen_at", 0))
            self.probes = data.get("probes", {}) if isinstance(data.get("probes"), dict) else {}

    def save_state(self) -> None:
        if not self._state_path:
            return
        self._saved_at = time.time()
        data = {"chosen": self.model, "chosen_at": self._chosen_at, "probes": self.probes, "cooldowns": self.cooldowns,
                "thinking_mode": self.thinking_mode, "tts_style_mode": self.tts_style_mode, "usage": self.usage, "limits": self.limits}
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def cooling(self, model: str) -> bool:
        return self.cooldowns.get(model, 0) > time.time()

    def count(self, model: str) -> None:
        """Conta um pedido atendido. É a contagem DESTE computador — o Google não informa o saldo."""
        if self.usage.get("day") != quota_day():
            self.usage = {"day": quota_day(), "counts": {}}
        self.usage["counts"][model] = int(self.usage["counts"].get(model, 0)) + 1
        self.connection = {"state": "online", "at": time.time(), "detail": ""}
        if time.time() - self._saved_at > 30:
            self.save_state()

    def note_network(self, err: AIError) -> None:
        if err.code in ("offline", "timeout"):
            self.connection = {"state": "offline" if err.code == "offline" else "instável", "at": time.time(), "detail": err.message}

    def usage_report(self) -> dict[str, Any]:
        if self.usage.get("day") != quota_day():
            self.usage = {"day": quota_day(), "counts": {}}
        models = sorted(set(self.usage["counts"]) | set(self.limits) | {self.model, self.tts_model, self.stt_model})
        return {
            "day": self.usage["day"],
            "models": {m: {"today": self.usage["counts"].get(m, 0), "day_limit": self.limits.get(m, {}).get("day"),
                           "minute_limit": self.limits.get(m, {}).get("minute"), "exhausted": self.cooling(m)} for m in models},
        }

    def note_limit(self, model: str, err: AIError) -> None:
        """Registra que a cota deste modelo estourou, para não insistir nele até voltar."""
        if err.code != "rate_limit":
            return
        limit = getattr(err, "limit", None)
        if isinstance(limit, int):
            self.limits.setdefault(model, {})["day" if err.scope == "day" else "minute"] = limit
        wait = err.retry_after_s or (3600.0 if err.scope == "day" else 30.0)
        self.cooldowns[model] = time.time() + min(wait, 86400.0) + 1.0
        self.save_state()

    def usable(self, models: list[str]) -> list[str]:
        """Os modelos da lista que não estão com a cota estourada (se todos estiverem, devolve a lista toda)."""
        free = [m for m in models if not self.cooling(m)]
        return free or models

    # ------------------------------------------------------------------ modelos da conta
    @property
    def available_models(self) -> list[str]:
        return [m["name"] for m in self.catalog]

    def chat_models(self) -> list[str]:
        # Flash primeiro (mais rápido para conversa falada), depois os demais
        return sorted((m["name"] for m in self.catalog if is_chat_model(m["name"], m["actions"])), key=lambda n: ("flash" in n and "lite" not in n, *_rank(n)), reverse=True)

    def tts_models(self) -> list[str]:
        return sorted((m["name"] for m in self.catalog if "tts" in m["name"] and (not m["actions"] or "generateContent" in m["actions"])), key=_rank, reverse=True)

    def generate_models(self) -> list[str]:
        return [m["name"] for m in self.catalog if not m["actions"] or "generateContent" in m["actions"]]

    async def resolve_models(self, force: bool = False) -> None:
        """Lista os modelos da conta e escolhe os de conversa e de voz. Sem rede, mantém o
        último palpite e tenta de novo depois (no máximo a cada 30 s)."""
        if self.resolved and not force:
            return
        if not force and time.monotonic() - self._last_try < 30 and self._last_try:
            return
        self._last_try = time.monotonic()
        try:
            pager = await asyncio.wait_for(self.client.aio.models.list(), timeout=self.settings.gemini_timeout_s)
            catalog = []
            async for m in pager:
                if getattr(m, "name", None):
                    catalog.append({"name": m.name.split("/")[-1], "label": getattr(m, "display_name", None) or "", "actions": list(getattr(m, "supported_actions", None) or [])})
        except Exception as exc:
            self.last_error = map_gemini_error(exc)
            self.model_note = f"Não foi possível listar os modelos da conta ({self.last_error.code}); usando {self.model} sem confirmação."
            return
        self.catalog = sorted(catalog, key=lambda m: m["name"])
        self.resolved = True
        names = self.generate_models()
        if not self.settings.gemini_auto_model and self.wanted_model != "auto":
            self.model_note = "" if self.model in names else f"Atenção: '{self.model}' não aparece na lista da conta."
            self.stt_model = self.settings.gemini_stt_model or self.model
            return
        chat = pick_chat_model(names, self.wanted_model)
        if chat is None:
            self.model_note = "A conta não lista nenhum modelo Gemini Flash para conversa."
        elif self.wanted_model == "auto":
            # o modelo que já respondeu em teste anterior (ver _load_state) é reaproveitado
            if self._chosen_at and self.model in names and not self.cooling(self.model):
                self.model_note = "Modelo confirmado em teste anterior (reaproveitado para poupar a cota)."
            else:
                self.model, self.model_note = chat, f"Escolhido automaticamente entre {len(self.chat_models())} modelos de conversa da conta."
                if self.settings.gemini_probe_models:
                    await self.probe_candidates()
        elif chat != self.wanted_model:
            self.model, self.model_note = chat, f"'{self.wanted_model}' não está disponível na conta; usando '{chat}'."
        else:
            self.model, self.model_note = chat, ""
        tts = pick_tts_model(names, self.wanted_tts)
        if tts:
            self.tts_model = tts
        self.stt_model = pick_stt_model(names, self.settings.gemini_stt_model, self.model)

    def set_models(self, chat: str | None = None, tts: str | None = None) -> None:
        """Escolha feita pelo usuário no painel — só entre modelos que a conta listou."""
        if chat and chat in self.chat_models():
            self.model, self.wanted_model, self.model_note = chat, chat, ""
        if tts and tts in self.tts_models():
            self.tts_model = self.wanted_tts = tts

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name, "model": self.model, "fallback_model": self.fallback, "tts_model": self.tts_model, "stt_model": self.stt_model, "cloud": True,
            "note": self.model_note, "resolved": self.resolved, "chat_models": self.chat_models(), "tts_models": self.tts_models(),
            "probes": self.probes, "thinking": self.thinking_mode.get(self.model),
            "limited": sorted(m for m in self.cooldowns if self.cooling(m)),
            "usage": self.usage_report(), "connection": self.connection,
            "last_error": self.last_error.code if self.last_error else None,
        }

    def thinking_ladder(self, model: str) -> list[str]:
        """Do raciocínio mais leve (resposta mais rápida) até o padrão do modelo. O que cada
        geração aceita varia — e muda —, então tentamos em ordem e guardamos o que funcionou."""
        s = self.settings
        if s.gemini_thinking_budget is not None:
            return ["fixed"]
        if not s.gemini_low_latency:
            return ["default"]
        if model in self.thinking_mode:
            return [self.thinking_mode[model]]
        version = model_version(model)
        if version >= (3, 0):
            return ["minimal", "low", "default"]
        if version >= (2, 5) and "flash" in model:
            return ["budget0", "default"]
        return ["default"]

    def thinking_config(self, mode: str) -> types.ThinkingConfig | None:
        if mode == "fixed":
            return types.ThinkingConfig(thinking_budget=self.settings.gemini_thinking_budget)
        if mode == "minimal":
            return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
        if mode == "low":
            return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
        if mode == "budget0":
            return types.ThinkingConfig(thinking_budget=0)
        return None

    # ------------------------------------------------------------------ teste de resposta
    async def probe(self, model: str) -> dict[str, Any]:
        """Uma pergunta mínima, em streaming: o modelo responde? em quanto tempo?"""
        limit = self.settings.gemini_probe_timeout_s
        last: AIError | None = None
        for mode in self.thinking_ladder(model):
            cfg: dict[str, Any] = {"system_instruction": "Responda em português, de forma direta.", "temperature": 0.0}
            thinking = self.thinking_config(mode)
            if thinking is not None:
                cfg["thinking_config"] = thinking
            started = time.monotonic()
            try:
                stream = await asyncio.wait_for(self.client.aio.models.generate_content_stream(model=model, contents="Diga apenas: pronto.", config=types.GenerateContentConfig(**cfg)), limit)
                it = stream.__aiter__()
                first = None
                while True:
                    try:
                        chunk = await asyncio.wait_for(it.__anext__(), limit)
                    except StopAsyncIteration:
                        break
                    if first is None and (chunk.text or ""):
                        first = time.monotonic() - started
                if first is None:
                    raise AIError("empty", "O modelo não devolveu texto.")
                self.thinking_mode[model] = mode
                return {"ok": True, "first_s": round(first, 2), "thinking": mode, "error": None}
            except Exception as exc:
                last = map_gemini_error(exc)
                if last.code == "bad_request" and mode not in ("default", "fixed"):
                    continue  # este modelo não aceita esse nível de raciocínio: tenta o próximo
                break
        return {"ok": False, "first_s": None, "thinking": None, "error": last.code if last else "unknown"}

    async def probe_candidates(self, limit: int = 4) -> None:
        """Escolhe um modelo de conversa que realmente responda, gastando o mínimo de cota:
        testa um por vez, do mais novo ao mais antigo, e para no primeiro que responde dentro
        do tempo-alvo. Se nenhum couber no alvo, fica com o mais rápido entre os que responderam."""
        ranked = [m for m in self.chat_models() if "flash" in m and "latest" not in m]
        order = self.usable([m for m in ranked if "lite" not in m])[:limit] + self.usable([m for m in ranked if "lite" in m])[:1]
        target = self.settings.gemini_max_first_token_s
        self.probes = {}
        chosen = None
        for model in order:
            result = self.probes[model] = await self.probe(model)
            if result["ok"] and result["first_s"] <= target:
                chosen = model
                break
        alive = [m for m in self.probes if self.probes[m]["ok"]]
        if chosen is None and alive:
            chosen = min(alive, key=lambda m: self.probes[m]["first_s"])
        if chosen is None:
            self.model_note = "Nenhum modelo de conversa respondeu ao teste inicial; mantendo " + self.model + "."
            return
        skipped = [f"{m} ({r['error'] or str(r['first_s']) + ' s'})" for m, r in self.probes.items() if m != chosen]
        self.model, self._chosen_at = chosen, time.time()
        self.model_note = f"Escolhido por teste real: respondeu em {self.probes[chosen]['first_s']} s." + (f" Testados antes dele: {', '.join(skipped)}." if skipped else "")
        self.save_state()

    def failover_chain(self) -> list[str]:
        """Modelo atual e os reservas, na ordem: os que já responderam em teste, depois os demais
        Flash da conta. Modelos com a cota estourada vão para o fim da fila."""
        ranked = [m for m in self.chat_models() if "flash" in m and "latest" not in m]
        proven = sorted((m for m, r in self.probes.items() if r.get("ok")), key=lambda m: self.probes[m]["first_s"])
        chain: list[str] = []
        for m in [self.model, *proven, *[m for m in ranked if "lite" not in m], *[m for m in ranked if "lite" in m]]:
            if m not in chain:
                chain.append(m)
        if self.fallback and self.fallback not in chain:
            chain.insert(1, self.fallback)
        chain = [m for m in chain if not self.cooling(m)] + [m for m in chain if self.cooling(m)]
        return chain[: max(2, self.settings.gemini_failover_models)]

    def tts_chain(self) -> list[str]:
        """Modelo de voz atual e os outros modelos de voz da conta (cotas são por modelo)."""
        chain = [self.tts_model] + [m for m in self.tts_models() if m != self.tts_model]
        return [m for m in chain if not self.cooling(m)] + [m for m in chain if self.cooling(m)]

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
        self._base: dict[str, Any] = {"system_instruction": system, "temperature": 0.7}
        if tools:
            decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]) for t in tools]
            self._base["tools"] = [types.Tool(function_declarations=decls)]
            self._base["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

    def _config(self, mode: str) -> types.GenerateContentConfig:
        cfg = dict(self._base)
        thinking = self.p.thinking_config(mode)
        if thinking is not None:
            cfg["thinking_config"] = thinking
        return types.GenerateContentConfig(**cfg)

    def send_user(self, text: str) -> AsyncIterator[ProviderEvent]:
        self.contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        return self._generate()

    def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]:
        parts = [types.Part.from_function_response(name=o.call.name, response=o.for_model()) for o in outcomes]
        self.contents.append(types.Content(role="user", parts=parts))
        return self._generate()

    async def _generate(self) -> AsyncIterator[ProviderEvent]:
        await self.p.resolve_models()
        settings = self.p.settings
        chain = self.p.failover_chain()
        # com alternativas, não insistimos no mesmo modelo: a próxima tentativa já é outro
        plan = chain if len(chain) > 1 else [chain[0], chain[0]]
        limited: list[str] = []
        last: AIError | None = None
        attempt = 0
        while attempt < len(plan):
            model = plan[attempt]
            ladder = self.p.thinking_ladder(model)
            step = 0
            moved = False
            while step < len(ladder):
                mode = ladder[step]
                emitted = False
                parts: list[types.Part] = []
                calls: list[ToolCall] = []
                finish = None
                try:
                    stream = await asyncio.wait_for(self.p.client.aio.models.generate_content_stream(model=model, contents=self.contents, config=self._config(mode)), settings.gemini_first_token_timeout_s)
                    it = stream.__aiter__()
                    got_any = False
                    while True:
                        try:
                            chunk = await asyncio.wait_for(it.__anext__(), settings.gemini_timeout_s if got_any else settings.gemini_first_token_timeout_s)
                        except StopAsyncIteration:
                            break
                        got_any = True
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
                    # o modelo não aceita este nível de raciocínio: desce um degrau e repete já
                    if last.code == "bad_request" and mode not in ("default", "fixed") and not emitted and step + 1 < len(ladder):
                        step += 1
                        continue
                    is_last = attempt == len(plan) - 1
                    self.p.note_network(last)
                    if last.code == "unavailable" or last.code == "timeout":
                        # modelo sobrecarregado/travado: evita por 20 min (aprendido com o uso, sem testes extras)
                        self.p.cooldowns[model] = time.time() + 1200
                    if last.code == "rate_limit":
                        self.p.note_limit(model, last)      # cota por modelo: o próximo da fila pode ter saldo
                        limited.append(model)
                    # depois de emitir texto não há como "desdizer": não repete a chamada
                    can_retry = last.retryable or (last.code in ("model_not_found", "rate_limit") and not is_last)
                    if emitted or is_last or not can_retry:
                        raise last from None
                    if last.code == "rate_limit":
                        # a cota não volta em segundos: pula as repetições do mesmo modelo
                        nxt = next((i for i in range(attempt + 1, len(plan)) if plan[i] not in limited), None)
                        if nxt is None:
                            raise last from None
                        attempt = nxt - 1
                    elif model == plan[attempt + 1]:
                        await asyncio.sleep(RETRY_BACKOFF_S)
                    moved = True
                    break
                if not emitted and not calls:
                    reason = str(getattr(finish, "name", finish) or "")
                    if "SAFETY" in reason or "PROHIBITED" in reason:
                        raise AIError("blocked", "O Gemini bloqueou a resposta pelas políticas de segurança.")
                    raise AIError("empty", "O Gemini não devolveu conteúdo para este pedido.", detail=f"finish_reason={reason}")
                self.p.thinking_mode[model] = mode
                self.p.count(model)
                if model != self.p.model:
                    # o modelo principal falhou e este respondeu: passa a ser o principal
                    why = "cota esgotada" if self.p.model in limited else (last.code if last else "erro")
                    self.p.model_note = f"'{self.p.model}' falhou ({why}); agora usando '{model}'."
                    self.p.model, self.p._chosen_at = model, time.time()
                    self.p.save_state()
                self.contents.append(types.Content(role="model", parts=parts))
                self.p.last_error = None
                for call in calls:
                    yield call
                return
            if moved:
                attempt += 1
                continue
            break
        raise last or AIError("unknown", "Falha inesperada ao falar com o Gemini.")
