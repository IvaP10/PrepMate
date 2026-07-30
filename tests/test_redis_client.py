import redis_client


class _FakeRedis:
    def __init__(self, *, connection_pool):
        self.connection_pool = connection_pool

    def ping(self):
        return True


def _reset_client():
    redis_client._redis_pool = None
    redis_client._redis_client = None
    redis_client._last_init_attempt = 0.0


def test_managed_redis_url_uses_url_pool(monkeypatch):
    _reset_client()
    pool = object()
    captured = {}

    def from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return pool

    monkeypatch.setattr(redis_client.settings, "REDIS_URL", "rediss://user:secret@redis.internal:6379/0")
    monkeypatch.setattr(redis_client.redis.ConnectionPool, "from_url", from_url)
    monkeypatch.setattr(redis_client.redis, "Redis", _FakeRedis)

    redis_client.init_redis_client()

    assert captured["url"] == "rediss://user:secret@redis.internal:6379/0"
    assert captured["kwargs"]["decode_responses"] is True
    assert redis_client.get_redis_client(reconnect=False).connection_pool is pool
    _reset_client()
