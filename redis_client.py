# ============================================================================
# MODULE: redis_client.py
# PURPOSE: Pooled Redis client + interview-session save/get/delete/extend helpers.
# STRUCTURE:
#   - init_redis_client() / get_redis_client() (lines 22-55)
#   - save_session / get_session / delete_session / extend_session_ttl (lines 57-112)
#   - close_redis() (lines 114-120)
# ENDPOINTS: none
# DEPENDS ON: config, security_utils
# CONSUMED BY: rate_limiter, auth, interview, technical_mode, app (lifespan)
# DATA TABLES: none (Redis only; key prefix `interview_session:`)
# ============================================================================

import redis

import logging
from typing import Optional, Dict, Any
from time import monotonic
from config import settings
from security_utils import redact_text, stable_hash

logger = logging.getLogger("redis_client")

_redis_pool = None
_redis_client = None
_last_init_attempt = 0.0
_RECONNECT_INTERVAL_SECONDS = 5.0

def init_redis_client():
    global _redis_pool, _redis_client, _last_init_attempt
    if _redis_client is not None:
        return

    _last_init_attempt = monotonic()
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
        logger.warning("Redis not available: %s. Session recovery will be disabled.", redact_text(e))
        _redis_pool = None
        _redis_client = None
    except Exception:
        logger.error("Failed to initialize Redis client")
        _redis_pool = None
        _redis_client = None

def get_redis_client(reconnect: bool = True):
    if _redis_client is None and reconnect:
        now = monotonic()
        if now - _last_init_attempt >= _RECONNECT_INTERVAL_SECONDS:
            init_redis_client()
    return _redis_client

# Alias used by knowledge_map.py and other modules that prefer the shorter name
get_redis = get_redis_client


def close_redis():
    global _redis_client, _redis_pool
    if _redis_pool:
        _redis_pool.disconnect()
        _redis_pool = None
    _redis_client = None
    logger.info("Redis connection pool closed")
