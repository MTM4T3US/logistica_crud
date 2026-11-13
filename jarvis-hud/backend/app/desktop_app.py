"""JARVIS como programa do Windows (0.6): sem janela de console, com ícone na bandeja e atalhos globais.

    backend\\.venv\\Scripts\\pythonw.exe -m app.desktop_app [--minimizado]

- sobe o núcleo (o mesmo servidor do INICIAR.bat) dentro deste processo;
- abre o HUD numa janela própria (Edge/Chrome/Brave em modo app, perfil exclusivo do JARVIS, que guarda as
  permissões de câmera e microfone e deixa a música da entrada tocar sem clique);
- ícone perto do relógio: abrir, falar, bloquear, iniciar com o Windows, registro, sair;
- atalhos globais (padrão): Ctrl+Alt+J abre/traz o HUD; Ctrl+Alt+Espaço começa a falar;
- uma instância só: abrir de novo apenas traz o HUD para a frente;
- registro em backend/data/jarvis.log (não há console).
Tudo continua só em 127.0.0.1.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

APP_NAME = "JARVIS"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_NAME = "Local\\JARVIS-OS-nucleo"
ICON = Path(__file__).resolve().parent / "static" / "jarvis.ico"
HUD_TITLE = "JARVIS OS"

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
NAMED_KEYS = {"space": 0x20, "espaco": 0x20, "enter": 0x0D, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
              "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B, "pause": 0x13, "insert": 0x2D}

log = logging.getLogger("jarvis.app")


# ------------------------------------------------------------------ peças puras (testadas no PC)
def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+j' → (modificadores para RegisterHotKey, tecla virtual). Exige ao menos um modificador."""
    parts = [p.strip().lower() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    mods = 0
    key = None
    for p in parts:
        if p in MOD:
            mods |= MOD[p]
        elif len(p) == 1 and p.isascii() and p.isalnum():   # só A–Z e 0–9 têm tecla virtual igual ao código
            key = ord(p.upper())
        elif p in NAMED_KEYS:
            key = NAMED_KEYS[p]
        else:
            raise ValueError(f"tecla desconhecida: {p}")
    if key is None or not mods:
        raise ValueError("o atalho precisa de um modificador (Ctrl, Alt, Shift ou Win) e uma tecla")
    return mods | MOD_NOREPEAT, key


def find_browser(env: dict[str, str] | None = None, exists: Callable[[str], bool] = os.path.isfile, preferred: str | None = None) -> str | None:
    """Navegador para a janela do HUD: o escolhido em JARVIS_BROWSER, senão Edge (vem no Windows), Chrome ou Brave."""
    env = dict(os.environ if env is None else env)
    if preferred and exists(preferred):
        return preferred
    pf, pf86, local = env.get("ProgramFiles", r"C:\Program Files"), env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), env.get("LOCALAPPDATA", "")
    candidates = [
        rf"{pf86}\Microsoft\Edge\Application\msedge.exe", rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        rf"{pf}\Google\Chrome\Application\chrome.exe", rf"{pf86}\Google\Chrome\Application\chrome.exe", rf"{local}\Google\Chrome\Application\chrome.exe",
        rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe", rf"{local}\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    return next((c for c in candidates if exists(c)), None)


def browser_args(exe: str, url: str, profile: Path) -> list[str]:
    # perfil próprio: as permissões de câmera/microfone ficam só nele e as opções valem mesmo com o navegador aberto
    return [exe, f"--app={url}", f"--user-data-dir={profile}", "--autoplay-policy=no-user-gesture-required",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "--window-size=1600,900"]


ENTRY = Path(__file__).resolve().parents[1] / "jarvis_app.pyw"
DEFAULT_HOTKEYS = {"open": "ctrl+alt+j", "talk": "ctrl+alt+space"}


def hotkeys(env: dict[str, str] | None = None) -> dict[str, str]:
    """Atalhos globais: os padrões, trocados por JARVIS_HOTKEY_OPEN / JARVIS_HOTKEY_TALK no backend\\.env."""
    env = dict(os.environ if env is None else env)
    return {"open": env.get("JARVIS_HOTKEY_OPEN") or DEFAULT_HOTKEYS["open"], "talk": env.get("JARVIS_HOTKEY_TALK") or DEFAULT_HOTKEYS["talk"]}


def startup_command(exe: str = sys.executable, entry: Path = ENTRY) -> str:
    """Comando gravado em "Executar ao iniciar": pythonw (sem console) + jarvis_app.pyw (acha a própria pasta),
    só na bandeja. O Windows inicia esses programas fora da pasta do JARVIS, por isso não dá para usar "-m"."""
    pyw = Path(exe).with_name("pythonw.exe")
    runner = pyw if pyw.exists() else Path(exe)
    return f'"{runner}" "{entry}" --minimizado'


def set_autostart(on: bool, winreg: Any = None, command: str | None = None) -> bool:
    """Liga/desliga "iniciar com o Windows" (HKCU\\...\\Run — só para este usuário, sem administrador)."""
    if winreg is None:
        import winreg  # type: ignore[no-redef]
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    try:
        if on:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command or startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)
    return on


