"""Configuração do JARVIS Core — tudo vem de variáveis de ambiente (backend/.env, fora do Git)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


def _env(name: str, default: str) -> str:
    """Valor da variável, ou o padrão se ela não existir OU estiver vazia (ex.: `JARVIS_MODELS_DIR=`
    no .env). Sem isso, `os.getenv(nome, padrão)` devolve "" e caminhos viram a pasta atual."""
    return (os.getenv(name) or "").strip() or default


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
    gemini_model: str = "auto"  # auto = escolhe entre os modelos que a conta lista
    gemini_fallback_model: str | None = None
    gemini_tts_model: str = "auto"
    gemini_stt_model: str | None = None
    gemini_api_version: str = "v1beta"  # a v1 não aceita instrução de sistema nem lista os modelos de voz
    gemini_timeout_s: float = 30.0
    gemini_thinking_budget: int | None = None
    gemini_low_latency: bool = True  # pede raciocínio mínimo para a fala começar antes
    gemini_probe_models: bool = False  # 0.3: não gasta cota testando modelos ao iniciar; aprende com o uso real
    gemini_probe_timeout_s: float = 8.0
    gemini_max_first_token_s: float = 1.5  # tempo-alvo até o 1º trecho ao escolher o modelo
    gemini_first_token_timeout_s: float = 12.0
    gemini_probe_ttl_s: float = 12 * 3600.0  # por quanto tempo vale o modelo escolhido no último teste
    gemini_failover_models: int = 5          # quantos modelos tentar em um mesmo pedido
    gemini_auto_model: bool = True
    history_turns: int = 16
    # --- Voz ---
    tts_engine: str = "auto"  # auto | gemini | piper | local | off
    tts_voice: str = "Charon"
    tts_style: str = "cinematografico"
    tts_parallel: int = 3
    tts_chunking: str = "economico"  # economico = no máximo 2 requisições de voz por resposta | frase = uma por frase
    stt_engine: str = "auto"  # auto | gemini | whisper | off
    whisper_model: str = "small"
    whisper_device: str = "auto"      # auto | cpu | cuda
    whisper_compute: str = "int8"
    wake_word: str = "jarvis"
    wake_engine: str = "auto"         # auto | openwakeword | whisper | off — sempre local
    wake_threshold: float = 0.5
    wake_model: str | None = None     # modelo .onnx próprio de "jarvis"; padrão: hey_jarvis do openWakeWord
    conversation_window_s: float = 8.0  # depois de uma resposta, segue ouvindo sem exigir "Jarvis"
    piper_model: Path | None = None
    # --- Roteador ---
    router_mode: str = "local_first"  # local_first = comandos conhecidos não gastam Gemini | ai_first
    # --- Modelos locais ---
    models_dir: Path = BACKEND_DIR / "models"
    # --- LEDs Bluetooth (ELK-BLEDDM) ---
    leds_mode: str = "simulador"      # simulador | bluetooth | off
    led_address: str | None = None
    led_name_prefix: str = "ELK-BLEDDM"
    led_effects: str = "voz,inicio"  # efeitos na fita real: voz (acompanha a fala), inicio (abertura) ou off
    led_brightness: str = "cor"        # cor (escurece a cor; validado) | comando (7e 04 01; não validado)
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
    #: feeds de notícias (rótulo, url); None = padrão (Google Notícias da cidade e do Brasil)
    news_feeds: tuple[tuple[str, str], ...] | None = None
    devices_simulators: bool = True
    # --- Entrada por rosto (0.4) ---
    face_threshold: float = 0.62      # semelhança mínima (0..1) para liberar
    face_liveness: str = "piscar"     # piscar | desligado
    face_relock_min: float = 2.0      # HUD fechado por mais que isso → pede o rosto de novo
    face_antispoof_min: float = 0.0   # 0 = só registra a nota anti-foto; calibre no seu PC antes de ligar
    # --- Mapa real (OpenStreetMap) ---
    map_radius_m: int = 1800
    # --- Luzes de casa (Smart Life / Tuya, rede local) ---
    tuya_devices: Path | None = None   # padrão: backend/data/tuya/devices.json
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    allow_lan: bool = False  # acesso pela rede só com autorização explícita e token forte
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


def _feeds(raw: str | None) -> tuple[tuple[str, str], ...] | None:
    """JARVIS_NEWS_FEEDS: vazio = padrão; "off" = desliga; "Rótulo|url;Rótulo|url" = os seus."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lower() in ("off", "desligado", "false", "0"):
        return ()
    out = []
    for part in raw.split(";"):
        label, _, url = part.partition("|")
        if url.strip().startswith(("http://", "https://")):
            out.append((label.strip() or "Notícias", url.strip()))
    return tuple(out)


