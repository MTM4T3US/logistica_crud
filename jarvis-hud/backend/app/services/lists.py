"""Anotações faladas e lista de compras (0.7) — locais, num SQLite em backend/data/.

"anota: ligar para o banco", "põe leite e pão na lista", "o que tem na lista?". Nada sai do PC, exceto quando
o próprio usuário consulta pelo celular pareado ou pelo Telegram dele.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

MAX_NOTE = 500
MAX_ITEM = 60


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn").strip()


def split_items(text: str) -> list[str]:
    """ "leite, pão e 2 kg de arroz" → ["leite", "pão", "2 kg de arroz"] (sem repetir, sem vazios)."""
    parts = re.split(r",|;|\s+e\s+|\s+mais\s+", text or "")
    out: list[str] = []
    for p in parts:
        p = re.sub(r"^\s*(?:o|a|os|as|um|uma|uns|umas)\s+", "", p.strip(" .!?\"'"), flags=re.IGNORECASE).strip()
        if p and p.lower() not in (x.lower() for x in out):
            out.append(p[:MAX_ITEM])
    return out[:20]


class Lists:
    def __init__(self, path: Path | str, tz: str = "America/Sao_Paulo", clock: Callable[[], datetime] | None = None):
        self.tz = ZoneInfo(tz)
        self._clock = clock or (lambda: datetime.now(self.tz).replace(tzinfo=None))
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS shopping (id INTEGER PRIMARY KEY, item TEXT NOT NULL UNIQUE COLLATE NOCASE, created TEXT NOT NULL)")

    def now(self) -> datetime:
        return self._clock()

    # ------------------------------------------------------------------ anotações
    def add_note(self, text: str) -> dict[str, Any]:
        text = re.sub(r"\s+", " ", text or "").strip()[:MAX_NOTE]
        if not text:
            raise ValueError("Anotação vazia.")
        text = text[:1].upper() + text[1:]
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO notes(text, created) VALUES (?, ?)", (text, self.now().isoformat(timespec="seconds")))
        return {"id": cur.lastrowid, "text": text, "created": self.now().isoformat(timespec="minutes")}

    def notes(self, since: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q, args = "SELECT id, text, created FROM notes", ()
        if since:
            q, args = q + " WHERE created >= ?", (since.isoformat(),)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY created DESC, id DESC LIMIT ?", (*args, limit)).fetchall()
        return [{"id": r[0], "text": r[1], "created": r[2][:16]} for r in rows]

    def notes_today(self) -> list[dict[str, Any]]:
        return self.notes(self.now().date())

    def notes_week(self) -> list[dict[str, Any]]:
        return self.notes(self.now().date() - timedelta(days=6))

    def find_notes(self, query: str) -> list[dict[str, Any]]:
        words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
        return [n for n in self.notes(limit=200) if words and all(w in n["text"].lower() for w in words)]

    def remove_note(self, note_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount > 0

    # ------------------------------------------------------------------ lista de compras
    def add_items(self, items: list[str]) -> tuple[list[str], list[str]]:
        added, already = [], []
        with self._lock, self._db:
            for it in items:
                it = it.strip()[:MAX_ITEM]
                if not it:
                    continue
                try:
                    self._db.execute("INSERT INTO shopping(item, created) VALUES (?, ?)", (it, self.now().isoformat(timespec="seconds")))
                    added.append(it)
                except sqlite3.IntegrityError:
                    already.append(it)
        return added, already

    def items(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT item FROM shopping ORDER BY id").fetchall()]

    def remove_items(self, items: list[str]) -> tuple[list[str], list[str]]:
        removed, missing = [], []
        current = self.items()
        with self._lock, self._db:
            for it in items:
                # "tira o leite" acha "leite integral" se for o único item que contém a palavra
                key = _fold(it)
                exact = [c for c in current if _fold(c) == key]
                partial = exact or [c for c in current if key in _fold(c)]
                if len(partial) == 1:
                    self._db.execute("DELETE FROM shopping WHERE item = ?", (partial[0],))
                    removed.append(partial[0])
                    current.remove(partial[0])
                else:
                    missing.append(it)
        return removed, missing

    def clear_items(self) -> int:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM shopping").rowcount

    def public(self) -> dict[str, Any]:
        return {"shopping": self.items(), "notes": self.notes(limit=30)}


def say_items(items: list[str]) -> str:
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]
