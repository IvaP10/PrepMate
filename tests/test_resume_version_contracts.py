import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

import database
import pre_interview
from local_runtime import LOCAL_USER_ID


def _resume(confidence: str = "medium"):
    return {
        "name": "Ada Lovelace",
        "summary": "Backend engineer",
        "target_role": "Platform Engineer",
        "skills": ["Python", "PostgreSQL"],
        "education": [],
        "experience": [],
        "projects": [{"name": "Reliable API", "description": "Idempotent requests"}],
        "languages": [],
        "certifications": [],
        "achievements": [],
        "confidence": {"overall": confidence, "notes": "fixture"},
    }


def test_resume_fact_reviews_keep_source_payload_immutable():
    original = _resume("medium")
    facts = pre_interview._resume_fact_payload(
        original,
        source_text="Ada Lovelace built a Reliable API with Python and PostgreSQL.",
        parser_version="fixture-v1",
    )

    skill_fact = next(item for item in facts["facts"] if item["field"] == "skills")
    assert skill_fact["status"] == "pending"
    skill_fact["status"] = "corrected"
    skill_fact["corrected_value"] = ["Python", "Redis"]

    materialized = pre_interview._materialize_resume(original, facts)
    assert original["skills"] == ["Python", "PostgreSQL"]
    assert materialized["skills"] == ["Python", "Redis"]
    assert pre_interview._confirmation_status(facts) == "needs_review"


def test_resume_encrypted_blob_round_trip():
    payload = _resume("high")
    encrypted = pre_interview._encrypted_json_blob(payload)

    assert isinstance(encrypted, bytes)
    assert pre_interview._decrypted_json_blob(encrypted, {}) == payload


class _ListCursor:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        return None

    def rollback(self):
        return None


class _DatabaseContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_list_resume_versions_uses_owned_rows_and_returns_active_id():
    resume = _resume("high")
    facts = pre_interview._resume_fact_payload(
        resume,
        source_text="Ada Lovelace built a Reliable API.",
        parser_version="fixture-v1",
    )
    now = datetime.now(timezone.utc)
    row = (
        "resume-1",
        2,
        pre_interview._encrypted_json_blob(resume),
        pre_interview._encrypted_json_blob(facts),
        {"skills": ["Python"]},
        True,
        "confirmed",
        "hash-1",
        "fixture-v1",
        "resume.pdf",
        now,
        now,
        None,
    )
    cursor = _ListCursor([row])
    context = _DatabaseContext(_Connection(cursor))

    with patch.object(pre_interview, "get_db", return_value=context):
        result = asyncio.run(pre_interview.list_resume_versions(
            current_user={"user_id": "user-1"},
        ))

    assert result["active_resume_id"] == "resume-1"
    assert result["resumes"][0]["resume_payload"]["name"] == "Ada Lovelace"
    assert cursor.queries[0][1] == ("user-1",)


def _persist_test_resume(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database.close_connection_pool()
    payload = _resume("high")
    persisted = pre_interview._persist_parsed_resume(
        user_id=LOCAL_USER_ID,
        email="candidate@example.test",
        resume_json=payload,
        resume_text="Synthetic resume content with Python and reliable platform engineering.",
        content_hash="resume-delete-contract-hash",
        source_filename="synthetic.docx",
        parser_version="fixture-v1",
        facts_payload={"review_version": "resume-facts-v1", "facts": []},
    )
    return str(persisted["resume"]["resume_id"])


def test_delete_resume_version_removes_owned_version_and_active_profile(tmp_path, monkeypatch):
    resume_id = _persist_test_resume(tmp_path, monkeypatch)
    try:
        result = asyncio.run(pre_interview.delete_resume_version(
            resume_id,
            current_user={"user_id": LOCAL_USER_ID},
        ))
        with database.get_db() as connection:
            resume_count = connection.execute(
                "SELECT COUNT(*) FROM ResumeVersions WHERE user_id = ?",
                (LOCAL_USER_ID,),
            ).fetchone()[0]
            profile = connection.execute(
                "SELECT full_name, resume_json, profile_json, active_resume_id FROM UserInfo WHERE user_id = ?",
                (LOCAL_USER_ID,),
            ).fetchone()
    finally:
        database.close_connection_pool()

    assert result["success"] is True
    assert result["deleted_counts"]["resume_versions"] == 1
    assert resume_count == 0
    assert profile == ("Local user", None, None, None)


def test_delete_resume_version_rejects_an_active_interview(tmp_path, monkeypatch):
    resume_id = _persist_test_resume(tmp_path, monkeypatch)
    try:
        with database.get_db() as connection:
            connection.execute(
                """
                INSERT INTO Interviews (
                    interview_id, user_id, interview_mode, interview_type,
                    strictness_level, status, resume_id
                ) VALUES ('active-resume-interview', ?, 'mock', 'behavioral',
                          'medium', 'in_progress', ?)
                """,
                (LOCAL_USER_ID, resume_id),
            )
            connection.commit()

        with pytest.raises(pre_interview.HTTPException) as rejected:
            asyncio.run(pre_interview.delete_resume_version(
                resume_id,
                current_user={"user_id": LOCAL_USER_ID},
            ))
    finally:
        database.close_connection_pool()

    assert rejected.value.status_code == 409
    assert "active interview" in str(rejected.value.detail).lower()
