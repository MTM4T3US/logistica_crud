"""Modo local (sem IA): mantém o JARVIS útil quando não há chave, internet ou cota.

NÃO é inteligência artificial e não finge ser: usa o roteador local (comandos conhecidos)
para chamar as mesmas ferramentas reais e responde com frases fixas. O HUD identifica o modo.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from ..router import LocalRouter, Plan
from .base import AIProvider, ChatSession, ProviderEvent, ToolOutcome

HELP = ("Comandos locais seguem funcionando: luzes, volume, música, janelas, abrir programas e projetos, "
        "rotinas, hora, clima e estado do computador.")


class LocalProvider(AIProvider):
    name = "local"
    model = "comandos locais (sem IA)"
    cloud = False

    def __init__(self, router: LocalRouter, reason: str = "IA não configurada", title: str = "senhor"):
        self.router = router
        self.reason = reason
        self.title = title

    def start(self, *, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatSession:
        return LocalSession(self)


class LocalSession(ChatSession):
    def __init__(self, provider: LocalProvider):
        self.p = provider
        self.plan: Plan | None = None

    async def send_user(self, text: str) -> AsyncIterator[ProviderEvent]:
        self.plan = self.p.router.match(text, allow_chat=True)
        if self.plan is None:
            yield f"Estou sem acesso à inteligência artificial agora ({self.p.reason}), então não consigo conversar sobre isso. {HELP}"
            return
        if self.plan.kind == "stop" or not self.plan.calls:
            return
        for call in self.plan.calls:
            yield call

    async def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]:
        if self.plan is not None:
            yield self.plan.render(outcomes, self.p.title)
