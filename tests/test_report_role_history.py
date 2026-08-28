import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

import interview
import workspace_api
from security_utils import encrypt_data


class _Cursor:
    def __init__(self, *, one_rows=None, all_rows=None):
        self.one_rows = list(one_rows or [])
        self.all_rows = list(all_rows or [])
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.one_rows.pop(0) if self.one_rows else None

    def fetchall(self):
        return list(self.all_rows)

    def close(self):
        return None


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _BatchCursor:
    def __init__(self, batches):
        self.batches = list(batches)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.batches.pop(0) if self.batches else []

    def close(self):
        return None


def test_report_role_comes_from_immutable_snapshot_and_exposes_reuse_state():
    snapshot = {
        "role": "Backend Engineer",
        "company": "Acme",
        "job_description": "Build reliable Python services.",
        "job_profile_id": 17,
    }
    encrypted = encrypt_data(json.dumps(snapshot)).encode("utf-8")
    cursor = _Cursor(one_rows=[(None, encrypted), (True,)])

    target = interview._report_job_target(
        cursor,
        interview_id="interview-1",
        user_id="user-1",
        job_profile_id=None,
        settings_value={},
    )

    assert target == {
        "profile_type": "custom",
        "is_custom": True,
        "role": "Backend Engineer",
        "company": "Acme",
        "job_description": "Build reliable Python services.",
        "saved_for_reuse": True,
    }
    assert "AttemptContextSnapshots" in cursor.queries[0][0]
    assert "FROM JobProfiles reusable_profile" in cursor.queries[1][0]
    assert "NOT EXISTS" not in cursor.queries[1][0]


def test_saved_roles_remain_reusable_after_an_interview():
    cursor = _Cursor(all_rows=[])
    connection = _Connection(cursor)

    with (
        patch.object(workspace_api, "get_db_connection", return_value=connection),
        patch.object(workspace_api, "return_db_connection"),
    ):
        result = asyncio.run(workspace_api.get_job_profiles(current_user={"user_id": "user-1"}))

    assert result == []
    query, params = cursor.queries[0]
    assert "FROM Interviews used_interview" not in query
    assert "ORDER BY is_selected DESC" in query
    assert params == ("user-1",)


def test_historical_custom_target_keeps_copyable_snapshot_data():
    snapshot = {
        "role": "Platform Engineer",
        "company": "Acme",
        "job_description": "Build the internal platform and deployment pipeline.",
    }
    encrypted = encrypt_data(json.dumps(snapshot)).encode("utf-8")

    target = workspace_api._historical_job_target(
        settings_value={"profile_type": "custom"},
        snapshot_profile_type="custom",
        snapshot_job_value=encrypted,
        fallback_title="Old title",
    )

    assert target["profile_type"] == "custom"
    assert target["is_custom"] is True
    assert target["role"] == "Platform Engineer"
    assert target["company"] == "Acme"
    assert target["job_description"] == snapshot["job_description"]
    assert target["job_description_hash"]


def test_saved_job_target_keeps_explicit_top_tier_profile_type():
    snapshot = {
        "role": "Platform Engineer",
        "company": "Acme",
        "job_description": "Build the internal platform and deployment pipeline.",
        "job_profile_id": 17,
    }
    encrypted = encrypt_data(json.dumps(snapshot)).encode("utf-8")

    target = workspace_api._historical_job_target(
        settings_value={"profile_type": "top_tier"},
        snapshot_profile_type="top_tier",
        snapshot_job_value=encrypted,
        fallback_title="Old title",
    )

    assert target["profile_type"] == "top_tier"
    assert target["is_custom"] is False
    assert target["role"] == "Platform Engineer"


def test_recent_activity_uses_current_canonical_score_not_legacy_score():
    now = datetime.now(timezone.utc)
    cursor = _BatchCursor([[
        (
            "interview-1", "behavioral", "Backend Engineer", 12, now, now,
            2700, "report_ready", True, True, True, 78, None, {}, "mid_tier", None,
        )
    ], []])
    connection = _Connection(cursor)
    historical_target = {
        "profile_type": "mid_tier",
        "is_custom": False,
        "role": "Backend Engineer",
        "company": None,
        "job_description": "",
        "job_description_hash": None,
    }

    with (
        patch.object(workspace_api, "get_db_connection", return_value=connection),
        patch.object(workspace_api, "return_db_connection"),
        patch.object(workspace_api, "_historical_job_target", return_value=historical_target),
    ):
        result = asyncio.run(workspace_api.get_recent_activity(
            current_user={"user_id": "user-1"},
            days=30,
        ))

    assert result["activities"][0]["overall_score"] == 78
    query, params = cursor.queries[0]
    assert query.count("analysis.producer_version = ?") == 2
    assert "analysis.evidence_status = 'sufficient'" in query
    assert params[:2] == (
        workspace_api.ANALYSIS_STAGE_VERSION,
        workspace_api.ANALYSIS_STAGE_VERSION,
    )


def test_technical_history_filters_current_canonical_producer():
    now = datetime.now(timezone.utc)
    row = (
        "round-1", "interview-1", "coding", "python", "Solve it", "completed",
        now, now, {}, 1, 1, 10, now, 2, 2, 3, 3, "accepted", now,
        "report_ready", now, "top_tier", "Backend Engineer", 4800,
        True, True, True, 82,
    )
    cursor = _BatchCursor([[row]])
    connection = _Connection(cursor)

    with (
        patch.object(workspace_api, "get_db_connection", return_value=connection),
        patch.object(workspace_api, "return_db_connection"),
    ):
        result = asyncio.run(workspace_api.get_technical_rounds(
            current_user={"user_id": "user-1"},
            limit=20,
        ))

    assert result["sessions"][0]["official_score"] == 82
    query, params = cursor.queries[0]
    assert query.count("analysis.producer_version = ?") == 2
    assert params == (
        workspace_api.ANALYSIS_STAGE_VERSION,
        workspace_api.ANALYSIS_STAGE_VERSION,
        "user-1",
        20,
    )
