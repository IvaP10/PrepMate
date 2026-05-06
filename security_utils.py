from __future__ import annotations

import hashlib
import re
from typing import Any

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_RE = re.compile(r"(?i)(token|secret|password|signature|api[_-]?key)=([^&\s]+)")


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
