"""Clima real via Open-Meteo (https://open-meteo.com) — sem chave, dados CC BY 4.0.

Nada é inventado: sem resposta do provedor, `ok` é False e o HUD mostra "sem dados".
Se uma atualização falhar e houver leitura anterior, ela volta marcada como `stale`.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import Location

URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Dados meteorológicos: Open-Meteo.com (CC BY 4.0)"

# Códigos WMO usados pelo Open-Meteo → descrição em português
WMO = {
    0: "Céu limpo", 1: "Quase sem nuvens", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Neblina", 48: "Neblina com geada",
    51: "Garoa fraca", 53: "Garoa", 55: "Garoa forte", 56: "Garoa congelante", 57: "Garoa congelante forte",
    61: "Chuva fraca", 63: "Chuva", 65: "Chuva forte", 66: "Chuva congelante", 67: "Chuva congelante forte",
    71: "Neve fraca", 73: "Neve", 75: "Neve forte", 77: "Grãos de neve",
    80: "Pancadas de chuva fracas", 81: "Pancadas de chuva", 82: "Pancadas de chuva fortes",
    85: "Pancadas de neve", 86: "Pancadas de neve fortes",
    95: "Trovoadas", 96: "Trovoadas com granizo", 99: "Trovoadas com granizo forte",
}


def describe(code: int | None) -> str:
    return WMO.get(int(code), f"Condição {code}") if code is not None else "Sem informação"


class WeatherService:
    def __init__(self, location: Location, *, enabled: bool = True, ttl_s: float = 600.0, client: httpx.AsyncClient | None = None):
        self.location = location
        self.enabled = enabled
        self.ttl_s = ttl_s
        self.attempts = 3
        self.retry_delay_s = 0.7
        self._client = client
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0

    def _base(self) -> dict[str, Any]:
        loc = self.location
        return {"source": "Open-Meteo", "attribution": ATTRIBUTION, "city": loc.city, "state": loc.state_code, "timezone": loc.timezone}

    async def get(self, *, force: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return {**self._base(), "ok": False, "error": "Serviço de clima desativado (JARVIS_WEATHER_ENABLED=false)."}
        now = time.time()
        if self._cache and not force and now - self._cache_at < self.ttl_s:
            return self._cache
        try:
            data = await self._fetch_with_retry()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            if isinstance(exc, httpx.TimeoutException):
                reason = "tempo esgotado"
            elif isinstance(exc, httpx.HTTPStatusError):
                code = exc.response.status_code
                reason = "limite de consultas do provedor atingido" if code == 429 else f"o provedor respondeu HTTP {code}"
            elif isinstance(exc, httpx.TransportError):
                reason = "sem conexão com o provedor"
            else:
                reason = f"resposta inesperada ({type(exc).__name__})"
            if self._cache:
                return {**self._cache, "stale": True, "error": f"Falha ao atualizar: {reason}."}
            return {**self._base(), "ok": False, "error": f"Clima indisponível: {reason}."}
        self._cache, self._cache_at = data, now
        return data

    async def _fetch_with_retry(self) -> dict[str, Any]:
        """Falhas passageiras (rede, 5xx, 429) ganham mais duas tentativas curtas."""
        last: Exception | None = None
        for attempt in range(self.attempts):
            if attempt:
                await asyncio.sleep(self.retry_delay_s * attempt)
            try:
                return await self._fetch()
            except httpx.HTTPStatusError as exc:
                last = exc
                if exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise
            except httpx.TransportError as exc:
                last = exc
        assert last is not None
        raise last

    async def _fetch(self) -> dict[str, Any]:
        loc = self.location
        params = {
            "latitude": loc.latitude, "longitude": loc.longitude, "timezone": loc.timezone, "forecast_days": 4,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,cloud_cover,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        }
        client = self._client or httpx.AsyncClient(timeout=12.0)
        try:
            resp = await client.get(URL, params=params)
            resp.raise_for_status()
            raw = resp.json()
        finally:
            if self._client is None:
                await client.aclose()
        cur, daily = raw["current"], raw["daily"]
        days = []
        for i, day in enumerate(daily["time"]):
            days.append(
                {
                    "date": day,
                    "condition": describe(daily["weather_code"][i]),
                    "code": daily["weather_code"][i],
                    "max_c": daily["temperature_2m_max"][i],
                    "min_c": daily["temperature_2m_min"][i],
                    "rain_probability": daily["precipitation_probability_max"][i],
                    "sunrise": daily["sunrise"][i][-5:],
                    "sunset": daily["sunset"][i][-5:],
                }
            )
        fetched = datetime.now(ZoneInfo(loc.timezone))
        return {
            **self._base(),
            "ok": True,
            "stale": False,
            "observed_at": cur["time"],
            "fetched_at": fetched.isoformat(timespec="seconds"),
            "fetched_at_text": fetched.strftime("%H:%M"),
            "temperature_c": cur["temperature_2m"],
            "feels_like_c": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"],
            "wind_kmh": cur["wind_speed_10m"],
            "cloud_cover": cur["cloud_cover"],
            "precipitation_mm": cur["precipitation"],
            "is_day": bool(cur["is_day"]),
            "code": cur["weather_code"],
            "condition": describe(cur["weather_code"]),
            "today": days[0] if days else None,
            "forecast": days,
        }
