"""Ações no computador: abrir apps/pastas pré-aprovados e controlar o volume.

Regras: nenhum shell, nenhum argumento vindo da IA. `command` é a lista fixa cadastrada em
config/permissions.json. Fora do Windows, as ações respondem honestamente que não estão
disponíveis — nada é fingido.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from ..security.permissions import AppEntry, FolderEntry


@dataclass
class ActionResult:
    ok: bool
    executed: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class SystemController:
    """Interface. Troque a implementação sem tocar no resto da aplicação."""

    platform = "desconhecido"

    def capabilities(self) -> dict[str, bool]:
        return {"open_app": False, "open_folder": False, "volume": False}

    def open_app(self, app: AppEntry) -> ActionResult:
        return ActionResult(False, False, f"Abrir aplicativos só está disponível no Windows (sistema atual: {self.platform}).")

    def open_folder(self, folder: FolderEntry) -> ActionResult:
        return ActionResult(False, False, f"Abrir pastas só está disponível no Windows (sistema atual: {self.platform}).")

    def get_volume(self) -> ActionResult:
        return ActionResult(False, False, f"Controle de volume só está disponível no Windows (sistema atual: {self.platform}).")

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> ActionResult:
        return self.get_volume()


class UnsupportedController(SystemController):
    def __init__(self) -> None:
        self.platform = sys.platform


class WindowsController(SystemController):
    platform = "windows"

    def __init__(
        self,
        spawn: Callable[[list[str]], Any] | None = None,
        startfile: Callable[[str], Any] | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._spawn = spawn or self._default_spawn
        self._startfile = startfile or getattr(os, "startfile", None)
        self._which = which

    @staticmethod
    def _default_spawn(argv: list[str]) -> Any:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(argv, shell=False, close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def capabilities(self) -> dict[str, bool]:
        return {"open_app": True, "open_folder": self._startfile is not None, "volume": self._endpoint() is not None}

    def open_app(self, app: AppEntry) -> ActionResult:
        argv = list(app.command)
        resolved = self._which(argv[0])
        try:
            if resolved:
                self._spawn([resolved, *argv[1:]])
            elif len(argv) == 1 and self._startfile is not None:
                # aplicativos registrados em "App Paths"/aliases (ex.: msedge.exe, wt.exe)
                self._startfile(argv[0])
            else:
                return ActionResult(False, False, f"{app.name}: executável '{argv[0]}' não encontrado neste computador.")
        except OSError as exc:
            return ActionResult(False, False, f"{app.name}: o Windows recusou a abertura ({exc.strerror or exc}).")
        return ActionResult(True, True, f"{app.name} aberto.", {"app_id": app.id})

    def open_folder(self, folder: FolderEntry) -> ActionResult:
        if not os.path.isdir(folder.path):
            return ActionResult(False, False, f"A pasta {folder.name} não existe em {folder.path}.")
        if self._startfile is None:
            return ActionResult(False, False, "Abrir pastas não está disponível neste sistema.")
        try:
            self._startfile(folder.path)
        except OSError as exc:
            return ActionResult(False, False, f"{folder.name}: o Windows recusou a abertura ({exc.strerror or exc}).")
        return ActionResult(True, True, f"Pasta {folder.name} aberta.", {"folder_id": folder.id})

    # ---- volume (pycaw / Core Audio) ----
    @staticmethod
    def _endpoint() -> Any | None:
        try:
            import comtypes  # type: ignore
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

            comtypes.CoInitialize()
            speakers = AudioUtilities.GetSpeakers()
            if hasattr(speakers, "EndpointVolume"):  # pycaw recente
                return speakers.EndpointVolume
            iface = speakers.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
            return iface.QueryInterface(IAudioEndpointVolume)
        except Exception:
            return None

    def get_volume(self) -> ActionResult:
        ep = self._endpoint()
        if ep is None:
            return ActionResult(False, False, "Controle de volume indisponível (pycaw não instalado ou sem dispositivo de saída).")
        level = round(float(ep.GetMasterVolumeLevelScalar()) * 100)
        muted = bool(ep.GetMute())
        return ActionResult(True, True, f"Volume em {level}%{' (mudo)' if muted else ''}.", {"percent": level, "muted": muted})

    def set_volume(self, percent: int | None = None, mute: bool | None = None) -> ActionResult:
        ep = self._endpoint()
        if ep is None:
            return ActionResult(False, False, "Controle de volume indisponível (pycaw não instalado ou sem dispositivo de saída).")
        if percent is not None:
            ep.SetMasterVolumeLevelScalar(max(0, min(100, int(percent))) / 100.0, None)
        if mute is not None:
            ep.SetMute(1 if mute else 0, None)
        return self.get_volume()


def get_controller() -> SystemController:
    return WindowsController() if sys.platform == "win32" else UnsupportedController()
