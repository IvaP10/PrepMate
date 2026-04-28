import psycopg2
import psycopg2.pool  # noqa: F401
import logging
import asyncio
from contextlib import contextmanager, asynccontextmanager
from config import settings

logger = logging.getLogger("database")

_connection_pool = None

def init_connection_pool():
    global _connection_pool
    if _connection_pool is not None:
        return

    try:
        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.DB_POOL_MIN,
            maxconn=settings.DB_POOL_MAX,
            host=settings.PG_HOST,
            database=settings.PG_DBNAME,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
            port=settings.PG_PORT,
        )
        logger.info("PostgreSQL connection pool created (min=%d, max=%d)", settings.DB_POOL_MIN, settings.DB_POOL_MAX)
    except Exception:
        logger.exception("Failed to create PostgreSQL connection pool")
        raise

def get_db_connection():
    if _connection_pool is None:
        raise RuntimeError("Database pool is not initialized — call init_connection_pool() first")
    try:
        return _connection_pool.getconn()
    except Exception:
        logger.exception("Failed to get connection from pool")
        raise

def return_db_connection(connection):
    if _connection_pool and connection:
        try:
            if connection.status != psycopg2.extensions.STATUS_READY:
                connection.rollback()
            _connection_pool.putconn(connection)
        except Exception:
            logger.exception("Failed to return connection to pool")

def close_connection_pool():
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("PostgreSQL connection pool closed")

def ensure_runtime_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        statements = [
            "ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS external_profile_signals JSONB",
            "ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS report_json JSONB",
            "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS topic_label VARCHAR(255)",
            "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS expected_signal TEXT",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS evaluation_json JSONB",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS technical_accuracy NUMERIC(5,2)",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS communication NUMERIC(5,2)",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS problem_solving NUMERIC(5,2)",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS confidence NUMERIC(5,2)",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS relevance NUMERIC(5,2)",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS answer_quality_flags JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS evidence_quotes JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS retry_state JSONB",
            "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS stt_confidence NUMERIC(5,2)",
            """
            CREATE TABLE IF NOT EXISTS SupportSubmissions (
                submission_id BIGSERIAL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                interview_id VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
                kind VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                title VARCHAR(255),
                message TEXT NOT NULL,
                steps TEXT,
                rating SMALLINT,
                page_url TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_support_user_created ON SupportSubmissions (user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_support_status_created ON SupportSubmissions (status, created_at DESC)",
        ]
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
        logger.info("Runtime schema upgrades verified")
    except Exception:
        conn.rollback()
        logger.exception("Failed to apply runtime schema upgrades")
        raise
    finally:
        cursor.close()
        return_db_connection(conn)

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        return_db_connection(conn)

@contextmanager
def transaction(conn):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

@asynccontextmanager
async def async_get_db():
    conn = await asyncio.to_thread(get_db_connection)
    try:
        yield conn
    finally:
        await asyncio.to_thread(return_db_connection, conn)

async def async_execute(query: str, params=None, fetchone=False, fetchall=False):
    def _run():
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            result = None
            if fetchone:
                result = cursor.fetchone()
            elif fetchall:
                result = cursor.fetchall()
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_run)
