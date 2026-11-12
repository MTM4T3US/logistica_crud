"""Histórico, memória opcional, registro de ações e ajustes — tudo em um arquivo SQLite local."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL,
  ok INTEGER NOT NULL, executed INTEGER NOT NULL, simulated INTEGER NOT NULL, summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class MemoryStore:
    """API síncrona e thread-safe; o backend chama via asyncio.to_thread."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---- conversa ----
    def add_message(self, role: str, content: str, meta: dict[str, Any] | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO messages (ts, role, content, meta) VALUES (?, ?, ?, ?)",
                (time.time(), role, content, json.dumps(meta or {}, ensure_ascii=False)),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def recent_messages(self, limit: int = 32) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {"id": r["id"], "ts": r["ts"], "role": r["role"], "content": r["content"], "meta": json.loads(r["meta"])}
            for r in reversed(rows)
        ]

    def clear_messages(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM messages")
            self._db.commit()

    # ---- memória de longo prazo (opcional) ----
    def add_fact(self, text: str) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO facts (ts, text) VALUES (?, ?)", (time.time(), text.strip()))
            self._db.commit()
            return int(cur.lastrowid)

    def facts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "text": r["text"]} for r in reversed(rows)]

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self._db.commit()
            return cur.rowcount > 0

    def clear_facts(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM facts")
            self._db.commit()

    # ---- registro do que foi realmente executado ----
    def log_action(self, tool: str, args: dict[str, Any], *, ok: bool, executed: bool, simulated: bool, summary: str) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO actions (ts, tool, args, ok, executed, simulated, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), tool, json.dumps(args, ensure_ascii=False), int(ok), int(executed), int(simulated), summary),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {
                "id": r["id"], "ts": r["ts"], "tool": r["tool"], "args": json.loads(r["args"]), "ok": bool(r["ok"]),
                "executed": bool(r["executed"]), "simulated": bool(r["simulated"]), "summary": r["summary"],
            }
            for r in reversed(rows)
        ]

    # ---- ajustes alteráveis pelo HUD ----
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
