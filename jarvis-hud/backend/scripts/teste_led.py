"""Teste direto da fita de LED ELK-BLEDDM, sem o núcleo do JARVIS.

Segue o mesmo caminho dos scripts que já funcionaram (led_test_blue.py / led_bridge.py):
BleakClient(endereço, timeout=15) → espera 0,5 s → escrita sem resposta na característica FFF3.
Os bytes vêm do driver do JARVIS (app/devices/elk_bleddm.py), então este teste valida o driver.

Uso:  .venv\\Scripts\\python scripts\\teste_led.py [--endereco BE:27:53:00:BC:1B] [--completo] [--perguntar] [--pausa 3]
  sem --endereco   procura por 10 s uma fita cujo nome começa com ELK-BLEDDM e usa a de sinal mais forte
  (padrão)         ligar → azul → desligar (os três comandos já validados fisicamente)
  --completo       ligar → azul → vermelho → verde → branco → branco 30 % → azul → desligar
  --perguntar      pergunta, depois de cada passo, se a fita mudou (registra no relatório)

A fita NÃO confirma o recebimento: "enviado" quer dizer só que a escrita Bluetooth terminou sem erro.
Só quem olha a fita pode dizer se funcionou. Relatório: backend/data/teste-led-AAAAMMDD-HHMMSS.md
"""
from __future__ import annotations

import argparse
import asyncio
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.devices.elk_bleddm import CONNECT_SETTLE_S, WRITE_UUID, cmd_color, cmd_power, scale  # noqa: E402

lines: list[str] = []


def out(text: str = "") -> None:
    print(text, flush=True)
    lines.append(text)


BASICO = [("Ligar", cmd_power(True)), ("Azul", cmd_color(0, 0, 255)), ("Desligar", cmd_power(False))]
COMPLETO = [
    ("Ligar", cmd_power(True)), ("Azul", cmd_color(0, 0, 255)), ("Vermelho", cmd_color(255, 0, 0)),
    ("Verde", cmd_color(0, 255, 0)), ("Branco", cmd_color(255, 255, 255)),
    ("Branco a 30 % (cor escurecida)", cmd_color(*scale((255, 255, 255), 30))), ("Azul", cmd_color(0, 0, 255)),
    ("Desligar", cmd_power(False)),
]


async def find(prefix: str) -> str | None:
    from bleak import BleakScanner

    out(f"Procurando fitas “{prefix}” por 10 s…")
    found = await BleakScanner.discover(timeout=10.0, return_adv=True)
    hits = []
    for device, adv in found.values():
        name = device.name or adv.local_name or ""
        if name.upper().startswith(prefix.upper()):
            hits.append((adv.rssi, device.address, name))
    if not hits:
        out(f"Nenhuma fita “{prefix}” encontrada ({len(found)} aparelhos BLE por perto). Ela está ligada? O app do celular está fechado?")
        return None
    for rssi, addr, name in sorted(hits, reverse=True):
        out(f"  {name}  {addr}  sinal {rssi} dBm")
    return sorted(hits, reverse=True)[0][1]


async def run(args: argparse.Namespace) -> int:
    from bleak import BleakClient

    try:
        address = args.endereco or await find(args.prefixo)
    except Exception as exc:
        out(f"FALHA ao procurar: {type(exc).__name__}: {exc}")
        out("O Bluetooth do Windows está ligado? Este PC tem adaptador Bluetooth LE?")
        return 1
    if not address:
        return 2
    out(f"Conectando a {address} (timeout 15 s)…")
    t0 = time.perf_counter()
    try:
        async with BleakClient(address, timeout=15.0) as client:
            out(f"Conectado em {time.perf_counter() - t0:.1f} s.")
            await asyncio.sleep(CONNECT_SETTLE_S)
            chars = [(c.uuid, ",".join(c.properties)) for s in client.services for c in s.characteristics]
            fff3 = [p for u, p in chars if u.lower() == WRITE_UUID]
            out(f"Característica de escrita {WRITE_UUID}: " + (f"presente ({fff3[0]})" if fff3 else "AUSENTE — este aparelho usa outro protocolo"))
            if args.inspecionar or not fff3:
                for u, p in chars:
                    out(f"  {u}  {p}")
            if not fff3:
                return 3
            for i, (name, data) in enumerate(COMPLETO if args.completo else BASICO, 1):
                await client.write_gatt_char(WRITE_UUID, data, response=False)
                out(f"[{time.strftime('%H:%M:%S')}] {i}. Enviado: {name}  ({data.hex(' ')})")
                if args.perguntar:
                    answer = (await asyncio.to_thread(input, "     A fita mudou como esperado? (s/n) ")).strip().lower()
                    out(f"     Resposta do usuário: {'SIM' if answer.startswith('s') else 'NÃO'}")
                else:
                    await asyncio.sleep(args.pausa)
    except Exception as exc:  # a mensagem do bleak explica (fora de alcance, ocupada pelo celular, Bluetooth desligado…)
        out(f"FALHA: {type(exc).__name__}: {exc}")
        out("Verifique: fita ligada e perto; app do celular (LotusLamp X) desconectado; Bluetooth do Windows ligado.")
        return 1
    out("Conexão encerrada. Lembrete: a fita não confirma o recebimento — vale o que você viu.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endereco", help="endereço Bluetooth da fita (ex.: BE:27:53:00:BC:1B)")
    ap.add_argument("--prefixo", default="ELK-BLEDDM")
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--perguntar", action="store_true")
    ap.add_argument("--inspecionar", action="store_true", help="lista todas as características GATT")
    ap.add_argument("--pausa", type=float, default=3.0)
    args = ap.parse_args()
    out(f"# Teste da fita de LED — {time.strftime('%d/%m/%Y %H:%M:%S')}")
    out(f"Python {platform.python_version()} · {platform.platform()}")
    try:
        import bleak

        from importlib.metadata import version

        out(f"bleak {getattr(bleak, '__version__', None) or version('bleak')}")
    except ImportError:
        out("bleak não instalado: rode INSTALAR_RECURSOS_LOCAIS.bat (ou pip install bleak).")
        return 4
    code = asyncio.run(run(args))
    folder = ROOT / "data"
    folder.mkdir(exist_ok=True)
    path = folder / f"teste-led-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nRelatório salvo em {path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
