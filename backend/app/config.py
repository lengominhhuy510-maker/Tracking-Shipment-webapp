"""Application settings loaded from repo-root .env via pydantic-settings.

Variable names/defaults are canonical per Interface-Contract v0.9.9 §7.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ============ Core ============
    DATABASE_URL: str = "postgresql+asyncpg://app:app@db:5432/shipment_demo"
    REDIS_URL: str = "redis://redis:6379/0"
    APP_PORT: int = 1476
    APP_BASE_URL: str = "http://localhost:1476"
    DOMAIN: str = ""

    # ============ LLM (OpenAI-compatible) ============
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""

    # ============ Data sources ============
    AISSTREAM_API_KEY: str = ""
    AIS_MODE: str = "live"
    STORMGLASS_API_KEY: str = ""
    SEARCH_API_PROVIDER: str = "tavily"
    SEARCH_API_KEY: str = ""
    WPI_DATA_PATH: str = "/app/data/wpi_ports.csv"

    # ============ Auth ============
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    SESSION_JWT_SECRET: str = ""
    SESSION_JWT_EXPIRE_HOURS: int = 72
    COOKIE_SECURE: bool = False

    # ============ Email Agent ============
    DELEGATE_MAILBOX_IMAP_HOST: str = ""
    DELEGATE_MAILBOX_USER: str = ""
    DELEGATE_MAILBOX_PASSWORD: str = ""
    EMAIL_POLL_INTERVAL_MINUTES: int = 5
    CARRIER_EMAIL_DOMAINS: str = "maersk.com,msc.com,one-line.com,wanhai.com,evergreen-line.com"
    INTERNAL_FORWARDER_EMAILS: str = ""
    AUTO_FORWARD_RECIPIENTS: str = ""

    # ============ ETA Engine coefficients ============
    SOG_MIN_KNOT: float = 1.5
    ETA_DEVIATION_THRESHOLD_PCT: float = 10
    CURRENT_AGAINST_THRESHOLD_KN: float = 1.0
    CURRENT_AGAINST_PENALTY_PCT: float = 8
    WIND_AGAINST_THRESHOLD_KN: float = 25
    WIND_AGAINST_PENALTY_PCT: float = 5
    AVG_SOG_WINDOW_MSGS: int = 10
    ETA_RECOMPUTE_DEBOUNCE_SECONDS: int = 60
    ETA_HISTORY_MIN_DELTA_MINUTES: int = 15
    ARRIVAL_RADIUS_KM: float = 5
    TIDAL_WINDOW_HOURS: float = 2

    # ============ Poll cadence ============
    WEATHER_POLL_HOURS: int = 6
    TIDE_POLL_HOURS: int = 12
    RESEARCH_CADENCE_HOURS: int = 12
    TRAIL_SNAPSHOT_HOURS: int = 6
    AIS_RESUBSCRIBE_POLL_SECONDS: int = 60

    # ============ Node playwright-mcp ============
    SCRAPE_REST_PORT: int = 3000
    MCP_SSE_PORT: int = 3001
    SCRAPE_CONCURRENCY: int = 2
    SCRAPE_JOB_TIMEOUT_SECONDS: int = 90

    # ============ Dev seed vessel ============
    DEV_SEED_VESSEL_NAME: str = ""
    DEV_SEED_VESSEL_VOYAGE: str = ""
    DEV_SEED_VESSEL_IMO: str = ""
    DEV_SEED_VESSEL_MMSI: str = ""


settings = Settings()
