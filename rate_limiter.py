import asyncio
import logging
from collections import deque
from time import time
from typing import Dict

logger = logging.getLogger("rate_limiter")

def _get_redis():
    try:
        from redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None

class RateLimiter:
    def __init__(self, max_calls: int, time_window: int):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time()

            while self.calls and self.calls[0] < now - self.time_window:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                wait_time = self.time_window - (now - self.calls[0])
                logger.warning("Rate limit reached, waiting %.1fs", wait_time)
                await asyncio.sleep(wait_time)
                self.calls.popleft()

            self.calls.append(now)

class UserRateLimiter:
    def __init__(self, max_calls: int, time_window: int, redis_prefix: str = "ratelimit"):
        self.max_calls = max_calls
        self.time_window = time_window
        self.redis_prefix = redis_prefix
        self._fallback_calls: Dict[str, deque] = {}
        self._fallback_lock = asyncio.Lock()
        self._last_prune = time()
        self._prune_interval = 300

    async def check_limit(self, user_id: str) -> bool:
        redis_client = _get_redis()
        if redis_client:
            return await self._check_redis(redis_client, user_id)
        return await self._check_memory(user_id)

    async def _check_redis(self, redis_client, user_id: str) -> bool:
        try:
            key = f"{self.redis_prefix}:{user_id}"
            now = time()
            cutoff = now - self.time_window

            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, self.time_window)
            results = pipe.execute()

            current_count = results[1]
            if current_count >= self.max_calls:
                redis_client.zrem(key, str(now))
                return False

            return True
        except Exception:
            logger.warning("Redis rate limit check failed, falling back to memory")
            return await self._check_memory(user_id)

    async def _check_memory(self, user_id: str) -> bool:
        async with self._fallback_lock:
            now = time()

            if now - self._last_prune > self._prune_interval:
                self._prune_stale_entries()
                self._last_prune = now

            if user_id not in self._fallback_calls:
                self._fallback_calls[user_id] = deque()

            calls = self._fallback_calls[user_id]

            while calls and calls[0] < now - self.time_window:
                calls.popleft()

            if len(calls) >= self.max_calls:
                return False

            calls.append(now)
            return True

    def _prune_stale_entries(self):
        now = time()
        stale_keys = [
            uid for uid, calls in self._fallback_calls.items()
            if not calls or calls[-1] < now - self.time_window
        ]
        for uid in stale_keys:
            del self._fallback_calls[uid]
        if stale_keys:
            logger.info("Pruned %d stale rate limiter entries", len(stale_keys))

    async def reset_user(self, user_id: str):
        redis_client = _get_redis()
        if redis_client:
            try:
                redis_client.delete(f"{self.redis_prefix}:{user_id}")
            except Exception:
                pass

        async with self._fallback_lock:
            if user_id in self._fallback_calls:
                self._fallback_calls[user_id].clear()
