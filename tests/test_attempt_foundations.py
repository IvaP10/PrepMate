import os

os.environ.setdefault("ENVIRONMENT", "test")

from attempt_context import canonical_context_hash, create_attempt_context_snapshot
from interview import StartInterviewRequest


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))


def test_context_hash_is_canonical_and_changes_with_material_context():
    first = {"resume": {"skills": ["Python"]}, "job": {"role": "Backend"}}
    reordered = {"job": {"role": "Backend"}, "resume": {"skills": ["Python"]}}
    changed = {"job": {"role": "Backend"}, "resume": {"skills": ["Go"]}}

    assert canonical_context_hash(first) == canonical_context_hash(reordered)
    assert canonical_context_hash(first) != canonical_context_hash(changed)


def test_snapshot_insert_links_interview_and_locks_resume():
    cursor = RecordingCursor()
    snapshot_id, context_hash = create_attempt_context_snapshot(
        cursor,
        interview_id="interview-1",
        user_id="user-1",
        resume_id="resume-1",
        job_profile_id=3,
        blueprint_id="blueprint-1",
        profile_type="mid_tier",
        profile_config_version="profiles-v1",
        role="Backend Engineer",
        company="Example",
        resume_payload={"skills": ["Python"]},
        job_context={"role": "Backend Engineer"},
        blueprint_context={"blueprint_hash": "hash-1"},
    )

    assert snapshot_id
    assert len(context_hash) == 64
    statements = [call[0] for call in cursor.calls]
    assert any("INSERT INTO AttemptContextSnapshots" in statement for statement in statements)
    assert any("SET context_snapshot_id" in statement for statement in statements)
    assert any("SET immutable_at = COALESCE" in statement for statement in statements)


def test_start_contract_accepts_bound_preflight_identity():
    request = StartInterviewRequest(
        blueprint_id="blueprint-123",
        preflight_id="preflight-123",
        start_idempotency_key="start-key-123",
    )
    assert request.preflight_id == "preflight-123"
