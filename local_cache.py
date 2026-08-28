"""Small in-process coordination store for the local desktop runtime."""

from __future__ import annotations

import threading
import time
from typing import Any


class LocalCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.RLock()

    def _read(self, key: str) -> Any:
        item = self._values.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at <= time.time():
            self._values.pop(key, None)
            return None
        return value

    def get(self, key: str) -> Any:
        with self._lock:
            return self._read(key)

    def set(self, key: str, value: Any, nx: bool = False, ex: int | float | None = None) -> bool:
        with self._lock:
            if nx and self._read(key) is not None:
                return False
            self._values[key] = (value, time.time() + float(ex) if ex else None)
            return True

    def setex(self, key: str, seconds: int | float, value: Any) -> bool:
        return self.set(key, value, ex=seconds)

    def expire(self, key: str, seconds: int | float) -> bool:
        with self._lock:
            value = self._read(key)
            if value is None:
                return False
            self._values[key] = (value, time.time() + float(seconds))
            return True

    def delete(self, *keys: str) -> int:
        with self._lock:
            removed = 0
            for key in keys:
                removed += int(self._values.pop(key, None) is not None)
            return removed

    def clear(self) -> None:
        """Drop all in-process coordination and generation cache entries."""
        with self._lock:
            self._values.clear()

    def compare_and_expire(self, key: str, expected: Any, seconds: int | float) -> bool:
        with self._lock:
            if self._read(key) != expected:
                return False
            return self.expire(key, seconds)

    def compare_and_delete(self, key: str, expected: Any) -> bool:
        with self._lock:
            if self._read(key) != expected:
                return False
            return bool(self.delete(key))

    def claim_sequence(
        self,
        event_key: str,
        sequence_key: str,
        incoming: int,
        ttl_seconds: int | float,
    ) -> int:
        """Atomically deduplicate an event and advance its client sequence."""
        with self._lock:
            if self._read(event_key) is not None:
                return 0
            try:
                last = int(self._read(sequence_key) or 0)
            except (TypeError, ValueError):
                last = 0
            if incoming <= last:
                return -1
            self.set(event_key, "1", ex=ttl_seconds)
            self.set(sequence_key, str(incoming), ex=ttl_seconds)
            return 1


_LOCAL_CACHE = LocalCache()


def get_local_cache() -> LocalCache:
    return _LOCAL_CACHE
