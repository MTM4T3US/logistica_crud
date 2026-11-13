"""Atualizador (0.7): troca o código, nunca os dados do usuário; backup e volta; zip estranho é recusado."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("atualizar", Path(__file__).resolve().parents[1] / "scripts" / "atualizar.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


def write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_install(root: Path):
    write(root, "backend/app/assistant.py", 'VERSION = "0.6.1"\n')
    write(root, "backend/app/main.py", "velho")
    write(root, "src/hud/Hud.tsx", "hud velho")
    write(root, "backend/.env", "GEMINI_API_KEY=segredo")
    write(root, "backend/config/permissions.json", '{"meu": true}')
    write(root, "backend/data/rosto.json", "meu rosto")
    write(root, "backend/data/agenda.sqlite3", "agenda")
    write(root, "node_modules/x/index.js", "dep")
    write(root, "backend/app/__pycache__/main.cpython-312.pyc", "cache")


def make_zip(path: Path, prefix: str, files: dict[str, str]):
    with zipfile.ZipFile(path, "w") as zf:
        for rel, text in files.items():
            zf.writestr(prefix + rel, text)


NEW = {"backend/app/assistant.py": 'VERSION = "0.7.0"\n', "backend/app/main.py": "novo", "src/hud/Hud.tsx": "hud novo",
       "ATUALIZAR.bat": "bat", "backend/.env": "GEMINI_API_KEY=", "backend/config/permissions.json": "{}",
       "backend/data/rosto.json": "OUTRO rosto"}


@pytest.mark.parametrize("prefix", ["jarvis-hud/", "logistica_crud-ccr-41dc01f1-0wlbjp/jarvis-hud/"])
def test_update_keeps_user_files_and_can_go_back(tmp_path, prefix):
    root = tmp_path / "jarvis-hud"
    make_install(root)
    z = tmp_path / "novo.zip"
    make_zip(z, prefix, NEW)
    b = up.backup(root)
    names = zipfile.ZipFile(b).namelist()
    assert "backend/app/main.py" in names and not any(n.startswith(("backend/data", "node_modules", "backend/.env")) or "__pycache__" in n for n in names)
    assert up.apply_zip(z, root) == ("0.6.1", "0.7.0", 4)
    assert (root / "backend/app/main.py").read_text() == "novo" and (root / "ATUALIZAR.bat").exists()
    assert (root / "backend/.env").read_text() == "GEMINI_API_KEY=segredo"                    # chave mantida
    assert (root / "backend/config/permissions.json").read_text() == '{"meu": true}'
    assert (root / "backend/data/rosto.json").read_text() == "meu rosto"                       # rosto mantido
    assert up.local_version(root) == "0.7.0"
    assert up.restore(root) == ("0.7.0", "0.6.1", len(names))
    assert (root / "backend/app/main.py").read_text() == "velho" and (root / "backend/.env").read_text() == "GEMINI_API_KEY=segredo"
    with pytest.raises(FileNotFoundError):
        up.restore(root)                                                                       # o backup foi usado


def test_strange_zips_are_refused(tmp_path):
    root = tmp_path / "jarvis-hud"
    make_install(root)
    other = tmp_path / "outro.zip"
    make_zip(other, "", {"leia.txt": "nada"})
    with pytest.raises(ValueError, match="não é do JARVIS"):
        up.apply_zip(other, root)
    evil = tmp_path / "mau.zip"
    make_zip(evil, "jarvis-hud/", {**NEW, "../../fora.txt": "x"})
    with pytest.raises(ValueError, match="suspeito"):
        up.apply_zip(evil, root)
    assert not (tmp_path / "fora.txt").exists() and (root / "backend/app/main.py").read_text() == "velho"   # nada trocado


def test_main_refuses_while_jarvis_is_open(monkeypatch, capsys):
    monkeypatch.setattr(up, "jarvis_running", lambda: True)
    assert up.main(["qualquer.zip"]) == 2 and "Feche-o antes" in capsys.readouterr().out
