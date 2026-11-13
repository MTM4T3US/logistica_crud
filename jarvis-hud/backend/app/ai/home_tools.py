"""Luzes de casa (Tuya) junto com a fita de LED: "apaga as luzes", "luz da sala em azul", "luzes a 30%"."""
from __future__ import annotations

import asyncio
import re
from typing import Any

from ..devices.registry import DeviceRegistry
from ..devices.tuya import TuyaLight, slug
from ..security.permissions import ActionClass
from .base import ToolOutcome


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


class HomeTools:
    def __init__(self, devices: DeviceRegistry):
        self.devices = devices

    def lights(self) -> list[TuyaLight]:
        return [d for d in (self.devices.get(i) for i in self.devices.ids()) if isinstance(d, TuyaLight)]

    def match(self, spoken: str) -> list[TuyaLight]:
        """Aparelhos cujo nome contém as palavras ditas ("sala", "quarto do fundo")."""
        words = [w for w in slug(spoken).split("_") if len(w) > 2 and w not in ("luz", "luzes", "lampada", "lampadas", "das", "dos", "the")]
        if not words:
            return []
        return [d for d in self.lights() if all(w in slug(d.name) for w in words)]

    def specs(self) -> list[Any]:
        from .tools import ToolSpec

        lights = self.lights()
        if not lights:
            return []
        names = "; ".join(f"{d.id} = {d.name}" for d in lights)
        return [ToolSpec(
            "house_lights", "Luzes de casa",
            f"Controla as luzes reais de casa (Tuya, rede local; o aparelho confirma): {names}. target = 'todas' (casa + fita LED), "
            "'casa' (só as de casa) ou o id de uma luz. Use power (on/off), color (#RRGGBB), brightness (1-100) ou white=true.",
            _obj({"target": {"type": "string", "enum": ["todas", "casa", *[d.id for d in lights]]}, "power": {"type": "string", "enum": ["on", "off"]},
                  "color": {"type": "string", "maxLength": 7}, "brightness": {"type": "integer", "minimum": 1, "maximum": 100}, "white": {"type": "boolean"}},
                 ["target"]),
            ActionClass.SAFE, self._run)]

    async def _run(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        target = args["target"]
        house = self.lights() if target in ("todas", "casa") else [d for d in self.lights() if d.id == target]
        with_led = target == "todas" and self.devices.get("leds") is not None
        if not house and not with_led:
            return ToolOutcome(run.call, False, False, "Nenhuma luz com esse nome.")
        steps: list[tuple[str, dict[str, Any]]] = []
        if args.get("power") == "off":
            steps = [("off", {})]
        else:
            if args.get("color") and re.fullmatch(r"#?[0-9a-fA-F]{6}", args["color"]):
                steps.append(("color", {"color": "#" + args["color"].lstrip("#")}))
            elif args.get("white"):
                steps.append(("white", {"value": args.get("brightness", 100)}))
            elif args.get("power") == "on" or not args.get("brightness"):
                steps.append(("on", {}))
            if args.get("brightness") and not args.get("white"):
                steps.append(("brightness", {"value": args["brightness"]}))

        async def one(dev_id: str, is_led: bool) -> list[Any]:
            out = []
            for action, params in steps:
                if is_led:
                    action, params = {"white": ("color", {"color": "#ffffff"})}.get(action, (action, params))
                    if action == "brightness":
                        params = {"value": params["value"]}
                dev = self.devices.get(dev_id)
                if dev is None or action not in dev.actions:
                    continue
                res = await self.devices.command(dev_id, action, params)
                out.append((dev, res))
                if not res.executed:
                    break
            return out

        jobs = [one(d.id, False) for d in house] + ([one("leds", True)] if with_led else [])
        results = [r for group in await asyncio.gather(*jobs) for r in group]
        await run.notify({"type": "devices", "devices": self.devices.describe()})
        failed = [(d, r) for d, r in results if not r.executed]
        done = {d.name for d, r in results if r.executed} - {d.name for d, _ in failed}
        parts = []
        if done:
            confirmed = [n for n in done if any(d.name == n and isinstance(d, TuyaLight) for d, _ in results)]
            others = [n for n in done if n not in confirmed]
            if confirmed:
                parts.append(f"{', '.join(sorted(confirmed))}: feito (confirmado pelos aparelhos).")
            if others:
                parts.append(f"{', '.join(sorted(others))}: comando enviado (a fita não confirma).")
        for d, r in failed:
            parts.append(r.message)
        ok = bool(done)
        return ToolOutcome(run.call, ok, ok, " ".join(parts) or "Nada a fazer.",
                           data={"confirmed": not failed and all(isinstance(d, TuyaLight) for d, _ in results), "failed": [d.name for d, _ in failed]})
