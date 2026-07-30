import pytest

import payment


@pytest.mark.parametrize(
    ("requested", "current", "expected"),
    [
        ("starter", "starter", "current"),
        ("pro", "starter", "upgrade"),
        ("pro_annual", "starter", "upgrade"),
        ("premium", "starter", "upgrade"),
        ("premium_annual", "pro", "upgrade"),
        ("pro", "pro", "current"),
        ("pro_annual", "pro", "unavailable"),
        ("starter", "pro", "unavailable"),
        ("pro", "premium", "unavailable"),
        ("premium", "premium", "current"),
        ("premium_annual", "premium", "unavailable"),
    ],
)
def test_purchase_state_only_allows_tier_upgrades(requested, current, expected):
    assert payment._purchase_state(requested, current) == expected


def test_payment_readiness_requires_checkout_and_webhook_configuration(monkeypatch):
    monkeypatch.setattr(payment.app_settings, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(payment.app_settings, "RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setattr(payment, "RAZORPAY_WEBHOOK_SECRET", "")
    monkeypatch.setattr(payment, "razorpay_client", object())

    assert payment._razorpay_checkout_ready() is False
    assert payment._razorpay_missing_config() == ["RAZORPAY_WEBHOOK_SECRET"]
