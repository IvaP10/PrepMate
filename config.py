"""Small local-runtime configuration surface.

PrepMate has no deployment, account, billing, remote-database, or telemetry
configuration. Provider credentials are deliberately absent from this file;
the selected key is read from the operating-system keychain by ``local_runtime``.
"""

from __future__ import annotations

import os


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() == "true"


class Settings:
    PREPMATE_DESKTOP_MODE: bool = True
    LOCAL_DATA_DIR: str = (os.getenv("PREPMATE_DATA_DIR", "").strip() or os.getenv("INTERAI_DATA_DIR", "").strip())
    LOCAL_PROVIDER: str = (os.getenv("PREPMATE_PROVIDER", "").strip() or os.getenv("INTERAI_PROVIDER", "openai")).strip().lower()
    LOCAL_MODEL: str = (os.getenv("PREPMATE_MODEL", "").strip() or os.getenv("INTERAI_MODEL", "gpt-5-mini")).strip()
    LOCAL_PROVIDER_TIMEOUT_SECONDS: float = float(os.getenv("PREPMATE_PROVIDER_TIMEOUT", os.getenv("INTERAI_PROVIDER_TIMEOUT", "60")))

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
    PORT: int = int(os.getenv("PORT", "8000"))
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api")
    MAX_REQUEST_BODY_MB: int = int(os.getenv("MAX_REQUEST_BODY_MB", "50"))
    RESUME_MAX_FILE_SIZE_MB: int = int(os.getenv("RESUME_MAX_FILE_SIZE_MB", "4"))
    MAX_RESUME_TEXT_LENGTH: int = int(os.getenv("MAX_RESUME_TEXT_LENGTH", "50000"))

    AI_MAX_RETRIES: int = int(os.getenv("AI_MAX_RETRIES", "2"))
    AI_RETRY_DELAY_SECONDS: float = float(os.getenv("AI_RETRY_DELAY_SECONDS", "1"))
    OPENAI_TRANSCRIBE_MODEL: str = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))
    OPENAI_MAX_RETRIES: int = int(os.getenv("OPENAI_MAX_RETRIES", "2"))

    RAW_VIDEO_RETENTION_HOURS: int = int(os.getenv("RAW_VIDEO_RETENTION_HOURS", "0"))
    AUDIO_RETENTION_DAYS: int = int(os.getenv("AUDIO_RETENTION_DAYS", "0"))
    MEDIA_UPLOAD_PROVIDER: str = "local_manifest"

    DEVELOPMENT_AUTO_WORKER: bool = _bool("DEVELOPMENT_AUTO_WORKER", "true")
    TECHNICAL_CODING_ONLY: bool = _bool("TECHNICAL_CODING_ONLY", "true")
    TECHNICAL_ALLOW_AUTHORED_FALLBACK: bool = _bool("TECHNICAL_ALLOW_AUTHORED_FALLBACK", "true")
    WS_MESSAGE_RATE_LIMIT: int = int(os.getenv("WS_MESSAGE_RATE_LIMIT", "100"))
    WS_MESSAGE_WINDOW: int = int(os.getenv("WS_MESSAGE_WINDOW", "60"))
    WS_MAX_MESSAGE_SIZE: int = int(os.getenv("WS_MAX_MESSAGE_SIZE", str(1024 * 1024)))
    SESSION_RECOVERY_GRACE_SECONDS: int = int(os.getenv("SESSION_RECOVERY_GRACE_SECONDS", "60"))

    @classmethod
    def validate(cls) -> None:
        if cls.LOCAL_PROVIDER not in {"openai", "anthropic", "google", "openai_compatible"}:
            raise RuntimeError("PREPMATE_PROVIDER must be openai, anthropic, google, or openai_compatible")
        if not cls.LOCAL_MODEL:
            raise RuntimeError("PREPMATE_MODEL cannot be empty")
        if cls.RESUME_MAX_FILE_SIZE_MB <= 0:
            raise RuntimeError("RESUME_MAX_FILE_SIZE_MB must be greater than zero")
        if cls.MAX_REQUEST_BODY_MB <= 0 or cls.MAX_RESUME_TEXT_LENGTH <= 0:
            raise RuntimeError("Local request and resume limits must be positive")


settings = Settings()
settings.validate()
