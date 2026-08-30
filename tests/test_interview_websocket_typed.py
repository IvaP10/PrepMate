import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

import database
import interview
from local_cache import get_local_cache
from local_runtime import LOCAL_USER_ID
from security_utils import decrypt_data, decrypt_json_field, encrypt_data


def _behavioral_section(section_id: str, question: str, *, current_turns: int = 0):
    return {
        "id": 1 if section_id == "ownership" else 2,
        "section_id": section_id,
        "label": section_id.title(),
        "kind": "behavioral",
        "importance": "high",
        "estimated_difficulty": "medium",
        "opening_question": question,
        "taxonomy_keys": [f"behavioral:{section_id}"],
        "expected_points": ["specific evidence"],
        "rubric": {"weights": {"relevance": 1.0}},
        "selection_reason": "resume anchor",
        "source_anchors": [section_id],
        "min_turns": 1,
        "max_turns": 1,
        "max_followups": 0,
        "current_turns": current_turns,
        "time_budget_seconds": 120,
        "transition_hint": "",
    }


def _evaluation(rubric):
    point_id = rubric["expected_points"][0]["point_id"]
    return {
        "version": interview.EVALUATION_VERSION,
        "overall_score": 86,
        "provisional_score": 86,
        "authoritative": True,
        "confidence": 0.88,
        "insufficient_evidence": False,
        "flags": [],
        "scores": {"technical_accuracy": None},
        "signals": {
            "word_count": 35,
            "lexical_relevance": {"score": 72},
            "structure": {"score": 76},
            "specificity_evidence": {"score": 82},
            "ownership": {"applicable": True, "score": 80},
            "directness": {"score": 78},
            "tradeoffs": {"applicable": False, "score": None},
        },
        "evidence": {
            "covered_points": [point_id],
            "missed_points": [],
            "incorrect_claims": [],
            "contradictions": [],
        },
        "semantic_status": {
            "state": "completed",
            "attempted": True,
            "semantic_confidence": 0.9,
            "answer_relevant": True,
        },
        "follow_up": {"action": "advance", "reason": "sufficient evidence"},
    }


