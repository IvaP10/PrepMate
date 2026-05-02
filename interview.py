from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from collections import deque
from datetime import datetime, timezone
from time import time
import json
import uuid
import logging
import asyncio

from auth import get_current_user, decode_token
from database import get_db_connection, return_db_connection
from config import settings
from redis_client import get_redis_client
from ai_services import (
    evaluate_response_realtime,
    transcribe_audio,
    generate_speech,
    generate_coaching_hint
)
from body_language import analyze_frame
from persona_generator import generate_persona, generate_opening_statement
import strictness_config
from report_generator import build_report_v2
from knowledge_map import (
    build_knowledge_map,
    get_next_battleground,
    mark_turn_used,
    is_interview_complete,
    should_transition,
    get_transition_to_next,
    generate_contextual_followup
)

router = APIRouter(tags=["Interview"])
logger = logging.getLogger("ai_interviewer.interview")
_memory_ws_tickets: Dict[str, Dict[str, Any]] = {}

class StartInterviewRequest(BaseModel):
    interview_mode: str
    interview_type: str
    job_id: Optional[int] = None
    job_profile_id: Optional[int] = None

class InterviewResponse(BaseModel):
    interview_id: str
    session_id: str
    mode: str
    message: str
    persona: Dict
    settings: Dict
    interviews_remaining: int

