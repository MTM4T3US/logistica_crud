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


def _de(label: str) -> str:
    return "do Brasil" if label == "Brasil" else f"de {label}"


_STOP = {"de", "da", "do", "das", "dos", "a", "o", "as", "os", "e", "em", "para", "com", "no", "na", "nos", "nas", "por", "um", "uma", "que", "se"}
TITLE_MAX = 140


def _words(text: str) -> set[str]:
    import re
    import unicodedata

    t = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOP and len(w) > 2}


def _clean_title(title: str) -> str:
    """Manchete falável. Alguns itens do Google Notícias (ex.: posts do Instagram) trazem como título a
    legenda cortada no meio de uma palavra ("…a expectativa d") — visto no teste do Windows. Corta na
    última frase completa ou, se não houver, na última palavra inteira com reticências."""
    t = " ".join((title or "").split())
    if len(t) <= TITLE_MAX:
        return t
    head = t[:TITLE_MAX]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end >= 40 else head[:head.rfind(" ")].rstrip(",;:") + "…"


def _distinct(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Até `limit` manchetes sem repetir o mesmo assunto (no teste, o mesmo fato veio pelo Instagram e
    pelo Rota Jurídica). Entre duplicatas fica a de título mais curto (a manchete de verdade)."""
    picked: list[dict[str, Any]] = []
    for item in items:
        words = _words(item.get("title", ""))
        dup = next((i for i, p in enumerate(picked) if words and len(words & _words(p["title"])) / max(1, min(len(words), len(_words(p["title"])))) >= 0.6), None)
        if dup is None:
            picked.append(item)
        elif len(item.get("title", "")) < len(picked[dup]["title"]):
            picked[dup] = item
    return picked[:limit]


def _news_text(news: dict[str, Any] | None, city: str) -> tuple[str, list[dict[str, Any]]]:
    if not news or not news.get("enabled"):
        return "", []
    sections = news.get("sections") or [{"label": "Notícias", "items": news.get("items", []), "error": news.get("error")}]
    parts: list[str] = []
    used: list[dict[str, Any]] = []
    for sec in sections:
        label = sec.get("label") or "Notícias"
        if sec.get("error"):
            parts.append(f"Não consegui ler as notícias {_de(label)} agora.")
            continue
        items = sec.get("items") or []
        if not items:
            parts.append(f"Não encontrei notícias recentes {_de(label)}.")
            continue
        take = [{**i, "title": _clean_title(i.get("title", ""))} for i in _distinct(items[:6], 2 if label == city else 1)]
        used.extend(take)
        heads = "; ".join(i["title"].rstrip(".") for i in take)
        parts.append(f"Nas notícias de {label}: {heads}." if label == city else f"No {label}: {heads}." if label == "Brasil" else f"{label}: {heads}.")
    return " ".join(parts), used


def compose(now: dict[str, Any], city: str, title: str, weather: dict[str, Any] | None, news: dict[str, Any] | None,
            agenda_text: str = "", agenda: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    news_text, headlines = _news_text(news, city)
    briefing = " ".join(x for x in (_weather_text(city, weather), news_text, f"Em que posso ajudar, {title}?") if x)
    w = weather if weather and weather.get("ok") else None
    return {
        "welcome": (welcome_text(now, title) + (" " + agenda_text if agenda_text else "")).strip(),
        "agenda": agenda or [],
        "briefing": briefing,
        "city": city,
        "weather": {k: w.get(k) for k in ("temperature_c", "condition", "humidity", "wind_kmh", "today", "fetched_at_text", "stale")} if w else None,
        "headlines": [{"title": h["title"], "source": h.get("source", ""), "region": h.get("region", ""), "link": h.get("link", "")} for h in headlines],
    }
