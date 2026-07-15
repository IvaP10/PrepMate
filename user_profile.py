# ============================================================================
# MODULE: user_profile.py
# PURPOSE: Account-level reads/writes — profile, avatar, account info, history,
#          stats, GDPR export, notification prefs. Mounted under /api/profile.
# STRUCTURE:
#   - Pydantic request/response models (lines 25-44)
#   - Route handlers (lines 46-700)
# ENDPOINTS (prefix /api/profile):
#   - GET    /me                    -> get_profile (line 46)
#   - PUT    /update                -> update_profile (103)
#   - DELETE /resume                -> wipe resume (157)
#   - GET    /completion-status     -> profile completion check (194)
#   - GET    /interview-history     -> list interviews (250)
#   - GET    /statistics            -> per-user stats (301)
#   - PUT    /update-account        -> change name/email (356)
#   - POST   /avatar                -> upload avatar (base64) (405)
#   - GET    /export-data           -> GDPR export JSON (439)
#   - DELETE /session-history       -> wipe interviews + responses (546)
#   - GET    /notification-prefs    -> read JSONB prefs (582)
#   - PUT    /notification-prefs    -> upsert JSONB prefs (611)
# DEPENDS ON: auth, database, security_utils
# CONSUMED BY: app.py, Frontend/lib/api.ts (updateAccountInfo, uploadAvatar,
#              exportUserData, deleteSessionHistory, getNotificationPrefs,
#              updateNotificationPrefs), settings tabs in dashboard
# DATA TABLES: UserInfo (all), Interviews, InterviewResponses (history/export/delete)
# ============================================================================

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging

from auth import get_current_user
from database import get_db_connection, return_db_connection
from entitlements import get_active_subscription_plan_type, get_entitlements_for_user
from security_utils import stable_hash, encrypt_json, decrypt_json, decrypt_data

router = APIRouter(tags=["Profile"])
logger = logging.getLogger("ai_interviewer.profile")


def _export_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


_JSON_ENCRYPTED_EXPORT_COLUMNS = {
    "analysis_json_encrypted",
    "blueprint_context_encrypted",
    "evidence_index_encrypted",
    "facts_encrypted",
    "job_context_encrypted",
    "manifest_encrypted",
    "output_json_encrypted",
    "payload_encrypted",
    "report_json_encrypted",
    "resume_payload_encrypted",
}
_SYSTEM_SECRET_EXPORT_COLUMNS = {
    # Execution cases may contain the private hidden-test suite. They are
    # system-owned evaluator material rather than user content.
    "cases_encrypted",
}


def _decrypt_export_blob(column: str, value: Any) -> Any:
    """Return user-readable content without exporting ciphertext or hidden tests."""
    if value is None:
        return None
    if column in _SYSTEM_SECRET_EXPORT_COLUMNS:
        return "[system evaluator data omitted]"
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    if column in _JSON_ENCRYPTED_EXPORT_COLUMNS:
        return _export_value(decrypt_json(value))
    return decrypt_data(str(value))


def _export_row(columns: List[str], row: Any) -> Dict[str, Any]:
    exported: Dict[str, Any] = {}
    for column, value in zip(columns, row):
        if column.endswith("_encrypted"):
            logical_name = column.removesuffix("_encrypted")
            decoded = _decrypt_export_blob(column, value)
            if decoded is not None or logical_name not in exported:
                exported[logical_name] = decoded
            continue
        # A legacy plaintext placeholder such as "[encrypted]" must not
        # overwrite the decoded value encountered later in the same row.
        if column in exported and exported[column] not in (None, "", "[encrypted]"):
            continue
        exported[column] = _export_value(value)
    return exported


def _fetch_user_table_rows(cursor, table_name: str, user_id: str) -> List[Dict[str, Any]]:
    cursor.execute(f"SELECT * FROM {table_name} WHERE user_id = %s", (user_id,))
    columns = [desc[0] for desc in cursor.description]
    return [_export_row(columns, row) for row in cursor.fetchall()]


