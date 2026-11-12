"""Configuração do JARVIS Core — tudo vem de variáveis de ambiente (backend/.env, fora do Git)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Location:
    city: str = "Itumbiara"
    state: str = "Goiás"
    state_code: str = "GO"
    country: str = "Brasil"
    latitude: float = -18.4192
    longitude: float = -49.2153
    timezone: str = "America/Sao_Paulo"
    language: str = "pt-BR"


@dataclass
class Settings:
    # --- IA (desabilitada enquanto não houver chave) ---
    gemini_api_key: str | None = field(default=None, repr=False)  # nunca aparece em logs/repr
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str | None = None
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_stt_model: str | None = None
    gemini_timeout_s: float = 30.0
    gemini_thinking_budget: int | None = None
    gemini_auto_model: bool = True
    history_turns: int = 16
    # --- Voz ---
    tts_engine: str = "auto"  # auto | gemini | local | off
    tts_voice: str = "Charon"
    stt_engine: str = "auto"  # auto | gemini | whisper | off
    whisper_model: str = "small"
    wake_word: str = "jarvis"
    # --- Memória ---
    memory_enabled: bool = False
    db_path: Path = BACKEND_DIR / "data" / "jarvis.sqlite3"
    # --- Servidor local ---
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: tuple[str, ...] = ()
    local_token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    # --- Serviços externos ---
    weather_enabled: bool = True
    news_rss_url: str | None = None
    devices_simulators: bool = True
    permissions_path: Path = BACKEND_DIR / "config" / "permissions.json"
    location: Location = field(default_factory=Location)

    @property
    def ai_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def origins(self) -> tuple[str, ...]:
        if self.allowed_origins:
            return self.allowed_origins
        ports = {self.port, 5173, 4173}
        return tuple(f"http://{h}:{p}" for h in ("127.0.0.1", "localhost") for p in sorted(ports))


def load_settings(env_file: Path | None = None) -> Settings:
    """Lê backend/.env (se existir) e o ambiente. Nunca registra o valor da chave."""
    load_dotenv(env_file or BACKEND_DIR / ".env", override=False)
    loc = Location(
        city=os.getenv("JARVIS_CITY", "Itumbiara"),
        state=os.getenv("JARVIS_STATE", "Goiás"),
        state_code=os.getenv("JARVIS_STATE_CODE", "GO"),
        country=os.getenv("JARVIS_COUNTRY", "Brasil"),
        latitude=_float("JARVIS_LATITUDE", -18.4192),
        longitude=_float("JARVIS_LONGITUDE", -49.2153),
        timezone=os.getenv("JARVIS_TIMEZONE", "America/Sao_Paulo"),
        language=os.getenv("JARVIS_LANGUAGE", "pt-BR"),
    )
    origins = tuple(o.strip() for o in os.getenv("JARVIS_ALLOWED_ORIGINS", "").split(",") if o.strip())
    key = (os.getenv("GEMINI_API_KEY") or "").strip() or None
    s = Settings(
        gemini_api_key=key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        gemini_fallback_model=(os.getenv("GEMINI_FALLBACK_MODEL") or "").strip() or None,
        gemini_tts_model=os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip(),
        gemini_stt_model=(os.getenv("GEMINI_STT_MODEL") or "").strip() or None,
        gemini_timeout_s=_float("GEMINI_TIMEOUT_S", 30.0),
        gemini_thinking_budget=_int("GEMINI_THINKING_BUDGET", None),
        gemini_auto_model=_bool("GEMINI_AUTO_MODEL", True),
        history_turns=_int("JARVIS_HISTORY_TURNS", 16) or 16,
        tts_engine=os.getenv("JARVIS_TTS_ENGINE", "auto").strip().lower(),
        tts_voice=os.getenv("JARVIS_TTS_VOICE", "Charon").strip(),
        stt_engine=os.getenv("JARVIS_STT_ENGINE", "auto").strip().lower(),
        whisper_model=os.getenv("JARVIS_WHISPER_MODEL", "small").strip(),
        wake_word=os.getenv("JARVIS_WAKE_WORD", "jarvis").strip().lower(),
        memory_enabled=_bool("JARVIS_MEMORY_ENABLED", False),
        db_path=Path(os.getenv("JARVIS_DB_PATH", str(BACKEND_DIR / "data" / "jarvis.sqlite3"))),
        host=os.getenv("JARVIS_HOST", "127.0.0.1"),
        port=_int("JARVIS_PORT", 8765) or 8765,
        allowed_origins=origins,
        weather_enabled=_bool("JARVIS_WEATHER_ENABLED", True),
        news_rss_url=(os.getenv("JARVIS_NEWS_RSS_URL") or "").strip() or None,
        devices_simulators=_bool("JARVIS_DEVICE_SIMULATORS", True),
        permissions_path=Path(os.getenv("JARVIS_PERMISSIONS_FILE", str(BACKEND_DIR / "config" / "permissions.json"))),
        location=loc,
    )
    token = (os.getenv("JARVIS_LOCAL_TOKEN") or "").strip()
    if token:
        s.local_token = token
    return s
