# ============================================================================
# MODULE: database.py
# PURPOSE: psycopg2 ThreadedConnectionPool + sync/async query helpers.
#          Schema management is handled exclusively by Alembic.
# STRUCTURE:
#   - init / get / return / close pool helpers
#   - verify_schema_migrations() — production boot check
#   - ensure_runtime_schema() — compatibility wrapper around Alembic upgrade
#   - get_db() / transaction() / async_execute() query helpers
# ENDPOINTS: none
# DEPENDS ON: config
# CONSUMED BY: every router + every domain module that touches DB
# ============================================================================

import psycopg2
import psycopg2.pool  # noqa: F401
import logging
import asyncio
import json
from contextlib import contextmanager, asynccontextmanager
from config import settings

logger = logging.getLogger("database")

_connection_pool = None
ALEMBIC_HEAD_REVISION = "015_improve_graph_invariants"
REQUIRED_SCHEMA_TABLES = (
    "ResumeVersions",
    "InterviewBlueprints",
    "ResponseAssessments",
    "SessionPerformanceAnalyses",
    "WeaknessStates",
    "TechnicalProblemBank",
    "TechnicalExecutionJobs",
    "AnalysisJobs",
    "AIUsageReservations",
    "AttemptContextSnapshots",
    "AttemptPreflightChecks",
    "AttemptIntegrityEvents",
)
REQUIRED_SCHEMA_COLUMNS = {
    "Interviews": {
        "blueprint_id", "resume_id", "job_profile_id", "llm_cost_usd",
        "analysis_job_id", "attempt_status", "analysis_status", "integrity_status",
        "lifecycle_revision", "context_snapshot_id",
    },
    "ResumeVersions": {"parent_resume_id", "superseded_at", "immutable_at"},
    "InterviewResponses": {"idempotency_key", "evidence_hash", "answer_text_encrypted"},
    "AnalysisJobs": {"lease_owner", "lease_expires_at", "heartbeat_at", "next_attempt_at"},
    "AnalysisStageOutputs": {"stage_version", "evidence_hash", "output_encrypted"},
    "SessionPerformanceAnalyses": {
        "evaluator_version", "taxonomy_version", "rubric_version",
        "analysis_json_encrypted", "evidence_index_encrypted",
    },
    "TechnicalExecutionJobs": {"lease_owner", "lease_expires_at", "heartbeat_at", "next_attempt_at"},
    "ImprovementAttemptSessions": {"deadline_at", "remaining_seconds", "expires_at"},
}

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

def verify_schema_migrations():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT to_regclass('public.alembic_version')")
        if not cursor.fetchone()[0]:
            raise RuntimeError("Alembic version table is missing; run `python -m alembic upgrade head`")
        cursor.execute("SELECT version_num FROM alembic_version")
        revisions = {str(row[0]) for row in cursor.fetchall()}
        if revisions != {ALEMBIC_HEAD_REVISION}:
            current = ", ".join(sorted(revisions)) or "none"
            raise RuntimeError(
                f"Database is not at Alembic head {ALEMBIC_HEAD_REVISION}; current revision: {current}"
            )

        missing_tables = []
        for table_name in REQUIRED_SCHEMA_TABLES:
            cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name.lower()}",))
            if not cursor.fetchone()[0]:
                missing_tables.append(table_name)

        missing_columns = []
        for table_name, required_columns in REQUIRED_SCHEMA_COLUMNS.items():
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table_name.lower(),),
            )
            actual_columns = {str(row[0]) for row in cursor.fetchall()}
            for column_name in sorted(required_columns - actual_columns):
                missing_columns.append(f"{table_name}.{column_name}")

        if missing_tables or missing_columns:
            details = []
            if missing_tables:
                details.append("tables=" + ",".join(missing_tables))
            if missing_columns:
                details.append("columns=" + ",".join(missing_columns))
            raise RuntimeError("Database schema contract is incomplete: " + "; ".join(details))
        return {
            "revision": ALEMBIC_HEAD_REVISION,
            "tables_checked": len(REQUIRED_SCHEMA_TABLES),
            "columns_checked": sum(len(value) for value in REQUIRED_SCHEMA_COLUMNS.values()),
        }
    finally:
        cursor.close()
        return_db_connection(conn)

def ensure_runtime_schema():
    """Apply Alembic migrations in development/test.

    Production startup is verification-only.  This compatibility entrypoint
    remains because older local commands import it, but it no longer owns or
    stamps schema state.
    """
    if settings.ENVIRONMENT == "production":
        return verify_schema_migrations()

    from pathlib import Path
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    alembic_ini = Path(__file__).resolve().with_name("alembic.ini")
    if not alembic_ini.exists():
        raise RuntimeError("alembic.ini is missing")
    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations applied to head")
    return verify_schema_migrations()
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