def _fetch_interview_table_rows(cursor, table_name: str, user_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT target.*
        FROM {table_name} target
        JOIN Interviews interview ON interview.interview_id = target.interview_id
        WHERE interview.user_id = %s
        """,
        (user_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [_export_row(columns, row) for row in cursor.fetchall()]


def _fetch_weakness_evidence_rows(cursor, user_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT link.*
        FROM WeaknessEvidenceLinks link
        JOIN WeaknessStates weakness
          ON weakness.weakness_state_id = link.weakness_state_id
        WHERE weakness.user_id = %s
        """,
        (user_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [_export_row(columns, row) for row in cursor.fetchall()]


def _fetch_analysis_stage_outputs(cursor, user_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT aso.*
        FROM AnalysisStageOutputs aso
        JOIN AnalysisJobs aj ON aj.job_id = aso.job_id
        WHERE aj.user_id = %s
        """,
        (user_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [_export_row(columns, row) for row in cursor.fetchall()]

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    skills: Optional[List[str]] = None
    education: Optional[List[Dict]] = None
    experience: Optional[List[Dict]] = None
    projects: Optional[List[Dict]] = None

class ProfileResponse(BaseModel):
    user_id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    job_id: Optional[str]
    job_title: Optional[str]
    resume_text: Optional[str]
    resume_json: Optional[Dict]
    profile_json: Optional[Dict]
    profile_completed: bool
    mock_interview_count: int
    practice_interview_count: int
    date_created: datetime

@router.get("/entitlements")
async def get_entitlements(current_user: Dict = Depends(get_current_user)):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        active_plan_type = get_active_subscription_plan_type(
            cursor,
            current_user["user_id"],
            datetime.now(timezone.utc),
        )
        return get_entitlements_for_user(cursor, current_user["user_id"], active_plan_type or "starter")
    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                u.user_id,
                u.full_name,
                l.email,
                COALESCE(u.job_id::text, selected_job.profile_id::text),
                u.resume_json,
                u.profile_json,
                u.profile_completed,
                u.mock_interview_count,
                u.practice_interview_count,
                u.date_created,
                COALESCE(j.title, selected_job.role)
            FROM UserInfo u
            JOIN Login l ON u.user_id = l.user_id
            LEFT JOIN Jobs j ON u.job_id = j.job_id
            LEFT JOIN LATERAL (
                SELECT profile_id, role
                FROM JobProfiles
                WHERE user_id = u.user_id AND is_selected = TRUE
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
            ) selected_job ON TRUE
            WHERE u.user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )

        return ProfileResponse(**{
            "user_id": row[0],
            "full_name": row[1],
            "email": row[2],
            "job_id": row[3],
            "job_title": row[10],
            "resume_text": None,
            "resume_json": decrypt_json(row[4]),
            "profile_json": decrypt_json(row[5]),
            "profile_completed": row[6],
            "mock_interview_count": row[7],
            "practice_interview_count": row[8],
            "date_created": row[9]
        })

    finally:
        cursor.close()
        return_db_connection(connection)

@router.put("/update")
async def update_profile(
    request: UpdateProfileRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT profile_json FROM UserInfo WHERE user_id = %s",
            (current_user["user_id"],)
        )

        row = cursor.fetchone()
        existing_profile = decrypt_json(row[0]) if row and row[0] else {}
        if not isinstance(existing_profile, dict):
            existing_profile = {}

        updates = request.model_dump(exclude_unset=True)
        existing_profile.update(updates)

        cursor.execute(
            """
            UPDATE UserInfo
            SET profile_json = %s,
                full_name = COALESCE(%s, full_name)
            WHERE user_id = %s
            """,
            (
                json.dumps(encrypt_json(existing_profile)),
                request.full_name,
                current_user["user_id"]
            ),
        )

        connection.commit()
        logger.info("Profile updated for %s", stable_hash(current_user["user_id"], "user"))

        return {
            "message": "Profile updated successfully",
            "profile": existing_profile
        }

    except Exception:
        connection.rollback()
        logger.error("Failed to update profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.delete("/resume")
async def delete_resume(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE ResumeVersions
            SET is_active = FALSE,
                updated_at = NOW()
            WHERE user_id = %s
            """,
            (current_user["user_id"],),
        )
        cursor.execute(
            """
            DELETE FROM ResumeVersions version
            WHERE version.user_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM Interviews interview
                  WHERE interview.resume_id = version.resume_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM InterviewBlueprints blueprint
                  WHERE blueprint.resume_id = version.resume_id
              )
            """,
            (current_user["user_id"],),
        )
        cursor.execute(
            """
            UPDATE UserInfo
            SET resume_json = NULL,
                resume_text_encrypted = NULL,
                resume_uploaded_at = NULL,
                active_resume_id = NULL,
                profile_completed = FALSE
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        connection.commit()
        logger.info("Resume deleted for %s", stable_hash(current_user["user_id"], "user"))

        return {
            "message": "Active resume removed successfully",
            "retained_history": "Resume versions tied to historical interviews remain inactive so their evidence stays auditable.",
        }

    except Exception:
        connection.rollback()
        logger.error("Failed to delete resume")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete resume"
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/completion-status")
async def get_completion_status(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                profile_completed,
                resume_json,
                profile_json,
                job_id,
                EXISTS (
                    SELECT 1 FROM ResumeVersions
                    WHERE user_id = UserInfo.user_id AND is_active = TRUE
                ) AS has_active_resume,
                EXISTS (
                    SELECT 1 FROM JobProfiles
                    WHERE user_id = UserInfo.user_id AND is_selected = TRUE
                ) AS has_selected_job_profile
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        profile_completed = row[0]
        has_resume = bool(row[1]) or bool(row[4])
        profile_json = decrypt_json(row[2]) if row[2] else {}
        has_job = bool(row[3]) or bool(row[5])

        missing_fields = []

        if not profile_json.get("name"):
            missing_fields.append("name")

        if not profile_json.get("skills") or len(profile_json.get("skills", [])) == 0:
            missing_fields.append("skills")

        if not has_job:
            missing_fields.append("job_selection")

        return {
            "completed": len(missing_fields) == 0,
            "has_resume": has_resume,
            "has_job": has_job,
            "missing_fields": missing_fields
        }

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/interview-history")
async def get_interview_history(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                interview_id,
                interview_type,
                job_title,
                strictness_level,
                overall_score,
                feedback_summary,
                created_at,
                completed_at
            FROM Interviews
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (current_user["user_id"],)
        )

        rows = cursor.fetchall()

        interviews = []
        for row in rows:
            interviews.append({
                "interview_id": row[0],
                "interview_type": row[1],
                "job_title": row[2],
                "strictness_level": row[3],
                "overall_score": row[4],
                "feedback_summary": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None
            })

        return {
            "total_interviews": len(interviews),
            "interviews": interviews
        }

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/statistics")
async def get_statistics(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                mock_interview_count,
                practice_interview_count
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()
        mock_count = row[0] if row else 0
        practice_count = row[1] if row else 0

        cursor.execute(
            """
            SELECT 
                AVG(overall_score) as avg_score,
                COUNT(*) as completed_count
            FROM Interviews
            WHERE user_id = %s
            AND overall_score IS NOT NULL
            """,
            (current_user["user_id"],)
        )

        stats_row = cursor.fetchone()
        avg_score = float(stats_row[0]) if stats_row and stats_row[0] else 0.0
        completed_count = stats_row[1] if stats_row else 0

        return {
            "mock_interviews": mock_count,
            "practice_interviews": practice_count,
            "total_interviews": mock_count + practice_count,
            "completed_interviews": completed_count,
            "average_score": round(avg_score, 2)
        }

    finally:
        cursor.close()
        return_db_connection(connection)

class UpdateAccountRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None

@router.put("/update-account")
async def update_account(
    request: UpdateAccountRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        if request.email:
            cursor.execute(
                "SELECT user_id FROM Login WHERE email = %s AND user_id != %s",
                (request.email.lower().strip(), current_user["user_id"])
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email is already in use by another account"
                )

        if request.full_name:
            cursor.execute(
                "UPDATE UserInfo SET full_name = %s WHERE user_id = %s",
                (request.full_name.strip(), current_user["user_id"])
            )

        if request.email:
            cursor.execute(
                "UPDATE Login SET email = %s WHERE user_id = %s",
                (request.email.lower().strip(), current_user["user_id"])
            )

        connection.commit()
        return {"message": "Account updated successfully"}
    except HTTPException:
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to update account")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update account"
        )
    finally:
        cursor.close()
        return_db_connection(connection)

class AvatarRequest(BaseModel):
    avatar_data: str

@router.post("/avatar")
async def upload_avatar(
    request: AvatarRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        data = request.avatar_data
        if len(data) > 1_400_000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image is too large. Please use an image under 1 MB."
            )

        cursor.execute(
            "UPDATE UserInfo SET avatar_url = %s WHERE user_id = %s",
            (data, current_user["user_id"])
        )
        connection.commit()
        return {"message": "Avatar updated", "avatar_url": data}
    except HTTPException:
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to upload avatar")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar"
        )
    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/export-data")
async def export_data(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT u.full_name, l.email, u.resume_json, u.profile_json,
                      u.mock_interview_count, u.practice_interview_count,
                      u.date_created
               FROM UserInfo u JOIN Login l ON u.user_id = l.user_id
               WHERE u.user_id = %s""",
            (current_user["user_id"],)
        )
        profile_row = cursor.fetchone()

        cursor.execute(
            """SELECT interview_id, interview_mode, interview_type, job_title,
                      strictness_level, status, overall_score, feedback_summary,
                      report_json, duration_seconds, full_transcript,
                      created_at, completed_at, report_json_encrypted,
                      transcript_encrypted
               FROM Interviews WHERE user_id = %s ORDER BY created_at DESC""",
            (current_user["user_id"],)
        )
        interview_rows = cursor.fetchall()

        interviews = []
        for row in interview_rows:
            cursor.execute(
                """SELECT question_id, question_text, question_order, question_type,
                          topic_label, difficulty_level, taxonomy_keys,
                          expected_points, rubric_json, selection_reason,
                          blueprint_section_id, provenance, profile_type,
                          rubric_version, source
                   FROM InterviewQuestions WHERE interview_id = %s ORDER BY question_order""",
                (row[0],)
            )
            question_columns = [desc[0] for desc in cursor.description]
            questions = []
            for question_row in cursor.fetchall():
                question = _export_row(question_columns, question_row)
                question["text"] = question.pop("question_text", None)
                question["order"] = question.pop("question_order", None)
                question["type"] = question.pop("question_type", None)
                question["topic"] = question.pop("topic_label", None)
                question["difficulty"] = question.pop("difficulty_level", None)
                questions.append(question)

            cursor.execute(
                """SELECT question_id, user_response, score, ai_feedback,
                          response_time_seconds, technical_accuracy,
                          communication, problem_solving, confidence, relevance,
                          answer_text_encrypted, transcript_encrypted,
                          input_mode, timing_json, evidence_hash
                   FROM InterviewResponses WHERE interview_id = %s""",
                (row[0],)
            )
            responses = []
            for response_row in cursor.fetchall():
                answer = _decrypt_export_blob("answer_text_encrypted", response_row[10])
                transcript = _decrypt_export_blob("transcript_encrypted", response_row[11])
                responses.append({
                    "question_id": response_row[0],
                    "response": answer or response_row[1],
                    "transcript": transcript,
                    "score": float(response_row[2]) if response_row[2] is not None else None,
                    "feedback": response_row[3],
                    "response_time": response_row[4],
                    "technical_accuracy": float(response_row[5]) if response_row[5] is not None else None,
                    "communication": float(response_row[6]) if response_row[6] is not None else None,
                    "problem_solving": float(response_row[7]) if response_row[7] is not None else None,
                    "confidence": float(response_row[8]) if response_row[8] is not None else None,
                    "relevance": float(response_row[9]) if response_row[9] is not None else None,
                    "input_mode": response_row[12],
                    "timing": _export_value(response_row[13]),
                    "evidence_hash": response_row[14],
                })

            report = _decrypt_export_blob("report_json_encrypted", row[13])
            if report is None:
                report = decrypt_json(row[8])
            transcript = _decrypt_export_blob("transcript_encrypted", row[14])
            if transcript is None:
                transcript = decrypt_json(row[10])

            interviews.append({
                "interview_id": row[0], "mode": row[1], "type": row[2],
                "job_title": row[3], "strictness": row[4], "status": row[5],
                "overall_score": float(row[6]) if row[6] is not None else None,
                "feedback_summary": row[7],
                "report": report,
                "transcript": transcript,
                "duration_seconds": row[9],
                "created_at": row[11].isoformat() if row[11] else None,
                "completed_at": row[12].isoformat() if row[12] else None,
                "questions": questions,
                "responses": responses,
            })

        job_profiles = _fetch_user_table_rows(cursor, "JobProfiles", current_user["user_id"])

        user_owned_tables = {
            "ai_event_logs": "AIEventLogs",
            "local_model_inference_logs": "LocalModelInferenceLogs",
            "learner_skill_states": "LearnerSkillStates",
            "skill_evidence_events": "SkillEvidenceEvents",
            "project_knowledge_gaps": "ProjectKnowledgeGaps",
            "coach_exercises": "CoachExercises",
            "generated_exercises": "GeneratedExercises",
            "exercise_attempts": "ExerciseAttempts",
            "technical_rounds": "TechnicalInterviewRounds",
            "technical_run_events": "TechnicalRunEvents",
            "technical_mistake_clusters": "TechnicalMistakeClusters",
            "client_body_language_metrics": "ClientBodyLanguageMetrics",
            "anti_cheat_events": "AntiCheatEvents",
            "malpractice_events": "MalpracticeEvents",
            "interview_media_assets": "InterviewMediaAssets",
            "analysis_jobs": "AnalysisJobs",
            "attempt_preflight_checks": "AttemptPreflightChecks",
            "attempt_context_snapshots": "AttemptContextSnapshots",
            "attempt_integrity_events": "AttemptIntegrityEvents",
            "evidence_manifests": "EvidenceManifests",
            "evidence_corrections": "EvidenceCorrections",
            "report_artifacts": "ReportArtifacts",
            "resume_versions": "ResumeVersions",
            "interview_blueprints": "InterviewBlueprints",
            "session_performance_analyses": "SessionPerformanceAnalyses",
            "weakness_states": "WeaknessStates",
            "technical_execution_jobs": "TechnicalExecutionJobs",
            "technical_reasoning_evidence": "TechnicalReasoningEvidence",
            "ai_usage_reservations": "AIUsageReservations",
            "improvement_missions": "ImprovementMissions",
            "improvement_mission_skills": "ImprovementMissionSkills",
            "improvement_roadmap_nodes": "ImprovementRoadmapNodes",
            "improvement_mission_events": "ImprovementMissionEvents",
            "improvement_attempt_sessions": "ImprovementAttemptSessions",
            "mission_validation_evidence": "MissionValidationEvidence",
            "technical_code_snapshots": "TechnicalCodeSnapshots",
            "technical_submissions": "TechnicalSubmissions",
            "technical_telemetry_events": "TechnicalTelemetryEvents",
            "proctoring_flags": "ProctoringFlags",
            "subscriptions": "Subscriptions",
            "transactions": "Transactions",
            "resume_upload_logs": "ResumeUploadLogs",
            "support_submissions": "SupportSubmissions",
        }
        derived_data = {
            export_key: _fetch_user_table_rows(cursor, table_name, current_user["user_id"])
            for export_key, table_name in user_owned_tables.items()
        }
        # Exact unconsumed blueprint questions are evaluator material. Export
        # the user's setup, preview metadata, hashes, and lifecycle without
        # leaking future interview questions.
        for blueprint in derived_data["interview_blueprints"]:
            blueprint.pop("blueprint_json", None)
        derived_data["analysis_stage_outputs"] = _fetch_analysis_stage_outputs(cursor, current_user["user_id"])
        derived_data["response_assessments"] = _fetch_interview_table_rows(
            cursor, "ResponseAssessments", current_user["user_id"]
        )
        derived_data["question_validation_results"] = _fetch_interview_table_rows(
            cursor, "QuestionValidationResults", current_user["user_id"]
        )
        derived_data["weakness_evidence_links"] = _fetch_weakness_evidence_rows(
            cursor, current_user["user_id"]
        )

        export = {
            "exported_at": datetime.now().isoformat(),
            "profile": {
                "full_name": profile_row[0] if profile_row else None,
                "email": profile_row[1] if profile_row else None,
                "resume_json": decrypt_json(profile_row[2]) if profile_row else None,
                "profile_json": decrypt_json(profile_row[3]) if profile_row else None,
                "mock_interview_count": profile_row[4] if profile_row else 0,
                "practice_interview_count": profile_row[5] if profile_row else 0,
                "date_created": profile_row[6].isoformat() if profile_row and profile_row[6] else None,
            },
            "interviews": interviews,
            "job_profiles": job_profiles,
            "derived_data": derived_data,
        }

        return export
    except Exception:
        logger.error("Failed to export data")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export data"
        )
    finally:
        cursor.close()
        return_db_connection(connection)

@router.delete("/session-history")
async def delete_session_history(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    user_id = current_user["user_id"]
    deleted_counts: Dict[str, int] = {}

    def _delete(label: str, query: str, params: tuple = (user_id,)) -> None:
        cursor.execute(query, params)
        deleted_counts[label] = max(cursor.rowcount or 0, 0)

    try:
        cursor.execute("SELECT COUNT(*) FROM Interviews WHERE user_id = %s", (user_id,))
        interview_count = int((cursor.fetchone() or [0])[0] or 0)

        # Delete the complete session-derived graph. PostgreSQL cascades cover
        # most interview children, while these explicit deletes also remove
        # learning state that intentionally survives an individual interview.
        _delete("improvement_attempt_sessions", "DELETE FROM ImprovementAttemptSessions WHERE user_id = %s")
        _delete("mission_validation_evidence", "DELETE FROM MissionValidationEvidence WHERE user_id = %s")
        _delete("improvement_mission_events", "DELETE FROM ImprovementMissionEvents WHERE user_id = %s")
        _delete("improvement_roadmap_nodes", "DELETE FROM ImprovementRoadmapNodes WHERE user_id = %s")
        _delete("improvement_mission_skills", "DELETE FROM ImprovementMissionSkills WHERE user_id = %s")
        _delete("improvement_missions", "DELETE FROM ImprovementMissions WHERE user_id = %s")
        _delete("ai_event_logs", "DELETE FROM AIEventLogs WHERE user_id = %s")
        _delete("local_model_inference_logs", "DELETE FROM LocalModelInferenceLogs WHERE user_id = %s")
        _delete("exercise_attempts", "DELETE FROM ExerciseAttempts WHERE user_id = %s")
        _delete("generated_exercises", "DELETE FROM GeneratedExercises WHERE user_id = %s")
        _delete("coach_exercises", "DELETE FROM CoachExercises WHERE user_id = %s")
        _delete(
            "weakness_evidence_links",
            """DELETE FROM WeaknessEvidenceLinks
               WHERE weakness_state_id IN (
                   SELECT weakness_state_id FROM WeaknessStates WHERE user_id = %s
               )""",
        )
        _delete("weakness_states", "DELETE FROM WeaknessStates WHERE user_id = %s")
        _delete("skill_evidence_events", "DELETE FROM SkillEvidenceEvents WHERE user_id = %s")
        _delete("learner_skill_states", "DELETE FROM LearnerSkillStates WHERE user_id = %s")
        _delete("project_knowledge_gaps", "DELETE FROM ProjectKnowledgeGaps WHERE user_id = %s")
        _delete("technical_mistake_clusters", "DELETE FROM TechnicalMistakeClusters WHERE user_id = %s")
        _delete("technical_telemetry_events", "DELETE FROM TechnicalTelemetryEvents WHERE user_id = %s")
        _delete("technical_reasoning_evidence", "DELETE FROM TechnicalReasoningEvidence WHERE user_id = %s")
        _delete("technical_execution_jobs", "DELETE FROM TechnicalExecutionJobs WHERE user_id = %s")
        _delete("technical_submissions", "DELETE FROM TechnicalSubmissions WHERE user_id = %s")
        _delete("technical_run_events", "DELETE FROM TechnicalRunEvents WHERE user_id = %s")
        _delete("technical_code_snapshots", "DELETE FROM TechnicalCodeSnapshots WHERE user_id = %s")
        _delete("technical_rounds", "DELETE FROM TechnicalInterviewRounds WHERE user_id = %s")
        _delete("report_artifacts", "DELETE FROM ReportArtifacts WHERE user_id = %s")
        _delete(
            "analysis_stage_outputs",
            """DELETE FROM AnalysisStageOutputs
               WHERE job_id IN (SELECT job_id FROM AnalysisJobs WHERE user_id = %s)""",
        )
        _delete("analysis_jobs", "DELETE FROM AnalysisJobs WHERE user_id = %s")
        _delete("interview_media_assets", "DELETE FROM InterviewMediaAssets WHERE user_id = %s")
        _delete("interviews", "DELETE FROM Interviews WHERE user_id = %s")
        _delete("interview_blueprints", "DELETE FROM InterviewBlueprints WHERE user_id = %s")
        cursor.execute(
            """
            UPDATE UserInfo
            SET mock_interview_count = 0,
                practice_interview_count = 0
            WHERE user_id = %s
            """,
            (user_id,),
        )
        connection.commit()
        return {
            "message": "Session history deleted successfully",
            "interviews_deleted": interview_count,
            "deleted_counts": deleted_counts,
        }
    except Exception:
        connection.rollback()
        logger.error("Failed to delete session history")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete session history",
        )
    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/notification-prefs")
async def get_notification_prefs(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT notification_prefs FROM UserInfo WHERE user_id = %s",
            (current_user["user_id"],)
        )
        row = cursor.fetchone()
        prefs = row[0] if row and row[0] else {}
        return {
            "inactive_reminder_days": prefs.get("inactive_reminder_days"),
            "target_date": prefs.get("target_date"),
            "weekly_summary": prefs.get("weekly_summary", False),
            "streak_reminder": prefs.get("streak_reminder", False),
        }
    finally:
        cursor.close()
        return_db_connection(connection)

class NotificationPrefsRequest(BaseModel):
    inactive_reminder_days: Optional[int] = None
    target_date: Optional[str] = None
    weekly_summary: bool = False
    streak_reminder: bool = False

    @field_validator("inactive_reminder_days")
    @classmethod
    def validate_inactive_days(cls, value):
        if value is not None and value not in {3, 5, 7, 14}:
            raise ValueError("Inactive reminder days must be one of: 3, 5, 7, 14")
        return value

    @field_validator("target_date")
    @classmethod
    def validate_target_date(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Target date must use YYYY-MM-DD format") from exc
        return value

@router.put("/notification-prefs")
async def update_notification_prefs(
    request: NotificationPrefsRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT notification_prefs FROM UserInfo WHERE user_id = %s",
            (current_user["user_id"],)
        )
        row = cursor.fetchone()
        existing_prefs = row[0] if row and row[0] else {}
        if isinstance(existing_prefs, str):
            existing_prefs = json.loads(existing_prefs)
        if not isinstance(existing_prefs, dict):
            existing_prefs = {}

        prefs_data = request.model_dump()
        sent_metadata = existing_prefs.get("_sent")
        if isinstance(sent_metadata, dict):
            prefs_data["_sent"] = sent_metadata

        prefs = json.dumps(prefs_data)
        cursor.execute(
            "UPDATE UserInfo SET notification_prefs = %s WHERE user_id = %s",
            (prefs, current_user["user_id"])
        )
        connection.commit()
        return {"message": "Notification preferences saved"}
    except Exception:
        connection.rollback()
        logger.error("Failed to update notification prefs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification preferences"
        )
    finally:
        cursor.close()
        return_db_connection(connection)
