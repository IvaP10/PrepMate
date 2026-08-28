from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import pytest

import database
from security_utils import decrypt_data, decrypt_json, encrypt_data, encrypt_json


ROOT = Path(__file__).resolve().parents[1]


def test_local_schema_has_no_account_billing_or_subscription_tables():
    schema = (ROOT / "local_schema.sql").read_text(encoding="utf-8").lower()

    for forbidden in (
        "subscriptions",
        "planentitlements",
        "paymentintentoutbox",
        "razorpay",
        "password_hash",
        "oauth",
    ):
        assert forbidden not in schema


def test_repository_uses_only_the_local_schema_source():
    assert (ROOT / "local_schema.sql").is_file()
    assert not (ROOT / "schema.sql").exists()
    assert not (ROOT / "alembic.ini").exists()
    assert not (ROOT / "migrations").exists()
    assert database.LOCAL_SCHEMA_REVISION == "006-desktop-runtime-compatibility"


def test_existing_sqlite_schema_gets_a_backup_before_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    path = database.local_database_path()
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE legacy_marker (value TEXT)")
    connection.execute("INSERT INTO legacy_marker VALUES ('synthetic')")
    connection.commit()
    connection.close()

    database._ensure_local_schema()

    backups = list(tmp_path.glob("prepmate.sqlite3.backup-*"))
    assert len(backups) == 1
    assert b"synthetic" in backups[0].read_bytes()


def test_local_schema_records_each_numbered_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database._ensure_local_schema()
    connection = sqlite3.connect(database.local_database_path())
    try:
        rows = connection.execute(
            "SELECT version, revision FROM LocalSchemaMigrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (1, "001-local-schema-base"),
        (2, "002-encrypted-evidence-columns"),
        (3, "003-prepmate-alpha-local-runtime"),
        (4, "004-sensitive-analysis-encryption"),
        (5, "005-sensitive-session-state-encryption"),
        (6, "006-desktop-runtime-compatibility"),
    ]


def test_local_schema_upgrade_is_idempotent_and_preserves_v1_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database._ensure_local_schema(target_version=1)
    path = database.local_database_path()
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE upgrade_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO upgrade_marker VALUES ('preserve-me')")
        connection.commit()
    finally:
        connection.close()

    database._ensure_local_schema()
    database._ensure_local_schema()

    connection = sqlite3.connect(path)
    try:
        marker = connection.execute("SELECT value FROM upgrade_marker").fetchone()[0]
        migrations = connection.execute(
            "SELECT version, COUNT(*) FROM LocalSchemaMigrations GROUP BY version ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert marker == "preserve-me"
    assert migrations == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1)]
    assert len(list(tmp_path.glob("prepmate.sqlite3.backup-*"))) == 1


