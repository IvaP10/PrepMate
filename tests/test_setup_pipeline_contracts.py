import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

import workspace_api
import blueprint_api
import pre_interview
import user_profile
from interview_profiles import PROFILE_CONFIGS, PROFILE_TYPES
from interview_blueprint import build_blueprint_preview, compile_interview_blueprint, validate_blueprint
from security_utils import encrypt_data, encrypt_json


def test_job_requirement_normalization_is_deterministic_and_server_owned():
    description = (
        "You must build Python APIs with PostgreSQL. "
        "Experience with Docker and Redis is required."
    )
    first = workspace_api.normalize_job_requirements(
        description,
        ["FastAPI", "Python"],
        ["Own production reliability"],
    )
    second = workspace_api.normalize_job_requirements(
        description,
        ["FastAPI", "Python"],
        ["Own production reliability"],
    )

    assert first == second
    assert first["version"] == workspace_api.JOB_REQUIREMENT_NORMALIZATION_VERSION
    assert "python" in {item.lower() for item in first["skills"]}
    assert any("reliability" in item.lower() for item in first["requirements"])


def test_job_description_encryption_round_trip():
    description = "Private JD: build a low-latency interview service."
    encrypted = workspace_api._encrypt_job_description(description)

    assert isinstance(encrypted, bytes)
    assert workspace_api._decrypt_job_description(encrypted) == description


def test_blueprint_preview_has_stable_ids_and_never_exposes_questions():
    kwargs = {
        "resume_data": {
            "skills": ["Python", "PostgreSQL"],
            "projects": [{"name": "PrepMate", "description": "Interview evidence pipeline"}],
        },
        "job_title": "Backend Engineer",
        "job_description": "Python, PostgreSQL, Redis, and system design",
        "interview_type": "behavioral",
        "duration_minutes": 30,
        "profile_type": "mid_tier",
        "focus": ["mixed"],
        "difficulty_level": "hard",
        "experience_level": "senior",
        "question_count": 5,
    }
    first = validate_blueprint(compile_interview_blueprint(**kwargs))
    second = validate_blueprint(compile_interview_blueprint(**kwargs))
    preview = build_blueprint_preview(first)

    assert first["blueprint_hash"] == second["blueprint_hash"]
    assert [item["question_id"] for item in first["battlegrounds"]] == [
        item["question_id"] for item in second["battlegrounds"]
    ]
    assert sum(item["time_budget_seconds"] for item in first["battlegrounds"]) <= first["total_time_budget"]
    assert all(item["difficulty"] == "hard" for item in preview["sections"])
    assert "opening_question" not in str(preview)


def test_impossible_blueprint_timing_is_rejected():
    with pytest.raises(ValueError, match="cannot fit"):
        compile_interview_blueprint(
            resume_data={"skills": ["Python"], "projects": []},
            job_title="Engineer",
            job_description="Python",
            interview_type="technical",
            duration_minutes=10,
            profile_type="mid_tier",
            question_count=12,
        )


def test_blueprint_request_rejects_candidate_question_shaping_fields():
    for field, value in {
        "difficulty_level": "easy",
        "duration_minutes": 10,
        "focus": ["hr"],
        "question_count": 1,
        "round_config": {"language": "java"},
        "experience_level": "junior",
    }.items():
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            blueprint_api.BlueprintCreateRequest(**{field: value})


def test_blueprint_question_shape_is_server_owned_for_all_four_profiles():
    expected_targets = {
        "top_tier": 60,
        "mid_tier": 50,
        "startup": 45,
        "custom": 50,
    }
    for profile_type, expected_target in expected_targets.items():
        request = blueprint_api.BlueprintCreateRequest(profile_type=profile_type)
        policy = blueprint_api.server_owned_interview_policy(request.profile_type)
        assert policy == {
            "difficulty_level": "adaptive",
            "duration_minutes": expected_target,
            "focus": ["mixed"],
            "question_count": None,
            "round_config": {},
        }

    assert blueprint_api.server_owned_interview_policy("top_tier", "technical") == {
        "difficulty_level": "adaptive",
        "duration_minutes": 80,
        "focus": ["mixed"],
        "question_count": 2,
        "round_config": {},
    }


