"""Agenda pessoal, guardada só neste computador (backend/data/agenda.sqlite3).

Compromissos com data, hora (ou dia inteiro), repetição e lembrete. Entende frases em português
("marca dentista amanhã às 15h", "toda segunda às 8h academia", "aniversário da mãe dia 20/11") sem IA.
"""
from __future__ import annotations

import calendar
import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

REPEATS = ("", "diario", "dias_uteis", "semanal", "mensal", "anual")
WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
WEEKDAY_NAMES = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
MONTHS = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
          "outubro": 10, "novembro": 11, "dezembro": 12}
MONTH_NAMES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
NUM = {"uma": 1, "um": 1, "duas": 2, "dois": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
       "onze": 11, "doze": 12}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def spoken_time(t: time) -> str:
    if t.hour == 12 and t.minute == 0:
        return "meio-dia"
    if t.hour == 0 and t.minute == 0:
        return "meia-noite"
    h = f"{t.hour} hora" + ("s" if t.hour != 1 else "")
    return h if t.minute == 0 else f"{h} e {t.minute}"


def spoken_day(d: date, today: date) -> str:
    if d == today:
        return "hoje"
    if d == today + timedelta(days=1):
        return "amanhã"
    if 0 < (d - today).days < 7:
        return WEEKDAY_NAMES[d.weekday()]
    return f"{WEEKDAY_NAMES[d.weekday()]}, {d.day} de {MONTH_NAMES[d.month - 1]}"


