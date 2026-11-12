"""Ações no computador: abrir apps/pastas pré-aprovados e controlar o volume.

Regras: nenhum shell, nenhum argumento vindo da IA. `command` é a lista fixa cadastrada em
config/permissions.json. Fora do Windows, as ações respondem honestamente que não estão
disponíveis — nada é fingido.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import re
import unicodedata

from ..security.permissions import AppEntry, FolderEntry, ProjectEntry
from .win32api import SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE, VK, Rect, Win32Api, Window


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

    def step_volume(self, delta: int) -> ActionResult:
        return self.get_volume()

    def media(self, action: str) -> ActionResult:
        return ActionResult(False, False, f"Controle de mídia só está disponível no Windows (sistema atual: {self.platform}).")

    def windows(self, action: str, query: str = "", other: str = "") -> ActionResult:
        return ActionResult(False, False, f"Organizar janelas só está disponível no Windows (sistema atual: {self.platform}).")

    def open_project(self, project: ProjectEntry, editor: AppEntry | None) -> ActionResult:
        return ActionResult(False, False, f"Abrir projetos só está disponível no Windows (sistema atual: {self.platform}).")


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
        win: Win32Api | None = None,
        volume_endpoint: Callable[[], Any] | None = None,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        verify_s: float = 6.0,
    ) -> None:
        self._spawn = spawn or self._default_spawn
        self._sleep, self._clock, self.verify_s = sleep, clock, verify_s
        self._startfile = startfile or getattr(os, "startfile", None)
        self._which = which
        self._win = win
        self._endpoint_factory = volume_endpoint

    @property
    def win(self) -> Win32Api | None:
        if self._win is None:
            try:
                from .win32api import RealWin32Api

                self._win = RealWin32Api()
            except OSError:
                return None
        return self._win

    @staticmethod
    def _default_spawn(argv: list[str]) -> Any:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(argv, shell=False, close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def capabilities(self) -> dict[str, bool]:
        return {"open_app": True, "open_folder": self._startfile is not None, "volume": self._endpoint() is not None,
                "media": self.win is not None, "windows": self.win is not None, "open_project": True}

    def open_app(self, app: AppEntry) -> ActionResult:
        argv = list(app.command)
        resolved = self._which(argv[0])
        win = self.win
        before = {w.hwnd for w in win.list_windows()} if win is not None else set()
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
        return self._verify_window(app, before)

    def _app_needles(self, app: AppEntry) -> list[str]:
        names = [*app.window, app.name, app.id.replace("_", " ")]
        names += self.ALIASES.get(self._fold(app.id.replace("_", " ")), [])
        return [n for n in dict.fromkeys(self._fold(x).strip() for x in names) if len(n) >= 3]

    def _verify_window(self, app: AppEntry, before: set[int]) -> ActionResult:
        """Só diz "aberto" quando uma janela do app aparece. Iniciar o processo não basta:
        a Calculadora, por exemplo, é um app da Loja e o processo lançado termina na hora."""
        data: dict[str, Any] = {"app_id": app.id}
        win = self.win
        if win is None:
            return ActionResult(True, True, f"{app.name}: comando de abertura enviado; não consegui verificar a janela.", {**data, "verified": False})
        needles = self._app_needles(app)
        deadline = self._clock() + self.verify_s
        existing: Window | None = None
        while True:
            matches = [w for w in win.list_windows() if any(n in self._fold(w.title) for n in needles)]
            new = [w for w in matches if w.hwnd not in before]
            if new:
                return ActionResult(True, True, f"{app.name} aberto — janela “{new[0].title}” apareceu.", {**data, "verified": True, "window": new[0].title})
            existing = existing or (matches[0] if matches else None)
            if self._clock() >= deadline:
                break
            self._sleep(0.25)
        if existing is not None:
            return ActionResult(True, True, f"{app.name}: já havia uma janela aberta (“{existing.title}”); nenhuma janela nova apareceu.",
                                {**data, "verified": True, "window": existing.title, "new_window": False})
        return ActionResult(True, True, f"{app.name}: o programa foi iniciado, mas nenhuma janela apareceu em {self.verify_s:g} s — não posso confirmar que abriu.",
                            {**data, "verified": False})

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

    def open_project(self, project: ProjectEntry, editor: AppEntry | None) -> ActionResult:
        if not os.path.isdir(project.path):
            return ActionResult(False, False, f"A pasta do projeto {project.name} não existe em {project.path}.")
        if editor is None:
            if self._startfile is None:
                return ActionResult(False, False, "Nenhum editor cadastrado para abrir o projeto.")
            self._startfile(project.path)
            return ActionResult(True, True, f"Pasta do projeto {project.name} aberta.", {"project_id": project.id})
        argv = list(editor.command)
        exe = self._which(argv[0])
        if not exe:
            return ActionResult(False, False, f"{editor.name}: executável '{argv[0]}' não encontrado neste computador.")
        try:
            # o caminho vem do cadastro (permissions.json), nunca do texto da IA
            self._spawn([exe, *argv[1:], project.path])
        except OSError as exc:
            return ActionResult(False, False, f"{editor.name}: o Windows recusou a abertura ({exc.strerror or exc}).")
        return ActionResult(True, True, f"Projeto {project.name} aberto no {editor.name}.", {"project_id": project.id})

    # ---- mídia (teclas multimídia do Windows) ----
    MEDIA_KEYS = {"play_pause": "play_pause", "pause": "play_pause", "play": "play_pause", "next": "next", "previous": "previous", "stop": "stop", "mute": "mute"}

    def media(self, action: str) -> ActionResult:
        key = self.MEDIA_KEYS.get(action)
        if key is None:
            return ActionResult(False, False, f"Ação de mídia desconhecida: {action}.")
        if self.win is None:
            return ActionResult(False, False, "Controle de mídia indisponível neste sistema.")
        self.win.press(VK[key])
        names = {"play_pause": "Tocar/pausar", "next": "Próxima faixa", "previous": "Faixa anterior", "stop": "Parar", "mute": "Mudo"}
        # a tecla é enviada; o Windows não informa se algum player reagiu
        return ActionResult(True, True, f"{names[key]}: tecla multimídia enviada ao Windows.", {"action": key, "confirmed": False})

    # ---- janelas ----
    @staticmethod
    def _fold(text: str) -> str:
        text = unicodedata.normalize("NFD", text.lower())
        # Mn: acentos · Cf: caracteres invisíveis (o Edge escreve "Microsoft\u200b Edge" no título)
        return "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Cf"))

    ALIASES = {
        "vscode": ["visual studio code"], "codigo": ["visual studio code"], "vs code": ["visual studio code"],
        "navegador": ["microsoft edge", "google chrome", "mozilla firefox", "opera", "brave"], "chrome": ["google chrome"],
        "edge": ["microsoft edge"], "terminal": ["terminal", "powershell", "prompt de comando", "command prompt"],
        "explorador": ["explorador de arquivos", "file explorer", "acesso rapido", "este computador", "quick access", "this pc"], "spotify": ["spotify"], "jarvis": ["jarvis os"],
        "calculadora": ["calculadora", "calculator"], "bloco de notas": ["bloco de notas", "notepad"], "notas": ["bloco de notas", "notepad"],
        "discord": ["discord"],
    }

    def find_windows(self, query: str) -> list[Window]:
        if self.win is None:
            return []
        q = self._fold(query).strip()
        wins = self.win.list_windows()
        if not q:
            return wins
        needles = [q] + [self._fold(a) for a in self.ALIASES.get(q, [])]
        return [w for w in wins if any(n in self._fold(w.title) for n in needles)]

    def windows(self, action: str, query: str = "", other: str = "") -> ActionResult:
        win = self.win
        if win is None:
            return ActionResult(False, False, "Controle de janelas indisponível neste sistema.")
        if action == "list":
            wins = win.list_windows()
            return ActionResult(True, True, f"{len(wins)} janelas abertas.", {"windows": [{"title": w.title, "minimized": w.minimized} for w in wins[:20]]})
        if action == "minimize_all":
            win.press(VK["lwin"], VK["d"])
            return ActionResult(True, True, "Atalho Win+D enviado (mostrar a área de trabalho).", {"confirmed": False})
        if action == "arrange":
            first = self.find_windows(query) if query else win.list_windows()[:1]
            second = self.find_windows(other) if other else [w for w in win.list_windows() if not first or w.hwnd != first[0].hwnd][:1]
            if not first or not second:
                return ActionResult(False, False, "Não encontrei duas janelas para organizar lado a lado.")
            a, b = first[0], second[0]
            area = win.work_area(a.hwnd)
            half = area.width // 2
            ok = win.move(a.hwnd, Rect(area.left, area.top, area.left + half, area.bottom)) and win.move(b.hwnd, Rect(area.left + half, area.top, area.right, area.bottom))
            if not ok:
                return ActionResult(False, False, "O Windows recusou mover as janelas.")
            return ActionResult(True, True, f"Lado a lado: “{a.title}” à esquerda e “{b.title}” à direita.", {"left": a.title, "right": b.title})
        found = self.find_windows(query)
        if not found:
            return ActionResult(False, False, f"Não encontrei nenhuma janela com “{query}”.")
        if len(found) > 1 and action == "close":
            return ActionResult(False, False, f"Mais de uma janela corresponde a “{query}”; seja mais específico.", {"candidates": [w.title for w in found[:5]]})
        w = found[0]
        if action == "focus":
            ok = win.focus(w.hwnd)
            return ActionResult(ok, ok, f"“{w.title}” em primeiro plano." if ok else f"O Windows não permitiu trazer “{w.title}” para a frente.")
        if action in ("minimize", "maximize", "restore"):
            win.show(w.hwnd, {"minimize": SW_MINIMIZE, "maximize": SW_MAXIMIZE, "restore": SW_RESTORE}[action])
            verb = {"minimize": "minimizada", "maximize": "maximizada", "restore": "restaurada"}[action]
            return ActionResult(True, True, f"Janela “{w.title}” {verb}.")
        if action in ("snap_left", "snap_right"):
            area = win.work_area(w.hwnd)
            half = area.width // 2
            rect = Rect(area.left, area.top, area.left + half, area.bottom) if action == "snap_left" else Rect(area.left + half, area.top, area.right, area.bottom)
            ok = win.move(w.hwnd, rect)
            side = "esquerda" if action == "snap_left" else "direita"
            return ActionResult(ok, ok, f"“{w.title}” na metade {side} da tela." if ok else "O Windows recusou mover a janela.")
        if action == "close":
            ok = win.post_close(w.hwnd)
            # WM_CLOSE pede para o programa fechar; ele pode perguntar se deve salvar
            return ActionResult(ok, ok, f"Pedido de fechamento enviado a “{w.title}”." if ok else f"Não consegui fechar “{w.title}”.")
        return ActionResult(False, False, f"Ação de janela desconhecida: {action}.")

    # ---- volume (pycaw / Core Audio) ----
    def step_volume(self, delta: int) -> ActionResult:
        cur = self.get_volume()
        if cur.ok:
            return self.set_volume(max(0, min(100, int(cur.data["percent"]) + int(delta))))
        if self.win is None:
            return cur
        key = VK["volume_up"] if delta > 0 else VK["volume_down"]
        for _ in range(max(1, min(25, abs(int(delta)) // 2))):   # cada tecla muda ~2%
            self.win.press(key)
        return ActionResult(True, True, f"Volume {'aumentado' if delta > 0 else 'diminuído'} pelas teclas multimídia.", {"confirmed": False})

    def _endpoint(self) -> Any | None:
        if self._endpoint_factory is not None:
            return self._endpoint_factory()
        return self._pycaw_endpoint()

    @staticmethod
    def _pycaw_endpoint() -> Any | None:
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
