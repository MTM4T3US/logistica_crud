"""Atualizador do JARVIS OS (0.7).

    ATUALIZAR.bat                          → git pull (se a pasta é um clone) ou baixa a versão do GitHub
    ATUALIZAR.bat jarvis-os-0.7.0.zip      → aplica o zip (no Windows: arraste o zip em cima do ATUALIZAR.bat)
    ATUALIZAR.bat --voltar                 → volta para a versão anterior (último backup)
    ATUALIZAR.bat --sem-instalar ...       → só troca os arquivos (não roda pip/npm)

Nunca toca em: backend\\.env, backend\\config\\permissions.json, backend\\data\\ (rosto, agenda, listas, mapa,
aparelhos, Telegram), backend\\models\\, o ambiente Python e o node_modules. Antes de trocar, guarda os arquivos
atuais em backend\\data\\atualizacoes\\ para poder voltar. Não apaga arquivos que saíram da versão nova.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]          # pasta jarvis-hud
REPO_ZIP = "https://codeload.github.com/MTM4T3US/logistica_crud/zip/refs/heads/ccr-41dc01f1-0wlbjp"
PROTECTED = ("backend/.env", "backend/config/permissions.json", "backend/data/", "backend/models/", "backend/.venv/", "backend/samples/",
             "node_modules/", "dist/", "public/models/", "firmware/fechadura_jarvis/secrets.h", ".git/")
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def protected(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("./")
    if any(part in SKIP_DIRS for part in rel.split("/")):
        return True
    return any(rel == p or rel.startswith(p) for p in PROTECTED)


def version_of(text: str) -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "?"


def local_version(root: Path = ROOT) -> str:
    f = root / "backend" / "app" / "assistant.py"
    return version_of(f.read_text(encoding="utf-8")) if f.exists() else "?"


def zip_root(zf: zipfile.ZipFile) -> str:
    """Prefixo da pasta jarvis-hud dentro do zip (pacote do chat ou zip do GitHub)."""
    for name in zf.namelist():
        if name.endswith("backend/app/main.py"):
            return name[: -len("backend/app/main.py")]
    raise ValueError("Esse zip não é do JARVIS (não achei backend/app/main.py).")


def safe_members(zf: zipfile.ZipFile, prefix: str) -> list[tuple[zipfile.ZipInfo, str]]:
    out = []
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix):]
        p = PurePosixPath(rel)
        if not rel or p.is_absolute() or ".." in p.parts or ":" in rel:
            raise ValueError(f"Caminho suspeito no zip: {info.filename}")
        if not protected(rel):
            out.append((info, rel))
    return out


def backup(root: Path = ROOT) -> Path:
    dest = root / "backend" / "data" / "atualizacoes"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"antes-de-atualizar-{local_version(root)}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, dirs, files in os.walk(root):
            base = Path(d).relative_to(root).as_posix()
            base = "" if base == "." else base + "/"
            dirs[:] = [x for x in dirs if not protected(base + x + "/")]     # não entra em node_modules, .venv, data…
            for name in files:
                if not protected(base + name):
                    zf.write(Path(d) / name, base + name)
    return path


def apply_zip(zip_path: Path, root: Path = ROOT) -> tuple[str, str, int]:
    """Troca os arquivos pelos do zip. Devolve (versão antes, versão do zip, arquivos escritos)."""
    with zipfile.ZipFile(zip_path) as zf:
        prefix = zip_root(zf)
        new_version = version_of(zf.read(prefix + "backend/app/assistant.py").decode("utf-8"))
        members = safe_members(zf, prefix)
        old = local_version(root)
        n = 0
        for info, rel in members:
            target = (root / rel).resolve()
            if root.resolve() not in target.parents:
                raise ValueError(f"Caminho fora da pasta do JARVIS: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(info)
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
                n += 1
    return old, new_version, n


def latest_backup(root: Path = ROOT) -> Path | None:
    files = sorted(f for f in (root / "backend" / "data" / "atualizacoes").glob("antes-de-atualizar-*.zip") if not f.stem.endswith("-restaurado"))
    return files[-1] if files else None


def restore(root: Path = ROOT) -> tuple[str, str, int]:
    b = latest_backup(root)
    if b is None:
        raise FileNotFoundError("Não há backup para voltar (nenhuma atualização foi feita por aqui).")
    old = local_version(root)
    with zipfile.ZipFile(b) as zf:
        n = 0
        for info, rel in safe_members(zf, ""):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            n += 1
    b.rename(b.with_name(b.stem + "-restaurado.zip"))
    return old, local_version(root), n


def jarvis_running(port: int = 8765) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.desktop_app import core_alive

        return core_alive(port)
    except Exception:
        return False


def run(cmd: list[str], cwd: Path) -> bool:
    print("  >", " ".join(cmd))
    try:
        return subprocess.run(cmd, cwd=cwd, shell=sys.platform == "win32").returncode == 0
    except OSError as err:
        print("   falhou:", err)
        return False


def post_install(root: Path = ROOT) -> bool:
    py = root / "backend" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    ok = run([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], root / "backend")
    ok = run(["npm", "install", "--no-audit", "--no-fund"], root) and ok
    ok = run(["npm", "run", "build"], root) and ok
    return ok


def download(dest: Path) -> Path:
    import httpx

    print("Baixando a versão mais nova do GitHub…")
    with httpx.stream("GET", REPO_ZIP, follow_redirects=True, timeout=120) as r:
        if r.status_code == 404:
            raise RuntimeError("O GitHub não deixou baixar (repositório privado?). Arraste o zip da versão nova em cima do ATUALIZAR.bat.")
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Atualiza o JARVIS OS mantendo seus dados e configurações.")
    ap.add_argument("zip", nargs="?", help="zip da versão nova (jarvis-os-X.zip)")
    ap.add_argument("--voltar", action="store_true", help="volta para a versão anterior")
    ap.add_argument("--sem-instalar", action="store_true", help="não roda pip/npm depois")
    args = ap.parse_args(argv)
    print(f"JARVIS OS — versão atual: {local_version()}")
    if jarvis_running():
        print("\nO JARVIS está aberto. Feche-o antes (ícone da bandeja → Sair) e rode de novo.")
        return 2
    try:
        if args.voltar:
            old, new, n = restore()
            print(f"Voltei de {old} para {new} ({n} arquivos).")
        else:
            git = (ROOT.parent / ".git").exists() or (ROOT / ".git").exists()
            if args.zip:
                src = Path(args.zip.strip('"'))
            elif git:
                print("Pasta é um clone do Git: atualizando com git pull…")
                b = backup()
                print("Backup:", b)
                if not run(["git", "pull", "--ff-only"], ROOT):
                    print("git pull falhou (mudanças locais?). Nada foi trocado à força.")
                    return 1
                src = None
            else:
                src = download(ROOT / "backend" / "data" / "atualizacoes" / "baixado.zip")
            if src is not None:
                if not src.exists():
                    print("Arquivo não encontrado:", src)
                    return 1
                b = backup()
                print("Backup da versão atual:", b)
                old, new, n = apply_zip(src)
                print(f"Atualizado de {old} para {new}: {n} arquivo(s) trocado(s). Seus dados e configurações foram mantidos.")
        if not args.sem_instalar:
            print("Instalando dependências e recompilando o HUD (pode levar alguns minutos)…")
            if not post_install():
                print("Algo falhou na instalação: veja as mensagens acima. Para voltar: ATUALIZAR.bat --voltar")
                return 1
        print("\nPronto. Abra o JARVIS pelo atalho.")
        return 0
    except (ValueError, FileNotFoundError, RuntimeError, zipfile.BadZipFile) as err:
        print("\nNão atualizei:", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
