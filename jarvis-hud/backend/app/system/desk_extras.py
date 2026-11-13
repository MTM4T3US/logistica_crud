"""Extras do computador (0.7): ler o texto selecionado e reconhecer jogos.

- `read_selection`: copia a seleção da janela em foco (Ctrl+C), lê a área de transferência e devolve o texto
  ANTERIOR dela no fim. Recusa terminais (Ctrl+C lá interrompe programas) e janelas de senhas/segredos.
- `is_game`: jogo = executável dentro das pastas de jogos conhecidas (Steam, Epic, Riot, Xbox, EA, Ubisoft,
  GOG, Battle.net, Rockstar) ou na lista do usuário (permissions.json → "jogos").
"""
from __future__ import annotations

import ctypes
import re
import time
from typing import Callable

from .screen_input import ScreenInput, is_sensitive, is_terminal

GAME_DIRS = ("steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\", "\\windowsapps\\microsoft.minecraft",
             "\\ea games\\", "\\electronic arts\\", "\\ubisoft game launcher\\games\\", "\\gog galaxy\\games\\", "\\battle.net\\",
             "\\rockstar games\\", "\\roblox\\versions\\", "\\riot client\\")
NOT_GAMES = ("steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "riotclientservices.exe", "riotclientux.exe",
             "battle.net.exe", "galaxyclient.exe", "eadesktop.exe", "upc.exe", "robloxplayerlauncher.exe")
MAX_READ = 1500


def is_game(exe_path: str, extra: tuple[str, ...] = ()) -> bool:
    p = (exe_path or "").replace("/", "\\").lower()
    if not p:
        return False
    name = p.rsplit("\\", 1)[-1]
    if name in NOT_GAMES:
        return False
    if any(e.lower() in (name, name.removesuffix(".exe")) for e in extra if e):
        return True
    return any(d in p for d in GAME_DIRS)


class Clipboard:
    """Interface: o real usa a API do Windows; os testes usam um dublê."""

    def get(self) -> str: ...
    def set(self, text: str) -> None: ...


class WinClipboard(Clipboard):  # pragma: no cover — só roda no Windows
    CF_UNICODETEXT = 13

    def __init__(self) -> None:
        self.u, self.k = ctypes.windll.user32, ctypes.windll.kernel32
        self.k.GlobalLock.restype = ctypes.c_void_p
        self.k.GlobalAlloc.restype = ctypes.c_void_p
        self.u.GetClipboardData.restype = ctypes.c_void_p

    def _open(self) -> bool:
        for _ in range(10):
            if self.u.OpenClipboard(None):
                return True
            time.sleep(0.03)
        return False

    def get(self) -> str:
        if not self._open():
            return ""
        try:
            h = self.u.GetClipboardData(self.CF_UNICODETEXT)
            if not h:
                return ""
            p = self.k.GlobalLock(ctypes.c_void_p(h))
            try:
                return ctypes.wstring_at(p) if p else ""
            finally:
                self.k.GlobalUnlock(ctypes.c_void_p(h))
        finally:
            self.u.CloseClipboard()

    def set(self, text: str) -> None:
        if not self._open():
            return
        try:
            self.u.EmptyClipboard()
            data = (text or "").encode("utf-16-le") + b"\x00\x00"
            h = self.k.GlobalAlloc(0x0042, len(data))
            p = self.k.GlobalLock(ctypes.c_void_p(h))
            ctypes.memmove(p, data, len(data))
            self.k.GlobalUnlock(ctypes.c_void_p(h))
            self.u.SetClipboardData(self.CF_UNICODETEXT, ctypes.c_void_p(h))
        finally:
            self.u.CloseClipboard()


def get_clipboard() -> Clipboard | None:
    try:
        return WinClipboard()
    except (AttributeError, OSError):
        return None


def read_selection(si: ScreenInput, clip: Clipboard, wait: Callable[[float], None] = time.sleep) -> tuple[bool, str]:
    """(ok, texto ou motivo). O que estava na área de transferência volta ao fim."""
    title, exe = si.foreground()
    if is_terminal(title, exe):
        return False, f"Não leio em terminais (“{title or exe}”): lá o Ctrl+C interrompe programas."
    if is_sensitive(title, exe):
        return False, f"Não leio essa janela (“{title or exe}”): parece ter senhas ou chaves."
    before = clip.get()
    marker = f"⁣jarvis-{time.time_ns()}"
    clip.set(marker)
    si.combo("ctrl+c")
    text = ""
    for _ in range(8):
        wait(0.06)
        text = clip.get()
        if text and text != marker:
            break
    clip.set(before)
    if not text or text == marker:
        return False, "Nada selecionado: selecione o texto e peça de novo."
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_READ:
        text = text[:MAX_READ].rsplit(" ", 1)[0] + "… (o resto ficou de fora)"
    return True, text
