"""Boas-vindas e resumo da cidade (clima + notícias), montados aqui mesmo — sem gastar o Gemini.

Só usa o que veio das fontes reais (Open-Meteo e os feeds de notícias). Se uma fonte falhar, o
texto diz que falhou; nunca preenche com dados inventados.
"""
from __future__ import annotations

from typing import Any

MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")


def _clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    hours = "meia-noite" if h == 0 else "meio-dia" if h == 12 else f"{h} hora" + ("s" if h != 1 else "")
    return hours if m == 0 else f"{hours} e {m}"


def welcome_text(now: dict[str, Any], title: str) -> str:
    """Ex.: "Boa noite, senhor. Bem-vindo de volta. São 19 horas e 40, quinta-feira, 12 de novembro."."""
    date = now.get("date", "")
    short = date.rsplit(" de ", 1)[0] if date.count(" de ") >= 2 else date      # sem o ano
    clock = _clock(now["time"]) if now.get("time") else ""
    verb = "É" if clock.startswith(("1 hora", "meia", "meio")) else "São"
    tail = f" {verb} {clock}, {short}." if clock else ""
    return f"{now.get('greeting', 'Olá')}, {title}. Bem-vindo de volta.{tail}"


def _weather_text(city: str, w: dict[str, Any] | None) -> str:
    if not w or not w.get("ok") or w.get("temperature_c") is None:
        return f"Não consegui o clima de {city} agora."
    out = f"{city} agora: {round(w['temperature_c'])} graus"
    if w.get("condition"):
        out += f", {str(w['condition']).lower()}"
    out += "."
    today = w.get("today") or {}
    if today.get("max_c") is not None and today.get("min_c") is not None:
        out += f" Hoje, máxima de {round(today['max_c'])} e mínima de {round(today['min_c'])} graus"
        rain = today.get("rain_probability")
        out += f", com {round(rain)} por cento de chance de chuva." if isinstance(rain, (int, float)) and rain >= 20 else "."
    if w.get("stale"):
        out += " Esses dados são da última leitura que consegui."
    return out


def _news_text(news: dict[str, Any] | None, city: str) -> tuple[str, list[dict[str, Any]]]:
    if not news or not news.get("enabled"):
        return "", []
    sections = news.get("sections") or [{"label": "Notícias", "items": news.get("items", []), "error": news.get("error")}]
    parts: list[str] = []
    used: list[dict[str, Any]] = []
    for sec in sections:
        label = sec.get("label") or "Notícias"
        if sec.get("error"):
            parts.append(f"Não consegui ler as notícias de {label} agora.")
            continue
        items = sec.get("items") or []
        if not items:
            parts.append(f"Não encontrei notícias recentes de {label}.")
            continue
        take = items[:2] if label == city else items[:1]
        used.extend(take)
        heads = "; ".join(i["title"].rstrip(".") for i in take)
        parts.append(f"Nas notícias de {label}: {heads}." if label == city else f"No {label}: {heads}." if label == "Brasil" else f"{label}: {heads}.")
    return " ".join(parts), used


def compose(now: dict[str, Any], city: str, title: str, weather: dict[str, Any] | None, news: dict[str, Any] | None) -> dict[str, Any]:
    news_text, headlines = _news_text(news, city)
    briefing = " ".join(x for x in (_weather_text(city, weather), news_text, f"Em que posso ajudar, {title}?") if x)
    w = weather if weather and weather.get("ok") else None
    return {
        "welcome": welcome_text(now, title),
        "briefing": briefing,
        "city": city,
        "weather": {k: w.get(k) for k in ("temperature_c", "condition", "humidity", "wind_kmh", "today", "fetched_at_text", "stale")} if w else None,
        "headlines": [{"title": h["title"], "source": h.get("source", ""), "region": h.get("region", ""), "link": h.get("link", "")} for h in headlines],
    }
