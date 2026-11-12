"""Dispositivos físicos planejados — nesta versão existem apenas interfaces e SIMULADORES.

Nenhum hardware é acionado. Todo resultado vindo daqui carrega `simulated=True`, e o
assistente é instruído a dizer isso ao usuário. As regras de segurança (fechadura, robô)
já valem para os simuladores, para que a integração real herde o mesmo contrato.
"""
from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceResult:
    ok: bool
    executed: bool
    message: str
    simulated: bool = True
    state: dict[str, Any] = field(default_factory=dict)


class Device(ABC):
    id: str
    name: str
    kind: str
    transport: str
    simulated: bool = True
    actions: tuple[str, ...] = ()

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    @abstractmethod
    def command(self, action: str, params: dict[str, Any]) -> DeviceResult: ...

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "transport": self.transport,
            "simulated": self.simulated, "connected": False, "actions": list(self.actions), "state": self.status(),
        }


class SimLedStrip(Device):
    """Fita DuoCo Strip / LotusLamp X — real: Bluetooth LE no Windows."""

    id, name, kind, transport = "leds", "Fita de LED", "led_strip", "Bluetooth LE"
    actions = ("on", "off", "color", "brightness")

    def __init__(self) -> None:
        self._s = {"on": False, "color": "#2b9bff", "brightness": 80}

    def status(self) -> dict[str, Any]:
        return dict(self._s)

    def command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        if action == "on":
            self._s["on"] = True
        elif action == "off":
            self._s["on"] = False
        elif action == "color":
            color = str(params.get("color", "")).strip()
            if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
                return DeviceResult(False, False, "Cor inválida: use o formato #RRGGBB.", state=self.status())
            self._s.update(on=True, color=color.lower())
            if params.get("brightness") is not None:
                try:
                    self._s["brightness"] = max(0, min(100, int(params["brightness"])))
                except (TypeError, ValueError):
                    return DeviceResult(False, False, "Brilho inválido: informe um valor de 0 a 100.", state=self.status())
        elif action == "brightness":
            try:
                self._s["brightness"] = max(0, min(100, int(params.get("value"))))
            except (TypeError, ValueError):
                return DeviceResult(False, False, "Brilho inválido: informe um valor de 0 a 100.", state=self.status())
        else:
            return DeviceResult(False, False, f"Ação '{action}' não existe para a fita de LED.", state=self.status())
        return DeviceResult(True, True, "Fita de LED atualizada no SIMULADOR (nenhum LED real foi acionado).", state=self.status())


class SimRollerBlind(Device):
    """Persiana com ESP32 + ESPHome — real: API na rede local."""

    id, name, kind, transport = "persiana", "Persiana", "roller_blind", "ESPHome (rede local)"
    actions = ("open", "close", "stop", "position")

    def __init__(self) -> None:
        self._s = {"position": 0, "moving": False}

    def status(self) -> dict[str, Any]:
        return dict(self._s)

    def command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        if action == "open":
            self._s["position"] = 100
        elif action == "close":
            self._s["position"] = 0
        elif action == "stop":
            self._s["moving"] = False
        elif action == "position":
            try:
                self._s["position"] = max(0, min(100, int(params.get("value"))))
            except (TypeError, ValueError):
                return DeviceResult(False, False, "Posição inválida: informe de 0 (fechada) a 100 (aberta).", state=self.status())
        else:
            return DeviceResult(False, False, f"Ação '{action}' não existe para a persiana.", state=self.status())
        return DeviceResult(True, True, "Persiana movida no SIMULADOR (nenhum motor real foi acionado).", state=self.status())


class SimLock(Device):
    """Fechadura ESP32. Destrancar NUNCA é possível por voz/IA: exige autenticação forte
    independente (ainda não implementada), registro de eventos e chave física de emergência."""

    id, name, kind, transport = "fechadura", "Fechadura", "lock", "ESP32 (rede local)"
    actions = ("status", "lock", "unlock")

    def __init__(self) -> None:
        self._s = {"locked": True}
        self.events: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        return dict(self._s)

    def _log(self, action: str, allowed: bool) -> None:
        self.events.append({"ts": time.time(), "action": action, "allowed": allowed})
        del self.events[:-100]

    def command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        if action == "status":
            self._log(action, True)
            return DeviceResult(True, True, "Estado lido do SIMULADOR da fechadura.", state=self.status())
        if action == "lock":
            self._s["locked"] = True
            self._log(action, True)
            return DeviceResult(True, True, "Fechadura trancada no SIMULADOR (nenhuma fechadura real foi acionada).", state=self.status())
        if action == "unlock":
            self._log(action, False)
            return DeviceResult(
                False, False,
                "Destrancar foi RECUSADO: comandos de voz ou da IA não podem abrir a fechadura. "
                "É necessária autenticação forte adicional, que ainda não existe nesta versão.",
                state=self.status(),
            )
        return DeviceResult(False, False, f"Ação '{action}' não existe para a fechadura.", state=self.status())