def test_preset_blueprint_uses_resume_context_without_a_saved_job_profile():
    target = blueprint_api._resolve_blueprint_job_target(
        job_row=None,
        resume_payload={
            "target_role": "Machine Learning Engineer",
            "summary": "Built and evaluated production machine-learning systems.",
            "skills": ["Python", "PyTorch", "PostgreSQL"],
        },
        profile_type="top_tier",
        requested_job_profile_id=None,
    )

    assert target["job_profile_id"] is None
    assert target["role"] == "Machine Learning Engineer"
    assert target["source"] == "resume"
    assert "production machine-learning systems" in target["job_description"]
    assert "Python, PyTorch, PostgreSQL" in target["job_description"]


def test_custom_blueprint_still_requires_a_saved_profile_with_full_jd():
    with pytest.raises(blueprint_api.HTTPException) as exc:
        blueprint_api._resolve_blueprint_job_target(
            job_row=None,
            resume_payload={"target_role": "Backend Engineer", "skills": ["Python"]},
            profile_type="custom",
            requested_job_profile_id=None,
        )

    assert exc.value.status_code == 422
    assert "saved profile" in exc.value.detail


def test_explicit_missing_job_profile_does_not_silently_fall_back_to_resume():
    with pytest.raises(blueprint_api.HTTPException) as exc:
        blueprint_api._resolve_blueprint_job_target(
            job_row=None,
            resume_payload={"target_role": "Backend Engineer", "skills": ["Python"]},
            profile_type="mid_tier",
            requested_job_profile_id=999,
        )

    assert exc.value.status_code == 404


def test_interview_and_technical_setup_expose_exactly_four_supported_profiles():
    expected = {"top_tier", "mid_tier", "startup", "custom"}

    assert PROFILE_TYPES == expected
    assert set(PROFILE_CONFIGS) == expected
    assert {option["profile_type"] for option in workspace_api._profile_options()} == expected
    for profile_type in expected:
        request = blueprint_api.BlueprintCreateRequest(
            interview_type="technical",
            profile_type=profile_type,
        )
        assert request.profile_type == profile_type
        assert PROFILE_CONFIGS[profile_type]["interview_instruction"]
        assert PROFILE_CONFIGS[profile_type]["technical_instruction"]

    with pytest.raises(ValueError):
        blueprint_api.BlueprintCreateRequest(profile_type="custom_only")


class _SingleRowCursor:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row

    def close(self):
        return None


class _SingleCursorConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_modern_resume_and_job_assets_satisfy_legacy_completion_reads():
    profile = encrypt_json({"name": "Ada Lovelace", "skills": ["Python"]})
    cursor = _SingleRowCursor((True, None, profile, None, True, True))
    connection = _SingleCursorConnection(cursor)

    with patch.object(user_profile, "get_db_connection", return_value=connection), patch.object(
        user_profile,
        "return_db_connection",
        return_value=None,
    ):
        payload = asyncio.run(user_profile.get_completion_status(current_user={"user_id": "user-1"}))

    assert payload == {
        "completed": True,
        "has_resume": True,
        "has_job": True,
        "missing_fields": [],
    }
    assert "FROM ResumeVersions" in cursor.queries[0][0]
    assert "FROM JobProfiles" in cursor.queries[0][0]


def test_modern_resume_and_job_assets_produce_interview_ready_status():
    cursor = _SingleRowCursor((None, None, None, True, None, True, True))
    connection = _SingleCursorConnection(cursor)

    with patch.object(pre_interview, "get_db", return_value=connection):
        payload = asyncio.run(pre_interview.get_profile_status(current_user={"user_id": "user-1"}))

    assert payload["resume_uploaded"] is True
    assert payload["job_selected"] is True
    assert payload["current_step"] == "interview_ready"
    assert "FROM ResumeVersions" in cursor.queries[0][0]
    assert "FROM JobProfiles" in cursor.queries[0][0]


def test_selected_job_description_decrypts_sqlite_binary_values():
    encrypted = encrypt_data("Private backend job description").encode("utf-8")

    assert pre_interview._decrypt_text_blob(memoryview(encrypted)) == "Private backend job description"




class _CanonicalCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    def execute(self, query, params=None):
        self.query = " ".join(query.split())

    def fetchall(self):
        return self.rows


