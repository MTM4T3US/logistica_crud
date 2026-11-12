"""Modo local (sem IA): mantém o sistema utilizável quando não há chave ou o Gemini falha.

NÃO é inteligência artificial e não finge ser: reconhece poucas palavras-chave, chama as
mesmas ferramentas reais e responde com frases fixas. O HUD identifica este modo.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any, AsyncIterator

from ..security.permissions import Permissions
from ..services.local_info import greeting
from .base import AIProvider, ChatSession, ProviderEvent, ToolCall, ToolOutcome

HELP = "No modo local eu entendo apenas: hora, clima, estado do computador, processos, volume e abrir um aplicativo autorizado."


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _n(v: Any) -> str:
    return str(round(float(v))) if v is not None else "?"


def say_weather(d: dict[str, Any]) -> str:
    today = d.get("today") or {}
    text = f"Em {d['city']} faz {_n(d['temperature_c'])} graus, {d['condition'].lower()}, com sensação de {_n(d['feels_like_c'])} e umidade de {_n(d['humidity'])} por cento."
    if today:
        text += f" Hoje a máxima é de {_n(today['max_c'])} e a mínima de {_n(today['min_c'])}, com {_n(today['rain_probability'])} por cento de chance de chuva."
    return text


def say_system(d: dict[str, Any]) -> str:
    text = f"O processador está em {_n(d['cpu_percent'])} por cento, a memória em {_n(d['ram_percent'])} por cento, e o disco principal tem {_n(d['disk_free_gb'])} gigabytes livres."
    if d.get("gpu"):
        text += f" A placa de vídeo está em {_n(d['gpu']['percent'])} por cento."
    return text


def say_processes(d: dict[str, Any]) -> str:
    rows = d.get("processes", [])[:3]
    if not rows:
        return "Não consegui ler os processos."
    return "Os processos que mais consomem agora são " + ", ".join(f"{r['name']} com {_n(r['cpu_percent'])} por cento" for r in rows) + "."


class LocalProvider(AIProvider):
    name = "local"
    model = "comandos locais (sem IA)"
    cloud = False

    def __init__(self, perms: Permissions, reason: str = "IA não configurada"):
        self.perms = perms
        self.reason = reason

    def start(self, *, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatSession:
        return LocalSession(self, {t["name"] for t in tools})


class LocalSession(ChatSession):
    def __init__(self, provider: LocalProvider, tool_names: set[str]):
        self.p, self.tools = provider, tool_names

    def _intent(self, text: str) -> ToolCall | str:
        t = norm(text)
        cid = "local-" + uuid.uuid4().hex[:8]
        if re.search(r"\b(clima|temperatura|chuva|chover|previsao|calor|frio)\b", t) or re.search(r"\b(como esta|qual) o tempo\b", t):
            return ToolCall(cid, "get_weather", {})
        if re.search(r"\b(que horas|hora|horas|que dia|data de hoje)\b", t):
            return ToolCall(cid, "get_local_time", {})
        if "processo" in t and "list_processes" in self.tools:
            return ToolCall(cid, "list_processes", {"top": 5, "sort_by": "ram" if "memoria" in t or "ram" in t else "cpu"})
        if re.search(r"\b(computador|sistema|cpu|processador|memoria|ram|disco|armazenamento|desempenho|pc)\b", t):
            return ToolCall(cid, "get_system_status", {})
        m = re.search(r"\bvolume\b.*?(\d{1,3})", t)
        if m and "set_volume" in self.tools:
            return ToolCall(cid, "set_volume", {"percent": max(0, min(100, int(m.group(1))))})
        if "volume" in t and "get_volume" in self.tools:
            return ToolCall(cid, "get_volume", {})
        if re.search(r"\b(abr[aei]r?|inici[ae]r?|execut[ae]r?)\b", t) and "open_app" in self.tools:
            for app in self.p.perms.apps.values():
                if norm(app.name) in t or app.id.replace("_", " ") in t:
                    return ToolCall(cid, "open_app", {"app_id": app.id})
        if re.search(r"\b(bom dia|boa tarde|boa noite|ola|oi)\b", t):
            return "greeting"
        return "help"

    async def send_user(self, text: str) -> AsyncIterator[ProviderEvent]:
        intent = self._intent(text)
        if isinstance(intent, ToolCall):
            yield intent
        elif intent == "greeting":
            self._greet = True
            yield ToolCall("local-" + uuid.uuid4().hex[:8], "get_local_time", {})
        else:
            yield f"Estou em modo local, sem inteligência artificial ({self.p.reason}). {HELP}"

    async def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]:
        o = outcomes[0]
        d = o.data
        if getattr(self, "_greet", False) and o.ok:
            self._greet = False
            hour = int(d["time"][:2])
            yield f"{greeting(hour)}, senhor. Estou em modo local, sem inteligência artificial ({self.p.reason}). {HELP}"
        elif not o.ok:
            yield f"Não foi possível: {o.summary}"
        elif o.call.name == "get_weather":
            yield say_weather(d)
        elif o.call.name == "get_local_time":
            yield f"São {d['time']} em {d['city']}, {d['date']}."
        elif o.call.name == "get_system_status":
            yield say_system(d)
        elif o.call.name == "list_processes":
            yield say_processes(d)
        else:
            yield o.summary
