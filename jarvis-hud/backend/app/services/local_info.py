"""Data e hora corretas da cidade configurada (padrão: Itumbiara, GO — America/Sao_Paulo)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Location

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "manhã"
    if 12 <= hour < 18:
        return "tarde"
    if 18 <= hour < 24:
        return "noite"
    return "madrugada"


def greeting(hour: int) -> str:
    return {"manhã": "Bom dia", "tarde": "Boa tarde"}.get(part_of_day(hour), "Boa noite")


def local_now(location: Location, now: datetime | None = None) -> dict[str, Any]:
    tz = ZoneInfo(location.timezone)
    dt = now.astimezone(tz) if now else datetime.now(tz)
    offset = dt.utcoffset()
    hours = int(offset.total_seconds() // 3600) if offset else 0
    return {
        "iso": dt.isoformat(timespec="seconds"),
        "time": dt.strftime("%H:%M"),
        "date": f"{WEEKDAYS[dt.weekday()]}, {dt.day} de {MONTHS[dt.month - 1]} de {dt.year}",
        "weekday": WEEKDAYS[dt.weekday()],
        "part_of_day": part_of_day(dt.hour),
        "greeting": greeting(dt.hour),
        "timezone": location.timezone,
        "utc_offset": f"UTC{hours:+d}",
        "city": location.city,
        "state": location.state,
        "country": location.country,
    }
