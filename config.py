import os
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("config")

PLACEHOLDER_PREFIXES = ("change_this", "your_secret", "replace_me", "xxx")

class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    PG_HOST: str = os.getenv("PG_HOST", "localhost")
    PG_DBNAME: str = os.getenv("PG_DBNAME", "ai_interviewer")
    PG_USER: str = os.getenv("PG_USER", "postgres")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
    PG_PORT: int = int(os.getenv("PG_PORT", "5432"))

    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_DAYS: int = int(os.getenv("JWT_EXPIRATION_DAYS", "1"))

    ENCRYPTION_MASTER_KEY: str = os.getenv("ENCRYPTION_MASTER_KEY", "")

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")

    SMTP_EMAIL: str = os.getenv("SMTP_EMAIL", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))

    RAZORPAY_KEY_ID: Optional[str] = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET: Optional[str] = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))

    DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "2"))
    DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "20"))

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")

    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:3000")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000/api")

    KOKORO_VOICE: str = os.getenv("KOKORO_VOICE", "af_heart")
    KOKORO_SPEED: float = float(os.getenv("KOKORO_SPEED", "1.0"))

    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_CHAT_MODEL: str = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
    GROQ_WHISPER_MODEL: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    OPENAI_RESUME_MODEL: str = os.getenv("OPENAI_RESUME_MODEL", "gpt-4o-mini")
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "groq")

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    PIPELINE_MODE: str = os.getenv("PIPELINE_MODE", "streaming")
    PIPELINE_TTFB_TARGET_MS: int = int(os.getenv("PIPELINE_TTFB_TARGET_MS", "800"))
    PIPELINE_AUDIO_SAMPLE_RATE: int = int(os.getenv("PIPELINE_AUDIO_SAMPLE_RATE", "16000"))
    PIPELINE_AUDIO_CHANNELS: int = int(os.getenv("PIPELINE_AUDIO_CHANNELS", "1"))

    COOKIE_DOMAIN: Optional[str] = os.getenv("COOKIE_DOMAIN")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "5"))
    MAX_UPLOADS_PER_DAY: int = int(os.getenv("MAX_UPLOADS_PER_DAY", "3"))
    UPLOAD_COOLDOWN_MINUTES: int = int(os.getenv("UPLOAD_COOLDOWN_MINUTES", "10"))

    PORT: int = int(os.getenv("PORT", "8000"))

    ENCRYPTION_SALT: str = os.getenv("ENCRYPTION_SALT", "interai-field-encryption-v1")

    FREE_CREDITS_ON_SIGNUP: int = int(os.getenv("FREE_CREDITS_ON_SIGNUP", "3"))
    FREE_INTERVIEW_DAILY_CAP: int = int(os.getenv("FREE_INTERVIEW_DAILY_CAP", "3"))
    RESUME_AI_FALLBACK_CONFIDENCE: float = float(os.getenv("RESUME_AI_FALLBACK_CONFIDENCE", "0.72"))
    PISTON_API_URL: str = os.getenv("PISTON_API_URL", "https://emkc.org/api/v2/piston")
    PISTON_TIMEOUT_SECONDS: int = int(os.getenv("PISTON_TIMEOUT_SECONDS", "12"))

    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    POSTHOG_API_KEY: str = os.getenv("POSTHOG_API_KEY", "")
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
    LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    AI_MAX_RETRIES: int = 2
    AI_RETRY_DELAY_SECONDS: int = 1
    AI_MAX_OUTPUT_TOKENS: int = 800
    MAX_RESUME_TEXT_LENGTH: int = 15000

    RATE_LIMIT_CALLS: int = 100
    RATE_LIMIT_WINDOW: int = 3600

    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 900

    WS_MESSAGE_RATE_LIMIT: int = 100
    WS_MESSAGE_WINDOW: int = 60
    WS_MAX_MESSAGE_SIZE: int = 1024 * 1024

    WS_TICKET_TTL_SECONDS: int = 30

    SESSION_REDIS_TTL: int = 1800
    CACHE_TTL: int = 3600

    @classmethod
    def _is_placeholder(cls, value: str) -> bool:
        lower = value.lower().strip()
        return any(lower.startswith(p) for p in PLACEHOLDER_PREFIXES)

    @classmethod
    def _is_local_url(cls, value: str) -> bool:
        parsed = urlparse(value)
        return parsed.hostname in {"localhost", "127.0.0.1", "::1"}

    @classmethod
    def _require_https(cls, field: str, value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" and not cls._is_local_url(value):
            raise RuntimeError(f"{field} must use https outside localhost")

    @classmethod
    def validate(cls):
        required = ["JWT_SECRET"]
        missing = []
        for field in required:
            val = getattr(cls, field, "")
            if not val:
                missing.append(field)
            elif cls._is_placeholder(val):
                missing.append(f"{field} (still set to placeholder value)")

        if missing:
            raise RuntimeError(f"Missing or invalid required config: {', '.join(missing)}")


        if len(cls.JWT_SECRET) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters long")

        origins = [origin.strip() for origin in cls.ALLOWED_ORIGINS.split(",") if origin.strip()]
        if not origins:
            raise RuntimeError("ALLOWED_ORIGINS must include at least one origin")
        if "*" in origins:
            raise RuntimeError("ALLOWED_ORIGINS cannot include * when credentials are enabled")

        for origin in origins:
            cls._require_https("ALLOWED_ORIGINS", origin)

        for field in ("APP_BASE_URL", "API_BASE_URL", "PISTON_API_URL", "POSTHOG_HOST", "LANGFUSE_HOST"):
            value = getattr(cls, field)
            if value:
                cls._require_https(field, value)

        if cls.ENVIRONMENT == "production" and not cls.COOKIE_SECURE:
            raise RuntimeError("COOKIE_SECURE must be true in production")

        if cls.ENCRYPTION_MASTER_KEY:
            if cls._is_placeholder(cls.ENCRYPTION_MASTER_KEY):
                raise RuntimeError("ENCRYPTION_MASTER_KEY is still a placeholder — set a real key or remove it")
            if len(cls.ENCRYPTION_MASTER_KEY) < 32:
                raise RuntimeError("ENCRYPTION_MASTER_KEY must be at least 32 characters long")

        if not cls.GOOGLE_CLIENT_ID:
            logger.warning("GOOGLE_CLIENT_ID not set - Google OAuth will be disabled")

        if not cls.SMTP_EMAIL or not cls.SMTP_PASSWORD:
            logger.warning("SMTP credentials not set - email verification will not work")

        if not cls.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set - Gemini primary LLM routing will be skipped")
        if not cls.GROQ_API_KEY:
            logger.warning("GROQ_API_KEY not set - Groq LLM fallback and Whisper STT will be unavailable")
        if not cls.RAZORPAY_KEY_ID or not cls.RAZORPAY_KEY_SECRET:
            logger.warning("Razorpay credentials not set - paid checkout will be disabled")

settings = Settings()

if os.getenv("ENVIRONMENT", "development") != "test":
    settings.validate()
