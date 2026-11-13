"""Permissões locais: o que o assistente pode executar e quem pode falar com o backend.

A IA nunca recebe shell, caminho ou argumento livre. Ela só escolhe um *identificador*
de uma lista pré-aprovada neste arquivo de configuração (config/permissions.json).
"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ActionClass(str, Enum):
    READ = "read"          # só consulta — executa direto
    SAFE = "safe"          # ação reversível em item pré-aprovado — executa direto
    CONFIRM = "confirm"    # exige clique de confirmação no HUD
    FORBIDDEN = "forbidden"  # nunca executável pela IA


@dataclass(frozen=True)
class AppEntry:
    id: str
    name: str
    command: tuple[str, ...]
    confirm: bool = False
    #: trechos do título da janela que provam que o app abriu (ex.: "Calculadora")
    window: tuple[str, ...] = ()


@dataclass(frozen=True)
class FolderEntry:
    id: str
    name: str
    path: str


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    name: str
    path: str
    editor: str = "vscode"   # id de um app cadastrado em "apps"; o caminho é passado como argumento fixo


@dataclass(frozen=True)
class SceneEntry:
    """Cena de luz: só cores, brilho e liga/desliga — nada além do que os LEDs aceitam."""
    id: str
    name: str
    on: bool = True
    color: str | None = None
    brightness: int | None = None


@dataclass(frozen=True)
class RoutineEntry:
    id: str
    name: str
    steps: tuple[dict[str, Any], ...]
    confirm: bool = False


#: ferramentas que uma rotina pode encadear (nada além disso — nunca ações destrutivas)
PC_DEFAULTS = {"apps": True, "web": True, "settings": True, "files": True, "teclado": True, "screenshot": True,
               "brightness": True, "power": True, "computer_use": True}
ROUTINE_TOOLS = {"open_app", "open_folder", "open_project", "set_volume", "media_control", "window_control", "set_lights", "house_lights", "launch_app", "open_website"}

_SHELL_META = set("&|;<>`$\n\r")


def _safe_arg(arg: str) -> bool:
    return isinstance(arg, str) and arg != "" and not (_SHELL_META & set(arg))


@dataclass
class Permissions:
    apps: dict[str, AppEntry] = field(default_factory=dict)
    folders: dict[str, FolderEntry] = field(default_factory=dict)
    routines: dict[str, RoutineEntry] = field(default_factory=dict)
    projects: dict[str, ProjectEntry] = field(default_factory=dict)
    scenes: dict[str, SceneEntry] = field(default_factory=dict)
    volume_control: bool = True
    process_list: bool = True
    media_control: bool = True
    window_control: bool = True
    #: fechar janelas pode perder trabalho não salvo: sempre exige confirmação específica
    close_windows: bool = False
    #: 0.5 — controle amplo do computador (escolha do usuário: amplo com confirmação). false desliga cada parte.
    pc: dict[str, bool] = field(default_factory=lambda: dict(PC_DEFAULTS))
    source: str = "padrão (vazio)"

    @classmethod
    def load(cls, path: Path) -> "Permissions":
        if not path.exists():
            return cls(source=f"{path.name} ausente — nenhum app/pasta autorizado")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))   # aceita BOM (Bloco de Notas antigo, PowerShell 5.1)
        perms = cls(source=str(path.name))
        for item in raw.get("apps", []):
            cmd = tuple(str(c) for c in item.get("command", []))
            if not cmd or not all(_safe_arg(c) for c in cmd):
                continue  # entrada inválida é ignorada, nunca "consertada"
            perms.apps[item["id"]] = AppEntry(item["id"], item.get("name", item["id"]), cmd, bool(item.get("confirm", False)),
                                               tuple(str(w) for w in item.get("window", []) if str(w).strip()))
        for item in raw.get("folders", []):
            p = os.path.expandvars(os.path.expanduser(str(item.get("path", ""))))
            if p:
                perms.folders[item["id"]] = FolderEntry(item["id"], item.get("name", item["id"]), p)
        for item in raw.get("projects", []):
            path = os.path.expandvars(os.path.expanduser(str(item.get("path", ""))))
            editor = str(item.get("editor", "vscode"))
            if path and item.get("id"):
                perms.projects[item["id"]] = ProjectEntry(item["id"], item.get("name", item["id"]), path, editor)
        for item in raw.get("scenes", []):
            color = item.get("color")
            if color is not None and not (isinstance(color, str) and len(color) == 7 and color.startswith("#")):
                continue
            bright = item.get("brightness")
            if bright is not None and not (isinstance(bright, int) and 0 <= bright <= 100):
                continue
            if item.get("id"):
                perms.scenes[item["id"]] = SceneEntry(item["id"], item.get("name", item["id"]), bool(item.get("on", True)), color, bright)
        for item in raw.get("routines", []):
            steps = tuple(s for s in item.get("steps", []) if s.get("tool") in ROUTINE_TOOLS)
            if steps and len(steps) == len(item.get("steps", [])):
                perms.routines[item["id"]] = RoutineEntry(item["id"], item.get("name", item["id"]), steps, bool(item.get("confirm", False)))
        perms.volume_control = bool(raw.get("volume_control", True))
        perms.process_list = bool(raw.get("process_list", True))
        perms.media_control = bool(raw.get("media_control", True))
        perms.window_control = bool(raw.get("window_control", True))
        perms.close_windows = bool(raw.get("close_windows", False))
        pc = raw.get("pc_control") if isinstance(raw.get("pc_control"), dict) else {}
        perms.pc = {k: bool(pc.get(k, v)) for k, v in PC_DEFAULTS.items()}
        return perms

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "apps": [{"id": a.id, "name": a.name, "confirm": a.confirm} for a in self.apps.values()],
            "folders": [{"id": f.id, "name": f.name} for f in self.folders.values()],
            "routines": [{"id": r.id, "name": r.name, "steps": len(r.steps), "confirm": r.confirm} for r in self.routines.values()],
            "projects": [{"id": p.id, "name": p.name} for p in self.projects.values()],
            "scenes": [{"id": c.id, "name": c.name} for c in self.scenes.values()],
            "media_control": self.media_control, "window_control": self.window_control, "close_windows": self.close_windows,
            "pc_control": dict(self.pc),
            "volume_control": self.volume_control,
            "process_list": self.process_list,
        }


class LocalAuth:
    """Autenticação do canal HUD ⇄ backend.

    Ameaça real de um serviço em localhost: páginas web abertas no navegador tentando
    falar com 127.0.0.1 (CSRF / DNS rebinding). Por isso validamos Host, Origin e um
    token de sessão entregue só a origens permitidas.
    """

    def __init__(self, token: str, origins: tuple[str, ...], port: int):
        self._token = token
        self.origins = set(origins)
        self.hosts = {o.split("://", 1)[1] for o in origins} | {f"127.0.0.1:{port}", f"localhost:{port}"}

    @property
    def token(self) -> str:
        return self._token

    def host_ok(self, host: str | None) -> bool:
        return bool(host) and host.lower() in self.hosts

    def origin_ok(self, origin: str | None, *, required: bool) -> bool:
        if origin is None or origin == "":
            return not required
        return origin in self.origins

    def token_ok(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate, self._token)
