"""Luzes de casa Smart Life / Tuya, controladas PELA REDE LOCAL (sem nuvem), com a biblioteca tinytuya (MIT).

Configuração (uma vez, pelo CONFIGURAR_LUZES.bat): o assistente do tinytuya obtém a "chave local" de cada
aparelho e grava `backend/data/tuya/devices.json` (fica fora do Git: tem segredos). Depois disso, o JARVIS
fala direto com cada lâmpada/interruptor pelo Wi-Fi de casa.

Diferente da fita ELK-BLEDDM, o aparelho Tuya RESPONDE: quando ele devolve o novo estado, o resultado sai
com `confirmed: True`. Se não responder, o JARVIS diz que não conseguiu — nunca "finge" que acendeu.
"""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

from .registry import Device, DeviceResult

LIGHT_CATS = {"dj": "lâmpada", "dd": "fita de luz", "xdd": "luz de teto", "fwd": "luz ambiente", "dc": "cordão de luz", "tgq": "dimmer",
              "tgkg": "dimmer", "fsd": "ventilador com luz", "gyd": "luz com sensor"}
SWITCH_CATS = {"kg": "interruptor", "cz": "tomada", "pc": "filtro de linha", "tdq": "disjuntor", "dlq": "disjuntor"}


def slug(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_") or "luz"


def load_devices(path: Path) -> list[dict[str, Any]]:
    """Lê o devices.json do assistente do tinytuya; fica só com luzes, interruptores e tomadas."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        cat = str(d.get("category", ""))
        if not d.get("id") or not d.get("key") or (cat not in LIGHT_CATS and cat not in SWITCH_CATS):
            continue
        out.append({"id": str(d["id"]), "key": str(d["key"]), "name": str(d.get("name") or d.get("product_name") or "Luz"),
                    "ip": str(d.get("ip") or ""), "version": str(d.get("version") or "3.3"), "category": cat})
    return out


def _real_factory(info: dict[str, Any]) -> Any:  # pragma: no cover — precisa da rede de casa
    import tinytuya

    cls = tinytuya.BulbDevice if info["category"] in LIGHT_CATS else tinytuya.OutletDevice
    dev = cls(dev_id=info["id"], address=info["ip"] or "Auto", local_key=info["key"], version=float(info["version"] or 3.3))
    dev.set_socketTimeout(3)
    dev.set_socketRetryLimit(1)
    return dev


class TuyaLight(Device):
    transport = "Wi-Fi local (Tuya)"
    simulated = False

    def __init__(self, info: dict[str, Any], factory: Callable[[dict[str, Any]], Any] = _real_factory, used_ids: set[str] | None = None):
        self.info = info
        self.name = info["name"]
        base = "luz_" + slug(self.name)
        dev_id, n = base, 2
        while used_ids is not None and dev_id in used_ids:
            dev_id, n = f"{base}_{n}", n + 1
        if used_ids is not None:
            used_ids.add(dev_id)
        self.id = dev_id
        self.bulb = info["category"] in LIGHT_CATS
        self.kind = "light" if self.bulb else "switch"
        self.actions = ("status", "on", "off", "color", "brightness", "white") if self.bulb else ("status", "on", "off")
        self._factory = factory
        self._dev: Any = None
        self._state: dict[str, Any] = {"on": None, "reachable": None}
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {**self._state, "category": LIGHT_CATS.get(self.info["category"]) or SWITCH_CATS.get(self.info["category"], "")}

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        d["connected"] = bool(self._state.get("reachable"))
        return d

    def _device(self) -> Any:
        if self._dev is None:
            self._dev = self._factory(self.info)
        return self._dev

    @staticmethod
    def _error(resp: Any) -> str | None:
        if resp is None:
            return "sem resposta"
        if isinstance(resp, dict) and ("Error" in resp or "Err" in resp):
            return str(resp.get("Error") or resp.get("Err"))
        return None

    def _call(self, fn: str, *args: Any) -> tuple[bool, Any]:
        try:
            resp = getattr(self._device(), fn)(*args)
        except Exception as exc:          # aparelho fora da rede, chave errada, IP mudou…
            self._dev = None
            return False, f"{type(exc).__name__}: {exc}"
        err = self._error(resp)
        return (err is None), (err or resp)

    async def command(self, action: str, params: dict[str, Any]) -> DeviceResult:  # type: ignore[override]
        async with self._lock:
            return await asyncio.to_thread(self._command, action, params)

    def _command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        if action == "status":
            ok, resp = self._call("status")
            if ok and isinstance(resp, dict):
                dps = resp.get("dps", {})
                on = dps.get("20", dps.get("1"))
                self._state.update(on=bool(on) if on is not None else None, reachable=True)
                return DeviceResult(True, True, f"{self.name}: {'ligada' if on else 'desligada'}.", simulated=False, state=self.status())
            self._state["reachable"] = False
            return DeviceResult(False, False, f"{self.name} não respondeu ({resp}). Está ligada na tomada e no Wi-Fi?", simulated=False, state=self.status())
        if action in ("on", "off"):
            ok, resp = self._call("turn_on" if action == "on" else "turn_off")
            label = "ligada" if action == "on" else "desligada"
            if ok:
                self._state.update(on=action == "on", reachable=True)
        elif action == "color":
            m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(params.get("color", "")))
            if not m:
                return DeviceResult(False, False, "Cor inválida: use #RRGGBB.", simulated=False, state=self.status())
            h = m.group(1)
            ok, resp = self._call("set_colour", int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            label = f"na cor #{h.lower()}"
            if ok:
                self._state.update(on=True, color="#" + h.lower(), reachable=True)
        elif action == "brightness":
            value = max(1, min(100, int(params.get("value", 100))))
            ok, resp = self._call("set_brightness_percentage", value)
            label = f"com brilho {value}%"
            if ok:
                self._state.update(on=True, brightness=value, reachable=True)
        elif action == "white":
            value = max(1, min(100, int(params.get("value", 100))))
            ok, resp = self._call("set_white_percentage", value, int(params.get("temp", 50)))
            label = "em luz branca"
            if ok:
                self._state.update(on=True, color="branca", brightness=value, reachable=True)
        else:
            return DeviceResult(False, False, f"Ação '{action}' não existe para {self.name}.", simulated=False, state=self.status())
        if not ok:
            self._state["reachable"] = False
            return DeviceResult(False, False, f"{self.name} não respondeu ({resp}).", simulated=False, state=self.status())
        return DeviceResult(True, True, f"{self.name} {label} (confirmado pelo aparelho).", simulated=False, state={**self.status(), "confirmed": True})


def build_lights(path: Path, factory: Callable[[dict[str, Any]], Any] | None = None) -> tuple[list[TuyaLight], str]:
    """Aparelhos do devices.json e uma explicação do estado (para o painel)."""
    infos = load_devices(path)
    if not infos:
        return [], "Nenhuma luz Tuya configurada (rode CONFIGURAR_LUZES.bat)."
    if factory is None:
        try:
            import tinytuya  # noqa: F401
        except ImportError:
            return [], "Biblioteca tinytuya não instalada (rode CONFIGURAR_LUZES.bat)."
        factory = _real_factory
    used: set[str] = set()
    return [TuyaLight(i, factory, used) for i in infos], f"{len(infos)} aparelho(s) Tuya na rede local."
