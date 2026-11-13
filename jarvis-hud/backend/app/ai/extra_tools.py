"""Ferramentas do assistente pessoal e do computador (0.7): cotações, time do coração, resumo da semana,
Pomodoro, ler o texto selecionado e modo jogo. A lógica fica no núcleo (`Assistant`)."""
from __future__ import annotations

from typing import Any

from ..security.permissions import ActionClass
from ..services.finance import say_quotes
from ..services.pomodoro import say_left
from .base import ToolOutcome


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


class ExtraTools:
    def __init__(self, core: Any):
        self.core = core

    def specs(self) -> list[Any]:
        from .tools import ToolSpec

        c = self.core
        out = [
            ToolSpec("get_quotes", "Cotações", "Dólar e Bitcoin em reais agora (fonte: AwesomeAPI). which = dolar, bitcoin ou ambos.",
                     _obj({"which": {"type": "string", "enum": ["dolar", "bitcoin", "ambos"]}}), ActionClass.READ, self._quotes),
            ToolSpec("week_summary", "Resumo da semana", "Compromissos dos próximos 7 dias, aniversários, previsão do tempo e pendências (lista e anotações).",
                     _obj(), ActionClass.READ, self._week),
            ToolSpec("pomodoro_start", "Começar Pomodoro", "Ciclos de foco e pausa com aviso e cor na fita de LED. Padrão 25/5 min, 4 ciclos.",
                     _obj({"focus_min": {"type": "integer", "minimum": 1, "maximum": 120}, "break_min": {"type": "integer", "minimum": 1, "maximum": 60},
                           "cycles": {"type": "integer", "minimum": 1, "maximum": 8}}), ActionClass.SAFE, self._pomo_start),
            ToolSpec("pomodoro_stop", "Parar Pomodoro", "Encerra o Pomodoro em andamento.", _obj(), ActionClass.SAFE, self._pomo_stop),
            ToolSpec("pomodoro_status", "Tempo do Pomodoro", "Quanto falta do foco ou da pausa.", _obj(), ActionClass.READ, self._pomo_status),
            ToolSpec("game_mode", "Modo jogo", "Liga (on=true) ou desliga o modo jogo: o HUD para de usar a GPU e a fita muda de cor.",
                     _obj({"on": {"type": "boolean"}}, ["on"]), ActionClass.SAFE, self._game),
        ]
        if c.runtime().get("team"):
            out.append(ToolSpec("team_news", "Notícias do time", f"Manchetes recentes sobre o time do usuário ({c.runtime()['team']}).",
                                _obj(), ActionClass.READ, self._team))
        if c.screen is not None and c.clipboard is not None and c.perms.pc.get("teclado", True):
            out.append(ToolSpec("read_selection", "Ler o texto selecionado", "Lê em voz alta o texto selecionado na janela em foco (copia, lê e devolve a área de transferência).",
                                _obj(), ActionClass.SAFE, self._read))
        return out

    async def _quotes(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        q = await self.core.finance.get()
        want = {"dolar": ("usd",), "bitcoin": ("btc",)}.get(args.get("which", "ambos"), ("usd", "btc"))
        return ToolOutcome(run.call, bool(q.get("ok")), bool(q.get("ok")), say_quotes(q, want), data=q)

    async def _team(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        text, items = await self.core.team_news()
        return ToolOutcome(run.call, bool(items), bool(items), text, data={"items": items})

    async def _week(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        text = await self.core.week_summary()
        return ToolOutcome(run.call, True, True, text)

    async def _pomo_start(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        p = self.core.pomodoro.start(args.get("focus_min", 25), args.get("break_min", 5), args.get("cycles", 4))
        led = " A fita fica branca no foco e verde na pausa." if self.core.devices.get("leds") is not None else ""
        return ToolOutcome(run.call, True, True, f"Pomodoro: {p['focus_min']} minutos de foco e {p['break_min']} de pausa, {p['cycles']} ciclos.{led}", data=p)

    async def _pomo_stop(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        was = await self.core.pomodoro.stop()
        await self.core.broadcast({"type": "pomodoro", "pomodoro": None})
        return ToolOutcome(run.call, True, was, "Pomodoro encerrado." if was else "Nenhum Pomodoro em andamento.")

    async def _pomo_status(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        p = self.core.pomodoro.public()
        return ToolOutcome(run.call, True, True, say_left(p), data=p or {})

    async def _game(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        await self.core.set_game_mode(bool(args["on"]), "voz")
        return ToolOutcome(run.call, True, True, "Modo jogo ligado: o HUD pausou para liberar a placa de vídeo." if args["on"] else "Modo jogo desligado: HUD de volta.")

    async def _read(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        ok, text = await self.core.read_selected()
        return ToolOutcome(run.call, ok, ok, text, data={"text": text} if ok else {})
