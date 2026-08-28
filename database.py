"""SQLite storage for the single-user desktop application.

The database is an ordinary file in the platform application-data directory.
There is no database server, connection URL, remote migration service, or
account database. Every domain query uses native SQLite syntax and executes
through Python's built-in ``sqlite3`` driver without runtime SQL translation.
"""

import sqlite3
import re
import logging
import asyncio
import json
import hashlib
from datetime import datetime, timezone
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from local_runtime import LOCAL_USER_ID, local_database_path

logger = logging.getLogger("database")

# SQLite stores local timestamps as ISO text. Register an explicit adapter so
# Python 3.12+ does not fall back to its deprecated implicit datetime adapter.
sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))

_connection_pool = None
LOCAL_SCHEMA_VERSION = 6
LOCAL_MIGRATIONS = (
    (1, "001-local-schema-base", "001-local-schema-base.sql"),
    (2, "002-encrypted-evidence-columns", "002-encrypted-evidence-columns.sql"),
    (3, "003-prepmate-alpha-local-runtime", "003-prepmate-alpha-local-runtime.sql"),
    (4, "004-sensitive-analysis-encryption", "004-sensitive-analysis-encryption.sql"),
    (5, "005-sensitive-session-state-encryption", "005-sensitive-session-state-encryption.sql"),
    (6, "006-desktop-runtime-compatibility", "006-desktop-runtime-compatibility.sql"),
)
LOCAL_SCHEMA_REVISION = LOCAL_MIGRATIONS[-1][1]
LOCAL_MIGRATION_DIRECTORY = Path(__file__).with_name("local_migrations")
# Early private alpha builds regenerated revisions 001 and 003 from the schema
# snapshot after those revisions had already been applied. Accept only those
# exact historical hashes; revision 006 supplies the additive schema changes
# that those builds did not record. Every other checksum mismatch still fails
# closed as evidence of a changed or corrupted migration.
HISTORICAL_LOCAL_MIGRATION_CHECKSUMS = {
    "001-local-schema-base": frozenset({
        "eb45be2ed268b5e280ba4f120a9c298290b1819667ddde63eae7f8ca3e933d0e",
    }),
    "003-prepmate-alpha-local-runtime": frozenset({
        "5cc4507e29a813018772f83b3df25640d382f4115e27c1672cb887f04796db1e",
    }),
}
_MIGRATION_TEST_HOOK = None
REQUIRED_SCHEMA_TABLES = (
    "LocalSchemaVersion",
    "ResumeVersions",
    "InterviewBlueprints",
    "ResponseAssessments",
    "SessionPerformanceAnalyses",
    "WeaknessStates",
    "TechnicalProblemBank",
    "TechnicalExecutionJobs",
    "AnalysisJobs",
    "EvidenceManifests",
    "AttemptContextSnapshots",
    "AttemptPreflightChecks",
    "AttemptIntegrityEvents",
    "TechnicalAttemptAggregates",
    "ReportSideEffectOutbox",
    "ResumeProcessingJobs",
)
REQUIRED_SCHEMA_COLUMNS = {
    "Interviews": {
        "blueprint_id", "resume_id", "job_profile_id", "llm_cost_usd",
        "analysis_job_id", "attempt_status", "analysis_status", "integrity_status",
        "lifecycle_revision", "context_snapshot_id", "questions_data_encrypted",
    },
    "ResumeVersions": {"parent_resume_id", "superseded_at", "immutable_at"},
    "InterviewResponses": {"idempotency_key", "evidence_hash", "answer_text_encrypted"},
    "AnalysisJobs": {
        "lease_owner", "lease_expires_at", "heartbeat_at", "next_attempt_at",
        "producer_version",
    },
    "AnalysisStageOutputs": {"stage_version", "evidence_hash", "output_encrypted"},
    "ResponseAssessments": {"assessment_json_encrypted"},
    "SessionPerformanceAnalyses": {
        "evaluator_version", "taxonomy_version", "rubric_version",
        "analysis_json_encrypted", "evidence_index_encrypted",
        "revision_no", "is_current", "supersedes_analysis_id",
        "producer_version",
    },
    "ReportArtifacts": {
        "payload_encrypted", "analysis_id", "publication_key", "published_at",
    },
    "ReportSideEffectOutbox": {
        "idempotency_key", "publication_key", "analysis_id", "interview_id",
        "user_id", "status", "attempt_count", "max_attempts", "available_at",
        "lease_owner", "lease_expires_at", "last_error",
        "payload_encrypted",
    },
    "ResumeProcessingJobs": {
        "user_id", "job_kind", "content_hash", "payload_encrypted",
        "result_encrypted", "status", "attempt_count", "max_attempts",
        "available_at", "lease_owner", "lease_expires_at", "last_error_code",
    },
    "EvidenceManifests": {
        "revision_no", "is_current", "supersedes_manifest_id",
        "producer_version",
    },
    "TechnicalExecutionJobs": {"lease_owner", "lease_expires_at", "heartbeat_at", "next_attempt_at"},
    "TechnicalAttemptAggregates": {
        "interview_id", "user_id", "lifecycle_state", "lifecycle_revision",
        "round_count", "open_round_count", "submitted_round_count",
        "round_states", "state_hash", "deadline_at", "updated_at",
    },
    "ImprovementAttemptSessions": {"deadline_at", "remaining_seconds", "expires_at"},
    "AttemptPreflightChecks": {"input_mode", "provider_ready"},
    "JobProfiles": {"job_description_encrypted", "normalized_requirements_encrypted"},
}
REQUIRED_SCHEMA_INDEXES = {
    "idx_analysis_jobs_claimable",
    "idx_report_side_effect_outbox_claim",
    "idx_resume_processing_jobs_claim",
    "idx_technical_attempt_owner_state",
    "uq_analysis_job_idempotency",
    "uq_interview_response_idempotency",
    "uq_report_artifact_publication_key",
    "uq_session_performance_current",
}


