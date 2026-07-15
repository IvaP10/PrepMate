import pytest
from pydantic import ValidationError

from user_profile import NotificationPrefsRequest


def test_notification_prefs_accept_supported_values():
    prefs = NotificationPrefsRequest(
        inactive_reminder_days=7,
        target_date="2026-06-09",
        weekly_summary=True,
        streak_reminder=True,
    )

    assert prefs.inactive_reminder_days == 7
    assert prefs.target_date == "2026-06-09"
    assert prefs.weekly_summary is True
    assert prefs.streak_reminder is True


def test_notification_prefs_reject_unsupported_inactivity_days():
    with pytest.raises(ValidationError):
        NotificationPrefsRequest(inactive_reminder_days=10)


def test_notification_prefs_reject_invalid_target_date():
    with pytest.raises(ValidationError):
        NotificationPrefsRequest(target_date="09/06/2026")


def test_notification_prefs_normalize_empty_target_date():
    prefs = NotificationPrefsRequest(target_date=" ")

    assert prefs.target_date is None
