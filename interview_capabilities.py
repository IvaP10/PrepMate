"""Shared interview profile helpers for the local application."""

from __future__ import annotations

from typing import Optional


TECHNICAL_PROFILE_TYPES = {"top_tier", "mid_tier", "startup", "custom"}
TECHNICAL_TYPE_LABELS = {"technical", "technical interview", "technical mode"}


def normalize_technical_profile(profile_type: Optional[str]) -> str:
    normalized = (profile_type or "mid_tier").strip().lower()
    return normalized if normalized in TECHNICAL_PROFILE_TYPES else "mid_tier"


def is_technical_interview_type(value: str) -> bool:
    return (value or "").strip().lower() in TECHNICAL_TYPE_LABELS
