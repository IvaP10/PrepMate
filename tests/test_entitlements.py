import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret-for-plan-normalization-123456")

import pytest
from fastapi import HTTPException

from entitlements import (
    enforce_interview_start,
    normalize_technical_profile,
    public_exercise_modes,
)
from auth import (
    SIGNUP_PROMO_CUTOFF_UTC,
    SIGNUP_PROMO_DURATION_DAYS,
    SIGNUP_PROMO_PLAN_TYPE,
    is_signup_promo_active,
    normalize_effective_plan_type,
)


class FakeCursor:
    def __init__(self, counts):
        self.counts = counts
        self.last_query = ""

    def execute(self, query, params=None):
        self.last_query = query.lower()

    def fetchone(self):
        if "created_at >= current_date" in self.last_query:
            return (self.counts.get("today", 0),)
        if "lower(interview_type) in" in self.last_query:
            return (self.counts.get("technical", 0),)
        if "lower(interview_type) not in" in self.last_query:
            return (self.counts.get("mock", 0),)
        return (0,)


def test_exercise_modes_include_voice_transcript_mode():
    modes = {mode["mode"]: mode for mode in public_exercise_modes()}
    assert modes["say_it"]["input_type"] == "voice_transcript"
    assert modes["say_it"]["timer_seconds"] == 60


def test_startup_technical_profile_maps_to_mid_tier():
    assert normalize_technical_profile("startup") == "startup"
    assert normalize_technical_profile("top_tier") == "top_tier"


def test_pro_is_limited_to_three_mock_interviews_per_week():
    cursor = FakeCursor({"mock": 3})
    with pytest.raises(HTTPException) as exc:
        enforce_interview_start(cursor, user_id="u1", plan_type="pro", is_technical=False)
    assert exc.value.status_code == 429
    assert "Weekly mock interview limit reached" in exc.value.detail


def test_starter_gets_one_technical_round_total():
    cursor = FakeCursor({"today": 0, "technical": 1})
    with pytest.raises(HTTPException) as exc:
        enforce_interview_start(cursor, user_id="u1", plan_type="starter", is_technical=True)
    assert exc.value.status_code == 403


def test_effective_plan_defaults_to_starter_without_active_subscription():
    assert normalize_effective_plan_type(None) == "starter"
    assert normalize_effective_plan_type("free") == "starter"
    assert normalize_effective_plan_type("premium") == "starter"


def test_effective_plan_uses_active_paid_subscription():
    assert normalize_effective_plan_type("starter", "pro") == "pro"
    assert normalize_effective_plan_type("starter", "premium_annual") == "premium_annual"


def test_signup_promo_grants_premium_through_august_31_2026():
    assert SIGNUP_PROMO_PLAN_TYPE == "premium"
    assert SIGNUP_PROMO_DURATION_DAYS == 30
    assert SIGNUP_PROMO_CUTOFF_UTC == datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
    assert is_signup_promo_active(SIGNUP_PROMO_CUTOFF_UTC)
    assert not is_signup_promo_active(SIGNUP_PROMO_CUTOFF_UTC + timedelta(seconds=1))
