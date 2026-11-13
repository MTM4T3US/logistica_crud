"""Controle amplo do Windows (0.5): qualquer programa instalado, sites, arquivos, energia, brilho,
páginas de Configurações e programas abertos.

Sem terminal: nenhum texto da IA vira comando. Os programas vêm do Menu Iniciar (Get-StartApps) e são
abertos pelo identificador que o próprio Windows deu; arquivos só a partir de uma busca feita aqui;
comandos externos usam listas de argumentos fixas, com números validados.
Ações que fecham, apagam ou desligam pedem confirmação (na camada de ferramentas).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

from .windows import ActionResult


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Cf")).strip()


#: nomes falados → nomes do Menu Iniciar (pt-BR e inglês)
APP_ALIASES = {
    "calculadora": ["calculadora", "calculator"], "bloco de notas": ["bloco de notas", "notepad"], "notas": ["bloco de notas", "notepad"],
    "vs code": ["visual studio code"], "vscode": ["visual studio code"], "codigo": ["visual studio code"], "visual studio": ["visual studio"],
    "explorador": ["explorador de arquivos", "file explorer"], "arquivos": ["explorador de arquivos", "file explorer"],
    "configuracoes": ["configuracoes", "settings"], "loja": ["microsoft store"], "paint": ["paint"], "word": ["word"], "excel": ["excel"],
    "powerpoint": ["powerpoint"], "whatsapp": ["whatsapp"], "spotify": ["spotify"], "discord": ["discord"], "steam": ["steam"],
    "chrome": ["google chrome"], "edge": ["microsoft edge"], "brave": ["brave"], "firefox": ["firefox"], "obs": ["obs studio"],
    "camera": ["camera", "câmera"], "fotos": ["fotos", "photos"], "relogio": ["relogio", "clock", "alarmes"], "email": ["outlook", "email", "mail"],
}
#: páginas de Configurações abertas por nome (nunca uma URI vinda da IA)
SETTINGS_PAGES = {
    "bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi", "rede": "ms-settings:network", "tela": "ms-settings:display",
    "som": "ms-settings:sound", "energia": "ms-settings:powersleep", "bateria": "ms-settings:batterysaver", "atualizacoes": "ms-settings:windowsupdate",
    "aplicativos": "ms-settings:appsfeatures", "notificacoes": "ms-settings:notifications", "privacidade": "ms-settings:privacy",
    "personalizacao": "ms-settings:personalization", "mouse": "ms-settings:mousetouchpad", "teclado": "ms-settings:typing",
    "impressoras": "ms-settings:printers", "armazenamento": "ms-settings:storagesense", "data e hora": "ms-settings:dateandtime",
    "idioma": "ms-settings:regionlanguage", "contas": "ms-settings:yourinfo", "jogos": "ms-settings:gaming-gamebar",
}
#: nunca encerrar à força (o Windows ou o próprio JARVIS cairiam)
PROTECTED = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
             "dwm.exe", "explorer.exe", "fontdrvhost.exe", "msmpeng.exe", "securityhealthservice.exe", "sihost.exe", "ctfmon.exe",
             "runtimebroker.exe", "audiodg.exe", "conhost.exe", "taskhostw.exe", "searchhost.exe", "startmenuexperiencehost.exe",
             "python.exe", "pythonw.exe", "lsaiso.exe", "memcompression", "spoolsv.exe", "wlanext.exe"}
#: arquivos que abririam como programa: abrir só via "abrir programa"
EXECUTABLE_EXT = {".exe", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".lnk",
                  ".scr", ".com", ".pif", ".reg", ".jar", ".hta", ".cpl", ".msc", ".url", ".appref-ms", ".ahk", ".py", ".pyw"}
USER_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive", "Área de Trabalho", "Documentos", "Imagens")
SKIP_DIRS = {"appdata", "node_modules", ".git", ".venv", "__pycache__", "$recycle.bin", ".cache"}


@dataclass
class AppInfo:
    name: str
    app_id: str


@dataclass
class FileHit:
    path: str
    name: str
    folder: str
    modified: float
    size: int


class Desktop:
    """Operações do Windows. Os efeitos externos passam por `runner`/`startfile`, trocáveis nos testes."""

    def __init__(self, runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
                 startfile: Callable[[str], Any] | None = None, home: Path | None = None, win: Any = None,
                 clock: Callable[[], float] = time.time, spawn: Callable[[list[str]], Any] | None = None,
                 sleep: Callable[[float], Any] = time.sleep, verify_s: float = 6.0):
        self._run = runner or self._default_run
        self._spawn = spawn or (lambda argv: subprocess.Popen(argv, shell=False, close_fds=True))
        self._sleep, self.verify_s = sleep, verify_s
        self._startfile = startfile or getattr(os, "startfile", None)
        self.home = home or Path(os.environ.get("USERPROFILE") or Path.home())
        self._win = win
        self._clock = clock
        self._apps: list[AppInfo] = []
        self._apps_at = 0.0
        self.last_files: list[FileHit] = []

    @staticmethod
    def _default_run(argv: list[str]) -> subprocess.CompletedProcess:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(argv, capture_output=True, text=True, timeout=25, shell=False, creationflags=flags, encoding="utf-8", errors="replace")

    @property
    def available(self) -> bool:
        return sys.platform == "win32" or self._startfile is not None

    # ------------------------------------------------------------------ programas
    def apps(self, refresh: bool = False) -> list[AppInfo]:
        """Todos os programas do Menu Iniciar (inclui os da Microsoft Store), lidos do próprio Windows."""
        if self._apps and not refresh and self._clock() - self._apps_at < 600:
            return self._apps
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"]
        try:
            out = self._run(ps)
            raw = json.loads(out.stdout or "[]")
        except (OSError, ValueError, subprocess.SubprocessError):
            return self._apps
        if isinstance(raw, dict):
            raw = [raw]
        self._apps = [AppInfo(str(a.get("Name", "")), str(a.get("AppID", ""))) for a in raw if a.get("Name") and a.get("AppID")]
        self._apps_at = self._clock()
        return self._apps

    def find_app(self, spoken: str) -> tuple[AppInfo | None, list[AppInfo]]:
        """Melhor programa para o nome falado, e as alternativas próximas."""
        q = fold(spoken)
        q = re.sub(r"^(o|a|os|as)\s+", "", q)
        needles = APP_ALIASES.get(q, [q])
        scored: list[tuple[int, AppInfo]] = []
        for app in self.apps():
            n = fold(app.name)
            best = 0
            for needle in needles:
                if n == needle:
                    best = max(best, 100)
                elif n.startswith(needle):
                    best = max(best, 80 - min(20, len(n) - len(needle)))
                elif re.search(rf"\b{re.escape(needle)}\b", n):
                    best = max(best, 60 - min(20, len(n) - len(needle)))
                elif all(t in n for t in needle.split()) and len(needle) >= 3:
                    best = max(best, 40)
            if "uninstall" in n or "desinstal" in n:
                best -= 50
            if best > 0:
                scored.append((best, app))
        scored.sort(key=lambda s: -s[0])
        if not scored:
            return None, []
        return scored[0][1], [a for _, a in scored[1:5]]

    def launch(self, app: AppInfo) -> ActionResult:
        before = {w.hwnd for w in self._win.list_windows()} if self._win is not None else set()
        # shell:AppsFolder abre qualquer item do Menu Iniciar (clássico ou da Loja) pelo AppID do próprio Windows
        try:
            self._spawn(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"])
        except OSError as exc:
            return ActionResult(False, False, f"{app.name}: o Windows recusou a abertura ({exc}).")
        return self._verify(app.name, before)

    def _verify(self, name: str, before: set[int]) -> ActionResult:
        """Só diz "aberto" quando aparece uma janela com o nome do programa."""
        if self._win is None:
            return ActionResult(True, True, f"{name}: pedido de abertura enviado; não consegui verificar a janela.", {"app": name, "verified": False})
        words = [w for w in fold(name).split() if len(w) >= 3] or [fold(name)]
        deadline = self._clock() + self.verify_s
        while True:
            new = [w for w in self._win.list_windows() if w.hwnd not in before and any(x in fold(w.title) for x in words)]
            if new:
                return ActionResult(True, True, f"{name} aberto — janela “{new[0].title}” apareceu.", {"app": name, "verified": True})
            if self._clock() >= deadline:
                break
            self._sleep(0.25)
        old = [w for w in self._win.list_windows() if any(x in fold(w.title) for x in words)]
        if old:
            return ActionResult(True, True, f"{name}: já estava aberto (“{old[0].title}”).", {"app": name, "verified": True})
        return ActionResult(True, True, f"{name}: o Windows recebeu o pedido, mas nenhuma janela apareceu em {self.verify_s:g} s — não posso confirmar que abriu.",
                            {"app": name, "verified": False})

    # ------------------------------------------------------------------ web
    def open_url(self, url: str) -> ActionResult:
        u = urlparse(url.strip() if "://" in url else "https://" + url.strip())
        if u.scheme not in ("http", "https") or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}(:\d{1,5})?", u.netloc.lower()):
            return ActionResult(False, False, "Endereço inválido: só sites http/https.")
        target = u.geturl()
        if self._startfile is None:
            return ActionResult(False, False, "Abrir sites só no Windows.")
        self._startfile(target)
        return ActionResult(True, True, f"Abrindo {u.netloc} no navegador padrão.", {"url": target})

    def web_search(self, query: str, site: str = "google") -> ActionResult:
        q = quote_plus(query.strip()[:300])
        base = {"google": "https://www.google.com/search?q=", "youtube": "https://www.youtube.com/results?search_query=",
                "maps": "https://www.google.com/maps/search/", "wikipedia": "https://pt.wikipedia.org/w/index.php?search="}.get(site, "https://www.google.com/search?q=")
        res = self.open_url(base + q)
        if res.ok:
            res.message = f"Pesquisando “{query.strip()[:80]}” {'no YouTube' if site == 'youtube' else 'no Maps' if site == 'maps' else 'na Wikipédia' if site == 'wikipedia' else 'no Google'}."
        return res

    def open_settings(self, page: str) -> ActionResult:
        uri = SETTINGS_PAGES.get(fold(page))
        if uri is None:
            return ActionResult(False, False, f"Página de Configurações desconhecida: {page}.")
        if self._startfile is None:
            return ActionResult(False, False, "Configurações do Windows só no Windows.")
        self._startfile(uri)
        return ActionResult(True, True, f"Configurações de {page} abertas.", {"uri": uri})

    # ------------------------------------------------------------------ arquivos
    def roots(self) -> list[Path]:
        out = []
        for name in USER_DIRS:
            p = self.home / name
            if p.is_dir() and p not in out:
                out.append(p)
        return out

    def search_files(self, query: str, limit: int = 10, max_scan: int = 40000) -> list[FileHit]:
        q = fold(query)
        terms = [t for t in re.split(r"\s+", q) if t]
        hits: list[tuple[int, FileHit]] = []
        scanned = 0
        for root in self.roots():
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if fold(d) not in SKIP_DIRS and not d.startswith(".")]
                if len(Path(dirpath).relative_to(root).parts) >= 5:
                    dirnames[:] = []
                for f in filenames:
                    scanned += 1
                    if scanned > max_scan:
                        break
                    name = fold(f)
                    if terms and all(t in name for t in terms):
                        full = Path(dirpath) / f
                        try:
                            st = full.stat()
                        except OSError:
                            continue
                        score = (50 if Path(name).stem == q else 0) + (20 if name.startswith(terms[0]) else 0)
                        hits.append((score, FileHit(str(full), f, str(Path(dirpath)), st.st_mtime, st.st_size)))
        hits.sort(key=lambda h: (-h[0], -h[1].modified))
        self.last_files = [h for _, h in hits[:limit]]
        return self.last_files

    def _hit(self, index: int) -> FileHit | None:
        return self.last_files[index - 1] if 1 <= index <= len(self.last_files) else None

    def open_file(self, index: int) -> ActionResult:
        hit = self._hit(index)
        if hit is None:
            return ActionResult(False, False, "Esse número não está na última busca de arquivos.")
        if Path(hit.path).suffix.lower() in EXECUTABLE_EXT:
            return ActionResult(False, False, f"“{hit.name}” é um programa ou script; por segurança eu não executo arquivos. Use “abrir programa”.")
        if self._startfile is None:
            return ActionResult(False, False, "Abrir arquivos só no Windows.")
        self._startfile(hit.path)
        return ActionResult(True, True, f"Abrindo “{hit.name}”.", {"path": hit.path})

    def reveal_file(self, index: int) -> ActionResult:
        hit = self._hit(index)
        if hit is None:
            return ActionResult(False, False, "Esse número não está na última busca de arquivos.")
        self._run(["explorer.exe", f"/select,{hit.path}"])
        return ActionResult(True, True, f"Mostrando “{hit.name}” na pasta.", {"path": hit.path})

    def recycle_file(self, index: int) -> ActionResult:
        """Manda para a LIXEIRA (dá para restaurar). A confirmação é pedida antes, na ferramenta."""
        hit = self._hit(index)
        if hit is None:
            return ActionResult(False, False, "Esse número não está na última busca de arquivos.")
        if not any(Path(hit.path).is_relative_to(r) for r in self.roots()):
            return ActionResult(False, False, "Só apago arquivos das suas pastas pessoais.")
        if sys.platform != "win32":
            return ActionResult(False, False, "Lixeira só no Windows.")
        ok = _recycle(hit.path)  # pragma: no cover
        if ok:
            self.last_files = [f for f in self.last_files if f.path != hit.path]
        return ActionResult(ok, ok, f"“{hit.name}” foi para a Lixeira." if ok else f"O Windows não conseguiu mover “{hit.name}” para a Lixeira.")

    # ------------------------------------------------------------------ energia e sessão
    def lock_windows(self) -> ActionResult:
        if sys.platform != "win32":
            return ActionResult(False, False, "Bloquear a sessão só no Windows.")
        import ctypes  # pragma: no cover

        ok = bool(ctypes.windll.user32.LockWorkStation())
        return ActionResult(ok, ok, "Windows bloqueado." if ok else "O Windows recusou o bloqueio.")

    def sleep(self) -> ActionResult:
        if sys.platform != "win32":
            return ActionResult(False, False, "Suspender só no Windows.")
        import ctypes  # pragma: no cover

        ok = bool(ctypes.windll.powrprof.SetSuspendState(0, 1, 0))
        return ActionResult(ok, ok, "Suspendendo o computador." if ok else "O Windows recusou a suspensão.")

    def shutdown(self, restart: bool, delay_s: int = 60) -> ActionResult:
        delay = max(30, min(600, int(delay_s)))
        verb = "reiniciar" if restart else "desligar"
        out = self._run(["shutdown.exe", "/r" if restart else "/s", "/t", str(delay), "/c", f"JARVIS: vou {verb} em {delay} s. Diga 'cancela o desligamento' para cancelar."])
        if out.returncode != 0:
            return ActionResult(False, False, f"O Windows recusou ({(out.stderr or out.stdout).strip()[:120]}).")
        return ActionResult(True, True, f"O computador vai {verb} em {delay} segundos. Diga “cancela o desligamento” para cancelar.", {"delay_s": delay})

    def cancel_shutdown(self) -> ActionResult:
        out = self._run(["shutdown.exe", "/a"])
        ok = out.returncode == 0
        return ActionResult(ok, ok, "Desligamento cancelado." if ok else "Não havia desligamento agendado.")

    # ------------------------------------------------------------------ brilho
    def set_brightness(self, percent: int) -> ActionResult:
        value = max(0, min(100, int(percent)))
        cmd = (f"$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop; "
               f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Brightness=[byte]{value}; Timeout=[uint32]1}} | Out-Null")
        out = self._run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd])
        if out.returncode != 0:
            return ActionResult(False, False, "Não consegui mudar o brilho: só funciona na tela do notebook (monitores externos não aceitam por aqui).")
        return ActionResult(True, True, f"Brilho em {value}%.", {"percent": value})

    # ------------------------------------------------------------------ programas abertos
    def close_app(self, spoken: str) -> ActionResult:
        """Pede para fechar (como clicar no X): o programa ainda pode perguntar se quer salvar."""
        win = self._win
        if win is None:
            return ActionResult(False, False, "Fechar programas só no Windows.")
        q = fold(spoken)
        needles = APP_ALIASES.get(q, [q])
        wins = [w for w in win.list_windows() if any(n in fold(w.title) for n in needles) and "jarvis os" not in fold(w.title)]
        if not wins:
            return ActionResult(False, False, f"Nenhuma janela de “{spoken}” aberta.")
        for w in wins:
            win.post_close(w.hwnd)
        return ActionResult(True, True, f"Pedi para fechar {len(wins)} janela(s) de “{spoken}”. Se houver algo sem salvar, o programa vai perguntar.", {"windows": [w.title for w in wins]})

    def kill_process(self, spoken: str) -> ActionResult:
        """Encerra à força (perde o que não foi salvo). Nunca processos do sistema nem o próprio JARVIS."""
        import psutil

        q = fold(spoken).replace(".exe", "")
        me = {os.getpid(), os.getppid()}
        found = []
        for p in psutil.process_iter(["pid", "name"]):
            name = (p.info.get("name") or "").lower()
            if q and q in fold(name).replace(".exe", "") and p.info["pid"] not in me:
                if name in PROTECTED:
                    return ActionResult(False, False, f"“{name}” é do sistema ou do próprio JARVIS: não encerro.")
                found.append(p)
        if not found:
            return ActionResult(False, False, f"Nenhum programa “{spoken}” em execução.")
        for p in found:
            try:
                p.terminate()
            except psutil.Error:
                pass
        return ActionResult(True, True, f"Encerrei {len(found)} processo(s) de “{spoken}”.", {"count": len(found)})


def _recycle(path: str) -> bool:  # pragma: no cover — só Windows
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW(None, 3, path + "\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)  # DELETE, ALLOWUNDO|NOCONFIRMATION|SILENT|NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted
