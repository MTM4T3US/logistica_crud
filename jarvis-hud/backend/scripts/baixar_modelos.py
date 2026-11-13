"""Baixa os modelos locais da 0.3 para backend/models (rode no SEU computador, com internet).

- Voz Piper pt_BR-faber-medium (masculina, ~63 MB) de huggingface.co/rhasspy/piper-voices
- Modelo Whisper (padrão "small", ~480 MB) para a transcrição local
- Modelo de palavra-chave "hey_jarvis" do openWakeWord (o pacote 0.5+ não o inclui; é baixado do GitHub dele)

Uso:  .venv\\Scripts\\python scripts\\baixar_modelos.py [--whisper base|small|medium] [--sem-whisper]
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path(os.getenv("JARVIS_MODELS_DIR", ROOT / "models"))
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"
PIPER_FILES = ["pt_BR-faber-medium.onnx", "pt_BR-faber-medium.onnx.json"]


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"  já existe: {dest.name}")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  baixando {url}")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def main() -> int:
    args = sys.argv[1:]
    size = args[args.index("--whisper") + 1] if "--whisper" in args else os.getenv("JARVIS_WHISPER_MODEL", "small")
    ok = True
    print(f"Pasta dos modelos: {MODELS}")
    print("\n[1/3] Voz Piper (pt_BR-faber-medium)")
    (MODELS / "piper").mkdir(parents=True, exist_ok=True)
    try:
        for name in PIPER_FILES:
            fetch(PIPER_BASE + name, MODELS / "piper" / name)
    except Exception as exc:
        ok = False
        print(f"  FALHOU: {type(exc).__name__}: {exc}")
    print(f"\n[2/3] Whisper local ({size})")
    if "--sem-whisper" in args:
        print("  pulado")
    else:
        try:
            from faster_whisper import WhisperModel

            WhisperModel(size, device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
            print("  pronto")
        except Exception as exc:
            ok = False
            print(f"  FALHOU: {type(exc).__name__}: {exc}")
    print("\n[3/3] Palavra-chave (openWakeWord)")
    try:
        import openwakeword

        path = Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
        if not path.exists():
            # o pacote (>= 0.5) não traz os modelos: baixa hey_jarvis + modelos de áudio (melspectrogram,
            # embedding, VAD) do GitHub do openWakeWord para a pasta do pacote
            print("  baixando hey_jarvis e modelos de áudio do openWakeWord (~10 MB)...")
            from openwakeword.utils import download_models

            download_models(["hey_jarvis_v0.1"])
        print(f"  {'pronto' if path.exists() else 'NÃO ENCONTRADO'}: {path}")
        ok = ok and path.exists()
    except Exception as exc:
        ok = False
        print(f"  FALHOU: {type(exc).__name__}: {exc}")
    print("\nTudo pronto." if ok else "\nAlgum item falhou — veja acima.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