class _SQLiteTimestamp(str):
    """String-compatible SQLite timestamp with the datetime API used by the domain layer."""

    def isoformat(self) -> str:
        return str(self).replace(" ", "T", 1)

    def _datetime(self) -> datetime:
        value = str(self).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def __sub__(self, other):
        if isinstance(other, _SQLiteTimestamp):
            return self._datetime() - other._datetime()
        if isinstance(other, datetime):
            normalized = other if other.tzinfo is not None else other.replace(tzinfo=timezone.utc)
            return self._datetime() - normalized
        return NotImplemented

    def __rsub__(self, other):
        if isinstance(other, datetime):
            normalized = other if other.tzinfo is not None else other.replace(tzinfo=timezone.utc)
            return normalized - self._datetime()
        return NotImplemented


def _row_with_timestamp_values(row, description):
    if row is None or not description:
        return row
    values = list(row)
    for index, column in enumerate(description):
        name = str(column[0] or "").lower()
        value = values[index]
        if (
            isinstance(value, str)
            and value
            and (name.endswith("_at") or name in {"created", "updated", "expires", "date_created"})
            and not value.startswith("enc:")
        ):
            values[index] = _SQLiteTimestamp(value)
    return tuple(values)


def _normalize_sqlite_params(params=None) -> tuple:
    if params is None:
        return ()
    values = list(params) if isinstance(params, (tuple, list)) else [params]
    return tuple(
        json.dumps(list(value) if isinstance(value, set) else value)
        if isinstance(value, (dict, list, tuple, set))
        else bytes(value) if isinstance(value, memoryview)
        else value
        for value in values
    )


def _sqlite_connection(path=None):
    connection = sqlite3.connect(
        str(path or local_database_path()),
        timeout=30,
        check_same_thread=False,
        isolation_level="",
    )
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    # Selective privacy deletion must also clear discarded SQLite cells rather
    # than leaving recoverable plaintext labels in freelist pages.
    connection.execute("PRAGMA secure_delete = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _migration_statements(source: str) -> list[str]:
    statements: list[str] = []
    pending: list[str] = []
    for line in source.splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("--")):
            continue
        pending.append(line)
        candidate = "\n".join(pending).strip()
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.rstrip(";").strip())
            pending = []
    if pending and "\n".join(pending).strip():
        raise RuntimeError("A local SQLite migration contains an incomplete statement")
    return statements


def _migration_payloads(max_version: int | None = None) -> list[tuple[int, str, Path, str, str]]:
    expected_versions = list(range(1, LOCAL_SCHEMA_VERSION + 1))
    actual_versions = [version for version, _, _ in LOCAL_MIGRATIONS]
    if actual_versions != expected_versions:
        raise RuntimeError("Local SQLite migrations must be contiguous and start at version 1")
    payloads = []
    for version, revision, filename in LOCAL_MIGRATIONS:
        if max_version is not None and version > max_version:
            continue
        path = LOCAL_MIGRATION_DIRECTORY / filename
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Required local SQLite migration is missing: {filename}") from exc
        checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
        payloads.append((version, revision, path, checksum, source))
    return payloads


