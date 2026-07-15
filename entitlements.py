from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status


TECHNICAL_PROFILE_TYPES = {"top_tier", "mid_tier", "startup", "custom"}
TECHNICAL_TYPE_LABELS = {"technical", "technical interview", "technical mode"}


PLAN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "starter": {
        "plan_type": "starter",
        "name": "Free",
        "amount": 0.0,
        "currency": "INR",
        "duration_days": 30,
        "is_unlimited": False,
        "entitlements": {
            "mock_interviews_total": None,
            "mock_interviews_per_week": 1,
            "technical_rounds_total": None,
            "technical_rounds_per_week": 0,
            "interviews_per_day": None,
            "dashboard_coach": True,
            "technical_rounds": False,
            "custom_mock_interview": False,
            "custom_technical_interview": False,
            "code_review": False,
            "personalized_performance_report": True,
            "prep_dashboard": True,
            "career_roadmap": False,
            "priority_support": False,
            "uses_legacy_credits": False,
        },
        "features": [
            "1 AI Mock Interview per week",
            "Personalised Performance Report",
            "Interactive Prep Dashboard",
        ],
    },
    "pro": {
        "plan_type": "pro",
        "name": "Pro",
        "amount": 999.0,
        "currency": "INR",
        "duration_days": 30,
        "is_unlimited": True,
        "entitlements": {
            "mock_interviews_total": None,
            "mock_interviews_per_week": 3,
            "technical_rounds_total": None,
            "technical_rounds_per_week": 1,
            "interviews_per_day": None,
            "dashboard_coach": True,
            "technical_rounds": True,
            "custom_mock_interview": True,
            "custom_technical_interview": False,
            "code_review": False,
            "personalized_performance_report": True,
            "prep_dashboard": True,
            "career_roadmap": True,
            "priority_support": False,
            "uses_legacy_credits": False,
        },
        "features": [
            "3 AI Mock Interviews per week",
            "1 Technical Assessment per week",
            "Custom Mock Interview (JD-Based)",
            "Personalised Performance Reports",
        ],
    },
    "pro_annual": {
        "plan_type": "pro_annual",
        "name": "Pro Annual",
        "amount": 9588.0,
        "currency": "INR",
        "duration_days": 365,
        "is_unlimited": True,
        "entitlements": {
            "mock_interviews_total": None,
            "mock_interviews_per_week": 3,
            "technical_rounds_total": None,
            "technical_rounds_per_week": 1,
            "interviews_per_day": None,
            "dashboard_coach": True,
            "technical_rounds": True,
            "custom_mock_interview": True,
            "custom_technical_interview": False,
            "code_review": False,
            "personalized_performance_report": True,
            "prep_dashboard": True,
            "career_roadmap": True,
            "priority_support": False,
            "uses_legacy_credits": False,
        },
        "features": [
            "3 AI Mock Interviews per week",
            "1 Technical Assessment per week",
            "Custom Mock Interview (JD-Based)",
            "Personalised Performance Reports",
            "Annual Pro pricing",
        ],
    },
    "premium": {
        "plan_type": "premium",
        "name": "Premium",
        "amount": 1499.0,
        "currency": "INR",
        "duration_days": 30,
        "is_unlimited": True,
        "entitlements": {
            "mock_interviews_total": None,
            "mock_interviews_per_week": 5,
            "technical_rounds_total": None,
            "technical_rounds_per_week": 3,
            "interviews_per_day": None,
            "dashboard_coach": True,
            "technical_rounds": True,
            "custom_mock_interview": True,
            "custom_technical_interview": True,
            "code_review": True,
            "personalized_performance_report": True,
            "prep_dashboard": True,
            "career_roadmap": True,
            "priority_support": True,
            "uses_legacy_credits": False,
        },
        "features": [
            "5 AI Mock Interviews per week",
            "3 Technical Assessments per week",
            "Custom Mock Interview (JD-Based)",
            "Custom Technical Interview (JD-Based)",
        ],
    },
    "premium_annual": {
        "plan_type": "premium_annual",
        "name": "Premium Annual",
        "amount": 14388.0,
        "currency": "INR",
        "duration_days": 365,
        "is_unlimited": True,
        "entitlements": {
            "mock_interviews_total": None,
            "mock_interviews_per_week": 5,
            "technical_rounds_total": None,
            "technical_rounds_per_week": 3,
            "interviews_per_day": None,
            "dashboard_coach": True,
            "technical_rounds": True,
            "custom_mock_interview": True,
            "custom_technical_interview": True,
            "code_review": True,
            "personalized_performance_report": True,
            "prep_dashboard": True,
            "career_roadmap": True,
            "priority_support": True,
            "uses_legacy_credits": False,
        },
        "features": [
            "5 AI Mock Interviews per week",
            "3 Technical Assessments per week",
            "Custom Mock Interview (JD-Based)",
            "Custom Technical Interview (JD-Based)",
            "Annual Premium pricing",
        ],
    },
}