def _db_execute(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        result = None
        if fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
        if commit:
            conn.commit()
        return result, cursor.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(conn)

def _json_load(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default

def _score_value(scores: Dict, key: str) -> Optional[float]:
    value = (scores or {}).get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _profile_context_from_rows(resume_json: Dict[str, Any], profile_json: Dict[str, Any], external_profile_signals: Dict[str, Any]) -> Dict[str, Any]:
    context = dict(resume_json or profile_json or {})
    if "projects" not in context and isinstance(profile_json, dict):
        context["projects"] = profile_json.get("projects", [])
    if "experience" not in context and isinstance(profile_json, dict):
        context["experience"] = profile_json.get("experience") or profile_json.get("experiences") or []
    context["external_profile_signals"] = external_profile_signals or {}
    return context


def _rows_to_turns(rows: List[Any]) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    for row in rows or []:
        turns.append({
            "question": row[0],
            "question_type": row[1],
            "is_followup": row[2],
            "topic_label": row[3],
            "response": row[4],
            "score": float(row[5]) if row[5] is not None else 0,
            "feedback": row[6],
            "time_taken": row[7],
            "nonverbal_metrics": _json_load(row[8], {}),
            "coaching_hint": row[9],
            "evaluation_json": _json_load(row[10], {}),
            "answer_quality_flags": _json_load(row[11], []),
            "evidence_quotes": _json_load(row[12], []),
            "retry_state": _json_load(row[13], {}),
        })
    return turns


def _load_report_payload(cursor, interview_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT iq.question_text, iq.question_type, iq.is_followup,
               iq.topic_label, ir.user_response, ir.score, ir.ai_feedback,
               ir.response_time_seconds, ir.nonverbal_metrics, ir.coaching_hint,
               ir.evaluation_json, ir.answer_quality_flags, ir.evidence_quotes,
               ir.retry_state
        FROM InterviewResponses ir
        JOIN InterviewQuestions iq ON ir.question_id = iq.question_id
        WHERE ir.interview_id = %s
        ORDER BY iq.question_order, ir.created_at
        """,
        (interview_id,)
    )
    return _rows_to_turns(cursor.fetchall())


def _build_safe_report(interview_meta: Dict[str, Any], turns: List[Dict[str, Any]], profile_context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return build_report_v2(interview_meta, turns, profile_context=profile_context)
    except Exception:
        logger.exception("Structured report build failed for interview_id=%s", interview_meta.get("interview_id"))
        question_count = len(turns)
        avg_score = round(sum(float(turn.get("score") or 0) for turn in turns) / question_count, 1) if question_count else 0.0
        weakest_turn = min(turns, key=lambda turn: float(turn.get("score") or 0), default={})
        fallback_detail = (
            weakest_turn.get("feedback")
            or weakest_turn.get("coaching_hint")
            or "Rehearse direct answers with one project example, one decision, and the result."
        )
        return {
            "version": "report_v2_fallback",
            "summary": (
                f"{question_count} answers were captured with an average score of {avg_score:.1f}/100. "
                f"Biggest next fix: {fallback_detail}"
            ),
            "readiness_label": "Completed",
            "overall_score": avg_score,
            "job_title": interview_meta.get("job_title"),
            "mode": interview_meta.get("mode"),
            "interview_type": interview_meta.get("interview_type"),
            "skill_scores": {},
            "pillar_scores": {},
            "topic_breakdown": [],
            "behavioral_metrics": {
                "average_response_time_seconds": 0,
                "answer_quality_flags": {},
                "question_count": question_count,
            },
            "student_summary": {
                "headline": "Your answers were recorded, but the structured coaching report had to fall back to basic feedback.",
                "blocker": "The session still contains enough answer-level signal to review and improve.",
                "next_step": fallback_detail,
                "interviewer_signal": "Focus on answer structure, concrete examples, and follow-up depth.",
                "proof_point": "Use your strongest project or internship story as your base example.",
            },
            "strengths": [],
            "improvements": [{"title": "Highest-leverage fix", "detail": fallback_detail}],
            "practice_plan": [
                {"day": "Day 1", "task": fallback_detail},
                {"day": "Day 2", "task": "Rewrite your two weakest answers using direct answer, example, result, and trade-off."},
                {"day": "Day 3", "task": "Practice one follow-up-heavy topic and prepare deeper technical reasoning."},
            ],
            "per_turn_feedback": [
                {
                    "question": turn.get("question", ""),
                    "question_type": turn.get("question_type") or "main",
                    "is_followup": bool(turn.get("is_followup")),
                    "response": turn.get("response", ""),
                    "topic": turn.get("topic_label") or "General",
                    "score": float(turn.get("score") or 0),
                    "feedback": turn.get("feedback") or "",
                    "time_taken": turn.get("time_taken"),
                    "coaching_hint": turn.get("coaching_hint") or "",
                    "answer_quality_flags": turn.get("answer_quality_flags") or [],
                    "evidence_quotes": turn.get("evidence_quotes") or [],
                    "retry_state": turn.get("retry_state") or {},
                    "stronger_answer_outline": (
                        f"Start by directly answering: {str(turn.get('question') or '')[:120]}. "
                        "Then give one concrete example, explain your decision, and close with the result."
                    ),
                }
                for turn in turns
            ],
            "next_recommended_session_date": (datetime.utcnow().date()).isoformat(),
        }

def _should_request_retry(evaluation: Dict, question_type: str, interview_mode: Optional[str]) -> bool:
    if interview_mode != "practice" or question_type == "retry":
        return False
    flags = set(evaluation.get("answer_quality_flags") or [])
    score = float(evaluation.get("score") or 0)
    return bool(flags & {"off_topic", "too_short", "vague", "no_evidence"}) and score < 55

def _build_retry_prompt(original_question: str, evaluation: Dict) -> str:
    flags = set(evaluation.get("answer_quality_flags") or [])
    if "off_topic" in flags:
        instruction = "Focus directly on the question first, then add one relevant example."
    elif "too_short" in flags:
        instruction = "Give a fuller answer: direct point, concrete example, result, and one trade-off."
    elif "no_evidence" in flags:
        instruction = "Add proof from a project, job, GitHub repo, or measurable outcome."
    else:
        instruction = "Make it more specific with decisions, tools, constraints, and results."
    return f"Let's retry that. {instruction} Same question: {original_question}"

def _build_personalized_opening(persona: Dict, profile: Dict, signals: Dict, interview_mode: str) -> str:
    name = (profile.get("name") or "").split(" ")[0] or "there"
    role = profile.get("target_role") or persona.get("job_title") or "this role"
    skills = profile.get("skills") or []
    skill_anchor = ", ".join([str(skill) for skill in skills[:2] if skill])
    projects = profile.get("projects") or []
    project_anchor = ""
    if projects and isinstance(projects[0], dict):
        project_anchor = projects[0].get("name") or ""

    github = (signals or {}).get("github", {})
    repo_anchor = ""
    repos = github.get("repositories") if isinstance(github, dict) else []
    if repos and isinstance(repos[0], dict):
        repo_anchor = repos[0].get("name") or ""

    anchors = [part for part in [project_anchor, repo_anchor, skill_anchor] if part]
    anchor_text = f" I noticed {anchors[0]}, so I may use that as context." if anchors else ""
    practice_text = " I will pause after weak answers and ask you to retry with sharper structure." if interview_mode == "practice" else ""
    return (
        f"Hi {name}, I am {persona.get('name', 'your interviewer')}. "
        f"We will focus on the {role} interview today.{anchor_text} "
        f"I will ask concise questions, listen for specific evidence, and use follow-ups when your answer needs depth.{practice_text} "
        "Let's begin."
    )

def _cleanup_expired_ws_tickets() -> None:
    now_ts = time()
    expired = [
        ticket
        for ticket, entry in _memory_ws_tickets.items()
        if entry.get("expires_at", 0) <= now_ts
    ]
    for ticket in expired:
        _memory_ws_tickets.pop(ticket, None)

def _store_memory_ws_ticket(ticket: str, user_id: str) -> None:
    _cleanup_expired_ws_tickets()
    _memory_ws_tickets[ticket] = {
        "user_id": user_id,
        "expires_at": time() + settings.WS_TICKET_TTL_SECONDS,
    }

def _pop_memory_ws_ticket(ticket: str) -> Optional[str]:
    _cleanup_expired_ws_tickets()
    entry = _memory_ws_tickets.pop(ticket, None)
    if not entry:
        return None
    if entry.get("expires_at", 0) <= time():
        return None
    return entry.get("user_id")

@router.post("/ws-ticket")
async def create_ws_ticket(current_user: Dict = Depends(get_current_user)):
    redis_client = get_redis_client()

    ticket = str(uuid.uuid4())
    if redis_client:
        redis_client.setex(
            f"ws_ticket:{ticket}",
            settings.WS_TICKET_TTL_SECONDS,
            current_user["user_id"]
        )
    else:
        _store_memory_ws_ticket(ticket, current_user["user_id"])

    return {"ticket": ticket}

@router.post("/start", response_model=InterviewResponse)
async def start_interview(
    request: StartInterviewRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        if request.interview_mode not in ["practice", "mock"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interview mode must be 'practice' or 'mock'"
            )

        cursor.execute(
            """
            SELECT profile_completed, job_id, profile_json, resume_json,
                   interviews_remaining, is_unlimited, external_profile_signals, plan_type
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please complete your profile before starting an interview"
            )

        profile_json = row[2] or {}
        resume_json = row[3] or {}
        interviews_remaining = row[4] or 0
        is_unlimited = row[5] or False
        external_profile_signals = row[6] or {}
        plan_type = row[7] or "free"

        selected_job_profile = None
        if request.job_profile_id:
            cursor.execute(
                """
                SELECT profile_id, role, company, tech_stack
                FROM JobProfiles
                WHERE profile_id = %s AND user_id = %s
                """,
                (request.job_profile_id, current_user["user_id"])
            )
            selected_job_profile = cursor.fetchone()
            if not selected_job_profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Job profile not found"
                )
        elif not request.job_id:
            cursor.execute(
                """
                SELECT profile_id, role, company, tech_stack
                FROM JobProfiles
                WHERE user_id = %s
                ORDER BY is_selected DESC, created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],)
            )
            selected_job_profile = cursor.fetchone()

        has_name = bool(profile_json.get("name", ""))
        has_skills = bool(profile_json.get("skills"))
        if not selected_job_profile and (not has_name or not has_skills):
            missing = []
            if not has_name:
                missing.append("name")
            if not has_skills:
                missing.append("at least one skill")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Please complete your profile: missing {', '.join(missing)}"
            )

        if plan_type == "starter" and not is_unlimited:
            cursor.execute(
                """
                SELECT COUNT(*), MAX(created_at)
                FROM Interviews
                WHERE user_id = %s
                  AND interview_mode = 'mock'
                  AND created_at >= NOW() - INTERVAL '30 days'
                """,
                (current_user["user_id"],)
            )
            cooldown_row = cursor.fetchone()
            starter_count = cooldown_row[0] or 0
            last_started = cooldown_row[1]
            if starter_count > 0 and starter_count % 3 == 0 and last_started:
                elapsed_seconds = (datetime.utcnow() - last_started).total_seconds()
                if elapsed_seconds < 86400:
                    hours_left = max(1, int((86400 - elapsed_seconds + 3599) // 3600))
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Starter cooldown active. You can start another mock in about {hours_left} hour(s), or upgrade to Pro for no cooldown."
                    )

        if not is_unlimited:
            cursor.execute(
                """
                UPDATE UserInfo
                SET interviews_remaining = interviews_remaining - 1
                WHERE user_id = %s AND interviews_remaining > 0
                RETURNING interviews_remaining
                """,
                (current_user["user_id"],)
            )
            deducted = cursor.fetchone()
            if not deducted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No interviews remaining. Please purchase a plan to continue."
                )
            interviews_remaining = deducted[0]

        job_id = request.job_id or row[1]

        if selected_job_profile:
            tech_stack = selected_job_profile[3] or []
            if isinstance(tech_stack, str):
                try:
                    tech_stack = json.loads(tech_stack)
                except Exception:
                    tech_stack = []
            role = selected_job_profile[1]
            company = selected_job_profile[2]
            job_title = f"{role} at {company}" if company else role
            job_description = "Tech stack: " + ", ".join(tech_stack) if tech_stack else ""
            profile_json = {
                **profile_json,
                "target_role": role,
                "skills": profile_json.get("skills") or tech_stack,
            }
        elif job_id:
            cursor.execute(
                "SELECT title, description FROM Jobs WHERE job_id = %s",
                (job_id,)
            )
            job_row = cursor.fetchone()
            if not job_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Job not found"
                )
            job_title = job_row[0]
            job_description = job_row[1]
        else:
            job_title = (
                profile_json.get("target_role")
                or profile_json.get("targetRole")
                or resume_json.get("target_role")
                or "General Interview"
            ) or "General Interview"
            job_description = (
                profile_json.get("summary")
                or profile_json.get("professionalSummary")
                or resume_json.get("summary")
                or ""
            ) or ""

        persona = generate_persona("medium", job_title)

        duration_minutes = 40 if request.interview_mode == "mock" else 30

        planner_profile = dict(profile_json or resume_json or {})
        planner_profile["external_profile_signals"] = external_profile_signals

        knowledge_map = build_knowledge_map(
            resume_data=planner_profile,
            job_title=job_title,
            job_description=job_description,
            interview_type=request.interview_type,
            duration_minutes=duration_minutes
        )

        interview_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        interview_settings = {
            "mode": request.interview_mode,
            "interview_type": request.interview_type,
            "job_title": job_title,
            "strictness_level": "medium",
            "total_battlegrounds": len(knowledge_map.get("battlegrounds", [])),
            "max_turns_per_battleground": 3 if request.interview_mode == "mock" else 2,
            "hints_enabled": request.interview_mode == "practice",
            "immediate_feedback": request.interview_mode == "practice",
            "time_limit_per_question": None if request.interview_mode == "practice" else 300,
            "nonverbal_analysis": True
        }

        cursor.execute(
            """
            INSERT INTO Interviews (
                interview_id, user_id, interview_mode, interview_type,
                job_title, strictness_level, status, session_id,
                persona_data, questions_data, settings, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                interview_id, current_user["user_id"], request.interview_mode,
                request.interview_type, job_title, "medium", "in_progress",
                session_id, json.dumps(persona), json.dumps(knowledge_map),
                json.dumps(interview_settings), datetime.utcnow()
            )
        )

        if request.interview_mode == "mock":
            cursor.execute(
                "UPDATE UserInfo SET mock_interview_count = mock_interview_count + 1 WHERE user_id = %s",
                (current_user["user_id"],)
            )
        else:
            cursor.execute(
                "UPDATE UserInfo SET practice_interview_count = practice_interview_count + 1 WHERE user_id = %s",
                (current_user["user_id"],)
            )

        connection.commit()

        logger.info(
            f"{request.interview_mode.upper()} interview started: {interview_id} — "
            f"interviews_remaining: {'unlimited' if is_unlimited else interviews_remaining}"
        )

        return InterviewResponse(**{
            "interview_id": interview_id,
            "session_id": session_id,
            "mode": request.interview_mode,
            "message": f"{request.interview_mode.title()} interview started. The interviewer will cover 5 topic areas with follow-up questions.",
            "persona": persona,
            "settings": interview_settings,
            "interviews_remaining": -1 if is_unlimited else interviews_remaining
        })

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to start interview")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start interview. Please try again."
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.websocket("/ws/video/{ticket}")
async def websocket_video_interview(websocket: WebSocket, ticket: str):
    redis_client = get_redis_client()
    user_id = None

    if redis_client:
        ticket_key = f"ws_ticket:{ticket}"
        user_id = redis_client.get(ticket_key)
        if user_id:
            redis_client.delete(ticket_key)
    else:
        user_id = _pop_memory_ws_ticket(ticket)

    if not user_id:
        await websocket.close(code=4001, reason="Invalid or expired ticket")
        return

    try:
        await websocket.accept()
        logger.info(f"Video WebSocket connected: user_id={user_id}")

        interview_id: Optional[str] = None
        interview_mode: Optional[str] = None
        knowledge_map: Optional[Dict] = None
        persona: Optional[Dict] = None
        ws_settings: Dict = {}
        current_battleground: Optional[Dict] = None
        nonverbal_data: deque[Dict] = deque(maxlen=20)
        question_start_time: Optional[datetime] = None
        conversation_history: List[Dict] = []
        current_question_text: Optional[str] = None
        current_question_type: str = "main"
        current_parent_question_id: Optional[str] = None
        pipeline: Any = None
        resume_context: str = ""
        report_profile_context: Dict[str, Any] = {}

        msg_timestamps: deque[float] = deque()
        server_frame_counter: int = 0

        async def send_ws_message(data: dict):
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.error(f"Failed to send WS message: {e}")

        def get_topic_number(battleground_id: Any) -> int:
            if not knowledge_map:
                return 1
            for index, bg in enumerate(knowledge_map.get("battlegrounds", []), start=1):
                if bg.get("id") == battleground_id:
                    return index
            return 1

        async def send_processing_idle():
            await send_ws_message({
                "type": "vad_state",
                "speaking": False,
                "processing": False,
            })

        async def complete_interview(include_closing_audio: bool = False):
            if not interview_id:
                return

            score_row, _ = await asyncio.to_thread(
                _db_execute,
                "SELECT AVG(score) FROM InterviewResponses WHERE interview_id = %s",
                (interview_id,),
                fetchone=True
            )
            overall_score = float(score_row[0] or 0) if score_row else 0

            report_rows, _ = await asyncio.to_thread(
                _db_execute,
                """
                SELECT iq.question_text, iq.question_type, iq.is_followup,
                       iq.topic_label, ir.user_response, ir.score, ir.ai_feedback,
                       ir.response_time_seconds, ir.nonverbal_metrics, ir.coaching_hint,
                       ir.evaluation_json, ir.answer_quality_flags, ir.evidence_quotes,
                       ir.retry_state
                FROM InterviewResponses ir
                JOIN InterviewQuestions iq ON ir.question_id = iq.question_id
                WHERE ir.interview_id = %s
                ORDER BY iq.question_order, ir.created_at
                """,
                (interview_id,),
                fetchall=True
            )
            turns = _rows_to_turns(report_rows or [])

            report_v2 = _build_safe_report({
                "interview_id": interview_id,
                "job_title": ws_settings.get("job_title") or "",
                "mode": interview_mode,
                "interview_type": ws_settings.get("interview_type") or "",
            }, turns, report_profile_context)
            feedback_summary = report_v2["summary"]
            transcript = [
                {"role": item.get("role"), "content": item.get("content")}
                for item in conversation_history
                if item.get("role") in {"interviewer", "candidate"}
            ]

            await asyncio.to_thread(
                _db_execute,
                """
                UPDATE Interviews
                SET status = 'completed',
                    overall_score = %s,
                    feedback_summary = %s,
                    report_json = %s,
                    full_transcript = %s,
                    completed_at = %s
                WHERE interview_id = %s
                """,
                (
                    overall_score,
                    feedback_summary,
                    json.dumps(report_v2),
                    json.dumps(transcript),
                    datetime.utcnow(),
                    interview_id,
                ),
                commit=True
            )

            payload = {
                "type": "interview_complete",
                "overall_score": overall_score,
                "redirect_to": f"/interview/{interview_id}/report",
            }

            if include_closing_audio:
                closing_text = (
                    "That covers everything I wanted to go through today. "
                    f"Thank you for your time. Your overall score is {overall_score:.1f} out of 100. "
                    "You can view your detailed report now."
                )
                payload["closing_text"] = closing_text
                payload["closing_audio"] = await generate_speech(closing_text)

            await send_ws_message(payload)

        async def process_candidate_response(response_text: str):
            nonlocal knowledge_map
            nonlocal current_battleground
            nonlocal question_start_time
            nonlocal current_question_text
            nonlocal current_question_type
            nonlocal current_parent_question_id

            try:
                cleaned_response = (response_text or "").strip()
                if not cleaned_response:
                    await send_ws_message({
                        "type": "error",
                        "message": "Empty response received"
                    })
                    return

                if not current_question_text or not current_battleground or not knowledge_map:
                    await send_ws_message({
                        "type": "error",
                        "message": "No active interview question"
                    })
                    return

                time_taken = (
                    (datetime.utcnow() - question_start_time).total_seconds()
                    if question_start_time else 0
                )

                conversation_history.append({
                    "role": "candidate",
                    "content": cleaned_response
                })

                recent_nonverbal = list(nonverbal_data)[-10:] if nonverbal_data else []
                evaluation = await evaluate_response_realtime(
                    question=current_question_text,
                    response=cleaned_response,
                    difficulty_level=ws_settings.get("strictness_level", "medium"),
                    body_language=recent_nonverbal,
                    battleground_label=current_battleground["label"],
                    interview_mode=interview_mode or "mock"
                )

                question_id = str(uuid.uuid4())
                question_kind = current_question_type
                parent_question_id = current_parent_question_id
                question_order = len(
                    [entry for entry in conversation_history if entry.get("role") == "interviewer"]
                )

                await asyncio.to_thread(
                    _db_execute,
                    """
                    INSERT INTO InterviewQuestions (
                        question_id, interview_id, question_text, question_order,
                        question_type, topic_label, expected_signal, difficulty_level,
                        is_followup, parent_question_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        question_id,
                        interview_id,
                        current_question_text,
                        question_order,
                        question_kind,
                        current_battleground.get("label"),
                        current_battleground.get("estimated_difficulty"),
                        ws_settings.get("strictness_level", "medium"),
                        question_kind in {"followup", "retry"},
                        parent_question_id,
                    ),
                    commit=True
                )

                response_id = str(uuid.uuid4())
                scores = evaluation.get("scores", {}) or {}
                answer_quality_flags = evaluation.get("answer_quality_flags", []) or []
                evidence_quotes = evaluation.get("evidence_quotes", []) or []
                retry_state = {
                    "question_type": question_kind,
                    "is_retry": question_kind == "retry",
                    "quality_flags": answer_quality_flags,
                }

                coaching_hint = ""
                if interview_mode == "practice":
                    try:
                        coaching_hint = await generate_coaching_hint(
                            question=current_question_text,
                            candidate_response=cleaned_response,
                            resume_context=resume_context,
                            score=evaluation["score"],
                            interview_mode=interview_mode or "practice"
                        )
                    except Exception as e:
                        logger.error(f"Coaching hint generation failed: {e}")
                        coaching_hint = ""

                await asyncio.to_thread(
                    _db_execute,
                    """
                    INSERT INTO InterviewResponses (
                        response_id, interview_id, question_id, user_response,
                        response_time_seconds, ai_feedback, score, evaluation_json,
                        technical_accuracy, communication, problem_solving, confidence,
                        relevance, answer_quality_flags, evidence_quotes, retry_state,
                        nonverbal_metrics, coaching_hint, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        response_id,
                        interview_id,
                        question_id,
                        cleaned_response,
                        int(time_taken),
                        evaluation["feedback"],
                        evaluation["score"],
                        json.dumps(evaluation),
                        _score_value(scores, "technical_accuracy"),
                        _score_value(scores, "communication"),
                        _score_value(scores, "problem_solving"),
                        _score_value(scores, "confidence"),
                        _score_value(scores, "relevance"),
                        json.dumps(answer_quality_flags),
                        json.dumps(evidence_quotes),
                        json.dumps(retry_state),
                        json.dumps(evaluation.get("nonverbal_summary", {})),
                        coaching_hint,
                        datetime.utcnow(),
                    ),
                    commit=True
                )

                if coaching_hint:
                    await send_ws_message({
                        "type": "coaching_hint",
                        "hint": coaching_hint,
                        "score": evaluation["score"],
                    })

                if ws_settings.get("immediate_feedback"):
                    await send_ws_message({
                        "type": "evaluation",
                        "score": evaluation["score"],
                        "feedback": evaluation["feedback"],
                        "strengths": evaluation.get("strengths", []),
                        "improvements": evaluation.get("improvements", []),
                    })
                    improvements = evaluation.get("improvements", [])
                    if improvements:
                        await send_ws_message({
                            "type": "dynamic_tooltip",
                            "tip": f"Try to mention: {improvements[0]}",
                        })

                if _should_request_retry(evaluation, question_kind, interview_mode):
                    retry_prompt = _build_retry_prompt(current_question_text, evaluation)
                    current_question_text = retry_prompt
                    current_question_type = "retry"
                    current_parent_question_id = question_id
                    question_start_time = datetime.utcnow()
                    nonverbal_data.clear()

                    conversation_history.append({
                        "role": "interviewer",
                        "content": retry_prompt,
                        "battleground_id": current_battleground["id"],
                        "type": "retry",
                    })

                    await send_ws_message({
                        "type": "question",
                        "question_type": "retry",
                        "topic": current_battleground["label"],
                        "battleground_id": current_battleground["id"],
                        "question_text": retry_prompt,
                        "question_audio": await generate_speech(retry_prompt),
                        "progress": f"Topic {get_topic_number(current_battleground['id'])} of {len(knowledge_map['battlegrounds'])} — retry",
                    })
                    return

                active_bg = current_battleground
                bg_exhausted = should_transition(knowledge_map, active_bg["id"], 0, [])

                if not bg_exhausted:
                    followup_text = generate_contextual_followup(
                        battleground_label=active_bg["label"],
                        main_question=current_question_text,
                        candidate_response=cleaned_response,
                        conversation_history=conversation_history,
                        performance_score=evaluation["score"],
                        interview_mode=interview_mode,
                    )

                    knowledge_map = mark_turn_used(knowledge_map, active_bg["id"])
                    current_question_text = followup_text
                    current_question_type = "followup"
                    current_parent_question_id = question_id
                    question_start_time = datetime.utcnow()
                    nonverbal_data.clear()

                    conversation_history.append({
                        "role": "interviewer",
                        "content": followup_text,
                        "battleground_id": active_bg["id"],
                        "type": "followup",
                    })

                    await send_ws_message({
                        "type": "question",
                        "question_type": "followup",
                        "topic": active_bg["label"],
                        "battleground_id": active_bg["id"],
                        "question_text": followup_text,
                        "question_audio": await generate_speech(followup_text),
                        "progress": f"Topic {get_topic_number(active_bg['id'])} of {len(knowledge_map['battlegrounds'])} — follow-up",
                    })
                    return

                if is_interview_complete(knowledge_map):
                    await complete_interview(include_closing_audio=True)
                    return

                transition_line = get_transition_to_next(knowledge_map, active_bg["id"])
                next_bg = get_next_battleground(knowledge_map)

                if not next_bg:
                    await complete_interview(include_closing_audio=True)
                    return

                next_question_text = (
                    f"{transition_line} {next_bg['opening_question']}"
                    if transition_line else next_bg["opening_question"]
                )

                knowledge_map = mark_turn_used(knowledge_map, next_bg["id"])
                current_battleground = next_bg
                current_question_text = next_question_text
                current_question_type = "main"
                current_parent_question_id = None
                question_start_time = datetime.utcnow()
                nonverbal_data.clear()

                conversation_history.append({
                    "role": "interviewer",
                    "content": next_question_text,
                    "battleground_id": next_bg["id"],
                    "type": "main"
                })

                completed_topics = sum(
                    1 for bg in knowledge_map["battlegrounds"]
                    if bg["current_turns"] >= bg["max_turns"]
                )

                await send_ws_message({
                    "type": "question",
                    "question_type": "main",
                    "topic": next_bg["label"],
                    "battleground_id": next_bg["id"],
                    "question_text": next_question_text,
                    "question_audio": await generate_speech(next_question_text),
                    "progress": f"Topic {completed_topics + 1} of {len(knowledge_map['battlegrounds'])}",
                })
            finally:
                await send_processing_idle()

        while True:
            try:
                data = await websocket.receive_text()

                if len(data) > settings.WS_MAX_MESSAGE_SIZE:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Message too large (max {settings.WS_MAX_MESSAGE_SIZE // 1024}KB)"
                    })
                    continue

                now_ts = time()
                msg_timestamps.append(now_ts)
                cutoff = now_ts - settings.WS_MESSAGE_WINDOW
                while msg_timestamps and msg_timestamps[0] < cutoff:
                    msg_timestamps.popleft()
                if len(msg_timestamps) > settings.WS_MESSAGE_RATE_LIMIT:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Rate limit exceeded — slow down"
                    })
                    await websocket.close(code=4008, reason="Rate limit exceeded")
                    return

                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "start_session":
                    interview_id = message.get("interview_id")

                    row, _ = await asyncio.to_thread(
                        _db_execute,
                        """
                        SELECT persona_data, questions_data, strictness_level, interview_mode, settings
                        FROM Interviews
                        WHERE interview_id = %s AND user_id = %s
                        """,
                        (interview_id, user_id),
                        fetchone=True
                    )

                    if not row:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Interview not found"
                        })
                        continue

                    persona = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    knowledge_map = row[1] if isinstance(row[1], dict) else json.loads(row[1])
                    interview_mode = row[3]
                    ws_settings = row[4] if isinstance(row[4], dict) else json.loads(row[4]) if row[4] else {}

                    resume_row, _ = await asyncio.to_thread(
                        _db_execute,
                        "SELECT resume_json, profile_json, external_profile_signals FROM UserInfo WHERE user_id = %s",
                        (user_id,),
                        fetchone=True
                    )
                    profile_for_opening: Dict[str, Any] = {}
                    external_signals: Dict[str, Any] = {}
                    if resume_row:
                        rj = resume_row[0] or {}
                        pj = resume_row[1] or {}
                        external_signals = resume_row[2] or {}
                        profile_for_opening = rj or pj
                        report_profile_context = _profile_context_from_rows(rj, pj, external_signals)
                        parts = []
                        if rj.get("summary") or pj.get("professionalSummary"):
                            parts.append(f"Summary: {rj.get('summary') or pj.get('professionalSummary', '')}")
                        if rj.get("target_role") or pj.get("targetRole"):
                            parts.append(f"Target Role: {rj.get('target_role') or pj.get('targetRole', '')}")
                        skills = rj.get("skills", []) or pj.get("skills", [])
                        if skills:
                            skill_names = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills[:15]]
                            parts.append(f"Skills: {', '.join(skill_names)}")
                        exps = rj.get("experience", []) or rj.get("experiences", []) or pj.get("experience", []) or pj.get("experiences", [])
                        for exp in exps[:3]:
                            if isinstance(exp, dict):
                                title = exp.get("title") or exp.get("position") or ""
                                parts.append(f"Experience: {title} at {exp.get('company', '')} - {exp.get('description', '')[:150]}")
                        projs = rj.get("projects", []) or pj.get("projects", [])
                        for proj in projs[:3]:
                            if isinstance(proj, dict):
                                parts.append(f"Project: {proj.get('name', '')} - {proj.get('description', '')[:150]}")
                        github = external_signals.get("github", {}) if isinstance(external_signals, dict) else {}
                        for repo in (github.get("repositories") or [])[:2]:
                            if isinstance(repo, dict):
                                parts.append(f"GitHub: {repo.get('name', '')} - {repo.get('description', '') or repo.get('language', '')}")
                        resume_context = "\n".join(parts)

                    opening_text = _build_personalized_opening(
                        persona,
                        profile_for_opening,
                        external_signals,
                        interview_mode or "mock",
                    )

                    current_battleground = get_next_battleground(knowledge_map)
                    first_question_text = current_battleground["opening_question"] if current_battleground else None
                    question_audio_task = None
                    if first_question_text:
                        question_audio_task = asyncio.create_task(generate_speech(first_question_text))

                    opening_audio = await generate_speech(opening_text)

                    await websocket.send_json({
                        "type": "session_started",
                        "mode": interview_mode,
                        "opening_text": opening_text,
                        "opening_audio": opening_audio,
                        "total_topics": len(knowledge_map.get("battlegrounds", [])),
                        "settings": ws_settings
                    })

                    if not current_battleground:
                        await websocket.send_json({
                            "type": "error",
                            "message": "No questions available for this interview"
                        })
                        continue

                    current_question_text = first_question_text
                    if question_audio_task:
                        question_audio = await question_audio_task
                    else:
                        question_audio = await generate_speech(current_question_text)
                    question_start_time = datetime.utcnow()

                    conversation_history.append({
                        "role": "interviewer",
                        "content": current_question_text,
                        "battleground_id": current_battleground["id"]
                    })

                    knowledge_map = mark_turn_used(knowledge_map, current_battleground["id"])
                    current_question_type = "main"
                    current_parent_question_id = None

                    await websocket.send_json({
                        "type": "question",
                        "question_type": "main",
                        "topic": current_battleground["label"],
                        "battleground_id": current_battleground["id"],
                        "question_text": current_question_text,
                        "question_audio": question_audio,
                        "progress": f"Topic 1 of {len(knowledge_map['battlegrounds'])}"
                    })

                elif msg_type == "init_pipeline":
                    await websocket.send_json({
                        "type": "pipeline_ready",
                        "pipeline_mode": "legacy",
                        "stt_connected": bool(settings.OPENAI_API_KEY),
                        "tts_connected": bool(settings.OPENAI_API_KEY),
                        "avatar_connected": False,
                        "avatar_session": None,
                    })

                elif msg_type in {"audio_stream", "vad_speech_start", "vad_speech_end", "interrupt", "avatar_sdp_answer", "avatar_ice"}:
                    continue

                elif msg_type == "audio_chunk":
                    audio_data = message.get("audio")
                    if not audio_data:
                        await send_ws_message({
                            "type": "error",
                            "message": "Audio chunk missing"
                        })
                        await send_processing_idle()
                        continue

                    transcribed_text = await transcribe_audio(audio_data)
                    if not transcribed_text:
                        await send_ws_message({
                            "type": "error",
                            "message": "Could not transcribe audio. Please try again."
                        })
                        await send_processing_idle()
                        continue

                    await send_ws_message({
                        "type": "transcription_final",
                        "role": "user",
                        "text": transcribed_text,
                    })
                    await process_candidate_response(transcribed_text)

                elif msg_type == "video_frame":
                    server_frame_counter += 1
                    if server_frame_counter % 5 != 0:
                        continue

                    frame_data = message.get("frame")
                    analysis = await analyze_frame(
                        frame_data,
                        server_frame_counter,
                        interview_mode or "mock"
                    )
                    nonverbal_data.append(analysis)

                    await websocket.send_json({
                        "type": "body_language",
                        "confidence_score": analysis.get("confidence", 0),
                        "emotion": analysis.get("emotion", "neutral"),
                        "eye_contact": analysis.get("eye_contact", False),
                        "posture": analysis.get("posture", "unknown"),
                        "facial_expression": analysis.get("facial_expression", "neutral")
                    })

                elif msg_type == "response_complete":
                    await process_candidate_response(message.get("response", ""))

                elif msg_type == "end_interview":
                    metrics = pipeline.get_metrics() if pipeline else {}
                    if pipeline:
                        await pipeline.shutdown()

                    await websocket.send_json({
                        "type": "interview_ending",
                        "message": "Analyzing Interview...",
                        "pipeline_metrics": metrics,
                    })
                    await complete_interview(include_closing_audio=False)

                elif msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid message format"
                })
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                await websocket.send_json({
                    "type": "error",
                    "message": "An error occurred processing your request"
                })

    except WebSocketDisconnect:
        logger.info(f"Video WebSocket disconnected: user_id={user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        if pipeline:
            await pipeline.shutdown()
        try:
            await websocket.close()
        except Exception:
            pass

@router.get("/status/{interview_id}")
async def get_interview_status(
    interview_id: str,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT status, overall_score, completed_at
            FROM Interviews
            WHERE interview_id = %s AND user_id = %s
            """,
            (interview_id, current_user["user_id"])
        )

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found"
            )

        return {
            "interview_id": interview_id,
            "status": row[0],
            "overall_score": float(row[1]) if row[1] else 0,
            "completed_at": row[2].isoformat() if row[2] else None,
        }
    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/report/{interview_id}")
async def get_interview_report(
    interview_id: str,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT interview_mode, interview_type, job_title, strictness_level,
                   overall_score, feedback_summary, report_json, created_at, completed_at
            FROM Interviews
            WHERE interview_id = %s AND user_id = %s
            """,
            (interview_id, current_user["user_id"])
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found"
            )

        turns = _load_report_payload(cursor, interview_id)
        detailed_responses = [
            {
                "question": turn.get("question", ""),
                "question_type": turn.get("question_type") or "main",
                "is_followup": bool(turn.get("is_followup")),
                "topic": turn.get("topic_label") or "General",
                "response": turn.get("response", ""),
                "score": float(turn.get("score") or 0),
                "feedback": turn.get("feedback") or "",
                "time_taken": turn.get("time_taken"),
                "nonverbal_metrics": turn.get("nonverbal_metrics") or {},
                "coaching_hint": turn.get("coaching_hint") or "",
                "evaluation_json": turn.get("evaluation_json") or {},
                "answer_quality_flags": turn.get("answer_quality_flags") or [],
                "evidence_quotes": turn.get("evidence_quotes") or [],
                "retry_state": turn.get("retry_state") or {},
            }
            for turn in turns
        ]

        cursor.execute(
            """
            SELECT resume_json, profile_json, external_profile_signals
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )
        profile_row = cursor.fetchone()
        resume_json = profile_row[0] if profile_row else {}
        profile_json = profile_row[1] if profile_row else {}
        external_profile_signals = profile_row[2] if profile_row else {}
        profile_context = _profile_context_from_rows(
            resume_json or {},
            profile_json or {},
            external_profile_signals or {},
        )

        stored_report = row[6]
        if isinstance(stored_report, str):
            try:
                stored_report = json.loads(stored_report)
            except Exception:
                stored_report = None

        needs_rebuild = not isinstance(stored_report, dict) or stored_report.get("version") not in {"report_v2", "report_v2_fallback"}
        if needs_rebuild:
            stored_report = _build_safe_report({
                "interview_id": interview_id,
                "job_title": row[2] or "",
                "mode": row[0],
                "interview_type": row[1],
            }, turns, profile_context)
            cursor.execute(
                """
                UPDATE Interviews
                SET report_json = %s,
                    feedback_summary = %s
                WHERE interview_id = %s AND user_id = %s
                """,
                (json.dumps(stored_report), stored_report.get("summary"), interview_id, current_user["user_id"])
            )
            connection.commit()

        return {
            "interview_id": interview_id,
            "mode": row[0],
            "interview_type": row[1],
            "job_title": row[2],
            "strictness_level": row[3],
            "overall_score": float(row[4]) if row[4] else 0,
            "report": stored_report.get("summary") if isinstance(stored_report, dict) else row[5],
            "report_v2": stored_report,
            "created_at": row[7].isoformat() if row[7] else None,
            "completed_at": row[8].isoformat() if row[8] else None,
            "detailed_responses": detailed_responses
        }

    finally:
        cursor.close()
        return_db_connection(connection)

@router.delete("/cancel/{interview_id}")
async def cancel_interview(
    interview_id: str,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE Interviews
            SET status = 'cancelled'
            WHERE interview_id = %s AND user_id = %s AND status = 'in_progress'
            """,
            (interview_id, current_user["user_id"])
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found or already completed"
            )

        cursor.execute(
            "SELECT is_unlimited FROM UserInfo WHERE user_id = %s",
            (current_user["user_id"],)
        )
        user_row = cursor.fetchone()
        is_unlimited = user_row[0] if user_row else False

        if not is_unlimited:
            cursor.execute(
                "UPDATE UserInfo SET interviews_remaining = interviews_remaining + 1 WHERE user_id = %s",
                (current_user["user_id"],)
            )

        connection.commit()

        return {
            "success": True,
            "message": "Interview cancelled. Your interview credit has been refunded."
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to cancel interview")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel interview"
        )

    finally:
        cursor.close()
        return_db_connection(connection)