def test_known_private_alpha_checksums_receive_additive_compatibility_repairs(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database._ensure_local_schema(target_version=3)
    path = database.local_database_path()
    connection = sqlite3.connect(path)
    try:
        for table in ("SelfReviewEvents", "SessionReviewEvents", "MediaCoachingSignals"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("ALTER TABLE AttemptPreflightChecks DROP COLUMN input_mode")
        connection.execute("ALTER TABLE AttemptPreflightChecks DROP COLUMN provider_ready")
        connection.execute("ALTER TABLE JobProfiles DROP COLUMN normalized_requirements_encrypted")
        connection.execute("DROP INDEX uq_interview_response_idempotency")
        for revision, checksums in database.HISTORICAL_LOCAL_MIGRATION_CHECKSUMS.items():
            connection.execute(
                "UPDATE LocalSchemaMigrations SET checksum = ? WHERE revision = ?",
                (next(iter(checksums)), revision),
            )
        connection.commit()
    finally:
        connection.close()

    database._ensure_local_schema()

    assert database.verify_local_schema()["revision"] == "006-desktop-runtime-compatibility"
    assert len(list(tmp_path.glob("prepmate.sqlite3.backup-*"))) == 1


def test_unknown_applied_migration_checksum_still_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database._ensure_local_schema(target_version=1)
    connection = sqlite3.connect(database.local_database_path())
    try:
        connection.execute(
            "UPDATE LocalSchemaMigrations SET checksum = ? WHERE revision = ?",
            ("0" * 64, "001-local-schema-base"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="changed after it was applied"):
        database._ensure_local_schema()


def test_v5_upgrade_encrypts_legacy_interview_question_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    marker = "PRIVATE-LEGACY-QUESTION-PLAN-75c3c2"
    database._ensure_local_schema(target_version=4)
    path = database.local_database_path()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO UserInfo (user_id, full_name, profile_completed, interview_profile_type)
            VALUES ('legacy-local-user', 'Synthetic User', 1, 'mid_tier')
            """
        )
        connection.execute(
            """
            INSERT INTO Interviews (
                interview_id, user_id, interview_mode, interview_type,
                strictness_level, questions_data
            ) VALUES ('legacy-interview', 'legacy-local-user', 'mock', 'behavioral',
                      'medium', ?)
            """,
            (f'{{"opening_question":"{marker}"}}',),
        )
        connection.commit()
    finally:
        connection.close()

    database._ensure_local_schema()
    connection = sqlite3.connect(path)
    try:
        legacy, encrypted = connection.execute(
            """
            SELECT questions_data, questions_data_encrypted
            FROM Interviews WHERE interview_id = 'legacy-interview'
            """
        ).fetchone()
    finally:
        connection.close()

    assert __import__("json").loads(legacy) == {"encrypted": True}
    assert decrypt_json(encrypted)["opening_question"] == marker
    assert marker.encode("utf-8") not in path.read_bytes()


def test_interrupted_migration_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database._ensure_local_schema(target_version=1)

    def interrupt(version, statement_index):
        if version == 2 and statement_index == 1:
            raise OSError("synthetic interruption")

    monkeypatch.setattr(database, "_MIGRATION_TEST_HOOK", interrupt)
    with pytest.raises(RuntimeError, match="migration 002-encrypted-evidence-columns failed"):
        database._ensure_local_schema(target_version=2)

    connection = sqlite3.connect(database.local_database_path())
    try:
        revisions = {
            row[0]
            for row in connection.execute("SELECT revision FROM LocalSchemaMigrations").fetchall()
        }
        interview_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(Interviews)").fetchall()
        }
    finally:
        connection.close()

    assert revisions == {"001-local-schema-base"}
    assert "report_json_encrypted" not in interview_columns

    monkeypatch.setattr(database, "_MIGRATION_TEST_HOOK", None)
    database._ensure_local_schema()
    connection = sqlite3.connect(database.local_database_path())
    try:
        versions = connection.execute(
            "SELECT version FROM LocalSchemaMigrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()
    assert versions == [(1,), (2,), (3,), (4,), (5,), (6,)]


def test_sqlite_timestamps_keep_domain_isoformat_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    connection = database.get_db_connection()
    try:
        value = connection.execute("SELECT CURRENT_TIMESTAMP AS created_at").fetchone()[0]
    finally:
        database.return_db_connection(connection)

    assert isinstance(value, str)
    assert "T" in value.isoformat()
    assert (value - value).total_seconds() == 0
    assert (datetime.now(timezone.utc) - value).total_seconds() >= 0


def test_local_connections_enable_secure_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    connection = database.get_db_connection()
    try:
        enabled = connection.execute("PRAGMA secure_delete").fetchone()[0]
    finally:
        database.return_db_connection(connection)

    assert enabled == 1


def test_sensitive_marker_is_not_readable_in_a_raw_sqlite_backup(tmp_path):
    marker = "PREPMATE-PRIVATE-MARKER-7f0d2d"
    ciphertext = encrypt_data(marker).encode("utf-8")
    path = tmp_path / "private.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE evidence (payload TEXT, payload_encrypted BLOB)")
        connection.execute(
            "INSERT INTO evidence (payload, payload_encrypted) VALUES (?, ?)",
            ("[encrypted]", ciphertext),
        )
        connection.commit()
    finally:
        connection.close()

    assert marker.encode("utf-8") not in path.read_bytes()
    assert decrypt_data(ciphertext) == marker


def test_quoted_encrypted_json_from_legacy_local_writes_still_round_trips():
    payload = {"name": "Synthetic Candidate", "skills": ["Python"]}
    quoted_ciphertext = __import__("json").dumps(encrypt_json(payload))

    assert decrypt_json(quoted_ciphertext) == payload
