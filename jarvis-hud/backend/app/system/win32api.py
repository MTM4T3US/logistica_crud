"""Acesso mínimo à API do Windows (user32) via ctypes, sem dependências externas.

Só é carregado no Windows. A lógica que decide O QUE fazer fica em windows.py e é testada com
um dublê desta classe; aqui fica apenas a tradução para chamadas do sistema.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

# teclas virtuais (https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes)
VK = {
    "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
    "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "lwin": 0x5B, "d": 0x44, "menu": 0x12,
}
SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9
WM_CLOSE = 0x0010
KEYEVENTF_KEYUP = 0x0002
GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x00000080
MONITOR_DEFAULTTONEAREST = 2


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    minimized: bool = False


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class Win32Api:
    """Interface usada por WindowsController. Os métodos não decidem nada: só executam."""

    def list_windows(self) -> list[Window]: ...
    def show(self, hwnd: int, cmd: int) -> bool: ...
    def focus(self, hwnd: int) -> bool: ...
    def move(self, hwnd: int, rect: Rect) -> bool: ...
    def work_area(self, hwnd: int) -> Rect: ...
    def post_close(self, hwnd: int) -> bool: ...
    def press(self, *keys: int) -> None: ...


class RealWin32Api(Win32Api):  # pragma: no cover — só roda no Windows
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("API do Windows indisponível neste sistema")
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.u.GetWindowLongW.restype = ctypes.c_long

    def list_windows(self) -> list[Window]:
        out: list[Window] = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd, _):
            if not self.u.IsWindowVisible(hwnd):
                return True
            if self.u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            n = self.u.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            self.u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if title and title not in ("Program Manager", "Configurações", "Settings"):
                out.append(Window(int(hwnd), title, bool(self.u.IsIconic(hwnd))))
            return True

        self.u.EnumWindows(proto(each), 0)
        return out

    def show(self, hwnd: int, cmd: int) -> bool:
        self.u.ShowWindow(hwnd, cmd)
        return True

    def focus(self, hwnd: int) -> bool:
        if self.u.IsIconic(hwnd):
            self.u.ShowWindow(hwnd, SW_RESTORE)
        # o Windows só deixa trocar o foco se o processo "recebeu" uma tecla: ALT solto resolve
        self.press(VK["menu"])
        return bool(self.u.SetForegroundWindow(hwnd))

    def move(self, hwnd: int, rect: Rect) -> bool:
        self.u.ShowWindow(hwnd, SW_RESTORE)
        return bool(self.u.MoveWindow(hwnd, rect.left, rect.top, rect.width, rect.height, True))

    def work_area(self, hwnd: int) -> Rect:
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        mon = self.u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        self.u.GetMonitorInfoW(mon, ctypes.byref(info))
        r = info.rcWork
        return Rect(r.left, r.top, r.right, r.bottom)

    def post_close(self, hwnd: int) -> bool:
        return bool(self.u.PostMessageW(hwnd, WM_CLOSE, 0, 0))

    def press(self, *keys: int) -> None:
        for k in keys:
            self.u.keybd_event(k, 0, 0, 0)
        for k in reversed(keys):
            self.u.keybd_event(k, 0, KEYEVENTF_KEYUP, 0)
