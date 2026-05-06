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
        logger.error("Failed to create PostgreSQL connection pool")
        raise

def get_db_connection():
    if _connection_pool is None:
        raise RuntimeError("Database pool is not initialized — call init_connection_pool() first")
    try:
        return _connection_pool.getconn()
    except Exception:
        logger.error("Failed to get connection from pool")
        raise

def return_db_connection(connection):
    if _connection_pool and connection:
        try:
            if connection.status != psycopg2.extensions.STATUS_READY:
                connection.rollback()
            _connection_pool.putconn(connection)
        except Exception:
            logger.error("Failed to return connection to pool")

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
            CREATE TABLE IF NOT EXISTS JobProfiles (
                profile_id SERIAL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                role VARCHAR(255) NOT NULL,
                company VARCHAR(255),
                tech_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
                is_selected BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_job_profiles_user ON JobProfiles (user_id, created_at DESC)",
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
            "ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS avatar_url TEXT",
            "ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '{}'::jsonb",
            f"ALTER TABLE UserInfo ALTER COLUMN interviews_remaining SET DEFAULT {settings.FREE_CREDITS_ON_SIGNUP}",
            """
            CREATE TABLE IF NOT EXISTS AIEventLogs (
                event_id BIGSERIAL PRIMARY KEY,
                user_id VARCHAR(64),
                interview_id VARCHAR(64),
                event_type VARCHAR(80) NOT NULL,
                provider VARCHAR(40),
                model VARCHAR(120),
                prompt_tokens INTEGER,
                output_tokens INTEGER,
                latency_ms INTEGER,
                success BOOLEAN NOT NULL DEFAULT TRUE,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ai_event_logs_created ON AIEventLogs (created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_ai_event_logs_interview ON AIEventLogs (interview_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS CoachExercises (
                exercise_id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                interview_id VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
                exercise_type VARCHAR(30) NOT NULL,
                title VARCHAR(255) NOT NULL,
                prompt TEXT NOT NULL,
                project_anchor VARCHAR(255),
                weakness_key VARCHAR(80),
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                completed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_coach_exercises_user_status ON CoachExercises (user_id, status, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS TechnicalInterviewRounds (
                round_id VARCHAR(64) PRIMARY KEY,
                interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                round_type VARCHAR(30) NOT NULL,
                language VARCHAR(20),
                prompt TEXT NOT NULL,
                starter_code TEXT,
                whiteboard_json JSONB,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_technical_rounds_interview ON TechnicalInterviewRounds (interview_id, round_type)",
            """
            CREATE TABLE IF NOT EXISTS TechnicalRunEvents (
                run_id VARCHAR(64) PRIMARY KEY,
                round_id VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                language VARCHAR(20) NOT NULL,
                source_chars INTEGER NOT NULL DEFAULT 0,
                stdout TEXT,
                stderr TEXT,
                exit_code INTEGER,
                runtime_ms INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_technical_run_events_round ON TechnicalRunEvents (round_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS ClientBodyLanguageMetrics (
                metric_id BIGSERIAL PRIMARY KEY,
                interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                payload JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_client_body_language_interview ON ClientBodyLanguageMetrics (interview_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS AntiCheatEvents (
                event_id BIGSERIAL PRIMARY KEY,
                interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
                user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
                event_type VARCHAR(50) NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_anti_cheat_interview ON AntiCheatEvents (interview_id, created_at DESC)",
        ]
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
        logger.info("Runtime schema upgrades verified")
    except Exception:
        conn.rollback()
        logger.error("Failed to apply runtime schema upgrades")
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
