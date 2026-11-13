"""Efeitos de luz na fita REAL (ELK-BLEDDM): acompanhar a voz do JARVIS e efeito de abertura.

Pedido do usuário no teste do Windows (12/11/2026): "o LED poderia acompanhar a voz do JARVIS em azul,
e quando entrar colocar efeito nele pra dar imersão".

Como funciona
- O núcleo já tem o áudio que vai para o HUD (pedaços PCM do Gemini ou WAV inteiro do Piper/sistema).
  Daqui se tira o volume em janelas de 50 ms, numa linha do tempo que começa quando o 1º áudio sai
  (+ a folga de reprodução do navegador). As frases tocam em sequência no HUD, então a linha é contínua.
- A cada FRAME_S (0,2 s) manda um azul entre "pausa" (azul bem escuro) e "pico" (azul-ciano claro),
  conforme o volume do trecho que está tocando, adiantado LEAD_S para compensar o Bluetooth.
  1ª versão (0,35 s, só brilho, sem adiantamento): o usuário achou a variação pouco visível e atrasada.
  A fita pode descartar quadros muito próximos; o brilho acompanha o RITMO da fala, não cada sílaba.
- Quadros de efeito nunca entram na fila: se um comando do usuário estiver em andamento, ou a fita
  desconectada, o quadro é descartado. Nada de efeito atrasa "desligue as luzes".
- No fim da fala (ou se ela for interrompida) a fita volta ao estado escolhido pelo usuário
  (ligada/desligada, cor e brilho); se ele nunca escolheu nada, fica no Azul JARVIS.
- Efeito de abertura: ao iniciar o núcleo, conecta, acende em azul aos poucos, pulsa e termina no
  Azul JARVIS (que passa a ser o estado escolhido).

A fita não confirma nada: estes efeitos são "enviados", nunca "confirmados".
"""
from __future__ import annotations

import asyncio
import io
import math
import time
import wave
from typing import Any, Awaitable, Callable

from .elk_bleddm import scale

QUIET_RGB = (0, 0, 22)              # pausa: azul bem escuro (a fita continua acesa)
LOUD_RGB = (45, 160, 255)           # pico da voz: azul-ciano claro
JARVIS_RGB = (0x2B, 0x9B, 0xFF)     # cena "Azul JARVIS"
JARVIS_LEVEL = 70
FRAME_S = 0.2                        # intervalo entre quadros. 1ª versão: 0,35 s (o usuário achou lento/sutil)
EFFECT_SETTLE_S = 0.15               # espaço mínimo entre quadros de EFEITO (comandos normais seguem 0,3 s);
                                     # um quadro perdido pela fita não faz mal — a volta ao estado usa 0,3 s
BIN_S = 0.05                         # resolução do envelope de volume
LEAD_S = 0.15                        # a luz se ADIANTA isso, para compensar o Bluetooth (1ª versão atrasava)
CONTRAST = 1.6                       # >1 escurece mais as partes fracas: pausa e fala ficam bem distintas
MIN_STEP = 12                        # só manda quadro novo se algum canal mudar pelo menos isso
REF_WINDOW = 80                      # referência de volume: pico dos últimos 4 s (80 × 50 ms)
RECONNECT_EVERY_S = 120.0
INTRO_LEVELS = (8, 20, 38, 60, 85, 100, 55, 100, 55, 100)
ENTRY_WAIT_S = 25.0                  # entrada: "respira" no máximo isto esperando a voz começar
BREATH_PERIOD_S = 2.4                # um ciclo da respiração (sobe e desce)
BREATH_LOW, BREATH_HIGH = 25, 85


def parse_effects(raw: str | None) -> set[str]:
    """JARVIS_LED_EFEITOS: "voz,inicio" (padrão), "voz", "inicio" ou "off"."""
    items = {p.strip().lower() for p in (raw or "voz,inicio").split(",") if p.strip()}
    return set() if items & {"off", "nao", "não", "0", "false"} else items & {"voz", "inicio"}


