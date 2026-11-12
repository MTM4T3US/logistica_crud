"""Notícias locais — somente de uma fonte verificável configurada pelo usuário (feed RSS/Atom).

Desativado por padrão. Sem JARVIS_NEWS_RSS_URL não há notícias: o assistente diz que não
tem fonte, em vez de inventar manchetes. Cada item mantém o link da origem.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

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
            items.append({"title": title, "link": link, "published": text(node, "pubDate", "published", "updated")})
        if len(items) >= limit:
            break
    return items


class NewsService:
    def __init__(self, rss_url: str | None, *, ttl_s: float = 900.0, client: httpx.AsyncClient | None = None):
        self.rss_url = rss_url
        self.ttl_s = ttl_s
        self._client = client
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.rss_url)

    async def get(self) -> dict[str, Any]:
        if not self.rss_url:
            return {"ok": False, "enabled": False, "items": [], "error": "Nenhuma fonte de notícias configurada (JARVIS_NEWS_RSS_URL)."}
        if self._cache and time.time() - self._cache_at < self.ttl_s:
            return self._cache
        source = urlparse(self.rss_url).netloc
        client = self._client or httpx.AsyncClient(timeout=12.0, follow_redirects=True)
        try:
            resp = await client.get(self.rss_url)
            resp.raise_for_status()
            if len(resp.content) > MAX_BYTES:
                raise ValueError("feed grande demais")
            items = parse_feed(resp.text)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            return {"ok": False, "enabled": True, "source": source, "items": [], "error": f"Não foi possível ler a fonte de notícias ({type(exc).__name__})."}
        finally:
            if self._client is None:
                await client.aclose()
        self._cache = {"ok": True, "enabled": True, "source": source, "items": items, "fetched_at": time.time()}
        self._cache_at = time.time()
        return self._cache
