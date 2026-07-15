# ============================================================================
# MODULE: config.py
# PURPOSE: Centralized Settings — env-var loading + production validation rules.
#          Imported by every module via `from config import settings`.
# STRUCTURE:
#   - PLACEHOLDER_PREFIXES (line 21)
#   - Settings class — every env var with default or empty fallback (lines 23-130)
#   - validation helpers _is_placeholder / _is_local_url / _require_https
#   - validate() — invariants that hold up boot (lines 153-220)
#   - settings singleton + boot-time validate() (lines 222-225)
# ENDPOINTS: none
# DEPENDS ON: stdlib only
# CONSUMED BY: every module touching env-configurable values
# DATA TABLES: none today (Phase 3 moves business tunables into `app_config`)
# ============================================================================

import os
import logging
import ipaddress
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("config")

PLACEHOLDER_PREFIXES = ("change_this", "your_secret", "replace_me", "xxx")

class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    PG_HOST: str = os.getenv("PG_HOST", "localhost")
    PG_DBNAME: str = os.getenv("PG_DBNAME", "ai_interviewer")
    PG_USER: str = os.getenv("PG_USER", "postgres")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
    PG_PORT: int = int(os.getenv("PG_PORT", "5432"))

    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_DAYS: int = int(os.getenv("JWT_EXPIRATION_DAYS", "30"))

    ENCRYPTION_MASTER_KEY: str = os.getenv("ENCRYPTION_MASTER_KEY", "")
    ENCRYPTION_KEY_VERSION: str = os.getenv("ENCRYPTION_KEY_VERSION", "v1")
    ENCRYPTION_KEYRING_JSON: str = os.getenv("ENCRYPTION_KEYRING_JSON", "")

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
    KOKORO_TIMEOUT_SECONDS: int = int(os.getenv("KOKORO_TIMEOUT_SECONDS", "8"))
    KOKORO_PREWARM_TIMEOUT_SECONDS: int = int(os.getenv("KOKORO_PREWARM_TIMEOUT_SECONDS", "60"))

    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")
    OPENAI_REPORT_MODEL: str = os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini")
    OPENAI_RESUME_MODEL: str = os.getenv("OPENAI_RESUME_MODEL", "gpt-4o-mini")
    OPENAI_QUESTION_MODEL: str = os.getenv("OPENAI_QUESTION_MODEL", "gpt-5-mini")
    OPENAI_EVALUATION_MODEL: str = os.getenv("OPENAI_EVALUATION_MODEL", "gpt-5-nano")
    OPENAI_TRANSCRIBE_MODEL: str = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    MODEL_DEFAULT_POLICY: str = os.getenv("MODEL_DEFAULT_POLICY", "openai_required")
    MODEL_EXTERNAL_INPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EXTERNAL_INPUT_COST_PER_M_TOKENS", "0.75"))
    MODEL_EXTERNAL_CACHED_INPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EXTERNAL_CACHED_INPUT_COST_PER_M_TOKENS", "0.075"))
    MODEL_EXTERNAL_OUTPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EXTERNAL_OUTPUT_COST_PER_M_TOKENS", "4.50"))
    MODEL_EVALUATION_INPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EVALUATION_INPUT_COST_PER_M_TOKENS", "0.20"))
    MODEL_EVALUATION_CACHED_INPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EVALUATION_CACHED_INPUT_COST_PER_M_TOKENS", "0.02"))
    MODEL_EVALUATION_OUTPUT_COST_PER_M_TOKENS: float = float(os.getenv("MODEL_EVALUATION_OUTPUT_COST_PER_M_TOKENS", "1.25"))
    MODEL_MAX_INTERVIEW_COST_USD: float = float(os.getenv("MODEL_MAX_INTERVIEW_COST_USD", "0.75"))
    MODEL_MAX_LIVE_EVALUATIONS_PER_INTERVIEW: int = int(os.getenv("MODEL_MAX_LIVE_EVALUATIONS_PER_INTERVIEW", "12"))
    MODEL_MONTHLY_BUDGET_USD: float = float(os.getenv("MODEL_MONTHLY_BUDGET_USD", "2500"))
    MODEL_MONTHLY_WARN_RATIO: float = float(os.getenv("MODEL_MONTHLY_WARN_RATIO", "0.80"))
    MODEL_MONTHLY_HARD_STOP_RATIO: float = float(os.getenv("MODEL_MONTHLY_HARD_STOP_RATIO", "0.98"))

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "interai-api")
    METRICS_BEARER_TOKEN: str = os.getenv("METRICS_BEARER_TOKEN", "")

    PIPELINE_MODE: str = os.getenv("PIPELINE_MODE", "streaming")
    PIPELINE_TTFB_TARGET_MS: int = int(os.getenv("PIPELINE_TTFB_TARGET_MS", "800"))
    PIPELINE_AUDIO_SAMPLE_RATE: int = int(os.getenv("PIPELINE_AUDIO_SAMPLE_RATE", "16000"))
    PIPELINE_AUDIO_CHANNELS: int = int(os.getenv("PIPELINE_AUDIO_CHANNELS", "1"))

    COOKIE_DOMAIN: Optional[str] = os.getenv("COOKIE_DOMAIN")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    MAX_REQUEST_BODY_MB: int = int(os.getenv("MAX_REQUEST_BODY_MB", "50"))
    RESUME_MAX_FILE_SIZE_MB: int = int(os.getenv("RESUME_MAX_FILE_SIZE_MB", "4"))

    PORT: int = int(os.getenv("PORT", "8000"))

    ENCRYPTION_SALT: str = os.getenv("ENCRYPTION_SALT", "")

    FREE_CREDITS_ON_SIGNUP: int = int(os.getenv("FREE_CREDITS_ON_SIGNUP", "3"))
    FREE_INTERVIEW_DAILY_CAP: int = int(os.getenv("FREE_INTERVIEW_DAILY_CAP", "3"))
    RESUME_AI_FALLBACK_CONFIDENCE: float = float(os.getenv("RESUME_AI_FALLBACK_CONFIDENCE", "0.72"))
    PISTON_API_URL: str = os.getenv("PISTON_API_URL", "http://sandbox:8080/api/v2")
    # Docker Compose loads `key.env` into containers after resolving compose
    # interpolation.  Use the first non-empty value so an empty
    # PISTON_API_TOKEN environment entry cannot mask the configured internal
    # token (or the legacy JWT-secret fallback used by existing deployments).
    PISTON_API_TOKEN: str = (
        os.getenv("PISTON_API_TOKEN")
        or os.getenv("INTERNAL_SERVICE_TOKEN")
        or os.getenv("JWT_SECRET", "")
    )
    PISTON_TIMEOUT_SECONDS: int = int(os.getenv("PISTON_TIMEOUT_SECONDS", "10"))
    PISTON_NORMAL_TIMEOUT_SECONDS: int = int(os.getenv("PISTON_NORMAL_TIMEOUT_SECONDS", "2"))
    PISTON_ABSOLUTE_TIMEOUT_SECONDS: int = int(os.getenv("PISTON_ABSOLUTE_TIMEOUT_SECONDS", "10"))
    PISTON_MEMORY_LIMIT_BYTES: int = int(os.getenv("PISTON_MEMORY_LIMIT_BYTES", str(256 * 1024 * 1024)))
    PISTON_PROCESS_LIMIT: int = int(os.getenv("PISTON_PROCESS_LIMIT", "32"))
    PISTON_SOURCE_LIMIT_BYTES: int = int(os.getenv("PISTON_SOURCE_LIMIT_BYTES", str(20 * 1024)))
    PISTON_OUTPUT_LIMIT_BYTES: int = int(os.getenv("PISTON_OUTPUT_LIMIT_BYTES", str(64 * 1024)))
    PISTON_EXPECTED_RUNTIMES: str = os.getenv(
        "PISTON_EXPECTED_RUNTIMES",
        "python,javascript,java,c++",
    )
    JUDGE0_API_URL: str = os.getenv("JUDGE0_API_URL", "")
    JUDGE0_API_KEY: str = os.getenv("JUDGE0_API_KEY", "")
    JUDGE0_TIMEOUT_SECONDS: int = int(os.getenv("JUDGE0_TIMEOUT_SECONDS", "15"))
    TECHNICAL_FAST_FALLBACK_FIRST: bool = os.getenv("TECHNICAL_FAST_FALLBACK_FIRST", "false").lower() == "true"
    E2B_API_KEY: str = os.getenv("E2B_API_KEY", "")
    GPTZERO_API_KEY: str = os.getenv("GPTZERO_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET: str = os.getenv("R2_BUCKET", "")
    R2_PUBLIC_BASE_URL: str = os.getenv("R2_PUBLIC_BASE_URL", "")
    MEDIA_UPLOAD_PROVIDER: str = os.getenv("MEDIA_UPLOAD_PROVIDER", "local_manifest")
    RAW_VIDEO_RETENTION_HOURS: int = int(os.getenv("RAW_VIDEO_RETENTION_HOURS", "0"))
    AUDIO_RETENTION_DAYS: int = int(os.getenv("AUDIO_RETENTION_DAYS", "0"))
    WORKER_HEARTBEAT_MAX_AGE_SECONDS: int = int(
        os.getenv("WORKER_HEARTBEAT_MAX_AGE_SECONDS", "45")
    )

    TRIGGER_DEV_API_KEY: str = os.getenv("TRIGGER_DEV_API_KEY", "")
    TRIGGER_DEV_API_URL: str = os.getenv("TRIGGER_DEV_API_URL", "")
    MODAL_ANALYSIS_ENDPOINT: str = os.getenv("MODAL_ANALYSIS_ENDPOINT", "")

    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    POSTHOG_API_KEY: str = os.getenv("POSTHOG_API_KEY", "")
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
    LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    AI_MAX_RETRIES: int = 2
    AI_RETRY_DELAY_SECONDS: int = 1
    AI_MAX_OUTPUT_TOKENS: int = 800
    MAX_RESUME_TEXT_LENGTH: int = int(os.getenv("MAX_RESUME_TEXT_LENGTH", "50000"))

    RATE_LIMIT_CALLS: int = 100
    RATE_LIMIT_WINDOW: int = 3600

    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 900

    WS_MESSAGE_RATE_LIMIT: int = 100
    WS_MESSAGE_WINDOW: int = 60
    WS_MAX_MESSAGE_SIZE: int = 1024 * 1024

    WS_TICKET_TTL_SECONDS: int = 30
    SESSION_RECOVERY_GRACE_SECONDS: int = int(os.getenv("SESSION_RECOVERY_GRACE_SECONDS", "60"))

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
    def _is_private_service_url(cls, value: str) -> bool:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname in {"localhost", "127.0.0.1", "::1", "piston"}:
            return True
        if "." not in hostname or hostname.endswith((".internal", ".local")):
            return True
        try:
            return ipaddress.ip_address(hostname).is_private
        except ValueError:
            return False

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

        for field in ("APP_BASE_URL", "API_BASE_URL", "POSTHOG_HOST", "LANGFUSE_HOST"):
            value = getattr(cls, field)
            if value:
                cls._require_https(field, value)

        if cls.ENVIRONMENT == "production" and not cls._is_private_service_url(cls.PISTON_API_URL):
            raise RuntimeError(
                "PISTON_API_URL must point to the private isolated execution service"
            )
        if cls.ENVIRONMENT != "production" and not cls._is_private_service_url(cls.PISTON_API_URL):
            logger.warning(
                "PISTON_API_URL is public; development may probe it, but production will refuse to start"
            )
        if cls.ENVIRONMENT == "production" and len(cls.PISTON_API_TOKEN) < 32:
            raise RuntimeError("PISTON_API_TOKEN must contain at least 32 characters in production")
        if cls.PISTON_NORMAL_TIMEOUT_SECONDS <= 0 or cls.PISTON_NORMAL_TIMEOUT_SECONDS > 2:
            raise RuntimeError("PISTON_NORMAL_TIMEOUT_SECONDS must be between 1 and 2")
        if cls.PISTON_ABSOLUTE_TIMEOUT_SECONDS > 10:
            raise RuntimeError("PISTON_ABSOLUTE_TIMEOUT_SECONDS cannot exceed 10")
        if cls.PISTON_MEMORY_LIMIT_BYTES > 256 * 1024 * 1024:
            raise RuntimeError("PISTON_MEMORY_LIMIT_BYTES cannot exceed 256 MB")
        if cls.PISTON_PROCESS_LIMIT > 32:
            raise RuntimeError("PISTON_PROCESS_LIMIT cannot exceed 32")
        if cls.PISTON_SOURCE_LIMIT_BYTES > 20 * 1024:
            raise RuntimeError("PISTON_SOURCE_LIMIT_BYTES cannot exceed 20 KB")
        if cls.PISTON_OUTPUT_LIMIT_BYTES > 64 * 1024:
            raise RuntimeError("PISTON_OUTPUT_LIMIT_BYTES cannot exceed 64 KB")

        if cls.ENVIRONMENT == "production" and not cls.COOKIE_SECURE:
            raise RuntimeError("COOKIE_SECURE must be true in production")

        if cls.ENCRYPTION_MASTER_KEY:
            if cls._is_placeholder(cls.ENCRYPTION_MASTER_KEY):
                raise RuntimeError("ENCRYPTION_MASTER_KEY is still a placeholder - set a real key or remove it")
            if len(cls.ENCRYPTION_MASTER_KEY) < 32:
                raise RuntimeError("ENCRYPTION_MASTER_KEY must be at least 32 characters long")
        elif cls.ENVIRONMENT == "production":
            raise RuntimeError("ENCRYPTION_MASTER_KEY must be set in production")

        if not cls.ENCRYPTION_SALT:
            if cls.ENVIRONMENT == "production":
                raise RuntimeError("ENCRYPTION_SALT must be set in production (used to derive field-encryption keys)")
            logger.warning("ENCRYPTION_SALT not set - field-level encryption will use an empty salt (development only)")

        if not cls.GOOGLE_CLIENT_ID:
            logger.warning("GOOGLE_CLIENT_ID not set - Google OAuth will be disabled")

        if not cls.SMTP_EMAIL or not cls.SMTP_PASSWORD:
            logger.warning("SMTP credentials not set - email verification will not work")

        if cls.MODEL_DEFAULT_POLICY != "openai_required":
            raise RuntimeError("MODEL_DEFAULT_POLICY must be openai_required")
        if cls.ENVIRONMENT == "production" and not cls.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY must be set in production when OpenAI is the primary model provider")
        if cls.MODEL_MONTHLY_BUDGET_USD <= 0:
            raise RuntimeError("MODEL_MONTHLY_BUDGET_USD must be greater than 0")
        if cls.MODEL_MAX_INTERVIEW_COST_USD <= 0:
            raise RuntimeError("MODEL_MAX_INTERVIEW_COST_USD must be greater than 0")
        if cls.MODEL_MAX_LIVE_EVALUATIONS_PER_INTERVIEW < 0:
            raise RuntimeError("MODEL_MAX_LIVE_EVALUATIONS_PER_INTERVIEW cannot be negative")
        if not 15 <= cls.SESSION_RECOVERY_GRACE_SECONDS <= 300:
            raise RuntimeError("SESSION_RECOVERY_GRACE_SECONDS must be between 15 and 300")
        if not 0 < cls.MODEL_MONTHLY_WARN_RATIO < cls.MODEL_MONTHLY_HARD_STOP_RATIO <= 1:
            raise RuntimeError("MODEL_MONTHLY_WARN_RATIO and MODEL_MONTHLY_HARD_STOP_RATIO must be ordered between 0 and 1")
        razorpay_fields = ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET")
        missing_razorpay = [field for field in razorpay_fields if not getattr(cls, field)]
        if cls.ENVIRONMENT == "production" and missing_razorpay:
            raise RuntimeError(
                "Missing required Razorpay production config: " + ", ".join(missing_razorpay)
            )
        if missing_razorpay:
            logger.warning(
                "Razorpay config incomplete (%s) - paid checkout or webhook reconciliation will be disabled",
                ", ".join(missing_razorpay),
            )

settings = Settings()

if os.getenv("ENVIRONMENT", "development") != "test":
    settings.validate()