def is_autostart(winreg: Any = None) -> bool:
    if winreg is None:
        import winreg  # type: ignore[no-redef]
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return "jarvis_app.pyw" in str(value)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False


def hud_request(port: int, token: str, action: str) -> bool:
    """Avisa o HUD aberto (ex.: 'talk' = começar a falar). Só 127.0.0.1, com o token da sessão."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/hud/{action}", method="POST", data=b"{}",
                                 headers={"X-Jarvis-Token": token, "Content-Type": "application/json", "Host": f"127.0.0.1:{port}"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read() or b"{}").get("ok", False)
    except OSError:
        return False


def core_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            return json.loads(resp.read()).get("name") == "JARVIS Core"
    except (OSError, ValueError):
        return False


# ------------------------------------------------------------------ Windows (só roda lá)
class SingleInstance:  # pragma: no cover
    def __init__(self) -> None:
        self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        self.first = ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


class Hotkeys(threading.Thread):  # pragma: no cover
    """Atalhos globais (RegisterHotKey) num laço de mensagens próprio."""

    def __init__(self, bindings: list[tuple[str, Callable[[], None]]]):
        super().__init__(name="jarvis-atalhos", daemon=True)
        self.bindings = bindings
        self.failed: list[str] = []

    def run(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        for i, (text, _fn) in enumerate(self.bindings, start=1):
            try:
                mods, vk = parse_hotkey(text)
            except ValueError as err:
                self.failed.append(f"{text}: {err}")
                continue
            if not user32.RegisterHotKey(None, i, mods, vk):
                self.failed.append(f"{text}: já usado por outro programa")
        if self.failed:
            log.warning("atalhos não registrados: %s", "; ".join(self.failed))
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312 and 1 <= msg.wParam <= len(self.bindings):   # WM_HOTKEY
                try:
                    self.bindings[msg.wParam - 1][1]()
                except Exception:
                    log.exception("atalho")


def focus_hud() -> bool:  # pragma: no cover
    """Traz a janela do HUD para a frente, se existir."""
    try:
        from .system.win32api import SW_RESTORE, RealWin32Api

        api = RealWin32Api()
        wins = [w for w in api.list_windows() if w.title.startswith(HUD_TITLE)]
        if not wins:
            return False
        api.show(wins[0].hwnd, SW_RESTORE)
        api.focus(wins[0].hwnd)
        return True
    except OSError:
        return False


class DesktopApp:  # pragma: no cover — interface do Windows
    def __init__(self, minimized: bool):
        from .config import load_settings

        self.settings = load_settings()
        self.port = self.settings.port
        self.url = f"http://127.0.0.1:{self.port}/"
        self.data = self.settings.db_path.parent
        self.profile = Path(os.environ.get("LOCALAPPDATA", str(self.data))) / "JARVIS" / "navegador"
        self.minimized = minimized
        self.server: Any = None
        self.icon: Any = None

    # núcleo -------------------------------------------------------------
    def start_core(self) -> None:
        import uvicorn

        from .main import check_exposure, create_app

        problem = check_exposure(self.settings)
        if problem:
            raise SystemExit(problem)
        os.environ["JARVIS_APP"] = "1"          # o HUD mostra que está no app da bandeja (atalhos ativos)
        config = uvicorn.Config(create_app(self.settings), host=self.settings.host, port=self.port, log_level="warning", log_config=None)
        self.server = uvicorn.Server(config)
        threading.Thread(target=self.server.run, name="jarvis-nucleo", daemon=True).start()
        for _ in range(120):
            if core_alive(self.port):
                log.info("núcleo no ar em %s", self.url)
                return
            time.sleep(0.25)
        raise SystemExit("O núcleo não subiu em 30 s (veja backend/data/jarvis.log).")

    # janela do HUD ------------------------------------------------------
    def open_hud(self) -> None:
        if focus_hud():
            return
        exe = find_browser(preferred=os.environ.get("JARVIS_BROWSER") or None)
        if exe:
            self.profile.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(browser_args(exe, self.url, self.profile), close_fds=True)
        else:
            import webbrowser

            webbrowser.open(self.url)

    def talk(self) -> None:
        if not focus_hud():
            self.open_hud()
            time.sleep(2.5)
        hud_request(self.port, self.settings.local_token, "talk")

    def lock(self) -> None:
        hud_request(self.port, self.settings.local_token, "lock")

    # bandeja ------------------------------------------------------------
    def tray(self) -> None:
        import pystray
        from PIL import Image

        hk = hotkeys()
        keys = (hk["open"], hk["talk"])

        def toggle_autostart(icon: Any, item: Any) -> None:
            set_autostart(not is_autostart())

        menu = pystray.Menu(
            pystray.MenuItem(f"Abrir o JARVIS ({keys[0].upper()})", lambda: self.open_hud(), default=True),
            pystray.MenuItem(f"Falar ({keys[1].upper()})", lambda: self.talk()),
            pystray.MenuItem("Bloquear o JARVIS", lambda: self.lock()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Iniciar com o Windows", toggle_autostart, checked=lambda item: is_autostart()),
            pystray.MenuItem("Abrir a pasta de dados", lambda: os.startfile(self.data)),   # type: ignore[attr-defined]
            pystray.MenuItem("Ver o registro (log)", lambda: os.startfile(self.data / "jarvis.log")),   # type: ignore[attr-defined]
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", lambda icon, item: self.quit()),
        )
        self.icon = pystray.Icon(APP_NAME, Image.open(ICON), "JARVIS OS — no ar", menu)
        Hotkeys([(keys[0], self.open_hud), (keys[1], self.talk)]).start()
        if not self.minimized:
            threading.Timer(0.5, self.open_hud).start()
        self.icon.run()   # bloqueia até "Sair"

    def quit(self) -> None:
        log.info("saindo")
        if self.server is not None:
            self.server.should_exit = True
        if self.icon is not None:
            self.icon.stop()


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / "jarvis.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description="JARVIS OS como programa do Windows")
    ap.add_argument("--minimizado", action="store_true", help="inicia só na bandeja (usado ao iniciar com o Windows)")
    ap.add_argument("--autostart", choices=["on", "off"], help="liga/desliga iniciar com o Windows e sai")
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("O app de bandeja é para o Windows. Em outros sistemas use: python -m app.main")
        return 2
    if args.autostart:
        set_autostart(args.autostart == "on")
        print("Iniciar com o Windows:", "ligado" if args.autostart == "on" else "desligado")
        return 0
    app = DesktopApp(args.minimizado)
    setup_logging(app.data)
    if not SingleInstance().first:          # já está rodando: só traz o HUD
        if not focus_hud():
            app.open_hud()
        return 0
    try:
        app.start_core()
        app.tray()
    except SystemExit as exc:
        log.error("%s", exc)
        ctypes.windll.user32.MessageBoxW(None, str(exc), "JARVIS OS", 0x10)
        return 1
    except Exception:
        log.exception("falha no app")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
