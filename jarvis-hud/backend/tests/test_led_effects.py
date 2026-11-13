"""Efeitos de luz da fita real: acompanhar a voz e abertura (pedido do usuário no teste do Windows)."""
from __future__ import annotations

import asyncio
import math
import struct

from app.devices.elk_bleddm import ElkBleddmLeds, cmd_power
from app.devices.led_effects import JARVIS_RGB, VoiceLights, parse_effects, pcm_envelope


class FakeBle:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._on = False

    async def scan(self, prefix, timeout):
        return [{"address": "AA:BB", "name": "ELK-BLEDDM", "rssi": -40}]

    async def connect(self, address, on_disconnect):
        self._on = True

    async def write(self, data):
        self.writes.append(data)

    async def disconnect(self):
        self._on = False

    @property
    def connected(self):
        return self._on


async def nosleep(_s):
    await asyncio.sleep(0)


def speech_pcm(seconds: float, rate: int = 24000) -> bytes:
    """Fala falsa: trechos altos e silêncios alternados a cada 0,5 s."""
    out = []
    for i in range(int(seconds * rate)):
        loud = int(i / rate / 0.5) % 2 == 0
        out.append(int((12000 if loud else 0) * math.sin(2 * math.pi * 220 * i / rate)))
    return struct.pack(f"<{len(out)}h", *out)


def colors(writes: list[bytes]) -> list[bytes]:
    return [w for w in writes if w[1] == 0x00]


def test_parse_effects():
    assert parse_effects(None) == {"voz", "inicio"} and parse_effects("voz") == {"voz"} and parse_effects("off") == set()


def test_envelope_and_levels_follow_the_voice():
    pcm = speech_pcm(2.0)
    env = pcm_envelope(pcm, 24000)
    assert len(env) == 40 and env[0] > 0.2 and env[12] == 0.0
    fx = VoiceLights(device=None)
    fx._env, fx._ref = env, max(env)
    assert fx.intensity_at(0.0) > 0.8 and fx.intensity_at(0.6) == 0.0   # fala → claro; pausa → escuro
    assert fx.color_at(0.6) == (0, 0, 22) and fx.color_at(0.0)[2] == 255


async def test_voice_frames_then_back_to_the_chosen_state():
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    await dev.command("color", {"color": "#ff0000"})           # escolha do usuário: vermelho
    ble.writes.clear()
    now = [0.0]
    fx = VoiceLights(dev, clock=lambda: now[0], sleep=nosleep)
    fx.begin()
    fx.feed_pcm(speech_pcm(2.0), 24000)
    fx.end()
    for _ in range(60):
        now[0] += 0.1
        await asyncio.sleep(0)
    await asyncio.gather(*(t for t in (fx._task, fx._restoring) if t))
    sent = colors(ble.writes)
    assert ble.writes[0] == cmd_power(True)                       # 1º quadro garante a fita ligada
    assert fx.frames_sent >= 3
    assert all(w[6] >= w[4] and w[6] >= w[5] for w in sent[:-1])  # sempre azul durante a fala
    assert min(w[6] for w in sent[:-1]) <= 40 and max(w[6] for w in sent[:-1]) >= 200   # contraste visível
    assert sent[-1][4:7] == bytes([255, 0, 0])                    # voltou ao vermelho escolhido
    assert dev.sent["color"] == "#ff0000"                         # o efeito não mudou a escolha


async def test_interrupted_speech_restores_immediately():
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    await dev.command("color", {"color": "#00ff00"})
    now = [0.0]
    fx = VoiceLights(dev, clock=lambda: now[0], sleep=nosleep)
    fx.begin()
    fx.feed_pcm(speech_pcm(5.0), 24000)
    for _ in range(10):
        now[0] += 0.1
        await asyncio.sleep(0)
    assert fx._dirty
    fx.end(interrupted=True)
    await fx._restoring
    assert ble.writes[-1][4:7] == bytes([0, 255, 0])              # voltou ao verde escolhido


async def test_effect_frames_never_wait_for_a_busy_or_disconnected_strip():
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    assert await dev.effect_frame((0, 0, 255)) is False and ble.writes == []   # desconectada: descarta
    await dev.command("connect", {})
    async with dev._lock:                                         # comando do usuário em andamento
        assert await dev.effect_frame((0, 0, 255)) is False


async def test_intro_ends_in_jarvis_blue_as_the_chosen_state():
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    fx = VoiceLights(dev, sleep=nosleep)
    assert await fx.intro() is True
    assert ble.writes[0] == cmd_power(True) and len(colors(ble.writes)) >= 10
    assert dev.sent["color"] == "#%02x%02x%02x" % JARVIS_RGB and dev.sent["brightness"] == 70


async def test_voice_effect_does_not_light_a_strip_the_user_turned_off():
    """Visto no teste: "desligue as luzes" → a resposta falada acendia a fita de novo."""
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    await dev.command("off", {})
    ble.writes.clear()
    fx = VoiceLights(dev, sleep=nosleep)
    fx.begin()
    fx.feed_pcm(speech_pcm(1.0), 24000)
    fx.end()
    await asyncio.sleep(0)
    assert fx._task is None and ble.writes == []


async def test_entry_presentation_breathes_until_the_voice_takes_over():
    """0.4: ao entrar (rosto/PIN) a fita acende, pulsa e "respira" com a música; a voz assume depois."""
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    now = [0.0]

    async def tick(_s):
        now[0] += 0.3
        await asyncio.sleep(0)

    fx = VoiceLights(dev, clock=lambda: now[0], sleep=tick)
    fx.start_entry()
    for _ in range(40):                       # ~12 s de música
        await asyncio.sleep(0)
    assert not fx._entry_task.done() and len(colors(ble.writes)) > 12      # ainda respirando
    levels = {w[6] for w in colors(ble.writes)[10:]}
    assert len(levels) >= 3                                                # o brilho sobe e desce
    fx.begin()
    fx.feed_pcm(speech_pcm(1.0), 24000)       # boas-vindas começam: a entrada para
    await asyncio.wait_for(fx._entry_task, 1)
    fx._task.cancel()


async def test_entry_with_lights_off_ends_off_again():
    ble = FakeBle()
    dev = ElkBleddmLeds("AA:BB", transport=ble, sleep=nosleep)
    await dev.command("off", {})
    fx = VoiceLights(dev, sleep=nosleep)
    fx._dirty = True                          # a apresentação de entrada acendeu a fita
    fx.begin()
    fx.feed_pcm(speech_pcm(1.0), 24000)
    await fx._restoring
    assert ble.writes[-1] == cmd_power(False)