def load_settings(env_file: Path | None = None) -> Settings:
    """Lê backend/.env (se existir) e o ambiente. Nunca registra o valor da chave."""
    load_dotenv(env_file or BACKEND_DIR / ".env", override=False)
    loc = Location(
        city=_env("JARVIS_CITY", "Itumbiara"),
        state=_env("JARVIS_STATE", "Goiás"),
        state_code=_env("JARVIS_STATE_CODE", "GO"),
        country=_env("JARVIS_COUNTRY", "Brasil"),
        latitude=_float("JARVIS_LATITUDE", -18.4192),
        longitude=_float("JARVIS_LONGITUDE", -49.2153),
        timezone=_env("JARVIS_TIMEZONE", "America/Sao_Paulo"),
        language=_env("JARVIS_LANGUAGE", "pt-BR"),
    )
    origins = tuple(o.strip() for o in _env("JARVIS_ALLOWED_ORIGINS", "").split(",") if o.strip())
    key = (os.getenv("GEMINI_API_KEY") or "").strip() or None
    s = Settings(
        gemini_api_key=key,
        gemini_model=(os.getenv("GEMINI_MODEL") or "auto").strip(),
        gemini_fallback_model=(os.getenv("GEMINI_FALLBACK_MODEL") or "").strip() or None,
        gemini_tts_model=(os.getenv("GEMINI_TTS_MODEL") or "auto").strip(),
        gemini_stt_model=(os.getenv("GEMINI_STT_MODEL") or "").strip() or None,
        gemini_api_version=(os.getenv("GEMINI_API_VERSION") or "v1beta").strip(),
        gemini_timeout_s=_float("GEMINI_TIMEOUT_S", 30.0),
        gemini_thinking_budget=_int("GEMINI_THINKING_BUDGET", None),
        gemini_low_latency=_bool("GEMINI_LOW_LATENCY", True),
        gemini_probe_models=_bool("GEMINI_PROBE_MODELS", False),
        gemini_max_first_token_s=_float("GEMINI_MAX_FIRST_TOKEN_S", 1.5),
        gemini_first_token_timeout_s=_float("GEMINI_FIRST_TOKEN_TIMEOUT_S", 12.0),
        gemini_auto_model=_bool("GEMINI_AUTO_MODEL", True),
        history_turns=_int("JARVIS_HISTORY_TURNS", 16) or 16,
        tts_engine=_env("JARVIS_TTS_ENGINE", "auto").strip().lower(),
        tts_voice=_env("JARVIS_TTS_VOICE", "Charon").strip(),
        tts_style=_env("JARVIS_TTS_STYLE", "cinematografico").strip().lower(),
        tts_parallel=max(1, min(_int("JARVIS_TTS_PARALLEL", 3) or 3, 6)),
        tts_chunking=(os.getenv("JARVIS_TTS_CHUNKING") or "economico").strip().lower(),
        stt_engine=_env("JARVIS_STT_ENGINE", "auto").strip().lower(),
        whisper_model=_env("JARVIS_WHISPER_MODEL", "small").strip(),
        whisper_device=(os.getenv("JARVIS_WHISPER_DEVICE") or "auto").strip().lower(),
        whisper_compute=(os.getenv("JARVIS_WHISPER_COMPUTE") or "int8").strip().lower(),
        wake_word=_env("JARVIS_WAKE_WORD", "jarvis").strip().lower(),
        wake_engine=(os.getenv("JARVIS_WAKE_ENGINE") or "auto").strip().lower(),
        wake_threshold=_float("JARVIS_WAKE_THRESHOLD", 0.5),
        wake_model=(os.getenv("JARVIS_WAKE_MODEL") or "").strip() or None,
        conversation_window_s=_float("JARVIS_CONVERSATION_WINDOW_S", 8.0),
        piper_model=Path(os.getenv("JARVIS_PIPER_MODEL")) if os.getenv("JARVIS_PIPER_MODEL") else None,
        router_mode=(os.getenv("JARVIS_ROUTER") or "local_first").strip().lower(),
        models_dir=Path(_env("JARVIS_MODELS_DIR", str(BACKEND_DIR / "models"))),
        leds_mode=(os.getenv("JARVIS_LEDS") or "simulador").strip().lower(),
        led_address=(os.getenv("JARVIS_LED_ADDRESS") or "").strip() or None,
        led_name_prefix=(os.getenv("JARVIS_LED_NAME_PREFIX") or "ELK-BLEDDM").strip(),
        led_brightness=(os.getenv("JARVIS_LED_BRILHO") or "cor").strip().lower(),
        led_effects=_env("JARVIS_LED_EFEITOS", "voz,inicio").lower(),
        allow_lan=_bool("JARVIS_ALLOW_LAN", False),
        memory_enabled=_bool("JARVIS_MEMORY_ENABLED", False),
        db_path=Path(_env("JARVIS_DB_PATH", str(BACKEND_DIR / "data" / "jarvis.sqlite3"))),
        host=_env("JARVIS_HOST", "127.0.0.1"),
        port=_int("JARVIS_PORT", 8765) or 8765,
        allowed_origins=origins,
        weather_enabled=_bool("JARVIS_WEATHER_ENABLED", True),
        news_rss_url=(os.getenv("JARVIS_NEWS_RSS_URL") or "").strip() or None,
        news_feeds=_feeds(os.getenv("JARVIS_NEWS_FEEDS")),
        face_threshold=_float("JARVIS_FACE_THRESHOLD", 0.62),
        face_liveness=(os.getenv("JARVIS_FACE_LIVENESS") or "piscar").strip().lower(),
        face_relock_min=_float("JARVIS_FACE_RELOCK_MIN", 2.0),
        face_antispoof_min=_float("JARVIS_FACE_ANTISPOOF_MIN", 0.0),
        tuya_devices=Path(os.getenv("JARVIS_TUYA_DEVICES")) if os.getenv("JARVIS_TUYA_DEVICES") else None,
        map_radius_m=max(500, min(4000, _int("JARVIS_MAP_RADIUS_M", 1800) or 1800)),
        overpass_url=(os.getenv("JARVIS_OVERPASS_URL") or "https://overpass-api.de/api/interpreter").strip(),
        devices_simulators=_bool("JARVIS_DEVICE_SIMULATORS", True),
        permissions_path=Path(_env("JARVIS_PERMISSIONS_FILE", str(BACKEND_DIR / "config" / "permissions.json"))),
        location=loc,
    )
    token = (os.getenv("JARVIS_LOCAL_TOKEN") or "").strip()
    if token:
        s.local_token = token
    return s
