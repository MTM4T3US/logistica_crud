"""Pomodoro com a fita de LED (0.7): foco (fita branca) → pausa (verde) → … ; avisa a cada troca.

O relógio é do núcleo (continua contando com o HUD fechado). A fita só muda se existir; sem fita, só os avisos.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Awaitable, Callable

Phase = str  # "foco" | "pausa" | "pausa longa"
OnChange = Callable[[str, dict[str, Any]], Awaitable[None]]


class Pomodoro:
    def __init__(self, on_change: OnChange, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.on_change, self.clock, self.sleep = on_change, clock, sleep
        self.task: asyncio.Task | None = None
        self.state: dict[str, Any] | None = None
        self.done_today = 0

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def public(self) -> dict[str, Any] | None:
        if not self.state:
            return None
        left = max(0, round(self.state["ends"] - self.clock()))
        return {"phase": self.state["phase"], "left_s": left, "cycle": self.state["cycle"], "cycles": self.state["cycles"],
                "focus_min": self.state["focus"], "break_min": self.state["break"], "done_today": self.done_today}

    def start(self, focus_min: int = 25, break_min: int = 5, cycles: int = 4) -> dict[str, Any]:
        self.stop_nowait()
        focus_min, break_min, cycles = max(1, min(120, int(focus_min))), max(1, min(60, int(break_min))), max(1, min(8, int(cycles)))
        self.state = {"phase": "foco", "ends": self.clock() + focus_min * 60, "cycle": 1, "cycles": cycles, "focus": focus_min, "break": break_min}
        self.task = asyncio.create_task(self._run())
        return self.public()  # type: ignore[return-value]

    def stop_nowait(self) -> bool:
        was = self.running
        if self.task and not self.task.done():
            self.task.cancel()
        self.task, self.state = None, None
        return was

    async def stop(self) -> bool:
        task = self.task
        was = self.stop_nowait()
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        return was

    async def _run(self) -> None:
        st = self.state
        assert st is not None
        await self.on_change("foco", self.public() or {})
        while True:
            await self.sleep(max(0.0, st["ends"] - self.clock()))
            if st["phase"] == "foco":
                self.done_today += 1
                if st["cycle"] >= st["cycles"]:
                    self.state = None
                    await self.on_change("fim", {"done_today": self.done_today, "cycles": st["cycles"]})
                    return
                longa = st["cycle"] % 4 == 0
                st.update(phase="pausa longa" if longa else "pausa", ends=self.clock() + st["break"] * 60 * (3 if longa else 1))
            else:
                st.update(phase="foco", ends=self.clock() + st["focus"] * 60, cycle=st["cycle"] + 1)
            await self.on_change(st["phase"], self.public() or {})


def say_left(p: dict[str, Any] | None) -> str:
    if not p:
        return "Nenhum Pomodoro em andamento."
    m, s = divmod(p["left_s"], 60)
    left = f"{m} minuto{'s' if m != 1 else ''}" if m else f"{s} segundos"
    return f"{p['phase'].capitalize()}, ciclo {p['cycle']} de {p['cycles']}: faltam {left}."