class SimRobot(Device):
    """Robô JARVIS (rodas, câmera, microfone, alto-falante). O contrato exige parada de
    emergência e parada automática ao perder comunicação (watchdog de heartbeat)."""

    id, name, kind, transport = "robo", "Robô JARVIS", "robot", "Wi-Fi (rede local)"
    actions = ("status", "move", "stop", "emergency_stop", "heartbeat", "reset_emergency")
    WATCHDOG_S = 1.5

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._s = {"moving": False, "direction": None, "speed": 0, "emergency": False, "stop_reason": None}
        self._last_beat = clock()

    def _watchdog(self) -> None:
        if self._s["moving"] and self._clock() - self._last_beat > self.WATCHDOG_S:
            self._s.update(moving=False, direction=None, speed=0, stop_reason="perda de comunicação")

    def status(self) -> dict[str, Any]:
        self._watchdog()
        return dict(self._s)

    def command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        self._watchdog()
        if action == "emergency_stop":
            self._s.update(moving=False, direction=None, speed=0, emergency=True, stop_reason="parada de emergência")
            return DeviceResult(True, True, "PARADA DE EMERGÊNCIA aplicada no SIMULADOR do robô.", state=self.status())
        if action == "reset_emergency":
            self._s.update(emergency=False, stop_reason=None)
            return DeviceResult(True, True, "Emergência liberada no SIMULADOR do robô.", state=self.status())
        if action == "heartbeat":
            self._last_beat = self._clock()
            return DeviceResult(True, True, "Heartbeat recebido pelo SIMULADOR.", state=self.status())
        if action == "status":
            return DeviceResult(True, True, "Estado lido do SIMULADOR do robô.", state=self.status())
        if action == "stop":
            self._s.update(moving=False, direction=None, speed=0, stop_reason="comando")
            return DeviceResult(True, True, "Robô parado no SIMULADOR.", state=self.status())
        if action == "move":
            if self._s["emergency"]:
                return DeviceResult(False, False, "Movimento recusado: a parada de emergência está ativa.", state=self.status())
            direction = str(params.get("direction", ""))
            if direction not in {"forward", "backward", "left", "right"}:
                return DeviceResult(False, False, "Direção inválida: forward, backward, left ou right.", state=self.status())
            try:
                speed = max(1, min(100, int(params.get("speed", 30))))
            except (TypeError, ValueError):
                speed = 30
            self._last_beat = self._clock()
            self._s.update(moving=True, direction=direction, speed=speed, stop_reason=None)
            return DeviceResult(True, True, "Robô em movimento no SIMULADOR (nenhum motor real foi acionado).", state=self.status())
        return DeviceResult(False, False, f"Ação '{action}' não existe para o robô.", state=self.status())


class DeviceRegistry:
    def __init__(self, simulators: bool = True, leds: Device | None = None, leds_off: bool = False) -> None:
        """`leds`: driver real (ex.: ElkBleddmLeds) no lugar do simulador; `leds_off`: sem LEDs."""
        self._devices: dict[str, Device] = {}
        if leds is not None:
            self.register(leds)
        elif simulators and not leds_off:
            self.register(SimLedStrip())
        if simulators:
            for dev in (SimRollerBlind(), SimLock(), SimRobot()):
                self.register(dev)

    def register(self, device: Device) -> None:
        self._devices[device.id] = device

    def ids(self) -> list[str]:
        return list(self._devices)

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def describe(self) -> list[dict[str, Any]]:
        return [d.describe() for d in self._devices.values()]

    async def command(self, device_id: str, action: str, params: dict[str, Any] | None = None) -> DeviceResult:
        dev = self.get(device_id)
        if dev is None:
            return DeviceResult(False, False, f"Dispositivo '{device_id}' não está cadastrado.", simulated=False)
        if action not in dev.actions:
            return DeviceResult(False, False, f"Ação '{action}' não existe para {dev.name}.", simulated=dev.simulated, state=dev.status())
        res = dev.command(action, params or {})
        if inspect.isawaitable(res):   # drivers reais (Bluetooth, rede) são assíncronos
            res = await res
        res.simulated = dev.simulated
        return res
