"""Driver real das fitas de LED com controlador ELK-BLEDDM (Bluetooth LE), via bleak.

Protocolo (comandos de 9 bytes, escritos sem resposta na característica FFF3):

    ligar      7e 04 04 f0 00 01 ff 00 ef     validado fisicamente pelo usuário
    desligar   7e 04 04 00 00 00 ff 00 ef     validado fisicamente pelo usuário
    cor        7e 00 05 03 RR GG BB 00 ef     validado com azul (00 00 ff); outras cores não testadas
    brilho     7e 04 01 BB ff 00 ff 00 ef     NÃO validado (só na referência pública dave-code-ruiz/elkbledom, MIT)

Os três primeiros coincidem com os scripts do usuário (led_test_blue.py / led_bridge.py), que
funcionaram na fita BE:27:53:00:BC:1B: conectar com timeout de 15 s, esperar 0,5 s, escrever com
`response=False`. Por padrão o brilho é feito escurecendo a cor (comando de cor, já validado); o
comando de brilho próprio só é usado com JARVIS_LED_BRILHO=comando.

O controlador NÃO confirma o recebimento. Por isso todo resultado deste driver diz
"comando enviado" com `confirmed: False` — nunca afirma que a luz mudou.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Awaitable, Callable

from .registry import Device, DeviceResult

WRITE_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
#: o ELK-BLEDDM descarta um comando que chega cedo demais depois do anterior
SETTLE_S = 0.3
#: espera depois de conectar, antes do primeiro comando (como nos scripts que funcionaram)
CONNECT_SETTLE_S = 0.5
CONNECT_ATTEMPTS = (0.0, 1.5, 4.0)       # esperas antes de cada tentativa (reconexão controlada)
CONNECT_BUDGET_S = 25.0                  # prazo total para conectar (todas as tentativas juntas)
IDLE_DISCONNECT_S = 300.0                # solta a fita depois de 5 min parada (o app do celular volta a funcionar)


def cmd_power(on: bool) -> bytes:
    return bytes([0x7E, 0x04, 0x04, 0xF0, 0x00, 0x01, 0xFF, 0x00, 0xEF]) if on else bytes([0x7E, 0x04, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00, 0xEF])


def cmd_color(r: int, g: int, b: int) -> bytes:
    return bytes([0x7E, 0x00, 0x05, 0x03, r & 0xFF, g & 0xFF, b & 0xFF, 0x00, 0xEF])


def cmd_brightness(percent: int) -> bytes:
    return bytes([0x7E, 0x04, 0x01, max(0, min(100, int(percent))), 0xFF, 0x00, 0xFF, 0x00, 0xEF])


def scale(rgb: tuple[int, int, int], percent: int) -> tuple[int, int, int]:
    """Brilho emulado: a mesma cor, escurecida (usa só o comando de cor, que é validado)."""
    p = max(0, min(100, int(percent)))
    return tuple(round(c * p / 100) for c in rgb)  # type: ignore[return-value]


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def parse_hex(color: str) -> tuple[int, int, int] | None:
    c = (color or "").strip().lower()
    if len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdef" for ch in c[1:]):
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    return None


class BleTransport:
    """O que o driver precisa do Bluetooth. Trocável por um dublê nos testes."""

    async def scan(self, name_prefix: str, timeout: float) -> list[dict[str, Any]]: ...
    async def connect(self, address: str, on_disconnect: Callable[[], None]) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...


class _BleLoop:  # pragma: no cover — exige adaptador Bluetooth
    """Loop asyncio próprio para o Bluetooth, numa thread só dele.

    No Windows o bleak (WinRT) exige uma thread em MTA. Bibliotecas COM usadas pelo núcleo
    (pycaw/comtypes para o volume, SAPI para a voz do sistema) põem a thread em que rodam em STA,
    e aí o bleak falha com "Thread is configured for Windows GUI…". Isolar o Bluetooth evita isso."""

    _shared: "_BleLoop | None" = None
    _guard = threading.Lock()

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="jarvis-bluetooth", daemon=True).start()

    @classmethod
    def shared(cls) -> "_BleLoop":
        with cls._guard:
            if cls._shared is None:
                cls._shared = cls()
            return cls._shared

    async def run(self, coro: Any) -> Any:
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, self.loop))


class BleakTransport(BleTransport):  # pragma: no cover — exige adaptador Bluetooth
    def __init__(self) -> None:
        self._client: Any = None
        self._loop: _BleLoop | None = None

    @property
    def _ble(self) -> _BleLoop:
        # criado só no 1º uso: uma falha do Windows ao abrir o loop (visto uma vez: WinError 10013 em
        # socket.socketpair) vira erro da fita, em vez de derrubar o núcleo na inicialização
        if self._loop is None:
            self._loop = _BleLoop.shared()
        return self._loop

    async def scan(self, name_prefix: str, timeout: float) -> list[dict[str, Any]]:
        async def go() -> list[dict[str, Any]]:
            from bleak import BleakScanner

            found = await BleakScanner.discover(timeout=timeout, return_adv=True)
            out = []
            for device, adv in found.values():
                name = device.name or adv.local_name or ""
                if name.upper().startswith(name_prefix.upper()):
                    out.append({"address": device.address, "name": name, "rssi": adv.rssi})
            return sorted(out, key=lambda d: d["rssi"], reverse=True)

        return await self._ble.run(go())

    async def connect(self, address: str, on_disconnect: Callable[[], None]) -> None:
        main = asyncio.get_running_loop()

        async def go() -> None:
            from bleak import BleakClient

            # o aviso de desconexão chega na thread do Bluetooth; o estado é tratado no loop principal
            self._client = BleakClient(address, disconnected_callback=lambda _c: main.call_soon_threadsafe(on_disconnect), timeout=15.0)
            await self._client.connect()

        await self._ble.run(go())

    async def write(self, data: bytes) -> None:
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("não conectado")
        client = self._client
        await self._ble.run(client.write_gatt_char(WRITE_UUID, data, response=False))

    async def disconnect(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await self._ble.run(client.disconnect())

    @property
    def connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected)


class ElkBleddmLeds(Device):
    id, name, kind = "leds", "Fita de LED", "led_strip"
    transport = "Bluetooth LE (ELK-BLEDDM)"
    simulated = False
    actions = ("status", "on", "off", "color", "brightness", "connect", "disconnect", "scan")

    def __init__(self, address: str | None = None, name_prefix: str = "ELK-BLEDDM", transport: BleTransport | None = None,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                 brightness_mode: str = "cor"):
        self.address = address
        self.name_prefix = name_prefix
        self.t = transport or BleakTransport()
        #: "cor" (padrão): brilho = cor escurecida, só comandos validados · "comando": 7e 04 01 (não validado)
        self.brightness_mode = "comando" if brightness_mode == "comando" else "cor"
        self._base = (255, 255, 255)          # cor pedida, em 100 %
        self._level = 100                      # brilho pedido
        self._sleep, self._clock = sleep, clock
        self._lock = asyncio.Lock()
        self._last_write = 0.0
        self._last_use = 0.0
        self.link = "desconectado"           # desconectado | procurando | conectando | conectado | falha
        self.last_error: str | None = None
        #: o que o JARVIS ENVIOU por último — não é leitura do aparelho
        self.sent: dict[str, Any] = {"on": None, "color": None, "brightness": None, "at": None}
        self._idle_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ estado
    def status(self) -> dict[str, Any]:
        return {"link": self.link, "address": self.address, "last_error": self.last_error, "sent": dict(self.sent),
                "confirmed": False, "brightness_mode": self.brightness_mode}

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        d["connected"] = self.link == "conectado"
        return d

    def _on_disconnect(self) -> None:
        if self.link == "conectado":
            self.link = "desconectado"
            self.last_error = "a fita encerrou a conexão Bluetooth"

    # ------------------------------------------------------------------ conexão
    async def _ensure(self) -> str | None:
        """Conecta se preciso, com até 3 tentativas espaçadas. Devolve o erro ou None."""
        if self.t.connected:
            self.link = "conectado"
            return None
        if not self.address:
            self.link = "procurando"
            try:
                found = await self.t.scan(self.name_prefix, 8.0)
            except Exception as exc:
                self.link, self.last_error = "falha", f"Bluetooth indisponível ({type(exc).__name__}: {exc})."
                return self.last_error
            if not found:
                self.link, self.last_error = "falha", f"Nenhuma fita “{self.name_prefix}” encontrada por perto. Ela está ligada e fora do app do celular?"
                return self.last_error
            self.address = found[0]["address"]
        # prazo TOTAL para conectar: sem ele, com a fita fora da tomada, cada tentativa do bleak levava
        # ~25 s e o comando só falhava depois de 82 s (medido no Windows)
        deadline = self._clock() + CONNECT_BUDGET_S
        last, not_found, tries = "", False, 0
        for wait in CONNECT_ATTEMPTS:
            if wait:
                await self._sleep(min(wait, max(0.0, deadline - self._clock())))
            left = deadline - self._clock()
            if left < 1.0:
                break
            self.link = "conectando"
            tries += 1
            try:
                await asyncio.wait_for(self.t.connect(self.address, self._on_disconnect), timeout=left)
                self.link, self.last_error = "conectado", None
                await self._sleep(CONNECT_SETTLE_S)
                return None
            except asyncio.TimeoutError as exc:
                if deadline - self._clock() < 1.0:   # acabou o prazo total
                    last = f"sem resposta em {CONNECT_BUDGET_S:.0f} s"
                    break
                last = f"{type(exc).__name__}: {exc}"   # só esta tentativa expirou: tenta de novo
            except Exception as exc:
                not_found = not_found or "NotFound" in type(exc).__name__
                last = f"{type(exc).__name__}: {exc}"
        self.link = "falha"
        if not_found or last.startswith("sem resposta"):
            why = last if last.startswith("sem resposta") else "não foi encontrada pelo Bluetooth"
            self.last_error = f"A fita de LED não respondeu ({why}). Ela está na tomada, por perto e desconectada do app do celular?"
        else:
            self.last_error = f"Não consegui conectar à fita {self.address} depois de {tries} {'tentativa' if tries == 1 else 'tentativas'} ({last})."
        return self.last_error

    async def _send(self, packets: list[bytes], settle: float = SETTLE_S) -> str | None:
        err = await self._ensure()
        if err:
            return err
        try:
            for data in packets:
                gap = settle - (self._clock() - self._last_write)
                if gap > 0:
                    await self._sleep(gap)
                await self.t.write(data)
                self._last_write = self._clock()
        except Exception as exc:
            self.link = "falha" if not self.t.connected else self.link
            self.last_error = f"Falha ao enviar à fita ({type(exc).__name__}: {exc})."
            return self.last_error
        self._last_use = self._clock()
        self._schedule_idle()
        return None

    def _schedule_idle(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        try:
            self._idle_task = asyncio.get_running_loop().create_task(self._idle_release())
        except RuntimeError:
            self._idle_task = None

    async def _idle_release(self) -> None:
        await asyncio.sleep(IDLE_DISCONNECT_S)
        if self._clock() - self._last_use >= IDLE_DISCONNECT_S - 1:
            async with self._lock:
                await self.t.disconnect()
                self.link = "desconectado"

    # ------------------------------------------------------------------ efeitos (voz, abertura)
    async def effect_frame(self, rgb: tuple[int, int, int], power: bool = False, settle: float = SETTLE_S) -> bool:
        """Um quadro de efeito. Nunca entra na fila: se a fita estiver ocupada (comando do usuário em
        andamento) ou desconectada, o quadro é descartado — o efeito não atrasa comando nenhum.
        Não altera `sent` (o estado escolhido pelo usuário)."""
        if self._lock.locked() or not self.t.connected:
            return False
        async with self._lock:
            packets = ([cmd_power(True)] if power else []) + [cmd_color(*rgb)]
            return await self._send(packets, settle) is None

    def chosen(self) -> tuple[bool, tuple[int, int, int], int] | None:
        """Último estado pedido pelo usuário (ligada?, cor base, brilho) — None se nada foi pedido."""
        if self.sent.get("on") is None:
            return None
        return bool(self.sent["on"]), self._base, self._level

    async def restore(self, default: tuple[tuple[int, int, int], int]) -> bool:
        """Volta ao estado escolhido pelo usuário depois de um efeito (ou ao `default`, cor+brilho,
        se ele nunca escolheu nada). Espera a fila: este comando não pode se perder."""
        state = self.chosen()
        async with self._lock:
            if state is not None and not state[0]:
                return await self._send([cmd_power(False)]) is None
            rgb, level = (state[1], state[2]) if state is not None else default
            return await self._send([cmd_color(*scale(rgb, level))]) is None

    def adopt(self, rgb: tuple[int, int, int], level: int) -> None:
        """Registra uma cor como escolhida (ex.: o efeito de abertura termina no Azul JARVIS)."""
        self._base, self._level = rgb, max(0, min(100, int(level)))
        self.sent.update(on=True, color=to_hex(rgb), brightness=self._level, at=time.time())

    # ------------------------------------------------------------------ comandos
    async def command(self, action: str, params: dict[str, Any]) -> DeviceResult:  # type: ignore[override]
        async with self._lock:
            return await self._command(action, params)

    async def _command(self, action: str, params: dict[str, Any]) -> DeviceResult:
        def done(msg: str, err: str | None) -> DeviceResult:
            if err:
                return DeviceResult(False, False, err, simulated=False, state=self.status())
            self.sent["at"] = time.time()
            return DeviceResult(True, True, msg + " A fita não confirma o recebimento.", simulated=False, state=self.status())

        if action == "status":
            return DeviceResult(True, True, f"Bluetooth: {self.link}.", simulated=False, state=self.status())
        if action == "scan":
            try:
                found = await self.t.scan(self.name_prefix, float(params.get("timeout", 8.0)))
            except Exception as exc:
                return DeviceResult(False, False, f"Bluetooth indisponível ({type(exc).__name__}).", simulated=False, state=self.status())
            return DeviceResult(True, True, f"{len(found)} fita(s) “{self.name_prefix}” encontrada(s).", simulated=False, state={**self.status(), "found": found})
        if action == "connect":
            err = await self._ensure()
            return DeviceResult(not err, not err, err or f"Conectado à fita {self.address}.", simulated=False, state=self.status())
        if action == "disconnect":
            await self.t.disconnect()
            self.link = "desconectado"
            return DeviceResult(True, True, "Fita desconectada.", simulated=False, state=self.status())
        if action in ("on", "off"):
            err = await self._send([cmd_power(action == "on")])
            if not err:
                self.sent["on"] = action == "on"
            return done("Comando para ligar as luzes enviado." if action == "on" else "Comando para desligar as luzes enviado.", err)
        if action == "color":
            rgb = parse_hex(str(params.get("color", "")))
            if rgb is None:
                return DeviceResult(False, False, "Cor inválida: use o formato #RRGGBB.", simulated=False, state=self.status())
            level = self._level
            if params.get("brightness") is not None:
                try:
                    level = max(0, min(100, int(params["brightness"])))
                except (TypeError, ValueError):
                    return DeviceResult(False, False, "Brilho inválido: informe de 0 a 100.", simulated=False, state=self.status())
            packets = [cmd_power(True)]
            if self.brightness_mode == "cor":
                packets.append(cmd_color(*scale(rgb, level)))
            else:
                packets.append(cmd_color(*rgb))
                if params.get("brightness") is not None:
                    packets.append(cmd_brightness(level))
            err = await self._send(packets)
            if not err:
                self._base, self._level = rgb, level
                self.sent.update(on=True, color=to_hex(rgb), brightness=level)
            extra = f" com brilho {level}%" if level != 100 else ""
            return done(f"Cor {to_hex(rgb)}{extra} enviada às luzes.", err)
        if action == "brightness":
            try:
                value = max(0, min(100, int(params.get("value"))))
            except (TypeError, ValueError):
                return DeviceResult(False, False, "Brilho inválido: informe de 0 a 100.", simulated=False, state=self.status())
            if self.brightness_mode == "cor":
                sent_rgb = scale(self._base, value)
                err = await self._send([cmd_power(True), cmd_color(*sent_rgb)])
                msg = f"Brilho {value}% enviado às luzes (cor {to_hex(self._base)} escurecida para {to_hex(sent_rgb)})."
            else:
                err = await self._send([cmd_brightness(value)])
                msg = f"Brilho {value}% enviado às luzes (comando de brilho experimental, não validado nesta fita)."
            if not err:
                self._level = value
                self.sent.update(on=True, brightness=value)
            return done(msg, err)
        return DeviceResult(False, False, f"Ação '{action}' não existe para a fita de LED.", simulated=False, state=self.status())
