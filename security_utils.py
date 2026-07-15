# ============================================================================
# MODULE: security_utils.py
# PURPOSE: Logging-safety helpers, field encryption, and PII redaction before
#          external model/provider calls.
# STRUCTURE:
#   - EMAIL_RE / TOKEN_RE regexes
#   - stable_hash / redact_text (logging)
#   - redact_pii_text / redact_messages_for_external (external AI providers)
#   - encrypt_data / decrypt_data / encrypt_json / decrypt_json
# ENDPOINTS: none
# DEPENDS ON: (stdlib only; config for encryption)
# CONSUMED BY: auth, redis_client, observability, llm_router, ai_services,
#              interview, dashboard, payment, technical_mode, pre_interview,
#              knowledge_map
# DATA TABLES: none
# ============================================================================

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Sequence

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_RE = re.compile(r"(?i)(token|secret|password|signature|api[_-]?key)=([^&\s]+)")

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)

PHONE_PATTERNS = [
    re.compile(r"\+\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    re.compile(r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}"),
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    re.compile(r"\b\d{10}\b"),
    re.compile(r"\+\d{1,3}[-.\s]?\d{4,5}[-.\s]?\d{5,6}"),
]

SOCIAL_PATTERNS = [
    re.compile(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"https?://(?:www\.)?twitter\.com/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"https?://(?:www\.)?x\.com/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9_./-]+/?", re.I),
    re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_./-]+/?", re.I),
    re.compile(r"linkedin\.com/in/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"github\.com/[A-Za-z0-9_-]+/?", re.I),
    re.compile(r"https?://[A-Za-z0-9_-]+\.(?:me|dev|io|com|org|net)/[^\s]*", re.I),
]

CREDIT_CARD_PATTERNS = [
    re.compile(r"\b4\d{3}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    re.compile(r"\b5[1-5]\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    re.compile(r"\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b"),
    re.compile(r"\b6(?:011|5\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"),
]

SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DOB_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)


def stable_hash(value: Any, prefix: str = "id") -> str:
    text = str(value or "")
    if not text:
        return f"{prefix}:empty"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub("[EMAIL]", text)
    return TOKEN_RE.sub(r"\1=[REDACTED]", text)


def redact_pii_text(text: str, *, extra_values: Iterable[str] | None = None) -> str:
    """Best-effort removal of direct identifiers from free text before external provider calls."""
    cleaned = str(text or "")
    if not cleaned:
        return cleaned

    for value in _sorted_identifier_values(extra_values):
        cleaned = cleaned.replace(value, "[NAME_REMOVED]")

    cleaned = EMAIL_PATTERN.sub("[EMAIL_REMOVED]", cleaned)
    for pattern in PHONE_PATTERNS:
        cleaned = pattern.sub("[PHONE_REMOVED]", cleaned)
    for pattern in SOCIAL_PATTERNS:
        cleaned = pattern.sub("[LINK_REMOVED]", cleaned)
    for pattern in CREDIT_CARD_PATTERNS:
        cleaned = pattern.sub("[CARD_REMOVED]", cleaned)
    cleaned = SSN_PATTERN.sub("[SSN_REMOVED]", cleaned)
    cleaned = DOB_PATTERN.sub("[DOB_REMOVED]", cleaned)
    return cleaned


def collect_profile_identifiers(*profiles: Any) -> List[str]:
    """Collect known profile identifiers for targeted redaction."""
    values: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for key in ("name", "email", "phone", "linkedin", "github", "portfolio"):
            raw = profile.get(key)
            if isinstance(raw, str) and raw.strip():
                values.add(raw.strip())
        links = profile.get("links")
        if isinstance(links, dict):
            for raw in links.values():
                if isinstance(raw, str) and raw.strip():
                    values.add(raw.strip())
        name = profile.get("name")
        if isinstance(name, str):
            for part in name.split():
                if len(part) >= 2:
                    values.add(part)
    return _sorted_identifier_values(values)


def redact_messages_for_external(messages: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Return a copy of chat messages with best-effort PII stripping for third-party model APIs."""
    redacted: List[Dict[str, str]] = []
    for message in messages:
        redacted.append(
            {
                "role": str(message.get("role", "user")),
                "content": redact_pii_text(str(message.get("content", ""))),
            }
        )
    return redacted


def _sorted_identifier_values(values: Iterable[str] | None) -> List[str]:
    unique = {str(value).strip() for value in (values or []) if str(value).strip()}
    return sorted(unique, key=len, reverse=True)


def _configured_master_key() -> str:
    from config import settings

    key_str = settings.ENCRYPTION_MASTER_KEY
    if not key_str:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError("ENCRYPTION_MASTER_KEY is required for field encryption")
        key_str = "development-only-interai-field-encryption-key"
    return key_str


def _configured_keyring() -> Dict[str, str]:
    from config import settings

    keyring: Dict[str, str] = {}
    if settings.ENCRYPTION_KEYRING_JSON:
        try:
            parsed = json.loads(settings.ENCRYPTION_KEYRING_JSON)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ENCRYPTION_KEYRING_JSON must be valid JSON") from exc
        if not isinstance(parsed, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
            raise RuntimeError("ENCRYPTION_KEYRING_JSON must map versions to master keys")
        keyring.update(parsed)
    keyring[settings.ENCRYPTION_KEY_VERSION] = _configured_master_key()
    return keyring


def _field_encryption_key(master_key: str | None = None) -> bytes:
    from config import settings

    key_material = f"{master_key or _configured_master_key()}:{settings.ENCRYPTION_SALT or 'development-only-salt'}"
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def _legacy_field_encryption_key() -> bytes:
    return hashlib.sha256(_configured_master_key().encode("utf-8")).digest()


def encrypt_data(plaintext: str) -> str:
    """
    Encrypts plaintext using AES-GCM and the ENCRYPTION_MASTER_KEY from settings.
    Returns base64 encoded ciphertext with prepended 12-byte IV.
    """
    if not plaintext:
        return ""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os
    import base64

    from config import settings

    version = settings.ENCRYPTION_KEY_VERSION
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", version):
        raise RuntimeError("ENCRYPTION_KEY_VERSION is invalid")
    aesgcm = AESGCM(_field_encryption_key())
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), version.encode("ascii"))

    combined = iv + ciphertext
    return f"enc:{version}:{base64.b64encode(combined).decode('utf-8')}"


def decrypt_data(ciphertext_b64: str) -> str:
    """
    Decrypts base64 encoded AES-GCM ciphertext.
    Falls back gracefully to original text if decryption fails (supporting legacy data).
    """
    if not ciphertext_b64:
        return ""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64

    try:
        version = None
        encoded = ciphertext_b64
        if ciphertext_b64.startswith("enc:"):
            parts = ciphertext_b64.split(":", 2)
            if len(parts) != 3 or not parts[1]:
                return ciphertext_b64
            version, encoded = parts[1], parts[2]
        combined = base64.b64decode(encoded.encode("utf-8"))
        if len(combined) < 12:
            return ciphertext_b64

        iv = combined[:12]
        ciphertext = combined[12:]

        if version is not None:
            master_key = _configured_keyring().get(version)
            if master_key is None:
                return ciphertext_b64
            candidates = [(_field_encryption_key(master_key), version.encode("ascii"))]
        else:
            candidates = [
                *[(_field_encryption_key(master_key), None) for master_key in _configured_keyring().values()],
                (_legacy_field_encryption_key(), None),
            ]
        for key, associated_data in candidates:
            try:
                aesgcm = AESGCM(key)
                plaintext = aesgcm.decrypt(iv, ciphertext, associated_data)
                return plaintext.decode("utf-8")
            except Exception:
                continue
        return ciphertext_b64
    except RuntimeError:
        raise
    except Exception:
        # Fallback to returning original string for plaintext or legacy data
        return ciphertext_b64


def encrypt_json(data: Any) -> Any:
    """
    Encrypts any JSON-serializable data structure into an encrypted JSONB-compatible string wrapper.
    """
    if data is None:
        return None
    import json
    plaintext = json.dumps(data)
    ciphertext = encrypt_data(plaintext)
    return ciphertext


def decrypt_json(cipher_data: Any) -> Any:
    """
    Decrypts an encrypted JSONB-compatible string wrapper back to its original data structure.
    Falls back gracefully if the data is already decrypted (e.g. legacy dict/list).
    """
    if cipher_data is None:
        return None

    import json
    if isinstance(cipher_data, str):
        # Check if it looks like standard decrypted JSON object (starts with { or [)
        trimmed = cipher_data.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                return json.loads(cipher_data)
            except Exception:
                pass

        # Otherwise try to decrypt
        decrypted = decrypt_data(cipher_data)
        if decrypted == cipher_data:
            # Decryption failed or returned same string, could be raw string data
            return cipher_data
        try:
            return json.loads(decrypted)
        except Exception:
            return decrypted

    return cipher_data
