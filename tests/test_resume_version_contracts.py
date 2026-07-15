import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

import pre_interview


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
