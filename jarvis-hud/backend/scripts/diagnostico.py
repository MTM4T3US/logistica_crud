"""Diagnóstico do JARVIS OS no computador (Fase 1 da 0.3). Não altera nada; só lê e relata.

Uso:  .venv\\Scripts\\python scripts\\diagnostico.py [--ble] [--procurar-leds]
  --ble            procura dispositivos Bluetooth LE por 10 s (mostra as fitas ELK-BLEDDM)
  --procurar-leds  procura no seu usuário scripts Python antigos que usam bleak (o driver que já funcionou)
Relatório: backend/data/diagnostico-AAAAMMDD-HHMMSS.md
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
lines: list[str] = []


def out(text: str = "") -> None:
    print(text)
    lines.append(text)


def check(name: str, ok: bool | None, detail: str = "") -> None:
    mark = {True: "OK  ", False: "FALHA", None: "AVISO"}[ok]
    out(f"- [{mark}] {name}" + (f" — {detail}" if detail else ""))


def version_of(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        return subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=15).stdout.strip() or "?"
    except Exception:
        return None


def main() -> int:
    args = set(sys.argv[1:])
    out(f"# Diagnóstico JARVIS OS — {time.strftime('%d/%m/%Y %H:%M')}\n")
    out("## Sistema\n")
    check("Sistema operacional", sys.platform == "win32", f"{platform.system()} {platform.release()} ({platform.version()})")
    check("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    node = version_of(["node", "-v"])
    check("Node.js", bool(node), node or "não encontrado no PATH")
    gpu = version_of(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    check("GPU NVIDIA (nvidia-smi)", bool(gpu) or None, gpu or "nvidia-smi não encontrado")

    out("\n## Pacotes Python\n")
    for mod, why in [("fastapi", "servidor"), ("google.genai", "Gemini"), ("psutil", "leituras do sistema"), ("pycaw", "volume (Windows)"),
                     ("comtypes", "volume (Windows)"), ("pyttsx3", "voz do Windows"), ("numpy", "áudio"), ("openwakeword", "palavra-chave local"),
                     ("faster_whisper", "transcrição local"), ("piper", "voz Piper local"), ("bleak", "Bluetooth dos LEDs")]:
        try:
            m = importlib.import_module(mod)
            check(f"{mod} ({why})", True, getattr(m, "__version__", ""))
        except Exception as exc:
            check(f"{mod} ({why})", None, f"não instalado ({type(exc).__name__})")

    out("\n## Configuração\n")
    env = ROOT / ".env"
    key_set = env.exists() and any(l.startswith("GEMINI_API_KEY=") and len(l.strip()) > len("GEMINI_API_KEY=") for l in env.read_text(encoding="utf-8").splitlines())
    check("backend/.env", env.exists(), "chave Gemini preenchida" if key_set else "sem chave (modo local)")
    check("config/permissions.json", (ROOT / "config" / "permissions.json").exists())
    from app.config import load_settings

    s = load_settings()
    check("LEDs", s.leds_mode == "bluetooth" or None, f"JARVIS_LEDS={s.leds_mode}" + (f", endereço {s.led_address}" if s.led_address else ""))
    models = s.models_dir
    piper = sorted(p.name for p in (models / "piper").glob("*.onnx")) if (models / "piper").is_dir() else []
    check("Voz Piper", bool(piper) or None, ", ".join(piper) or f"nenhuma em {models / 'piper'}")
    whisper = (models / "whisper").is_dir() and any((models / "whisper").rglob("model.bin"))
    check("Modelo Whisper", whisper or None, str(models / "whisper"))
    try:
        from app.voice.wake import OpenWakeWordDetector

        ok, reason = OpenWakeWordDetector().available()
        check("Detector local de “Jarvis”", ok or None, reason or "hey_jarvis (openWakeWord)")
    except Exception as exc:
        check("Detector local de “Jarvis”", None, str(exc))

    out("\n## Núcleo\n")
    with socket.socket() as sock:
        busy = sock.connect_ex(("127.0.0.1", s.port)) == 0
    if busy:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/api/health", timeout=3) as r:
                check(f"Porta {s.port}", True, f"núcleo respondendo: {json.loads(r.read())}")
        except Exception as exc:
            check(f"Porta {s.port}", False, f"ocupada por outro programa ({exc})")
    else:
        check(f"Porta {s.port}", None, "livre (núcleo não está rodando)")

    if sys.platform == "win32":
        out("\n## Voz do Windows (SAPI)\n")
        try:
            import pyttsx3

            for v in pyttsx3.init().getProperty("voices"):
                out(f"- {v.name}")
        except Exception as exc:
            check("SAPI", False, str(exc))

    if "--ble" in args:
        out("\n## Bluetooth LE (10 s)\n")
        try:
            from bleak import BleakScanner

            # numa thread nova: a seção SAPI acima (pyttsx3/pythoncom) deixa esta thread em STA e o
            # bleak no Windows falha com "Thread is configured for Windows GUI…" (mesmo motivo do _BleLoop)
            import threading

            box: dict = {}

            def scan() -> None:
                try:
                    box["found"] = asyncio.run(BleakScanner.discover(timeout=10.0, return_adv=True))
                except Exception as exc:  # repassado para a thread principal
                    box["error"] = exc

            worker = threading.Thread(target=scan, name="diagnostico-ble")
            worker.start()
            worker.join()
            if "error" in box:
                raise box["error"]
            found = box["found"]
            rows = sorted(((d.address, d.name or a.local_name or "", a.rssi) for d, a in found.values()), key=lambda r: -r[2])
            for addr, name, rssi in rows[:25]:
                tag = "  ← ELK-BLEDDM" if name.upper().startswith("ELK-BLE") else ""
                out(f"- {addr} · {name or '(sem nome)'} · {rssi} dBm{tag}")
            if not any(n.upper().startswith("ELK-BLE") for _, n, _ in rows):
                check("Fita ELK-BLEDDM", None, "não apareceu; ligue a fita e feche o app do celular")
        except Exception as exc:
            check("Bluetooth", False, f"{type(exc).__name__}: {exc}")

    if "--procurar-leds" in args:
        out("\n## Scripts antigos de LED (bleak)\n")
        home = Path.home()
        skip = {"node_modules", ".venv", "venv", "AppData", ".git", "site-packages", "__pycache__", "$Recycle.Bin"}
        hits = []
        for base in [home / d for d in ("Desktop", "Documents", "Downloads", "OneDrive", "Projetos", "projects", "source")] + [home]:
            if not base.is_dir():
                continue
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
                if root.count(os.sep) - str(base).count(os.sep) > 5:
                    dirs[:] = []
                for f in files:
                    if f.endswith(".py"):
                        p = Path(root) / f
                        try:
                            if p.stat().st_size > 400_000:
                                continue
                            txt = p.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            continue
                        if "bleak" in txt and any(k in txt.lower() for k in ("fff3", "bleddm", "bledom", "0x7e", "elk")):
                            hits.append(p)
            if base == home:
                break
        for p in dict.fromkeys(hits):
            out(f"- {p}")
        if not hits:
            out("- nenhum encontrado")

    folder = ROOT / "data"
    folder.mkdir(exist_ok=True)
    path = folder / f"diagnostico-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nRelatório salvo em {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