def _database_backup(connection: sqlite3.Connection, path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.with_name(f"{path.name}.backup-{timestamp}")
    destination = sqlite3.connect(str(backup_path))
    try:
        connection.backup(destination)
    finally:
        destination.close()
    try:
        backup_path.chmod(0o600)
    except OSError:
        pass
    logger.info("Backed up local SQLite database before migration: %s", backup_path)
    return backup_path


def _apply_migration_statement(connection: sqlite3.Connection, statement: str) -> None:
    additive = re.match(
        r"ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if additive:
        table, column, definition = additive.groups()
        existing = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        if column in existing:
            return
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
        return
    connection.execute(statement)


def _read_migration_tracker(connection: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'LocalSchemaMigrations'"
    ).fetchone()
    if not exists:
        return {}
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(LocalSchemaMigrations)").fetchall()
    }
    version = "version" if "version" in columns else "0"
    checksum = "checksum" if "checksum" in columns else "NULL"
    return {
        str(row[0]): (int(row[1] or 0), str(row[2]) if row[2] else None)
        for row in connection.execute(
            f"SELECT revision, {version}, {checksum} FROM LocalSchemaMigrations"
        ).fetchall()
    }


def _ensure_migration_tracker(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS LocalSchemaMigrations (
            revision TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            checksum TEXT,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(LocalSchemaMigrations)").fetchall()
    }
    if "version" not in columns:
        connection.execute(
            "ALTER TABLE LocalSchemaMigrations ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
        )
    if "checksum" not in columns:
        connection.execute("ALTER TABLE LocalSchemaMigrations ADD COLUMN checksum TEXT")


def _apply_local_data_migration(connection: sqlite3.Connection, version: int) -> None:
    """Apply keychain-backed data transforms that cannot be expressed in SQL."""
    if version not in {4, 5}:
        return

    from security_utils import encrypt_data

    marker = '{"encrypted":true}'
    analysis_fields = (
        ("ResponseAssessments", "assessment_json", "assessment_json_encrypted"),
        ("ReportSideEffectOutbox", "payload", "payload_encrypted"),
    )
    fields = analysis_fields if version == 4 else (
        ("Interviews", "questions_data", "questions_data_encrypted"),
        *analysis_fields,
    )
    for table, legacy_column, encrypted_column in fields:
        rows = connection.execute(
            f'''SELECT rowid, "{legacy_column}"
                FROM "{table}"
                WHERE "{encrypted_column}" IS NULL
                  AND "{legacy_column}" IS NOT NULL'''
        ).fetchall()
        for rowid, value in rows:
            if isinstance(value, memoryview):
                value = value.tobytes()
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="strict")
            text = str(value)
            if text.strip() in {"", "[encrypted]", marker, '{"encrypted": true}'}:
                continue
            ciphertext = text if text.startswith("enc:") else encrypt_data(text)
            connection.execute(
                f'''UPDATE "{table}"
                    SET "{legacy_column}" = ?, "{encrypted_column}" = ?
                    WHERE rowid = ?''',
                (marker, ciphertext.encode("utf-8"), rowid),
            )


def _ensure_local_schema(*, target_version: int | None = None) -> None:
    """Apply each pending SQLite migration transactionally and verify its hash.

    ``target_version`` exists for migration-upgrade tests; production callers
    always apply the complete set.
    """
    target = LOCAL_SCHEMA_VERSION if target_version is None else int(target_version)
    if target < 1 or target > LOCAL_SCHEMA_VERSION:
        raise ValueError("Invalid local SQLite target version")

    path = local_database_path()
    preexisting_file = path.exists() and path.stat().st_size > 0
    connection = _sqlite_connection(path)
    backup_path: Path | None = None
    try:
        applied = _read_migration_tracker(connection)
        payloads = _migration_payloads(target)
        known_revisions = {revision for _, revision, _, _, _ in payloads}
        existing_version = max((version for version, _ in applied.values()), default=0)
        if existing_version > LOCAL_SCHEMA_VERSION:
            raise RuntimeError(
                f"Local SQLite schema version {existing_version} is newer than this PrepMate build ({LOCAL_SCHEMA_VERSION})"
            )
        for revision, (_, recorded_checksum) in applied.items():
            matching = next((item for item in payloads if item[1] == revision), None)
            historical_checksums = HISTORICAL_LOCAL_MIGRATION_CHECKSUMS.get(revision, frozenset())
            if (
                matching
                and recorded_checksum
                and recorded_checksum != matching[3]
                and recorded_checksum not in historical_checksums
            ):
                raise RuntimeError(
                    f"Local SQLite migration {revision} changed after it was applied; restore a backup before continuing"
                )

        pending = [
            payload
            for payload in payloads
            if payload[1] not in applied or not applied[payload[1]][1]
        ]
        if pending and preexisting_file:
            user_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if str(row[0]) not in {"LocalSchemaMigrations", "LocalSchemaVersion"}
            }
            if user_tables:
                backup_path = _database_backup(connection, path)

        _ensure_migration_tracker(connection)
        connection.commit()

        for version, revision, migration_path, checksum, source in pending:
            if revision not in known_revisions:
                raise RuntimeError(f"Unknown local SQLite migration: {revision}")
            statements = _migration_statements(source)
            if not statements:
                raise RuntimeError(f"Local SQLite migration is empty: {migration_path.name}")
            try:
                connection.execute("BEGIN IMMEDIATE")
                for index, statement in enumerate(statements, start=1):
                    _apply_migration_statement(connection, statement)
                    if _MIGRATION_TEST_HOOK is not None:
                        _MIGRATION_TEST_HOOK(version, index)
                _apply_local_data_migration(connection, version)
                connection.execute(
                    """
                    INSERT INTO LocalSchemaMigrations (revision, version, checksum, applied_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(revision) DO UPDATE SET
                        version = excluded.version,
                        checksum = excluded.checksum,
                        applied_at = excluded.applied_at
                    """,
                    (revision, version, checksum),
                )
                connection.execute(
                    "DELETE FROM LocalSchemaVersion WHERE version = ? OR revision = ?",
                    (version, revision),
                )
                connection.execute(
                    "INSERT INTO LocalSchemaVersion (version, revision) VALUES (?, ?)",
                    (version, revision),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                recovery = f" Restore {backup_path}." if backup_path else ""
                raise RuntimeError(
                    f"Local SQLite migration {revision} failed; the migration was rolled back.{recovery}"
                ) from exc

        if target == LOCAL_SCHEMA_VERSION:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO UserInfo (
                    user_id, full_name, profile_completed, interview_profile_type
                ) VALUES (?, 'Local user', 0, 'mid_tier')
                """,
                (LOCAL_USER_ID,),
            )
            connection.commit()
    finally:
        connection.close()


class _LocalCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        return self._cursor.execute(str(query), _normalize_sqlite_params(params))

    def executemany(self, query, params_seq):
        normalized = [_normalize_sqlite_params(params) for params in params_seq]
        return self._cursor.executemany(str(query), normalized)

    def fetchone(self):
        return _row_with_timestamp_values(self._cursor.fetchone(), self._cursor.description)

    def fetchall(self):
        description = self._cursor.description
        return [_row_with_timestamp_values(row, description) for row in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        description = self._cursor.description
        rows = self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)
        return [_row_with_timestamp_values(row, description) for row in rows]

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def close(self):
        return self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _LocalConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return _LocalCursor(self._connection.cursor())

    def execute(self, query, params=None):
        return _LocalCursor(
            self._connection.execute(str(query), _normalize_sqlite_params(params))
        )

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()

    @property
    def status(self):
        return 1

    def __getattr__(self, name):
        return getattr(self._connection, name)

def init_connection_pool():
    global _connection_pool
    if _connection_pool is not None:
        return

    _ensure_local_schema()
    _connection_pool = "sqlite"
    logger.info("Local SQLite data store initialized at %s", local_database_path())

def get_db_connection():
    if _connection_pool is None:
        init_connection_pool()
    return _LocalConnection(_sqlite_connection())

def return_db_connection(connection):
    if connection:
        try:
            connection.close()
        except Exception:
            logger.debug("Failed to close local SQLite connection", exc_info=True)

def close_connection_pool():
    global _connection_pool
    _connection_pool = None

def verify_local_schema():
    connection = get_db_connection()
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = [name for name in REQUIRED_SCHEMA_TABLES if name not in tables]
        if missing:
            raise RuntimeError("Local SQLite schema is incomplete: " + ",".join(missing))
        missing_columns: list[str] = []
        columns_checked = 0
        for table, required in REQUIRED_SCHEMA_COLUMNS.items():
            actual = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            columns_checked += len(required)
            missing_columns.extend(f"{table}.{column}" for column in sorted(set(required) - actual))
        if missing_columns:
            raise RuntimeError("Local SQLite schema columns are incomplete: " + ",".join(missing_columns))
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        missing_indexes = sorted(REQUIRED_SCHEMA_INDEXES - indexes)
        if missing_indexes:
            raise RuntimeError("Local SQLite schema indexes are incomplete: " + ",".join(missing_indexes))
        version_row = connection.execute(
            "SELECT version, revision FROM LocalSchemaVersion ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not version_row or int(version_row[0]) != LOCAL_SCHEMA_VERSION or str(version_row[1]) != LOCAL_SCHEMA_REVISION:
            raise RuntimeError("Local SQLite schema version is not current; run the migration with a backup")
        return {
            "revision": LOCAL_SCHEMA_REVISION,
            "version": LOCAL_SCHEMA_VERSION,
            "tables_checked": len(REQUIRED_SCHEMA_TABLES),
            "columns_checked": columns_checked,
            "indexes_checked": len(REQUIRED_SCHEMA_INDEXES),
        }
    finally:
        return_db_connection(connection)

def ensure_local_schema():
    """Create or validate the local schema."""
    _ensure_local_schema()
    return verify_local_schema()
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
