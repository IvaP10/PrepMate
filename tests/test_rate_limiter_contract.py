import asyncio

import rate_limiter


def test_distributed_rate_limit_fails_closed_in_production(monkeypatch):
    limiter = rate_limiter.UserRateLimiter(max_calls=2, time_window=60)
    monkeypatch.setattr(rate_limiter, "_get_redis", lambda: None)
    monkeypatch.setattr(rate_limiter, "_production", lambda: True)

    assert asyncio.run(limiter.check_limit("user-1")) is False


def test_development_rate_limit_retains_bounded_local_fallback(monkeypatch):
    limiter = rate_limiter.UserRateLimiter(max_calls=1, time_window=60)
    monkeypatch.setattr(rate_limiter, "_get_redis", lambda: None)
    monkeypatch.setattr(rate_limiter, "_production", lambda: False)

    assert asyncio.run(limiter.check_limit("user-1")) is True
    assert asyncio.run(limiter.check_limit("user-1")) is False