def test_canonical_performance_groups_only_comparable_versions_and_keeps_unknown_score():
    now = datetime.now(timezone.utc)
    rows = [
        (
            "analysis-new", "interview-new", "mock", "v2", "hash-new", "ready",
            {"dimensions": {"relevance": 78}, "question_analyses": []},
            {"response_ids": ["response-1"]}, None,
            "evaluator-v2", "taxonomy-v2", "rubric-v2", 1500,
            "insufficient_evidence", now,
        ),
        (
            "analysis-comparable", "interview-old", "mock", "v2", "hash-old", "ready",
            {"dimensions": {"relevance": 70}}, {"response_ids": ["response-2"]}, 74.0,
            "evaluator-v2", "taxonomy-v2", "rubric-v2", 1400, "sufficient", now,
        ),
        (
            "analysis-incompatible", "interview-legacy", "mock", "legacy", "hash-legacy", "ready",
            {}, {}, 92.0, "legacy", "legacy", "legacy", 1200, "legacy", now,
        ),
    ]
    payload = workspace_api._canonical_performance_payloads(_CanonicalCursor(rows), "user-1")["interview"]

    assert payload["source"] == "canonical"
    assert payload["overall_score"] is None
    assert payload["evidence_status"] == "insufficient_evidence"
    assert payload["evidence_index"] == {"response_ids": ["response-1"]}
    assert payload["comparability"]["comparable_analysis_count"] == 1
    assert payload["comparability"]["evidence_status"] == "sufficient"
    assert payload["comparability"]["excluded_incompatible_count"] == 2
    assert len(payload["trend"]) == 1
    assert payload["trend"][0]["score"] == 74.0
    assert payload["confidence"] == "insufficient"
    assert payload["evidence_count"] == 1
    assert payload["empty_state_explanation"]


def test_canonical_technical_performance_exposes_attempted_problem_evidence():
    now = datetime.now(timezone.utc)
    rows = [
        (
            "analysis-technical", "interview-technical", "technical", "v2", "hash", "ready",
            {
                "dimension_scores": {"problem_solving": 72},
                "technical": {
                    "correctness_score": 75,
                    "submission_count": 1,
                    "run_event_count": 2,
                    "typed_assessed_count": 0,
                    "test_matrix": [{
                        "round_id": "round-1",
                        "title": "Two Sum",
                        "language": "python",
                        "final_verdict": "needs_work",
                        "final_pass_rate": 75,
                        "runtime_ms": 12,
                    }],
                    "weak_topics": [{
                        "topic": "hash maps",
                        "repair_action": "Rework the failing edge case, then prove the complexity.",
                    }],
                },
            },
            {"round_ids": ["round-1"]}, 75.0,
            "evaluator-v2", "taxonomy-v2", "rubric-v2", 2400, "sufficient", now,
        )
    ]

    payload = workspace_api._canonical_performance_payloads(_CanonicalCursor(rows), "user-1")["technical"]

    sections = {section["id"]: section for section in payload["sections"]}
    assert sections["technical_summary"]["metrics"][0]["value"] == "75%"
    assert sections["technical_problem_evidence"]["rows"][0]["round_id"] == "round-1"
    assert sections["technical_problem_evidence"]["rows"][0]["score"] == "75%"
    assert payload["next_focus"]["title"] == "Hash Maps"
    assert payload["mode"] == "technical"
    assert payload["evidence_count"] == 1
    assert payload["source_analysis_ids"] == ["analysis-technical"]


def test_canonical_performance_does_not_join_different_profile_families():
    now = datetime.now(timezone.utc)
    rows = [
        (
            "analysis-top", "interview-top", "mock", "session-performance-v3", "hash-top", "ready",
            {"report": {"profile_type": "top_tier"}, "dimension_scores": {"relevance": 82}},
            {"response_ids": ["response-top"]}, 82.0,
            "evaluator-v3", "taxonomy-v3", "rubric-v3", 1200, "sufficient", now,
        ),
        (
            "analysis-mid", "interview-mid", "mock", "session-performance-v3", "hash-mid", "ready",
            {"report": {"profile_type": "mid_tier"}, "dimension_scores": {"relevance": 76}},
            {"response_ids": ["response-mid"]}, 76.0,
            "evaluator-v3", "taxonomy-v3", "rubric-v3", 1200, "sufficient", now,
        ),
    ]

    payload = workspace_api._canonical_performance_payloads(_CanonicalCursor(rows), "user-1")["interview"]

    assert payload["comparability"]["profile_family"] == "top_tier"
    assert payload["comparability"]["comparable_analysis_count"] == 1
    assert payload["comparability"]["excluded_incompatible_count"] == 1
    assert payload["source_analysis_ids"] == ["analysis-top"]


