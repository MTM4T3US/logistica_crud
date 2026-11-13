"""Ferramentas da agenda pessoal (local). Apagar um compromisso pede confirmação com o nome e a data."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any

from ..security.permissions import ActionClass
from ..services.agenda import REPEATS, Agenda, parse_event
from .base import ToolOutcome


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


class AgendaTools:
    def __init__(self, agenda: Agenda):
        self.a = agenda

    def specs(self) -> list[Any]:
        from .tools import ToolSpec

        return [
            ToolSpec("agenda_add", "Marcar compromisso",
                     "Adiciona um compromisso à agenda local do usuário. date=AAAA-MM-DD; time=HH:MM (vazio = dia inteiro); "
                     "repeat: '', diario, dias_uteis, semanal, mensal, anual; remind_min = minutos antes para lembrar. "
                     "Alternativa: phrase = a frase do usuário (ex.: 'dentista amanhã às 15h').",
                     _obj({"title": {"type": "string", "maxLength": 120}, "date": {"type": "string", "maxLength": 10}, "time": {"type": "string", "maxLength": 5},
                           "repeat": {"type": "string", "enum": list(REPEATS)}, "remind_min": {"type": "integer", "minimum": 0, "maximum": 1440},
                           "duration_min": {"type": "integer", "minimum": 5, "maximum": 1440}, "place": {"type": "string", "maxLength": 120},
                           "phrase": {"type": "string", "maxLength": 200}}),
                     ActionClass.SAFE, self._add),
            ToolSpec("agenda_list", "Ver agenda", "Compromissos de um dia (day = hoje, amanha ou AAAA-MM-DD) ou dos próximos N dias (days).",
                     _obj({"day": {"type": "string", "maxLength": 10}, "days": {"type": "integer", "minimum": 1, "maximum": 31}}), ActionClass.READ, self._list),
            ToolSpec("agenda_remove", "Desmarcar compromisso", "Remove um compromisso, pelo id ou por palavras do título (pede confirmação).",
                     _obj({"id": {"type": "integer", "minimum": 1}, "query": {"type": "string", "maxLength": 80}}), ActionClass.CONFIRM, self._remove),
        ]

    async def _changed(self, run: Any) -> None:
        await run.notify({"type": "agenda", "agenda": {"today": [Agenda.public(e) for e in self.a.today()],
                                                      "upcoming": [Agenda.public(e) for e in self.a.upcoming(14)]}})

    async def _add(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        now = self.a.now()
        if args.get("phrase") and not args.get("date"):
            parsed = parse_event(args["phrase"], now)
            if parsed is None:
                return ToolOutcome(run.call, False, False, "Faltou dizer quando: por exemplo, “dentista amanhã às 15h”.")
            title, start, all_day, repeat = parsed["title"], parsed["start"], parsed["all_day"], args.get("repeat") or parsed["repeat"]
        else:
            title = (args.get("title") or "").strip()
            try:
                day = date.fromisoformat(args["date"]) if args.get("date") else now.date()
                hm = time.fromisoformat(args["time"]) if args.get("time") else None
            except (KeyError, ValueError):
                return ToolOutcome(run.call, False, False, "Data ou hora inválida (use AAAA-MM-DD e HH:MM).")
            start, all_day, repeat = datetime.combine(day, hm or time(0, 0)), hm is None, args.get("repeat", "")
        if not title:
            return ToolOutcome(run.call, False, False, "Faltou o nome do compromisso.")
        if not repeat and not all_day and start < now - timedelta(minutes=1):
            return ToolOutcome(run.call, False, False, "Essa data e hora já passaram.")
        try:
            ev = await asyncio.to_thread(self.a.add, title, start, all_day=all_day, repeat=repeat, remind_min=args.get("remind_min", 15),
                                         duration_min=args.get("duration_min", 60), place=args.get("place", ""))
        except ValueError as err:
            return ToolOutcome(run.call, False, False, str(err))
        await self._changed(run)
        rep = {"diario": ", todos os dias", "dias_uteis": ", nos dias úteis", "semanal": ", toda semana", "mensal": ", todo mês", "anual": ", todo ano"}.get(repeat, "")
        return ToolOutcome(run.call, True, True, f"Marcado: {self.a.describe(ev)}{rep}.", data={"event": Agenda.public(ev)})

    async def _list(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        now = self.a.now()
        day_arg = (args.get("day") or "").strip().lower()
        if args.get("days"):
            evs = self.a.occurrences(now.date(), now.date() + timedelta(days=int(args["days"]) - 1))
            evs = [e for e in evs if e["all_day"] or e["start"] >= now - timedelta(minutes=30)]
            if not evs:
                text = f"Nenhum compromisso nos próximos {args['days']} dias."
            else:
                text = "; ".join(self.a.describe(e) for e in evs[:10]) + "."
            return ToolOutcome(run.call, True, True, text, data={"events": [Agenda.public(e) for e in evs]})
        if day_arg in ("", "hoje"):
            d, label = now.date(), "hoje"
        elif day_arg in ("amanha", "amanhã"):
            d, label = now.date() + timedelta(days=1), "amanhã"
        else:
            try:
                d = date.fromisoformat(day_arg)
            except ValueError:
                return ToolOutcome(run.call, False, False, "Dia inválido (hoje, amanha ou AAAA-MM-DD).")
            label = f"dia {d.day}/{d.month}"
        evs = self.a.occurrences(d, d)
        return ToolOutcome(run.call, True, True, self.a.say_day(evs, label), data={"events": [Agenda.public(e) for e in evs]})

    async def _remove(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        if args.get("id"):
            ev = self.a.get(int(args["id"]))
            found = [ev] if ev else []
        else:
            found = self.a.find(args.get("query", ""))
        if not found:
            return ToolOutcome(run.call, False, False, "Não encontrei esse compromisso na agenda.")
        if len(found) > 1:
            names = "; ".join(self.a.describe(e) for e in found[:5])
            return ToolOutcome(run.call, False, False, f"Encontrei {len(found)}: {names}. Diga qual.", data={"events": [Agenda.public(e) for e in found]})
        ev = found[0]
        extra = " (é repetido: todas as ocorrências)" if ev["repeat"] else ""
        if not await run.confirm(f"Desmarcar “{self.a.describe(ev)}”{extra}?"):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou desmarcar.")
        await asyncio.to_thread(self.a.remove, ev["id"])
        await self._changed(run)
        return ToolOutcome(run.call, True, True, f"Desmarcado: {ev['title']}.")