# ---------------------------------------------------------------- interpretação de frases
def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def parse_event(text: str, now: datetime) -> dict[str, Any] | None:
    """Tira data, hora e repetição da frase; o resto vira o título. None se não houver data nem hora."""
    # o texto original anda junto com o "dobrado" (sem acentos, minúsculo): mesmo tamanho, mesmos cortes,
    # e o título sai com os acentos e as maiúsculas de quem falou
    o = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip(" .,!?")
    t = fold(o)
    if len(t) != len(o):
        o = t
    today = now.date()
    day: date | None = None
    hm: time | None = None
    repeat = ""
    weekday: int | None = None

    def drop(a: int, b: int) -> None:
        nonlocal t, o
        t, o = t[:a] + " " + t[b:], o[:a] + " " + o[b:]
        while "  " in t:
            i = t.index("  ")
            t, o = t[:i] + t[i + 1:], o[:i] + o[i + 1:]
        lead = len(t) - len(t.lstrip())
        t, o = t[lead:].rstrip(), o[lead:][:len(t[lead:].rstrip())]

    def cut(pattern: str) -> re.Match | None:
        m = re.search(pattern, t)
        if m:
            drop(m.start(), m.end())
        return m

    # repetição
    if cut(r"\b(todos os dias|todo dia|diariamente)\b"):
        repeat = "diario"
    elif cut(r"\b(dias uteis|de segunda a sexta)\b"):
        repeat = "dias_uteis"
    m = cut(r"\b(?:toda|todo|todas as|todos os) (segunda|terca|quarta|quinta|sexta|sabado|domingo)s?(?:-feiras?| feiras?)?\b")
    if m:
        repeat, weekday = "semanal", WEEKDAYS[m.group(1)]
    if cut(r"\b(todo mes|mensalmente|todos os meses)\b"):
        repeat = "mensal"
    if cut(r"\b(todo ano|anualmente|todos os anos)\b"):
        repeat = "anual"

    # hora
    m = cut(r"\b(?:as |a |ao )?(meio[- ]dia|meia[- ]noite)\b")
    if m:
        hm = time(12, 0) if "meio" in m.group(1) else time(0, 0)
    if hm is None:
        m = cut(r"\b(?:as |a |por volta das )?(\d{1,2})(?:[:h](\d{2})|h| horas?)(?: e (\d{1,2})(?: minutos)?)?(?: da (manha|tarde|noite|madrugada))?\b")
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
            part = m.group(4)
            if part in ("tarde", "noite") and h < 12:
                h += 12
            if h <= 23 and mi <= 59:
                hm = time(h, mi)
    if hm is None:
        m = cut(r"\b(?:as |a )(\d{1,2}|" + "|".join(NUM) + r")(?: e meia)? da (manha|tarde|noite)\b")
        if m:
            h = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1)]
            h += 12 if m.group(2) in ("tarde", "noite") and h < 12 else 0
            hm = time(h % 24, 30 if "e meia" in m.group(0) else 0)

    # data
    if cut(r"\bdepois de amanha\b"):
        day = today + timedelta(days=2)
    elif cut(r"\bamanha\b"):
        day = today + timedelta(days=1)
    elif cut(r"\bhoje\b"):
        day = today
    m = cut(r"\b(?:dia )?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b") if day is None else None
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        y += 2000 if y < 100 else 0
        try:
            day = date(y, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and day < today:
                day = day.replace(year=y + 1)
        except ValueError:
            day = None
    if day is None:
        m = cut(r"\b(?:dia |no dia |em )?(\d{1,2}) de (" + "|".join(MONTHS) + r")(?: de (\d{4}))?\b")
        if m:
            try:
                day = date(int(m.group(3) or today.year), MONTHS[m.group(2)], int(m.group(1)))
                if not m.group(3) and day < today:
                    day = day.replace(year=day.year + 1)
            except ValueError:
                day = None
    if day is None:
        m = cut(r"\b(?:no |na |nesta |nessa |proxima |proximo )?(?:dia )?(\d{1,2})\b(?! horas?)") if re.search(r"\bdia \d{1,2}\b", t) else None
        if m:
            n = int(m.group(1))
            try:
                day = date(today.year, today.month, n)
                if day < today:
                    day = _add_months(day, 1)
            except ValueError:
                day = None
    if day is None and weekday is None:
        m = cut(r"\b(?:na |no |nesta |nessa |proxima |proximo |esta |essa )?(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:-feira| feira)?\b")
        if m:
            weekday = WEEKDAYS[m.group(1)]
    if day is None and weekday is not None:
        ahead = (weekday - today.weekday()) % 7
        if ahead == 0 and (hm is None or hm <= now.time()):
            ahead = 7
        day = today + timedelta(days=ahead)
    if day is None and repeat in ("diario", "dias_uteis", "mensal", "anual") and hm is not None:
        day = today if hm > now.time() else today + timedelta(days=1)
    if day is None and hm is not None:
        day = today if hm > now.time() else today + timedelta(days=1)
    if day is None:
        return None

    m = re.match(r"^(?:(?:de|que|pra|para|o|a|um|uma) )+", t)
    if m:
        drop(0, m.end())
    m = re.search(r"\s*\b(?:no|na|em|para|pra|de)$", t)
    if m:
        drop(m.start(), m.end())
    title = o.strip(" ,-")
    if not title:
        return None
    start = datetime.combine(day, hm or time(0, 0))
    return {"title": title[:1].upper() + title[1:120], "start": start, "all_day": hm is None, "repeat": repeat}


# ---------------------------------------------------------------- armazenamento
class Agenda:
    def __init__(self, path: Path | str, tz: str = "America/Sao_Paulo", clock: Callable[[], datetime] | None = None):
        self.tz = ZoneInfo(tz)
        self._clock = clock or (lambda: datetime.now(self.tz).replace(tzinfo=None))
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, start TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
                duration_min INTEGER NOT NULL DEFAULT 60, place TEXT NOT NULL DEFAULT '', remind_min INTEGER NOT NULL DEFAULT 15,
                repeat TEXT NOT NULL DEFAULT '', created TEXT NOT NULL)""")
        self._reminded: set[str] = set()

    def now(self) -> datetime:
        return self._clock()

    def add(self, title: str, start: datetime, *, all_day: bool = False, duration_min: int = 60, place: str = "",
            remind_min: int = 15, repeat: str = "") -> dict[str, Any]:
        title = (title or "").strip()[:120]
        if not title:
            raise ValueError("Compromisso sem título.")
        if repeat not in REPEATS:
            raise ValueError("Repetição inválida.")
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO events(title,start,all_day,duration_min,place,remind_min,repeat,created) VALUES (?,?,?,?,?,?,?,?)",
                                   (title, start.isoformat(timespec="minutes"), int(all_day), max(5, min(1440, int(duration_min))), (place or "")[:120],
                                    max(0, min(1440, int(remind_min))), repeat, self.now().isoformat(timespec="seconds")))
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, event_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT id,title,start,all_day,duration_min,place,remind_min,repeat FROM events WHERE id=?", (event_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(r: tuple) -> dict[str, Any]:
        return {"id": r[0], "title": r[1], "start": datetime.fromisoformat(r[2]), "all_day": bool(r[3]), "duration_min": r[4], "place": r[5],
                "remind_min": r[6], "repeat": r[7]}

    def remove(self, event_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount > 0

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT id,title,start,all_day,duration_min,place,remind_min,repeat FROM events ORDER BY start").fetchall()
        return [self._row(r) for r in rows]

    def occurrences(self, first: date, last: date) -> list[dict[str, Any]]:
        """Ocorrências entre `first` e `last` (inclusive), com as repetições expandidas, em ordem."""
        out = []
        for ev in self.all():
            start: datetime = ev["start"]
            rep = ev["repeat"]
            d = start.date()
            if not rep:
                if first <= d <= last:
                    out.append({**ev})
                continue
            day = max(first, d)
            while day <= last:
                hit = (rep == "diario" or (rep == "dias_uteis" and day.weekday() < 5) or (rep == "semanal" and day.weekday() == d.weekday())
                       or (rep == "mensal" and day.day == min(d.day, calendar.monthrange(day.year, day.month)[1]))
                       or (rep == "anual" and (day.month, day.day) == (d.month, d.day)))
                if hit and day >= d:
                    out.append({**ev, "start": datetime.combine(day, start.time())})
                day += timedelta(days=1)
        return sorted(out, key=lambda e: (e["start"], e["id"]))

    def today(self, remaining: bool = False) -> list[dict[str, Any]]:
        now = self.now()
        evs = self.occurrences(now.date(), now.date())
        if remaining:
            evs = [e for e in evs if e["all_day"] or e["start"] + timedelta(minutes=e["duration_min"]) >= now]
        return evs

    def upcoming(self, days: int = 7) -> list[dict[str, Any]]:
        now = self.now()
        return [e for e in self.occurrences(now.date(), now.date() + timedelta(days=days)) if e["all_day"] or e["start"] >= now - timedelta(minutes=30)]

    def find(self, query: str) -> list[dict[str, Any]]:
        q = fold(query).strip()
        words = [w for w in re.split(r"\s+", q) if len(w) > 2 and w not in ("compromisso", "lembrete", "evento", "com", "das", "dos")]
        return [e for e in self.all() if words and all(w in fold(e["title"]) for w in words)]

    def due_reminders(self) -> list[dict[str, Any]]:
        """Ocorrências cujo lembrete venceu agora (cada uma é avisada uma única vez)."""
        now = self.now()
        out = []
        for e in self.occurrences(now.date(), now.date() + timedelta(days=1)):
            if e["all_day"] or e["remind_min"] <= 0:
                continue
            key = f"{e['id']}@{e['start'].isoformat()}"
            if e["start"] - timedelta(minutes=e["remind_min"]) <= now < e["start"] and key not in self._reminded:
                self._reminded.add(key)
                out.append(e)
        return out

    # ------------------------------------------------------------------ texto
    def describe(self, e: dict[str, Any], today: date | None = None) -> str:
        today = today or self.now().date()
        when = spoken_day(e["start"].date(), today)
        at = "" if e["all_day"] else f" às {spoken_time(e['start'].time())}"
        return f"{e['title']}, {when}{at}"

    def say_day(self, evs: list[dict[str, Any]], label: str = "hoje") -> str:
        if not evs:
            return f"Sua agenda de {label} está livre."
        parts = [e["title"] + ("" if e["all_day"] else f" às {spoken_time(e['start'].time())}") for e in evs[:6]]
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " e " + parts[-1]
        n = len(evs)
        return f"{label.capitalize()} você tem {n} compromisso{'s' if n > 1 else ''}: {joined}."

    @staticmethod
    def public(e: dict[str, Any]) -> dict[str, Any]:
        return {**{k: v for k, v in e.items() if k != "start"}, "start": e["start"].isoformat(timespec="minutes")}
