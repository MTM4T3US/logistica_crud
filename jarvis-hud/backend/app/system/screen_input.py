"""Tela, mouse e teclado do Windows (ctypes, sem dependências obrigatórias).

Usado pelos comandos diretos (captura de tela, digitar, atalhos) e pelo modo "computer use".
Regras que valem para tudo que passa por aqui:
- nada é digitado nem enviado como atalho quando a janela em foco é um terminal, o "Executar" ou o
  Editor do Registro (o texto viraria comando);
- só atalhos de uma lista fechada;
- a captura fica na memória; só é gravada em disco quando o usuário pede uma captura de tela.
"""
from __future__ import annotations

import ctypes
import struct
import sys
import time
import zlib
from dataclasses import dataclass
from typing import Any

#: janelas onde texto digitado vira comando — o JARVIS nunca digita nelas
TERMINAL_EXES = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe", "openconsole.exe",
                 "regedit.exe", "mmc.exe", "wsl.exe", "bash.exe", "mintty.exe", "putty.exe", "python.exe", "pythonw.exe"}
TERMINAL_TITLES = ("prompt de comando", "command prompt", "powershell", "windows terminal", "terminal", "executar", "run",
                   "editor do registro", "registry editor", "git bash", "ubuntu", "wsl")

# teclas virtuais
VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "windows": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "espaco": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "printscreen": 0x2C,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    **{chr(c): c for c in range(ord("a"), ord("z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
}
#: atalhos permitidos (normalizados, em ordem: modificadores + tecla)
ALLOWED_COMBOS = {
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+f", "ctrl+t", "ctrl+n", "ctrl+w", "ctrl+tab",
    "ctrl+shift+tab", "ctrl+l", "ctrl+p", "ctrl+plus", "ctrl+minus", "ctrl+0", "ctrl+home", "ctrl+end", "ctrl+shift+t",
    "alt+tab", "alt+left", "alt+right", "alt+f4", "win+d", "win+e", "win+up", "win+down", "win+left", "win+right", "win+tab",
    "win+shift+s", "win+v", "win+i", "win+a", "win+n",
    "enter", "esc", "tab", "shift+tab", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end",
    "pageup", "pagedown", "f5", "f11", "f2",
}
#: atalhos que exigem confirmação (fecham coisas ou apagam)
RISKY_COMBOS = {"alt+f4", "ctrl+w", "delete", "shift+delete"}
VK.update({"plus": 0xBB, "minus": 0xBD})


def normalize_combo(keys: str) -> str:
    parts = [p.strip().lower() for p in keys.replace("-", "+").replace(" ", "+").split("+") if p.strip()]
    alias = {"control": "ctrl", "return": "enter", "escape": "esc", "windows": "win", "del": "delete", "espaco": "space"}
    parts = [alias.get(p, p) for p in parts]
    mods = [m for m in ("ctrl", "alt", "shift", "win") if m in parts]
    rest = [p for p in parts if p not in mods]
    return "+".join(mods + rest)


def is_terminal(title: str, exe: str) -> bool:
    t = (title or "").lower()
    return (exe or "").lower() in TERMINAL_EXES or any(t == k or t.startswith(k + " ") or f" - {k}" in t for k in TERMINAL_TITLES)


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """PNG RGB 8 bits sem dependências (zlib)."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def downscale_bgra(bgra: bytes, w: int, h: int, max_w: int) -> tuple[bytes, int, int]:
    """Reduz a captura (BGRA de cima para baixo) para no máximo `max_w` de largura e devolve RGB."""
    try:
        from PIL import Image  # type: ignore

        img = Image.frombuffer("RGBA", (w, h), bgra, "raw", "BGRA", 0, 1).convert("RGB")
        if w > max_w:
            img = img.resize((max_w, round(h * max_w / w)), Image.BILINEAR)
        return img.tobytes(), img.width, img.height
    except ImportError:
        step = max(1, -(-w // max_w))   # sem Pillow: amostragem simples
        out = bytearray()
        nw, nh = len(range(0, w, step)), len(range(0, h, step))
        for y in range(0, h, step):
            row = bgra[y * w * 4:(y + 1) * w * 4]
            for x in range(0, w, step):
                b, g, r = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
                out += bytes((r, g, b))
        return bytes(out), nw, nh


@dataclass
class Shot:
    png: bytes
    width: int          # da imagem enviada
    height: int
    screen_w: int       # da tela real
    screen_h: int


class ScreenInput:
    """Interface. `RealScreenInput` no Windows; dublês nos testes."""

    def screen_size(self) -> tuple[int, int]: ...
    def capture(self, max_w: int = 1280) -> Shot: ...
    def cursor(self) -> tuple[int, int]: ...
    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None: ...
    def move(self, x: int, y: int) -> None: ...
    def scroll(self, x: int, y: int, clicks: int) -> None: ...
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def combo(self, combo: str) -> None: ...
    def foreground(self) -> tuple[str, str]: ...      # (título, exe)
    def minimize_titled(self, needle: str) -> list[int]: ...
    def restore(self, handles: list[int]) -> None: ...


class RealScreenInput(ScreenInput):  # pragma: no cover — só roda no Windows
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("controle de tela só no Windows")
        from ctypes import wintypes

        self.wt = wintypes
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.g = ctypes.WinDLL("gdi32", use_last_error=True)
        try:   # coordenadas reais da tela, mesmo com escala de 125 %/150 %
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            self.u.SetProcessDPIAware()

    def screen_size(self) -> tuple[int, int]:
        return self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def capture(self, max_w: int = 1280) -> Shot:
        w, h = self.screen_size()
        hdc = self.u.GetDC(0)
        mem = self.g.CreateCompatibleDC(hdc)
        bmp = self.g.CreateCompatibleBitmap(hdc, w, h)
        self.g.SelectObject(mem, bmp)
        self.g.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                        ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        self.g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
        self.g.DeleteObject(bmp)
        self.g.DeleteDC(mem)
        self.u.ReleaseDC(0, hdc)
        rgb, nw, nh = downscale_bgra(buf.raw, w, h, max_w)
        return Shot(encode_png(nw, nh, rgb), nw, nh, w, h)

    def cursor(self) -> tuple[int, int]:
        pt = self.wt.POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _mouse(self, flags: int, data: int = 0) -> None:
        self.u.mouse_event(flags, 0, 0, data, 0)

    def move(self, x: int, y: int) -> None:
        self.u.SetCursorPos(int(x), int(y))

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        self.move(x, y)
        time.sleep(0.05)
        down, up = {"left": (0x02, 0x04), "right": (0x08, 0x10), "middle": (0x20, 0x40)}[button]
        for _ in range(2 if double else 1):
            self._mouse(down)
            self._mouse(up)
            time.sleep(0.06)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self.move(x, y)
        self._mouse(0x0800, int(clicks) * 120)

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.move(x1, y1)
        self._mouse(0x02)
        for i in range(1, 11):
            self.move(x1 + (x2 - x1) * i // 10, y1 + (y2 - y1) * i // 10)
            time.sleep(0.02)
        self._mouse(0x04)

    def _key(self, vk: int, up: bool = False) -> None:
        self.u.keybd_event(vk, 0, 0x0002 if up else 0, 0)

    def type_text(self, text: str) -> None:
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
            _anonymous_ = ("u",)
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

        for ch in text:
            if ch == "\n":
                self.combo("enter")
                continue
            for code in struct.unpack("<%dH" % (len(ch.encode("utf-16-le")) // 2), ch.encode("utf-16-le")):
                for flags in (0x0004, 0x0004 | 0x0002):   # KEYEVENTF_UNICODE (+ KEYUP)
                    inp = INPUT(type=1)
                    inp.ki = KEYBDINPUT(0, code, flags, 0, 0)
                    self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            time.sleep(0.008)

    def combo(self, combo: str) -> None:
        keys = [VK[k] for k in combo.split("+")]
        for k in keys:
            self._key(k)
        for k in reversed(keys):
            self._key(k, up=True)

    def foreground(self) -> tuple[str, str]:
        hwnd = self.u.GetForegroundWindow()
        n = self.u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        pid = self.wt.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        try:
            import psutil

            exe = psutil.Process(pid.value).name()
        except Exception:
            pass
        return buf.value, exe

    def minimize_titled(self, needle: str) -> list[int]:
        from .win32api import SW_MINIMIZE, RealWin32Api

        api = RealWin32Api()
        hit = [w.hwnd for w in api.list_windows() if needle.lower() in w.title.lower()]
        for h in hit:
            api.show(h, SW_MINIMIZE)
        return hit

    def restore(self, handles: list[int]) -> None:
        from .win32api import SW_RESTORE, RealWin32Api

        api = RealWin32Api()
        for h in handles:
            api.show(h, SW_RESTORE)
            api.focus(h)


def get_screen_input() -> ScreenInput | None:
    try:
        return RealScreenInput()
    except OSError:
        return None


def guard(si: ScreenInput, kind: str, combo: str = "") -> str | None:
    """Barreira comum: devolve o motivo da recusa ou None."""
    title, exe = si.foreground()
    if kind in ("type", "combo") and is_terminal(title, exe):
        return f"Recusado: a janela em foco (“{title or exe}”) é um terminal ou o Executar — o JARVIS não digita onde o texto vira comando."
    if kind == "combo" and combo not in ALLOWED_COMBOS:
        return f"Atalho “{combo}” fora da lista permitida."
    return None


def describe_shot(shot: Shot) -> dict[str, Any]:
    return {"width": shot.width, "height": shot.height, "screen": [shot.screen_w, shot.screen_h], "bytes": len(shot.png)}
