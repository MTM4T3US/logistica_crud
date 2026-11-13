"""Cotações (0.7): dólar e Bitcoin em reais, da AwesomeAPI (economia.awesomeapi.com.br — gratuita, sem chave).

Valores sempre com a fonte e o horário; sem resposta da fonte, diz que não conseguiu (nunca inventa número).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL,BTC-BRL"


def brl(v: float, decimals: int = 2) -> str:
    s = f"{v:,.{decimals}f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float) -> str:
    return ("+" if v > 0 else "") + f"{v:.1f}".replace(".", ",") + "%"


class Finance:
    def __init__(self, url: str = URL, ttl_s: float = 600.0, client: httpx.AsyncClient | None = None, enabled: bool = True):
        self.url, self.ttl_s, self._client, self.enabled = url, ttl_s, client, enabled
        self._cache: dict[str, Any] | None = None
        self._at = 0.0

    async def get(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "Cotações desligadas (JARVIS_COTACOES=off)."}
        if self._cache and time.time() - self._at < self.ttl_s:
            return self._cache
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            resp = await client.get(self.url)
            resp.raise_for_status()
            raw = resp.json()
            out: dict[str, Any] = {"ok": True, "source": "AwesomeAPI"}
            for key, name in (("USDBRL", "usd"), ("BTCBRL", "btc")):
                q = raw.get(key)
                if q:
                    out[name] = {"bid": float(q["bid"]), "pct": float(q.get("pctChange") or 0)}
            if "usd" not in out and "btc" not in out:
                raise ValueError("resposta sem cotações")
            out["at"] = datetime.now().strftime("%H:%M")
            self._cache, self._at = out, time.time()
            return out
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
            if self._cache:
                return {**self._cache, "stale": True}
            return {"ok": False, "error": f"Não consegui as cotações agora ({type(err).__name__})."}
        finally:
            if self._client is None:
                await client.aclose()


def say_quotes(q: dict[str, Any], want: tuple[str, ...] = ("usd", "btc")) -> str:
    if not q.get("ok"):
        return q.get("error", "Cotações indisponíveis.")
    parts = []
    if "usd" in want and "usd" in q:
        parts.append(f"dólar a {brl(q['usd']['bid'])} ({pct(q['usd']['pct'])} hoje)")
    if "btc" in want and "btc" in q:
        mil = q["btc"]["bid"] / 1000
        parts.append(f"Bitcoin a {brl(mil, 0)} mil ({pct(q['btc']['pct'])})")
    if not parts:
        return "Essa cotação não veio da fonte agora."
    text = " e ".join(parts)
    return text[0].upper() + text[1:] + "."
