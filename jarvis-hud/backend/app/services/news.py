"""Notícias — só de feeds RSS/Atom verificáveis; nunca inventa manchetes.

Padrão (0.4): Google Notícias de Itumbiara (últimos 7 dias) e do Brasil (último dia), os mesmos feeds
do noticias_jarvis.py do usuário. JARVIS_NEWS_FEEDS=off desliga. Cada item mantém link, fonte e data.
"""
from __future__ import annotations

import email.utils
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

MAX_BYTES = 1_500_000


def parse_feed(xml_text: str, limit: int = 8) -> list[dict[str, str]]:
    """Aceita RSS 2.0 e Atom. Devolve título, link e data como vieram da fonte."""
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []

    def text(node: ET.Element, *names: str) -> str:
        for child in node:
            if child.tag.split("}")[-1] in names and (child.text or "").strip():
                return (child.text or "").strip()
        return ""

    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        link = text(node, "link")
        if not link:
            for child in node:
                if child.tag.split("}")[-1] == "link" and child.get("href"):
                    link = child.get("href", "")
                    break
        title = text(node, "title")
        if title:
            items.append({"title": title, "link": link, "published": text(node, "pubDate", "published", "updated"), "source": text(node, "source")})
        if len(items) >= limit:
            break
    return items


def google_news_feed(query: str, days: int) -> str:
    """Busca do Google Notícias em pt-BR (mesmo formato do noticias_jarvis.py)."""
    q = quote_plus(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR%3Apt-419"


def default_feeds(city: str, state: str) -> list[tuple[str, str]]:
    return [(city, google_news_feed(f"{city} {state}", 7)), ("Brasil", google_news_feed("Brasil", 1))]


def _age(published: str, now: datetime) -> timedelta | None:
    try:
        when = email.utils.parsedate_to_datetime(published)
    except (TypeError, ValueError, IndexError):
        try:
            when = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now - when.astimezone(timezone.utc)


def clean_item(item: dict[str, str]) -> dict[str, str]:
    """No Google Notícias o título vem como "Manchete - Fonte": separa a fonte."""
    title, source = item["title"].strip(), (item.get("source") or "").strip()
    if source and title.endswith(f" - {source}"):
        title = title[: -len(source) - 3].strip()
    elif not source and " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if 2 <= len(tail) <= 40:
            title, source = head.strip(), tail.strip()
    return {**item, "title": title, "source": source}


class NewsService:
    """`NewsService(url)` (um feed) ou `NewsService(feeds=[(rótulo, url), …])`."""

    def __init__(self, rss_url: str | None = None, *, feeds: list[tuple[str, str]] | None = None, ttl_s: float = 900.0,
                 client: httpx.AsyncClient | None = None, per_feed: int = 4, max_age_days: float = 7.0):
        self.feeds = list(feeds) if feeds is not None else ([("Notícias", rss_url)] if rss_url else [])
        self.rss_url = self.feeds[0][1] if self.feeds else None
        self.ttl_s, self.per_feed, self.max_age = ttl_s, per_feed, timedelta(days=max_age_days)
        self._client = client
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.feeds)

    async def _one(self, client: httpx.AsyncClient, label: str, url: str, now: datetime) -> dict[str, Any]:
        source = urlparse(url).netloc
        try:
            resp = await client.get(url, headers={"User-Agent": "JARVIS-OS-local/0.4"})
            resp.raise_for_status()
            if len(resp.content) > MAX_BYTES:
                raise ValueError("feed grande demais")
            raw = parse_feed(resp.text, limit=40)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            return {"label": label, "source": source, "items": [], "error": f"Não foi possível ler as notícias de {label} ({type(exc).__name__})."}
        items = []
        for item in raw:
            age = _age(item.get("published", ""), now)
            if age is not None and (age < -timedelta(minutes=10) or age > self.max_age):
                continue                      # velha demais ou com data no futuro
            items.append({**clean_item(item), "region": label})
            if len(items) >= self.per_feed:
                break
        return {"label": label, "source": source, "items": items, "error": None}

    async def get(self) -> dict[str, Any]:
        if not self.feeds:
            return {"ok": False, "enabled": False, "items": [], "sections": [], "error": "Notícias desligadas (JARVIS_NEWS_FEEDS=off)."}
        if self._cache and time.time() - self._cache_at < self.ttl_s:
            return self._cache
        client = self._client or httpx.AsyncClient(timeout=12.0, follow_redirects=True)
        now = datetime.now(timezone.utc)
        try:
            sections = [await self._one(client, label, url, now) for label, url in self.feeds]
        finally:
            if self._client is None:
                await client.aclose()
        items = [i for s in sections for i in s["items"]]
        ok = any(s["error"] is None for s in sections)
        result = {"ok": ok, "enabled": True, "source": ", ".join(dict.fromkeys(s["source"] for s in sections)), "items": items, "sections": sections,
                  "fetched_at": time.time()}
        if not ok:
            result["error"] = sections[0]["error"]
            return result                       # falha não fica em cache: tenta de novo na próxima
        self._cache, self._cache_at = result, time.time()
        return result