def pcm_envelope(pcm: bytes, rate: int) -> list[float]:
    """RMS (0..1) de PCM 16 bits mono em janelas de BIN_S."""
    import numpy as np

    x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0
    n = max(1, int(rate * BIN_S))
    if len(x) < n:
        return [float(np.sqrt(np.mean(x * x)))] if len(x) else []
    x = x[: len(x) - len(x) % n].reshape(-1, n)
    return [float(v) for v in np.sqrt((x * x).mean(axis=1))]


def wav_to_pcm(wav: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(wav), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        return b"", rate
    if ch > 1:
        import numpy as np

        raw = np.frombuffer(raw, dtype="<i2").reshape(-1, ch).mean(axis=1).astype("<i2").tobytes()
    return raw, rate


class VoiceLights:
    def __init__(self, device: Any, voice: bool = True, intro: bool = True,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.dev, self.voice, self.intro_enabled = device, voice, intro
        self._clock, self._sleep = clock, sleep
        self._env: list[float] = []
        self._ref = 0.02
        self._t0: float | None = None
        self._done = False
        self._task: asyncio.Task | None = None
        self._restoring: asyncio.Task | None = None
        self._dirty = False                 # a fita está mostrando efeito, não o estado escolhido
        self._last_connect = -1e9
        self.frames_sent = 0
        self._speaking = False             # a voz assumiu a fita (a apresentação de entrada para)
        self._entry_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ fala
    def begin(self) -> None:
        """Novo turno de fala: zera a linha do tempo (o efeito anterior, se houver, é substituído)."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._env, self._t0, self._done, self._task = [], None, False, None

    def feed_pcm(self, pcm: bytes, rate: int) -> None:
        if not self.voice or not pcm:
            return
        try:
            self._env.extend(pcm_envelope(pcm, rate))
        except Exception:
            return
        self._ref = max(0.02, max(self._env[-REF_WINDOW:], default=0.0))
        self._speaking = True
        if self._task is None:
            chosen = self.dev.chosen()
            if chosen is not None and not chosen[0]:
                self._schedule_restore()   # se a entrada acendeu a fita, ela volta a apagar
                return   # o usuário desligou as luzes: a voz não acende a fita (nem "desligando…" pisca)
            self._maybe_connect()
            self._t0 = self._clock() - LEAD_S
            self._task = asyncio.get_running_loop().create_task(self._run())

    def feed_wav(self, wav: bytes) -> None:
        try:
            pcm, rate = wav_to_pcm(wav)
        except Exception:
            return
        self.feed_pcm(pcm, rate)

    def end(self, interrupted: bool = False) -> None:
        """Fim do turno: o efeito termina quando o áudio acabar de tocar; interrompido, termina já."""
        self._done = True
        if interrupted and self._task and not self._task.done():
            self._task.cancel()
            self._schedule_restore()
        elif self._task is None and self._dirty:
            self._schedule_restore()

    def intensity_at(self, t: float) -> float:
        """0 (pausa) a 1 (pico) para o trecho que toca em [t, t + FRAME_S]."""
        i0, i1 = max(0, int(t / BIN_S)), max(1, int((t + FRAME_S) / BIN_S))
        seg = self._env[i0:i1]
        if not seg:
            return 0.0
        mean = sum(seg) / len(seg)
        ref = max(self._ref, 1e-4)
        x = min(1.0, max(0.0, (mean - 0.12 * ref) / (0.8 * ref)))
        return x ** CONTRAST

    def color_at(self, t: float) -> tuple[int, int, int]:
        x = self.intensity_at(t)
        return tuple(round(q + (l - q) * x) for q, l in zip(QUIET_RGB, LOUD_RGB))  # type: ignore[return-value]

    async def _run(self) -> None:
        first, last = True, None
        try:
            while True:
                t = self._clock() - (self._t0 or self._clock())
                if self._done and t > len(self._env) * BIN_S:
                    break
                if t >= 0:
                    rgb = self.color_at(t)
                    if last is None or max(abs(a - b) for a, b in zip(rgb, last)) >= MIN_STEP:
                        if await self.dev.effect_frame(rgb, power=first, settle=EFFECT_SETTLE_S):
                            first, last, self._dirty = False, rgb, True
                            self.frames_sent += 1
                await self._sleep(FRAME_S)
        except asyncio.CancelledError:
            return   # substituído por outro turno ou interrompido: quem cancelou cuida da volta
        self._schedule_restore()

    def _schedule_restore(self) -> None:
        if not self._dirty:
            return
        self._dirty = False

        async def go() -> None:
            try:
                await self.dev.restore((JARVIS_RGB, JARVIS_LEVEL))
            except Exception:
                pass

        self._restoring = asyncio.get_running_loop().create_task(go())

    def _maybe_connect(self) -> None:
        """Fita desconectada (ex.: soltou por inatividade): reconecta em segundo plano, sem esperar."""
        if self.dev.link in ("conectado", "conectando", "procurando"):
            return
        now = self._clock()
        if now - self._last_connect < RECONNECT_EVERY_S:
            return
        self._last_connect = now
        asyncio.get_running_loop().create_task(self.dev.command("connect", {}))

    # ------------------------------------------------------------------ abertura
    async def intro(self) -> bool:
        """Efeito de abertura: acende em azul aos poucos, pulsa e termina no Azul JARVIS."""
        if not self.intro_enabled:
            return False
        self._last_connect = self._clock()
        res = await self.dev.command("connect", {})
        if not res.ok:
            return False
        for i, level in enumerate(INTRO_LEVELS):
            await self.dev.effect_frame(scale(JARVIS_RGB, level), power=i == 0)
            await self._sleep(FRAME_S)
        if self.dev.chosen() is None:          # ninguém escolheu cor ainda: o Azul JARVIS passa a ser o estado
            self.dev.adopt(JARVIS_RGB, JARVIS_LEVEL)
        return await self.dev.restore((JARVIS_RGB, JARVIS_LEVEL))

    # ------------------------------------------------------------------ entrada (rosto/PIN aceito)
    def start_entry(self) -> None:
        """Chamado quando o usuário entra: roda em segundo plano, junto com a música de entrada."""
        if not self.intro_enabled or (self._entry_task and not self._entry_task.done()):
            return
        self._speaking = False
        self._entry_task = asyncio.get_running_loop().create_task(self.entry())

    async def entry(self) -> bool:
        """Apresentação de entrada: acende em azul aos poucos, dois pulsos e fica "respirando" enquanto a
        música toca. Quando o JARVIS começa a falar (boas-vindas), o efeito de voz assume; no fim da fala a
        fita volta ao estado escolhido (ou ao Azul JARVIS)."""
        self._last_connect = self._clock()
        res = await self.dev.command("connect", {})
        if not res.ok:
            return False
        self._dirty = True
        for i, level in enumerate(INTRO_LEVELS):
            if self._speaking:
                return True
            await self.dev.effect_frame(scale(JARVIS_RGB, level), power=i == 0)
            await self._sleep(FRAME_S + 0.1)
        start = self._clock()
        while not self._speaking and self._clock() - start < ENTRY_WAIT_S:
            phase = (self._clock() - start) / BREATH_PERIOD_S * 2 * math.pi
            level = BREATH_LOW + (BREATH_HIGH - BREATH_LOW) * (1 - math.cos(phase)) / 2
            await self.dev.effect_frame(scale(JARVIS_RGB, round(level)), settle=EFFECT_SETTLE_S)
            await self._sleep(0.3)
        if not self._speaking:            # ninguém falou (ex.: sem voz): termina no estado escolhido
            if self.dev.chosen() is None:
                self.dev.adopt(JARVIS_RGB, JARVIS_LEVEL)
            self._schedule_restore()
        return True