EXERCISE_MODE_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "mode": "write_it",
        "title": "Write it",
        "description": "Draft a five-line answer with direct answer, proof, trade-off, and result.",
        "input_type": "text",
        "timer_seconds": None,
    },
    {
        "mode": "say_it",
        "title": "Say it",
        "description": "Use the microphone for a 60-second spoken answer; only the transcript is submitted.",
        "input_type": "voice_transcript",
        "timer_seconds": 60,
    },
    {
        "mode": "fix_it",
        "title": "Fix it",
        "description": "Rewrite a weak answer by adding the missing number, trade-off, or edge case.",
        "input_type": "text",
        "timer_seconds": None,
    },
    {
        "mode": "chain_it",
        "title": "Chain it",
        "description": "Answer the main question, predict the follow-up, then answer that follow-up.",
        "input_type": "text",
        "timer_seconds": None,
    },
    {
        "mode": "blind_start",
        "title": "Blind Start",
        "description": "Start immediately with only the question visible and capture the first attempt.",
        "input_type": "voice_or_text",
        "timer_seconds": 60,
    },
    {
        "mode": "best_vs_worst",
        "title": "Best vs Worst",
        "description": "Compare your weakest answer with a stronger structure and rewrite the gap.",
        "input_type": "text",
        "timer_seconds": None,
    },
]


def normalize_plan_type(plan_type: Optional[str]) -> str:
    normalized = (plan_type or "starter").strip().lower()
    if normalized == "free":
        return "starter"
    return normalized if normalized in PLAN_DEFINITIONS else "starter"


def normalize_technical_profile(profile_type: Optional[str]) -> str:
    normalized = (profile_type or "mid_tier").strip().lower()
    return normalized if normalized in TECHNICAL_PROFILE_TYPES else "mid_tier"


def is_technical_interview_type(value: str) -> bool:
    return (value or "").strip().lower() in TECHNICAL_TYPE_LABELS


def membership_plans() -> Dict[str, Dict[str, Any]]:
    return {
        key: {
            "amount": value["amount"],
            "currency": value["currency"],
            "interviews": value["entitlements"].get("mock_interviews_total"),
            "is_unlimited": value["is_unlimited"],
            "duration_days": value["duration_days"],
            "name": value["name"],
        }
        for key, value in PLAN_DEFINITIONS.items()
    }


def public_plans() -> List[Dict[str, Any]]:
    return [
        {
            "plan_type": key,
            "name": value["name"],
            "amount": value["amount"],
            "currency": value["currency"],
            "duration_days": value["duration_days"],
            "features": value["features"],
            "entitlements": value["entitlements"],
        }
        for key, value in PLAN_DEFINITIONS.items()
    ]


def public_exercise_modes() -> List[Dict[str, Any]]:
    return [dict(mode) for mode in EXERCISE_MODE_DEFINITIONS]


def exercise_mode(mode: str) -> Dict[str, Any]:
    normalized = (mode or "").strip().lower()
    for item in EXERCISE_MODE_DEFINITIONS:
        if item["mode"] == normalized:
            return dict(item)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported exercise mode")


