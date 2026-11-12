"""Dublês de teste. Nenhum teste chama a API Gemini nem precisa de chave ou de rede."""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.base import AIProvider, ChatSession, ProviderEvent, ToolCall, ToolOutcome  # noqa: E402
from app.config import Settings  # noqa: E402
from app.security.permissions import AppEntry, FolderEntry, Permissions, RoutineEntry  # noqa: E402
from app.system.windows import ActionResult, SystemController  # noqa: E402
from app.voice.audio_stream import pcm16_to_wav  # noqa: E402
from app.voice.stt import STTEngine, STTError, STTResult  # noqa: E402
from app.voice.tts import TTSEngine, TTSError, TTSResult  # noqa: E402


def tone_wav(seconds: float = 0.6, rate: int = 16000, amp: float = 0.3, freq: float = 220.0) -> bytes:
    n = int(seconds * rate)
    pcm = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))
    return pcm16_to_wav(pcm, rate)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "jarvis.sqlite3", permissions_path=tmp_path / "permissions.json", weather_enabled=False)


@pytest.fixture
def perms() -> Permissions:
    p = Permissions(source="teste")
    p.apps = {"notas": AppEntry("notas", "Bloco de Notas", ("notepad.exe",)), "editor": AppEntry("editor", "Editor", ("code",), confirm=True)}
    p.folders = {"docs": FolderEntry("docs", "Documentos", "/tmp")}
    p.routines = {"programar": RoutineEntry("programar", "Programar", ({"tool": "open_app", "args": {"app_id": "notas"}}, {"tool": "open_folder", "args": {"folder_id": "docs"}}), confirm=True)}
    return p


class FakeController(SystemController):
    platform = "teste"

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.volume = 40

    def capabilities(self) -> dict[str, bool]:
        return {"open_app": True, "open_folder": True, "volume": True}

    def open_app(self, app: AppEntry) -> ActionResult:
        self.opened.append(app.id)
        return ActionResult(True, True, f"{app.name} aberto.", {"app_id": app.id})

    def open_folder(self, folder: FolderEntry) -> ActionResult:
        self.opened.append(folder.id)
        return ActionResult(True, True, f"Pasta {folder.name} aberta.", {"folder_id": folder.id})

    def get_volume(self) -> ActionResult:
        return ActionResult(True, True, f"Volume em {self.volume}%.", {"percent": self.volume, "muted": False})

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> ActionResult:
        if percent is not None:
            self.volume = percent
        return self.get_volume()


class ScriptedSession(ChatSession):
    def __init__(self, provider: "ScriptedProvider"):
        self.p = provider

    async def _play(self) -> AsyncIterator[ProviderEvent]:
        step = self.p.script.pop(0) if self.p.script else []
        if isinstance(step, Exception):
            raise step
        for ev in step:
            if isinstance(ev, Exception):
                raise ev
            if callable(ev):
                await ev()
                continue
            yield ev

    def send_user(self, text: str) -> AsyncIterator[ProviderEvent]:
        self.p.seen_user.append(text)
        return self._play()

    def send_tool_results(self, outcomes: list[ToolOutcome]) -> AsyncIterator[ProviderEvent]:
        self.p.seen_results.append(outcomes)
        return self._play()


class ScriptedProvider(AIProvider):
    """Provedor roteirizado: cada item de `script` é uma rodada (lista de str/ToolCall/exceções)."""

    name, model, cloud = "gemini", "gemini-teste", True

    def __init__(self, script: list[Any]):
        self.script = script
        self.seen_user: list[str] = []
        self.seen_results: list[list[ToolOutcome]] = []
        self.started: list[dict[str, Any]] = []
        self.tts_model = "tts-teste"
        self.settings = None

    async def resolve_models(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "cloud": True, "note": "", "last_error": None, "fallback_model": None, "tts_model": self.tts_model}

    def start(self, *, system: str, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatSession:
        self.started.append({"system": system, "history": history, "tools": tools})
        return ScriptedSession(self)


class FakeTTS(TTSEngine):
    def __init__(self, engine_id: str = "local", cloud: bool = False, fail: bool = False):
        self.id, self.label, self.cloud, self.fail = engine_id, f"teste-{engine_id}", cloud, fail
        self.spoken: list[tuple[str, str | None]] = []

    def available(self) -> tuple[bool, str]:
        return True, ""

    def voices(self) -> list[dict[str, str]]:
        return [{"id": "v1", "label": "Voz 1"}]

    async def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        if self.fail:
            raise TTSError("rate_limit", "O Gemini TTS atingiu o limite.")
        self.spoken.append((text, voice))
        return TTSResult(tone_wav(0.2), 0.2, self.id, voice or "v1", self.cloud)


class FakeSTT(STTEngine):
    def __init__(self, text: str = "", engine_id: str = "whisper", cloud: bool = False, error: STTError | None = None):
        self.id, self.label, self.cloud, self.text, self.error = engine_id, f"teste-{engine_id}", cloud, text, error
        self.calls = 0

    def available(self) -> tuple[bool, str]:
        return True, ""

    async def transcribe(self, wav: bytes, language: str = "pt-BR") -> STTResult:
        self.calls += 1
        if self.error:
            raise self.error
        return STTResult(self.text, self.id, self.cloud)


class FakeConn:
    """Substitui a conexão WebSocket: guarda os eventos enviados ao HUD."""

    def __init__(self, approve: bool = True):
        self.events: list[dict[str, Any]] = []
        self.approve = approve
        self.confirm_texts: list[str] = []
        self.closed = False

    async def send(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def confirm(self, text: str) -> bool:
        self.confirm_texts.append(text)
        return self.approve

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]

    def kinds(self) -> list[str]:
        return [e["type"] for e in self.events]


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(id=f"c-{name}", name=name, args=args)