def test_history_report_cta_links_real_evidence_without_requiring_performance_backfill():
    unavailable = workspace_api._candidate_report_cta(
        "interview-legacy",
        interview_status="completed",
        report_present=True,
        has_candidate_evidence=False,
        canonical_report_ready=False,
    )
    assert unavailable == {
        "label": "Report unavailable",
        "nav": "unavailable",
        "entity_id": "interview-legacy",
    }

    available = workspace_api._candidate_report_cta(
        "interview-current",
        interview_status="completed",
        report_present=True,
        has_candidate_evidence=True,
        canonical_report_ready=True,
    )
    assert available["nav"] == "report"

    recorded_report = workspace_api._candidate_report_cta(
        "interview-recorded",
        interview_status="completed",
        report_present=True,
        has_candidate_evidence=True,
        canonical_report_ready=False,
    )
    assert recorded_report["nav"] == "report"
    assert recorded_report["label"] == "View Full Report"

    missing_report = workspace_api._candidate_report_cta(
        "interview-needs-report",
        interview_status="completed",
        report_present=False,
        has_candidate_evidence=True,
        canonical_report_ready=False,
    )
    assert missing_report["nav"] == "report"
    assert missing_report["label"] == "Open report"

    generating = workspace_api._candidate_report_cta(
        "interview-running-analysis",
        interview_status="analysis_running",
        report_present=False,
        has_candidate_evidence=True,
        canonical_report_ready=False,
    )
    assert generating["nav"] == "report"
    assert generating["label"] == "View report progress"


class _LearningCursor:
    def __init__(self):
        self.queries = []
        self.rows = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.queries.append(normalized)
        if "FROM LearnerSkillStates" in normalized:
            self.rows = [("behavioral:star", "interview", 52.0, 70.0, 4, None, None)]
        elif "FROM WeaknessStates" in normalized:
            self.rows = [
                (
                    "weakness-1", "behavioral:star", "repeated", 4, 2,
                    50.0, 58.0, 0.75, "Answer planning", "medium", {}, None,
                )
            ]
        elif any(
            table in normalized
            for table in ("TechnicalMistakeClusters", "ProjectKnowledgeGaps", "GeneratedExercises", "SessionReviewEvents")
        ):
            self.rows = []
        elif "FROM Interviews i" in normalized:
            self.rows = [(5, 5)]
        elif "FROM SessionPerformanceAnalyses" in normalized:
            # Improve is unlocked only after repeatable Performance evidence
            # exists for one mode, represented by the max mode count.
            self.rows = [(2,)]
        else:
            raise AssertionError(f"Unexpected direct query: {normalized}")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_learning_snapshot_is_read_only_and_exposes_exact_next_action_ids():
    cursor = _LearningCursor()
    mission = {
        "mission_id": "mission-1",
        "mode": "mock",
        "title": "Fix STAR depth",
        "roadmap": [
            {
                "roadmap_node_id": "node-1",
                "exercise_id": "exercise-1",
                "title": "Rewrite one answer",
                "availability_status": "current",
                "result_status": "not_attempted",
            }
        ],
    }
    with patch.object(
        workspace_api,
        "_active_mission_payload",
        side_effect=[mission, None],
    ), patch.object(
        workspace_api,
        "_improvement_history_payload",
        return_value={"skills": [], "completed_missions": [], "recent_attempts": [], "has_history": False},
    ):
        payload = workspace_api.build_readonly_learning_snapshot(cursor, "user-1")

    assert payload["next_action"]["mode"] == "mock"
    assert payload["next_action"]["mission_id"] == "mission-1"
    assert payload["next_action"]["roadmap_node_id"] == "node-1"
    assert payload["next_action"]["exercise_id"] == "exercise-1"
    assert payload["weakness_states"][0]["lifecycle_state"] == "repeated"
    assert not any(query.startswith(("INSERT ", "UPDATE ", "DELETE ")) for query in cursor.queries)


def test_learning_snapshot_starts_improve_after_one_report_but_keeps_comparison_pending():
    cursor = _LearningCursor()
    with patch.object(workspace_api, "_performance_ready_count", return_value=1), patch.object(
        workspace_api, "_active_mission_payload", return_value=None,
    ), patch.object(
        workspace_api,
        "_improvement_history_payload",
        return_value={"skills": [], "completed_missions": [], "recent_attempts": [], "has_history": False},
    ):
        payload = workspace_api.build_readonly_learning_snapshot(cursor, "user-1")

    assert payload["performance_ready"] is True
    assert payload["comparison_ready"] is False
    assert payload["analysis_availability"]["performance_ready"] is True
    assert payload["analysis_availability"]["comparison_ready"] is False
    assert payload["active_mission"] is None
    assert payload["exercise_queue"] == []
    assert payload["improve_available"] is False