def test_typed_behavioral_answer_uses_live_websocket_persistence_and_adaptive_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database.close_connection_pool()
    database.ensure_local_schema()
    get_local_cache().clear()

    interview_id = str(uuid4())
    session_id = str(uuid4())
    blueprint = {
        "battlegrounds": [
            _behavioral_section(
                "ownership",
                "Tell me about a difficult decision you owned?",
            ),
            _behavioral_section(
                "collaboration",
                "Tell me about a conflict you resolved?",
            ),
        ]
    }
    with database.get_db() as connection:
        connection.execute(
            """
            INSERT INTO Interviews (
                interview_id, user_id, interview_mode, interview_type,
                job_title, status, session_id, persona_data, questions_data,
                questions_data_encrypted, settings, attempt_status,
                analysis_status, integrity_status, lifecycle_revision
            ) VALUES (?, ?, 'mock', 'behavioral', 'Backend Engineer',
                      'in_progress', ?, ?, ?, ?, ?, 'active',
                      'not_requested', 'clean', 1)
            """,
            (
                interview_id,
                LOCAL_USER_ID,
                session_id,
                json.dumps({"name": "Alex", "job_title": "Backend Engineer"}),
                json.dumps({"encrypted": True}),
                encrypt_data(json.dumps(blueprint)).encode("utf-8"),
                json.dumps({
                    "profile_type": "mid_tier",
                    "profile_label": "Mid Tier",
                    "job_title": "Backend Engineer",
                    "duration": {"min_minutes": 1, "target_minutes": 1, "max_minutes": 1},
                }),
            ),
        )
        connection.commit()

    calls = []

    async def fake_evaluate(question, answer, rubric, context, response_seconds, prior, **kwargs):
        calls.append({
            "question": question,
            "answer": answer,
            "rubric": rubric,
            "context": context,
            "prior": list(prior),
        })
        return _evaluation(rubric)

    async def fake_question(**kwargs):
        return f"What specifically did you change in {kwargs['battleground']['label']}?"

    app = FastAPI()
    app.include_router(interview.router, prefix="/api/interview")
    sequence = 0
    client_session_id = str(uuid4())
    all_messages = []

    def send_event(websocket, event_type, payload=None):
        nonlocal sequence
        sequence += 1
        websocket.send_json({
            "type": event_type,
            "event_id": str(uuid4()),
            "sequence": sequence,
            "client_session_id": client_session_id,
            "interview_id": interview_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        })

    def receive_until(websocket, predicate):
        for _ in range(40):
            message = websocket.receive_json()
            all_messages.append(message)
            if message.get("type") == "question" and message.get("requires_ack"):
                send_event(websocket, "question_ack", {
                    "question_id": message.get("question_id"),
                    "delivery_id": message.get("delivery_id"),
                })
            if predicate(message):
                return message
        raise AssertionError(f"Expected WebSocket message; got {[item.get('type') for item in all_messages]}")

    try:
        with (
            monkeypatch.context() as patches,
            TestClient(app, base_url="http://127.0.0.1") as client,
        ):
            patches.setattr(interview, "evaluate_answer", fake_evaluate)
            patches.setattr(interview, "generate_battleground_question", fake_question)
            # The handler awaits this function, so use an async replacement
            # while keeping the test independent of the analysis worker.
            async def fake_finalize(**kwargs):
                return {"status": "analysis_pending", "analysis_job_id": "analysis-test"}

            patches.setattr(interview, "_finalize_interview_for_analysis", fake_finalize)
            with client.websocket_connect(
                "/api/interview/ws/video",
                headers={"host": "127.0.0.1", "origin": "http://127.0.0.1"},
            ) as websocket:
                send_event(websocket, "start_session")
                started = receive_until(websocket, lambda item: item.get("type") == "session_started")
                warmup_question_id = started["question_id"]

                send_event(websocket, "init_pipeline", {"input_mode": "text", "camera_enabled": False})
                receive_until(websocket, lambda item: item.get("type") == "pipeline_ready")

                send_event(websocket, "text_answer", {
                    "question_id": warmup_question_id,
                    "idempotency_key": "typed-warmup",
                    "text": "I am a backend engineer interested in this role and its product challenges.",
                    "response_seconds": 8,
                    "timing": {"response_seconds": 8},
                })
                receive_until(websocket, lambda item: item.get("type") == "answer_committed")
                main_question = receive_until(
                    websocket,
                    lambda item: item.get("type") == "question" and item.get("question_type") == "main",
                )

                typed_answer = (
                    "I owned the migration decision, compared a queue with bounded retries, and chose retries "
                    "because they reduced latency. The rollout cut failures by 30 percent for 200 users."
                )
                send_event(websocket, "text_answer", {
                    "question_id": main_question["question_id"],
                    "idempotency_key": "typed-main",
                    "text": typed_answer,
                    "response_seconds": 18,
                    "timing": {"response_seconds": 18},
                })
                committed = receive_until(websocket, lambda item: item.get("type") == "answer_committed")
                next_question = receive_until(
                    websocket,
                    lambda item: item.get("type") == "question" and item.get("question_type") == "main",
                )

                assert next_question["topic"] == "Collaboration"
                assert committed["decision"]["action"] == "advance"
                assert committed["next_question"]["question_id"] == next_question["question_id"]
                assert calls[1]["answer"] == typed_answer
                assert calls[1]["context"]["profile_type"] == "mid_tier"
                assert calls[1]["prior"] == []

                with database.get_db() as connection:
                    stored = connection.execute(
                        """
                        SELECT response_id, input_mode, answer_text_encrypted,
                               response_time_seconds, timing_json
                        FROM InterviewResponses
                        WHERE interview_id = ? AND question_id = ?
                        """,
                        (interview_id, main_question["question_id"]),
                    ).fetchone()
                    assessment = connection.execute(
                        """
                        SELECT assessment_json_encrypted, assessment_json
                        FROM ResponseAssessments
                        WHERE response_id = ?
                        """,
                        (stored[0],),
                    ).fetchone()

                assert stored[1] == "text"
                assert decrypt_data(stored[2]) == typed_answer
                assert stored[3] == 18
                assert json.loads(stored[4])["response_latency_seconds"] == 18
                assessment_payload = decrypt_json_field(assessment[0], assessment[1], {})
                assert assessment_payload["follow_up"]["adaptive"]["evidence_state_used"] is True

                send_event(websocket, "end_interview")
                receive_until(websocket, lambda item: item.get("type") == "interview_complete")

        assert not [item for item in all_messages if item.get("type") == "error"]
    finally:
        get_local_cache().clear()
        database.close_connection_pool()
