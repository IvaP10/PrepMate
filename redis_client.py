import redis
import json
import logging
from typing import Optional, Dict, Any
from config import settings

logger = logging.getLogger("redis_client")

_redis_pool = None
_redis_client = None

def init_redis_client():
    global _redis_pool, _redis_client
    if _redis_client is not None:
        return

    try:
        _redis_pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        _redis_client = redis.Redis(connection_pool=_redis_pool)
        _redis_client.ping()
        logger.info(
            "Redis client initialized with connection pool (max=%d)",
            settings.REDIS_MAX_CONNECTIONS,
        )
    except redis.ConnectionError as e:
        logger.warning(f"Redis not available: {e}. Session recovery will be disabled.")
        _redis_pool = None
        _redis_client = None
    except Exception:
        logger.exception("Failed to initialize Redis client")
        _redis_pool = None
        _redis_client = None

def get_redis_client():
    return _redis_client

def save_session(session_id: str, session_data: Dict[str, Any], ttl: int = None) -> bool:
    if not _redis_client:
        return False

    try:
        key = f"interview_session:{session_id}"
        data = json.dumps(session_data)

        if ttl:
            _redis_client.setex(key, ttl, data)
        else:
            _redis_client.set(key, data)

        return True
    except Exception as e:
        logger.error(f"Failed to save session {session_id}: {e}")
        return False

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    if not _redis_client:
        return None

    try:
        key = f"interview_session:{session_id}"
        data = _redis_client.get(key)

        if data:
            return json.loads(data)
        return None
    except Exception as e:
        logger.error(f"Failed to get session {session_id}: {e}")
        return None

def delete_session(session_id: str) -> bool:
    if not _redis_client:
        return False

    try:
        key = f"interview_session:{session_id}"
        _redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"Failed to delete session {session_id}: {e}")
        return False

def extend_session_ttl(session_id: str, ttl: int) -> bool:
    if not _redis_client:
        return False

    try:
        key = f"interview_session:{session_id}"
        _redis_client.expire(key, ttl)
        return True
    except Exception as e:
        logger.error(f"Failed to extend session TTL {session_id}: {e}")
        return False

def close_redis():
    global _redis_client, _redis_pool
    if _redis_pool:
        _redis_pool.disconnect()
        _redis_pool = None
    _redis_client = None
    logger.info("Redis connection pool closed")