def _count_today(cursor, user_id: str) -> int:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM Interviews
        WHERE user_id = %s
          AND created_at >= CURRENT_DATE
          AND status <> 'cancelled'
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def current_week_start_utc(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    start = current - timedelta(days=current.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def next_week_start_utc(now: Optional[datetime] = None) -> datetime:
    return current_week_start_utc(now) + timedelta(days=7)


def next_day_start_utc(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    return (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _seconds_until(reset_at: datetime, now: Optional[datetime] = None) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    reset_at = reset_at.astimezone(timezone.utc)
    return max(0, int((reset_at - current).total_seconds()))


def _format_wait(seconds: int) -> str:
    if seconds < 60:
        return "less than 1 minute"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts: List[str] = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts[:2]) if parts else "less than 1 minute"


def _format_reset_hint(reset_at: datetime, now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    seconds = _seconds_until(reset_at, current)
    reset_label = reset_at.astimezone(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    return f"Your limit resets in {_format_wait(seconds)} ({reset_label})."


def _count_by_type(cursor, user_id: str, *, technical: bool) -> int:
    if technical:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM Interviews
            WHERE user_id = %s
              AND LOWER(interview_type) IN ('technical', 'technical interview', 'technical mode')
              AND status <> 'cancelled'
            """,
            (user_id,),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM Interviews
            WHERE user_id = %s
              AND LOWER(interview_type) NOT IN ('technical', 'technical interview', 'technical mode')
              AND status <> 'cancelled'
            """,
            (user_id,),
        )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _count_by_type_since(cursor, user_id: str, *, technical: bool, since: datetime) -> int:
    if technical:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM Interviews
            WHERE user_id = %s
              AND LOWER(interview_type) IN ('technical', 'technical interview', 'technical mode')
              AND status <> 'cancelled'
              AND created_at >= %s
            """,
            (user_id, since),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM Interviews
            WHERE user_id = %s
              AND LOWER(interview_type) NOT IN ('technical', 'technical interview', 'technical mode')
              AND status <> 'cancelled'
              AND created_at >= %s
            """,
            (user_id, since),
        )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def get_active_subscription_plan_type(cursor, user_id: str, now: Optional[datetime] = None) -> Optional[str]:
    checked_at = now or datetime.now(timezone.utc)
    cursor.execute(
        """
        SELECT plan_type
        FROM Subscriptions
        WHERE user_id = %s
          AND status = 'active'
          AND end_date >= %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, checked_at),
    )
    row = cursor.fetchone()
    return normalize_plan_type(row[0]) if row else None


def get_entitlements_for_user(cursor, user_id: str, plan_type: Optional[str]) -> Dict[str, Any]:
    normalized = normalize_plan_type(plan_type)
    plan = PLAN_DEFINITIONS[normalized]
    entitlements = dict(plan["entitlements"])
    now = datetime.now(timezone.utc)
    week_start = current_week_start_utc(now)
    week_reset = next_week_start_utc(now)
    day_reset = next_day_start_utc(now)
    today_used = _count_today(cursor, user_id)
    mock_week_used = _count_by_type_since(cursor, user_id, technical=False, since=week_start)
    technical_week_used = _count_by_type_since(cursor, user_id, technical=True, since=week_start)
    daily_limit = entitlements.get("interviews_per_day")
    mock_weekly_limit = entitlements.get("mock_interviews_per_week")
    technical_weekly_limit = entitlements.get("technical_rounds_per_week")
    return {
        "plan_type": normalized,
        "plan_name": plan["name"],
        "entitlements": entitlements,
        "usage": {
            "interviews_today": today_used,
            "interviews_per_day": daily_limit,
            "daily_remaining": None if daily_limit is None else max(0, int(daily_limit) - today_used),
            "daily_resets_at": day_reset.isoformat(),
            "week_starts_at": week_start.isoformat(),
            "week_resets_at": week_reset.isoformat(),
            "mock_interviews_this_week": mock_week_used,
            "mock_interviews_per_week": mock_weekly_limit,
            "mock_interviews_remaining_week": None if mock_weekly_limit is None else max(0, int(mock_weekly_limit) - mock_week_used),
            "technical_rounds_this_week": technical_week_used,
            "technical_rounds_per_week": technical_weekly_limit,
            "technical_rounds_remaining_week": None if technical_weekly_limit is None else max(0, int(technical_weekly_limit) - technical_week_used),
        },
        "server_time": now.isoformat(),
    }


def enforce_interview_start(
    cursor,
    *,
    user_id: str,
    plan_type: Optional[str],
    is_technical: bool,
    uses_custom_jd: bool = False,
) -> Dict[str, Any]:
    payload = get_entitlements_for_user(cursor, user_id, plan_type)
    entitlements = payload["entitlements"]
    now = datetime.now(timezone.utc)
    daily_limit = entitlements.get("interviews_per_day")
    today_used = int(payload["usage"]["interviews_today"])
    if daily_limit is not None and today_used >= int(daily_limit):
        reset_at = next_day_start_utc(now)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily interview limit reached ({today_used}/{daily_limit} used). "
                f"{_format_reset_hint(reset_at, now)} Upgrade your plan for more interviews."
            ),
        )

    if is_technical:
        if not entitlements.get("technical_rounds"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Technical rounds are locked on the Free plan. Upgrade to Pro or Premium to start technical rounds.",
            )
        if uses_custom_jd and not entitlements.get("custom_technical_interview"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Custom technical interviews require the Premium plan.",
            )
        weekly_limit = entitlements.get("technical_rounds_per_week")
        weekly_used = int(payload["usage"]["technical_rounds_this_week"])
        if weekly_limit is not None and weekly_used >= int(weekly_limit):
            reset_at = next_week_start_utc(now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Weekly technical assessment limit reached ({weekly_used}/{weekly_limit} used). "
                    f"{_format_reset_hint(reset_at, now)} Upgrade your plan for more technical rounds."
                ),
            )
        total = entitlements.get("technical_rounds_total")
        if total is not None and _count_by_type(cursor, user_id, technical=True) >= int(total):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your plan includes {total} technical round(s). Please upgrade to continue.",
            )
    else:
        if uses_custom_jd and not entitlements.get("custom_mock_interview"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Custom JD-based mock interviews require the Pro or Premium plan.",
            )
        weekly_limit = entitlements.get("mock_interviews_per_week")
        weekly_used = int(payload["usage"]["mock_interviews_this_week"])
        if weekly_limit is not None and weekly_used >= int(weekly_limit):
            reset_at = next_week_start_utc(now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Weekly mock interview limit reached ({weekly_used}/{weekly_limit} used). "
                    f"{_format_reset_hint(reset_at, now)} Upgrade your plan for more mock interviews."
                ),
            )
        total = entitlements.get("mock_interviews_total")
        if total is not None and _count_by_type(cursor, user_id, technical=False) >= int(total):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your plan includes {total} mock interview(s). Please upgrade to continue.",
            )

    return payload
