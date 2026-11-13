"""Ferramentas de anotações e lista de compras (0.7). Apagar a lista inteira pede confirmação."""
from __future__ import annotations

from typing import Any

from ..security.permissions import ActionClass
from ..services.lists import Lists, say_items, split_items
from .base import ToolOutcome


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


class ListTools:
    def __init__(self, lists: Lists):
        self.l = lists

    def specs(self) -> list[Any]:
        from .tools import ToolSpec

        return [
            ToolSpec("note_add", "Anotar", "Guarda uma anotação do usuário (texto livre, ex.: 'ligar para o banco').",
                     _obj({"text": {"type": "string", "maxLength": 500}}, ["text"]), ActionClass.SAFE, self._note_add),
            ToolSpec("notes_list", "Ver anotações", "Lê as anotações de hoje (period=hoje), da semana (semana) ou as últimas (todas).",
                     _obj({"period": {"type": "string", "enum": ["hoje", "semana", "todas"]}}), ActionClass.READ, self._notes_list),
            ToolSpec("note_remove", "Apagar anotação", "Apaga uma anotação pelas palavras dela (pede confirmação).",
                     _obj({"query": {"type": "string", "maxLength": 80}}, ["query"]), ActionClass.CONFIRM, self._note_remove),
            ToolSpec("shop_add", "Pôr na lista de compras", "Adiciona itens à lista de compras (ex.: 'leite, pão e café').",
                     _obj({"items": {"type": "string", "maxLength": 300}}, ["items"]), ActionClass.SAFE, self._shop_add),
            ToolSpec("shop_remove", "Tirar da lista de compras", "Tira itens da lista de compras.",
                     _obj({"items": {"type": "string", "maxLength": 300}}, ["items"]), ActionClass.SAFE, self._shop_remove),
            ToolSpec("shop_list", "Ver lista de compras", "Lê a lista de compras.", _obj(), ActionClass.READ, self._shop_list),
            ToolSpec("shop_clear", "Limpar lista de compras", "Apaga a lista de compras inteira (pede confirmação).", _obj(), ActionClass.CONFIRM, self._shop_clear),
        ]

    async def _changed(self, run: Any) -> None:
        await run.notify({"type": "lists", "lists": self.l.public()})

    async def _note_add(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        try:
            note = self.l.add_note(args["text"])
        except ValueError:
            return ToolOutcome(run.call, False, False, "Não ouvi o que anotar.")
        await self._changed(run)
        return ToolOutcome(run.call, True, True, f"Anotado: {note['text']}", data={"note": note})

    async def _notes_list(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        period = args.get("period", "hoje")
        notes = self.l.notes_today() if period == "hoje" else self.l.notes_week() if period == "semana" else self.l.notes(limit=10)
        when = {"hoje": "hoje", "semana": "nesta semana", "todas": "por último"}[period]
        if not notes:
            return ToolOutcome(run.call, True, True, f"Nenhuma anotação {when}.", data={"notes": []})
        texts = [n["text"].rstrip(".") for n in reversed(notes[:8])]
        head = f"Uma anotação {when}" if len(notes) == 1 else f"{len(notes)} anotações {when}"
        return ToolOutcome(run.call, True, True, f"{head}: " + "; ".join(texts) + ".", data={"notes": notes})

    async def _note_remove(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        found = self.l.find_notes(args["query"])
        if not found:
            return ToolOutcome(run.call, False, False, f"Não achei anotação com “{args['query']}”.")
        if len(found) > 1:
            return ToolOutcome(run.call, False, False, f"Achei {len(found)} anotações com essas palavras; diga mais uma palavra.")
        if not await run.confirm(f"Apagar a anotação “{found[0]['text']}”?"):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou.")
        self.l.remove_note(found[0]["id"])
        await self._changed(run)
        return ToolOutcome(run.call, True, True, f"Anotação apagada: {found[0]['text']}")

    async def _shop_add(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        items = split_items(args["items"])
        if not items:
            return ToolOutcome(run.call, False, False, "Não entendi o que pôr na lista.")
        added, already = self.l.add_items(items)
        await self._changed(run)
        parts = []
        if added:
            parts.append(f"{say_items(added)} na lista")
        if already:
            parts.append(f"{say_items(already)} já {'estava' if len(already) == 1 else 'estavam'}")
        return ToolOutcome(run.call, True, True, "Pronto: " + "; ".join(parts) + ".", data={"items": self.l.items()})

    async def _shop_remove(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        removed, missing = self.l.remove_items(split_items(args["items"]))
        await self._changed(run)
        if not removed:
            return ToolOutcome(run.call, False, False, f"{say_items(missing).capitalize()} não {'está' if len(missing) == 1 else 'estão'} na lista.")
        tail = f" ({say_items(missing)} não estava)" if missing else ""
        return ToolOutcome(run.call, True, True, f"Tirei {say_items(removed)} da lista{tail}.", data={"items": self.l.items()})

    async def _shop_list(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        items = self.l.items()
        if not items:
            return ToolOutcome(run.call, True, True, "A lista de compras está vazia.", data={"items": []})
        return ToolOutcome(run.call, True, True, f"Na lista ({len(items)}): {say_items(items)}.", data={"items": items})

    async def _shop_clear(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        n = len(self.l.items())
        if not n:
            return ToolOutcome(run.call, True, True, "A lista já está vazia.")
        if not await run.confirm(f"Apagar a lista de compras inteira ({n} itens)?"):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou.")
        self.l.clear_items()
        await self._changed(run)
        return ToolOutcome(run.call, True, True, "Lista de compras limpa.")
