"""Contratos da camada de IA. Qualquer provedor (Gemini, local, outro) implementa isto."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Union


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolOutcome:
    call: ToolCall
    ok: bool
    executed: bool
    summary: str
    simulated: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def for_model(self) -> dict[str, Any]:
        """O que a IA recebe de volta. `executed` é a única prova de que algo aconteceu."""
        return {"ok": self.ok, "executed": self.executed, "simulated": self.simulated, "message": self.summary, **self.data}


class AIError(Exception):
    """Falha da IA já traduzida para o usuário. `code` é estável; `message` é em pt-BR."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, detail: str = ""):
        super().__init__(message)
        self.code, self.message, self.retryable, self.detail = code, message, retryable, detail


#: um provedor emite pedaços de texto (str) e pedidos de ferramenta (ToolCall)
ProviderEvent = Union[str, ToolCall]


class ChatSession(ABC):
    @abstractmethod
    def send_user(self, text: str) -> AsyncIterator[ProviderEvent]: ...

    @abstractmethod
    def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]: ...


class AIProvider(ABC):
    name: str = "base"
    model: str = ""
    cloud: bool = False

    @abstractmethod
    def start(self, *, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatSession: ...

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "cloud": self.cloud}
