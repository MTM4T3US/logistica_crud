"""Pareia a fechadura do usuário com o JARVIS (só trancar e ver o estado).

Uso:  .venv\\Scripts\\python scripts\\parear_fechadura.py http://IP-DA-FECHADURA
Gera um segredo novo, grava em backend/data/fechadura.json (fora do Git) e mostra o segredo UMA vez
para você gravar no firmware da fechadura. Protocolo: docs/FECHADURA.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.devices.own_lock import new_config  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].startswith(("http://", "https://")):
        print("Uso: parear_fechadura.py http://192.168.0.50   (o endereço da fechadura na sua rede)")
        return 2
    path = ROOT / "data" / "fechadura.json"
    if path.exists() and input("Já existe uma fechadura pareada. Gerar um segredo NOVO (o antigo para de valer)? (s/n) ").strip().lower() != "s":
        return 0
    cfg = new_config(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"\nPareamento salvo em {path}.")
    print("Grave este segredo no firmware da fechadura (constante JARVIS_SECRET_HEX) e não compartilhe:\n")
    print("   " + cfg["secret"] + "\n")
    print("Depois reinicie o INICIAR.bat e diga “a porta está trancada?”.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
