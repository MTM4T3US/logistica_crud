"""Configura as luzes Smart Life / Tuya para o JARVIS controlar PELA REDE LOCAL (uma vez só).

Uso:  .venv\\Scripts\\python scripts\\configurar_luzes.py [--testar]

O controle local precisa da "chave local" de cada aparelho. Quem a fornece é a nuvem da Tuya, uma única
vez, pelo assistente do tinytuya (biblioteca MIT). Depois, o JARVIS fala direto com as lâmpadas pelo Wi-Fi
de casa, mesmo sem internet. As chaves ficam em backend/data/tuya/ (fora do Git) e nunca são mostradas.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FOLDER = ROOT / "data" / "tuya"

PASSOS = """
=== Luzes Smart Life / Tuya — preparação (uma vez) ===

1. Entre em https://iot.tuya.com e crie uma conta gratuita (pode ser com o mesmo e-mail do Smart Life).
2. Cloud → Development → Create Cloud Project:
     - Industry: Smart Home · Development Method: Smart Home
     - Data Center: "Western America Data Center" (é o das contas do Brasil; se não achar
       os aparelhos depois, tente "Eastern America")
3. No projeto: Devices → Link App Account → Add App Account → aparece um QR code.
   No celular, app Smart Life → Eu (Me) → ícone de leitor no topo → leia o QR. Os aparelhos aparecem na lista.
4. Overview: copie o "Access ID/Client ID" e o "Access Secret/Client Secret".
   Anote também o "Device ID" de qualquer um dos aparelhos.
5. A seguir, o assistente do tinytuya vai pedir esses dados (cole com o botão direito no terminal).
   Quando perguntar se deve procurar os aparelhos na rede ("Poll local devices?"), responda Y.

Observação: o plano gratuito "IoT Core" da Tuya expira de tempos em tempos; ele só é necessário para
buscar as chaves de novo (ex.: se você reconfigurar uma lâmpada no app). O controle local do JARVIS
continua funcionando sem ele.
"""


def main() -> int:
    try:
        import tinytuya  # noqa: F401
    except ImportError:
        print("Falta a biblioteca tinytuya. Rode CONFIGURAR_LUZES.bat (ele instala) ou: pip install tinytuya")
        return 2
    FOLDER.mkdir(parents=True, exist_ok=True)
    devices = FOLDER / "devices.json"
    if not devices.exists() or "--refazer" in sys.argv:
        print(PASSOS)
        input("Pressione Enter quando tiver o Access ID, o Access Secret e um Device ID… ")
        # o assistente grava devices.json, tinytuya.json (credenciais da nuvem) e snapshot.json NESTA pasta
        code = subprocess.call([sys.executable, "-m", "tinytuya", "wizard"], cwd=FOLDER)
        if code != 0 or not devices.exists():
            print("O assistente não terminou. Rode de novo quando quiser.")
            return 1
    from app.devices.tuya import LIGHT_CATS, SWITCH_CATS, load_devices

    raw = json.loads(devices.read_text(encoding="utf-8-sig"))
    found = load_devices(devices)
    print(f"\n{len(raw)} aparelho(s) na conta; {len(found)} são luzes, interruptores ou tomadas:")
    for d in found:
        kind = LIGHT_CATS.get(d["category"]) or SWITCH_CATS.get(d["category"])
        print(f"  - {d['name']}  ({kind}; {'IP ' + d['ip'] if d['ip'] else 'IP será procurado na rede'}; protocolo {d['version']})")
    if not found:
        print("Nenhuma luz encontrada. Os aparelhos aparecem no app Smart Life? A conta foi vinculada ao projeto (passo 3)?")
        return 1
    if "--testar" in sys.argv:
        from app.devices.tuya import TuyaLight, _real_factory

        if input("\nPiscar cada luz uma vez para conferir (desliga e liga)? (s/n) ").strip().lower().startswith("s"):
            for info in found:
                light = TuyaLight(info, _real_factory)
                for action in ("off", "on"):
                    res = light._command(action, {})
                    print(f"  {info['name']}: {res.message}")
                    time.sleep(1.2)
    print("\nPronto. Reinicie o INICIAR.bat: as luzes aparecem em DISPOSITIVOS e respondem a “apaga as luzes”, “luz da sala em azul”…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
