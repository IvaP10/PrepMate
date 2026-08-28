"""Real local SQLite lifecycle coverage for the source-only desktop alpha."""

import asyncio
import json
import uuid

import database
import analysis_pipeline
import app as application
import blueprint_api
import interview
import pre_interview
import technical_mode
import user_profile
import workspace_api
from local_runtime import LOCAL_USER_ID


def test_readiness_exposes_capabilities_once(monkeypatch):
    checks = {
        "database": {"healthy": True},
        "provider": {"healthy": False, "configured": False},
        "workers": {"healthy": True},
        "code_runner": {"healthy": True, "available_languages": ["python"]},
        "technical_content": {"healthy": True},
    }
    monkeypatch.setattr(application, "_local_checks", lambda: checks)

    payload = application.collect_readiness()

    assert payload["ready"] is False
    assert payload["features"]
    assert "features" not in payload["checks"]


def test_fresh_local_profile_form_is_an_empty_success(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database.close_connection_pool()

    payload = asyncio.run(pre_interview.get_form({"user_id": LOCAL_USER_ID}))

    assert payload == {"success": True, "form_data": None, "job_info": None}
    database.close_connection_pool()


def test_fresh_local_lifecycle_reaches_an_active_interview(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database.close_connection_pool()

    resume_marker = "PRIVATE-RESUME-MARKER-8d197c"
    job_marker = "PRIVATE-JOB-MARKER-4ae2b1"
    answer_marker = "PRIVATE-ANSWER-MARKER-f90c62"
    assessment_marker = "PRIVATE-ASSESSMENT-MARKER-0c73de"
    question_plan_marker = "PRIVATE-QUESTION-PLAN-MARKER-9167b0"
    code_marker = "PRIVATE-CODE-MARKER-cc581a"
    resume = {
        "name": "Synthetic Candidate",
        "email": "candidate@example.test",
        "skills": ["Python", "SQLite"],
        "summary": f"Builds local tools. {resume_marker}",
        "target_role": "Software Engineer",
        "experience": [],
        "projects": [],
        "education": [],
        "languages": [],
        "certifications": [],
        "achievements": [],
    }
    persisted = pre_interview._persist_parsed_resume(
        user_id=LOCAL_USER_ID,
        email=resume["email"],
        resume_json=resume,
        resume_text=f"Synthetic resume {resume_marker}",
        content_hash="local-lifecycle-resume-hash",
        source_filename="synthetic.pdf",
        parser_version="test",
        facts_payload={"review_version": "resume-facts-v1", "facts": []},
    )
    assert persisted["resume"]["confirmation_status"] == "confirmed"

    job_profile = asyncio.run(
        workspace_api.create_job_profile(
            workspace_api.JobProfileCreate(
                role="Software Engineer",
                company="Example Company",
                tech_stack=["Python", "SQLite"],
                job_description=f"Candidates must understand SQLite. {job_marker}",
                requirements=[f"Required private detail {job_marker}"],
            ),
            {"user_id": LOCAL_USER_ID},
        )
    )
    assert job_profile["job_description"].endswith(job_marker)

    blueprint = asyncio.run(
        blueprint_api.create_interview_blueprint(
            blueprint_api.BlueprintCreateRequest(
                profile_type="custom",
                interview_type="behavioral",
                job_profile_id=job_profile["profile_id"],
            ),
            {"user_id": LOCAL_USER_ID},
        )
    )
    preflight_id = str(uuid.uuid4())
    with database.get_db() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO AttemptPreflightChecks (
                preflight_id, user_id, blueprint_id, flow, input_mode, camera_ready,
                microphone_ready, microphone_level_detected, screen_share_ready,
                network_ready, backend_ready, provider_ready, sandbox_ready,
                worker_ready, error_codes, created_at, expires_at
            ) VALUES (
                ?, ?, ?, 'interview', 'text', FALSE, FALSE, FALSE, FALSE,
                TRUE, TRUE, TRUE, FALSE, TRUE, '[]', CURRENT_TIMESTAMP,
                datetime(CURRENT_TIMESTAMP, '+5 minutes')
            )
            """,
            (preflight_id, LOCAL_USER_ID, blueprint["blueprint_id"]),
        )
        connection.commit()

    started = asyncio.run(
        interview.start_interview(
            interview.StartInterviewRequest(
                blueprint_id=blueprint["blueprint_id"],
                preflight_id=preflight_id,
                input_mode="text",
                camera_mode="optional",
                interview_mode="mock",
                interview_type="behavioral",
                profile_type="custom",
            ),
            {"user_id": LOCAL_USER_ID},
        )
    )
    status = asyncio.run(
        interview.get_interview_status(
            started.interview_id,
            {"user_id": LOCAL_USER_ID},
        )
    )
    assert status["status"] == "in_progress"
    assert status["attempt_status"] == "active"
    assert "T" in status["started_at"]

    question_id = str(uuid.uuid4())
    with database.get_db() as connection:
        connection.execute(
            """
            INSERT INTO InterviewQuestions (
                question_id, interview_id, question_text, question_order,
                question_type, difficulty_level
            ) VALUES (?, ?, 'Tell me about a project.', 1, 'main', 'medium')
            """,
            (question_id, started.interview_id),
        )
        connection.commit()
    response_id = str(uuid.uuid4())
    stored = interview._persist_raw_answer(
        response_id=response_id,
        interview_id=started.interview_id,
        question_id=question_id,
        answer=f"I delivered the project successfully. {answer_marker}",
        response_seconds=12,
        idempotency_key="local-lifecycle-answer-1",
        input_mode="text",
        timing={"response_latency_seconds": 12},
        nonverbal_metrics={},
    )
    assert stored["inserted"] is True
    committed = interview._commit_live_assessment(
        response_id=response_id,
        interview_id=started.interview_id,
        assessment={
            "overall_score": 72,
            "feedback": f"Synthetic private evidence. {assessment_marker}",
            "dimension_scores": {"communication": 72},
            "evidence_status": "sufficient",
        },
        evidence_hash="local-lifecycle-assessment-hash",
        knowledge_map={"battlegrounds": [], "private_test_marker": question_plan_marker},
        next_question=None,
    )
    assert committed["duplicate"] is False

    round_id = str(uuid.uuid4())
    starter_code = "def solve():\n    pass\n"
    with database.get_db() as connection:
        connection.execute(
            """
            INSERT INTO TechnicalInterviewRounds (
                round_id, interview_id, user_id, round_type, language,
                prompt, starter_code, metadata, status
            ) VALUES (?, ?, ?, 'coding', 'python', ?, ?, '{}', 'active')
            """,
            (
                round_id,
                started.interview_id,
                LOCAL_USER_ID,
                "Write a small local function.",
                starter_code,
            ),
        )
        connection.commit()
    round_row = [None] * 21
    round_row[0] = round_id
    round_row[1] = started.interview_id
    round_row[20] = starter_code
    draft = technical_mode._persist_draft_snapshot_sync(
        tuple(round_row),
        LOCAL_USER_ID,
        technical_mode.DraftSaveRequest(
            language="python",
            code=f"def solve():\n    return '{code_marker}'\n",
            editor_revision=1,
        ),
    )
    assert draft["saved"] is True

    with database.get_db() as connection:
        connection.execute(
            """
            UPDATE Interviews
            SET status = 'analysis_pending', attempt_status = 'completed',
                analysis_status = 'queued', completed_at = CURRENT_TIMESTAMP
            WHERE interview_id = ?
            """,
            (started.interview_id,),
        )
        connection.commit()
    queued = asyncio.run(
        analysis_pipeline.enqueue_analysis_result(
            started.interview_id,
            LOCAL_USER_ID,
            reason="local_lifecycle_test",
        )
    )
    assert queued["state"] == "queued"
    asyncio.run(analysis_pipeline.run_analysis_job(queued["job_id"]))

    with database.get_db() as connection:
        interview_row = connection.execute(
            """
            SELECT status, analysis_status, report_json, report_json_encrypted
            FROM Interviews WHERE interview_id = ?
            """,
            (started.interview_id,),
        ).fetchone()
        stage_rows = connection.execute(
            """
            SELECT output_json, output_encrypted
            FROM AnalysisStageOutputs WHERE interview_id = ?
            """,
            (started.interview_id,),
        ).fetchall()
        outbox_row = connection.execute(
            """
            SELECT payload, payload_encrypted
            FROM ReportSideEffectOutbox WHERE interview_id = ?
            """,
            (started.interview_id,),
        ).fetchone()
    assert interview_row[0] in {"completed", "partial"}
    assert interview_row[1] == "ready"
    assert interview_row[2] == "[encrypted]"
    assert interview_row[3]
    assert stage_rows and all(json.loads(row[0]).get("encrypted") is True and row[1] for row in stage_rows)
    assert json.loads(outbox_row[0]).get("encrypted") is True
    assert outbox_row[1]

    exported = asyncio.run(user_profile.export_data({"user_id": LOCAL_USER_ID}))
    assert exported["profile"]["resume_json"]["summary"].endswith(resume_marker)
    assert exported["job_profiles"][0]["job_description"].endswith(job_marker)
    assert exported["interviews"][0]["responses"][0]["response"].endswith(answer_marker)
    exported_assessment = exported["derived_data"]["response_assessments"][0]["assessment_json"]
    assert exported_assessment["feedback"].endswith(assessment_marker)
    assert exported["interviews"][0]["question_plan"]["private_test_marker"] == question_plan_marker
    exported_code = exported["derived_data"]["technical_code_snapshots"][0]["source_code"]
    assert exported_code.endswith(f"'{code_marker}'\n")
    assert all(
        isinstance(row["output_json"], dict) and row["output_json"].get("encrypted") is not True
        for row in exported["derived_data"]["analysis_stage_outputs"]
    )

    with database.get_db() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    private_bytes = b"".join(
        path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file() and path.name.startswith("prepmate.sqlite3")
    )
    for marker in (
        resume_marker,
        job_marker,
        answer_marker,
        assessment_marker,
        question_plan_marker,
        code_marker,
    ):
        assert marker.encode("utf-8") not in private_bytes

    deletion = asyncio.run(user_profile.delete_resume({"user_id": LOCAL_USER_ID}))
    assert deletion["deleted_counts"]["resume_versions"] == 1
    assert deletion["deleted_counts"]["attempt_context_snapshots"] == 1
    assert deletion["deleted_counts"]["interview_blueprints"] == 1
    with database.get_db() as connection:
        retained_interview = connection.execute(
            """
            SELECT resume_id, blueprint_id, context_snapshot_id
            FROM Interviews WHERE interview_id = ?
            """,
            (started.interview_id,),
        ).fetchone()
        remaining_resumes = connection.execute(
            "SELECT COUNT(*) FROM ResumeVersions WHERE user_id = ?",
            (LOCAL_USER_ID,),
        ).fetchone()[0]
        profile_sources = connection.execute(
            "SELECT resume_json, profile_json, active_resume_id FROM UserInfo WHERE user_id = ?",
            (LOCAL_USER_ID,),
        ).fetchone()
    assert retained_interview == (None, None, None)
    assert remaining_resumes == 0
    assert profile_sources == (None, None, None)
    export_after_resume_deletion = asyncio.run(user_profile.export_data({"user_id": LOCAL_USER_ID}))
    assert export_after_resume_deletion["profile"]["resume_json"] is None
    assert export_after_resume_deletion["interviews"][0]["report"]

    history_deletion = asyncio.run(user_profile.delete_session_history({"user_id": LOCAL_USER_ID}))
    assert history_deletion["interviews_deleted"] == 1
    export_after_history_deletion = asyncio.run(user_profile.export_data({"user_id": LOCAL_USER_ID}))
    assert export_after_history_deletion["interviews"] == []
    assert export_after_history_deletion["derived_data"]["session_performance_analyses"] == []

    database.close_connection_pool()
