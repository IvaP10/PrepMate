# ============================================================================
# MODULE: security_utils.py
# PURPOSE: Logging-safety helpers and PII redaction before direct provider calls.
# STRUCTURE:
#   - EMAIL_RE / TOKEN_RE regexes
#   - stable_hash / redact_text (logging)
#   - redact_pii_text / redact_messages_for_external (external AI providers)
#   - AES-GCM field encryption backed by the operating-system keychain
# ENDPOINTS: none
# DEPENDS ON: standard library only
# DATA TABLES: none
# ============================================================================

from __future__ import annotations

import base64
import hashlib
import json
import os
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


def encrypt_data(plaintext: str) -> str:
    """Encrypt a sensitive local value with an OS-keychain-backed AES key."""
    if plaintext is None or plaintext == "":
        return ""
    if isinstance(plaintext, bytes):
        plaintext = plaintext.decode("utf-8", errors="strict")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from local_runtime import get_or_create_data_encryption_key

    version = "local-v1"
    nonce = os.urandom(12)
    ciphertext = AESGCM(get_or_create_data_encryption_key()).encrypt(
        nonce,
        str(plaintext).encode("utf-8"),
        version.encode("ascii"),
    )
    return f"enc:{version}:{base64.b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt_data(value: Any) -> str:
    """Decrypt a sensitive value while accepting pre-encryption local data."""
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    text = str(value)
    if not text.startswith("enc:"):
        return text

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from local_runtime import get_or_create_data_encryption_key

    parts = text.split(":", 2)
    if len(parts) != 3 or parts[1] != "local-v1":
        raise RuntimeError("This local data uses an unsupported encryption version")
    try:
        combined = base64.b64decode(parts[2].encode("ascii"), validate=True)
        if len(combined) < 29:
            raise ValueError("ciphertext is too short")
        plaintext = AESGCM(get_or_create_data_encryption_key()).decrypt(
            combined[:12],
            combined[12:],
            parts[1].encode("ascii"),
        )
        return plaintext.decode("utf-8")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Encrypted local data could not be decrypted") from exc


def encrypt_json(data: Any) -> Any:
    """Serialize and encrypt a JSON-compatible local value."""
    if data is None:
        return None
    return encrypt_data(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


def decrypt_json(cipher_data: Any) -> Any:
    """Decrypt JSON while accepting legacy materialized objects and strings."""
    if cipher_data is None:
        return None

    if isinstance(cipher_data, memoryview):
        cipher_data = cipher_data.tobytes()
    if isinstance(cipher_data, (bytes, bytearray)):
        cipher_data = bytes(cipher_data).decode("utf-8", errors="strict")

    if isinstance(cipher_data, str):
        # Check if it looks like standard decrypted JSON object (starts with { or [)
        trimmed = cipher_data.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                return json.loads(cipher_data)
            except Exception:
                pass

        # Older local writes wrapped the encrypted string in json.dumps().
        # Unwrap that representation before decrypting so the rename does not
        # strand existing private profile data.
        if trimmed.startswith('"') and trimmed.endswith('"'):
            try:
                unwrapped = json.loads(trimmed)
            except Exception:
                unwrapped = None
            if isinstance(unwrapped, str) and unwrapped != cipher_data:
                return decrypt_json(unwrapped)

        decrypted = decrypt_data(cipher_data)
        try:
            return json.loads(decrypted)
        except Exception:
            return decrypted

    return cipher_data


def decrypt_json_field(encrypted: Any, legacy: Any = None, default: Any = None) -> Any:
    """Read an encrypted JSON field with a legacy-plaintext migration fallback.

    Once encrypted data exists it is authoritative: a corrupt ciphertext must
    fail instead of silently falling back to a stale plaintext shadow. Marker
    objects in legacy columns intentionally contain no recoverable payload.
    """
    source = encrypted if encrypted is not None else legacy
    if source is None:
        return default
    decoded = decrypt_json(source)
    if encrypted is None and isinstance(decoded, dict) and decoded.get("encrypted") is True:
        return default
    return default if decoded is None else decoded
