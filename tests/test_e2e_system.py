from dotenv import load_dotenv
import os
import sys

# Force test environment settings
os.environ["ENVIRONMENT"] = "test"

# Make sure we can load modules from workspace root
workspace_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, workspace_root)

# Clean up any potential test stubs registered by other unit tests in sys.modules
# to ensure E2E tests always run against the actual physical modules.
for module_name in ["database", "auth", "learning_engine", "llm_router", "config", "app"]:
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        if not hasattr(mod, "__file__") or not mod.__file__ or "INTER" not in mod.__file__:
            del sys.modules[module_name]

# Load key.env before other imports so config.py gets the environment variables
load_dotenv(os.path.join(workspace_root, "key.env"))

import unittest
import uuid
import json
import time
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from database import get_db, transaction, init_connection_pool, close_connection_pool
from security_utils import decrypt_data, decrypt_json
from config import settings


def ws_event(interview_id, event_type, payload, client_session_id, sequence):
    return {
        "event_id": str(uuid.uuid4()),
        "sequence": sequence,
        "client_session_id": client_session_id,
        "interview_id": interview_id,
        "type": event_type,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }

# Import app to initialize routes
from app import app


class InterAIE2ESystemTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Manually initialize the DB connection pool for direct database queries inside the test
        init_connection_pool()
        self.client = TestClient(app)
        self.test_email = "test_e2e_candidate@example.com"
        self.test_password = "TestPassword123!"
        self.test_name = "E2E Test User"
        self._cleanup_test_user()

    def tearDown(self):
        self._cleanup_test_user()
        close_connection_pool()

    def _cleanup_test_user(self):
        """Clean up test user from the database to ensure test is fully idempotent."""
        init_connection_pool()
        with get_db() as connection:
            cursor = connection.cursor()
            try:
                with transaction(connection):
                    # 1. Retrieve the user_id if it exists
                    cursor.execute(
                        "SELECT user_id FROM Login WHERE email = %s",
                        (self.test_email,)
                    )
                    row = cursor.fetchone()
                    if row:
                        user_id = row[0]
                        # 2. Delete from non-cascading referencing tables in order
                        cursor.execute("DELETE FROM ResumeUploadLogs WHERE user_id = %s", (user_id,))
                        cursor.execute("DELETE FROM Transactions WHERE user_id = %s", (user_id,))
                        cursor.execute("DELETE FROM Subscriptions WHERE user_id = %s", (user_id,))
                        cursor.execute("DELETE FROM Interviews WHERE user_id = %s", (user_id,))
                        cursor.execute("DELETE FROM UserInfo WHERE user_id = %s", (user_id,))
                        cursor.execute("DELETE FROM Login WHERE user_id = %s", (user_id,))
            except Exception as e:
                print(f"Error during tearDown cleanup: {e}")
            finally:
                cursor.close()

    def test_complete_e2e_candidate_flow(self):
        # We also wrap in the with TestClient(app) block to trigger FastAPI's lifespan correctly
        with TestClient(app) as client:
            # 1. Signup E2E
            signup_payload = {
                "name": self.test_name,
                "email": self.test_email,
                "password": self.test_password
            }
            signup_response = client.post(
                "/api/auth/signup",
                json=signup_payload,
                headers={"X-Request-ID": "e2e-signup-request-0001"},
            )
            self.assertEqual(signup_response.status_code, 201)
            self.assertEqual(signup_response.headers.get("X-Request-ID"), "e2e-signup-request-0001")
            signup_data = signup_response.json()
            self.assertEqual(signup_data["email"], self.test_email)
            self.assertEqual(signup_data["name"], self.test_name)

            # 2. Retrieve verification token directly from DB
            verification_token = None
            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT verification_token FROM Login WHERE email = %s",
                    (self.test_email,)
                )
                row = cursor.fetchone()
                if row:
                    verification_token = row[0]
                cursor.close()

            self.assertIsNotNone(verification_token, "Verification token was not written to database login table.")

            # 3. Verify Email E2E
            verify_response = client.get(f"/api/auth/verify-email?token={verification_token}", follow_redirects=False)
            # Should redirect back to frontend base url with verified=true
            self.assertEqual(verify_response.status_code, 307)
            self.assertIn("verified=true", verify_response.headers.get("location", ""))

            # 4. Login E2E
            login_payload = {
                "email": self.test_email,
                "password": self.test_password
            }
            login_response = client.post("/api/auth/login", json=login_payload)
            self.assertEqual(login_response.status_code, 200)
            login_data = login_response.json()
            self.assertIsNotNone(login_data["token"])
            user_id = login_data["user_id"]
            csrf_token = client.cookies.get("interai_csrf")
            self.assertIsNotNone(csrf_token)
            auth_headers = {
                "Authorization": f"Bearer {login_data['token']}",
                "X-CSRF-Token": csrf_token,
            }

            removed_mode_response = client.post(
                "/api/interview/start",
                headers=auth_headers,
                json={"interview_mode": "practice"},
            )
            self.assertEqual(removed_mode_response.status_code, 422)

            # 5. Confirm Profile E2E
            profile_payload = {
                "job_id": None,
                "profile": {
                    "name": self.test_name,
                    "email": self.test_email,
                    "phone": "+1 555 123 4567",
                    "skills": ["Python", "PostgreSQL", "FastAPI"],
                    "target_role": "Backend Engineer",
                    "summary": "Experienced python developer specializing in robust APIs."
                }
            }
            
            # Patch background task scheduling so it runs synchronously/is skipped during enrichment
            with patch("pre_interview.schedule_profile_enrichment") as mock_enrich:
                confirm_response = client.post(
                    "/api/pre-interview/confirm-profile",
                    headers=auth_headers,
                    json=profile_payload
                )
                self.assertEqual(confirm_response.status_code, 200)
                self.assertTrue(confirm_response.json()["success"])
                mock_enrich.assert_called_once()

            # 6. Verify Transparent Database Encryption works E2E
            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT resume_json, profile_json, interviews_remaining FROM UserInfo WHERE user_id = %s",
                    (user_id,)
                )
                db_row = cursor.fetchone()
                cursor.close()

            self.assertIsNotNone(db_row)
            encrypted_resume = db_row[0]
            encrypted_profile = db_row[1]
            interviews_remaining = db_row[2]

            self.assertEqual(interviews_remaining, settings.FREE_CREDITS_ON_SIGNUP)

            # Assert that raw data is not stored in plaintext in the DB (is encrypted)
            self.assertNotIn("Experienced python developer", encrypted_resume)
            self.assertNotIn("FastAPI", encrypted_profile)

            # Decrypt using our AES-GCM utils and assert they match
            decrypted_resume = decrypt_json(encrypted_resume)
            self.assertEqual(decrypted_resume["target_role"], "Backend Engineer")
            self.assertIn("FastAPI", decrypted_resume["skills"])

            # 7. A dropped behavioral WebSocket is resumable as the same
            # continuous attempt. The server must restore the committed
            # question rather than generate a new opening or score the drop.
            behavioral_map = {
                "duration_minutes": 45,
                "battlegrounds": [
                    {
                        "id": 1,
                        "section_id": "resume-ownership",
                        "label": "Project ownership",
                        "kind": "resume",
                        "opening_question": "Which project best demonstrates your own engineering work?",
                        "importance": "critical",
                        "estimated_difficulty": "matched",
                        "min_turns": 1,
                        "max_turns": 3,
                        "current_turns": 0,
                        "time_budget_seconds": 900,
                        "expected_points": ["personal contribution", "measurable result"],
                        "taxonomy_keys": ["behavioral:ownership"],
                        "rubric": {"version": "e2e-v1", "unknown_dimensions_are_null": True},
                    }
                ],
            }
            with patch("interview.generate_persona", return_value={"name": "Ava", "personality": "Professional"}), \
                 patch("interview.build_knowledge_map", new_callable=AsyncMock, return_value=behavioral_map):
                behavioral_start = client.post(
                    "/api/interview/start",
                    headers=auth_headers,
                    json={
                        "interview_mode": "mock",
                        "interview_type": "Mock Interview",
                        "profile_type": "mid_tier",
                        "input_mode": "voice",
                        "camera_mode": "off",
                    },
                )
            self.assertEqual(behavioral_start.status_code, 200, behavioral_start.text)
            self.assertEqual(behavioral_start.json()["settings"]["camera_mode"], "required")
            behavioral_id = behavioral_start.json()["interview_id"]

            first_ticket = client.post("/api/interview/ws-ticket", headers=auth_headers)
            self.assertEqual(first_ticket.status_code, 200, first_ticket.text)
            with patch("interview.generate_speech", new_callable=AsyncMock, return_value=None):
                with client.websocket_connect(
                    f"/api/interview/ws/video/{first_ticket.json()['ticket']}"
                ) as socket:
                    first_client_session = str(uuid.uuid4())
                    socket.send_json(ws_event(behavioral_id, "start_session", {"interview_id": behavioral_id}, first_client_session, 1))
                    first_session = socket.receive_json()
                    self.assertEqual(first_session["type"], "session_started", first_session)
                    self.assertFalse(first_session.get("resumed", False))
                    first_question_id = first_session["question_id"]
                    socket.send_json(ws_event(behavioral_id, "init_pipeline", {"camera_enabled": False, "screen_share_enabled": True}, first_client_session, 2))
                    camera_rejected = socket.receive_json()
                    while camera_rejected.get("type") == "speech_unavailable":
                        camera_rejected = socket.receive_json()
                    self.assertEqual(camera_rejected["code"], "camera_required")
                    socket.send_json(ws_event(behavioral_id, "init_pipeline", {"camera_enabled": True, "screen_share_enabled": False}, first_client_session, 3))
                    screen_rejected = socket.receive_json()
                    self.assertEqual(screen_rejected["code"], "screen_share_required")
                    socket.send_json(ws_event(behavioral_id, "init_pipeline", {"camera_enabled": True, "screen_share_enabled": True, "input_mode": "voice"}, first_client_session, 4))
                    pipeline_ready = socket.receive_json()
                    self.assertEqual(pipeline_ready["type"], "pipeline_ready")
                    duplicate_ticket = client.post("/api/interview/ws-ticket", headers=auth_headers)
                    self.assertEqual(duplicate_ticket.status_code, 200)
                    with client.websocket_connect(
                        f"/api/interview/ws/video/{duplicate_ticket.json()['ticket']}"
                    ) as duplicate_socket:
                        duplicate_session = str(uuid.uuid4())
                        duplicate_socket.send_json(ws_event(
                            behavioral_id,
                            "start_session",
                            {"interview_id": behavioral_id},
                            duplicate_session,
                            1,
                        ))
                        duplicate_error = duplicate_socket.receive_json()
                        self.assertEqual(duplicate_error["code"], "duplicate_controller_rejected")
                    ping_event = ws_event(behavioral_id, "ping", {}, first_client_session, 5)
                    socket.send_json(ping_event)
                    self.assertEqual(socket.receive_json()["type"], "pong")
                    socket.send_json(ping_event)
                    duplicate_ack = socket.receive_json()
                    self.assertEqual(duplicate_ack["type"], "event_ack")
                    self.assertEqual(duplicate_ack["status"], "duplicate")
                    socket.send_json(ws_event(behavioral_id, "ping", {}, first_client_session, 5))
                    out_of_order = socket.receive_json()
                    self.assertEqual(out_of_order["code"], "event_sequence_out_of_order")
                    socket.close()

            interrupted = None
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with get_db() as connection:
                    cursor = connection.cursor()
                    cursor.execute("SELECT status, overall_score FROM Interviews WHERE interview_id = %s", (behavioral_id,))
                    interrupted = cursor.fetchone()
                    cursor.close()
                if interrupted and interrupted[0] == "recovering":
                    break
                time.sleep(0.025)
            self.assertEqual(interrupted[0], "recovering")
            self.assertIsNone(interrupted[1])

            second_ticket = client.post("/api/interview/ws-ticket", headers=auth_headers)
            self.assertEqual(second_ticket.status_code, 200, second_ticket.text)
            with patch("interview.generate_speech", new_callable=AsyncMock, return_value=None):
                with client.websocket_connect(
                    f"/api/interview/ws/video/{second_ticket.json()['ticket']}"
                ) as socket:
                    second_client_session = str(uuid.uuid4())
                    socket.send_json(ws_event(behavioral_id, "start_session", {"interview_id": behavioral_id}, second_client_session, 1))
                    restored_session = socket.receive_json()
                    self.assertEqual(restored_session["type"], "session_started")
                    self.assertTrue(restored_session["resumed"])
                    self.assertTrue(restored_session["recovered_connection"])
                    self.assertEqual(restored_session["question_id"], first_question_id)
                    self.assertEqual(restored_session["current_question"], first_session["current_question"])

            cancel_behavioral = client.delete(
                f"/api/interview/cancel/{behavioral_id}", headers=auth_headers
            )
            self.assertEqual(cancel_behavioral.status_code, 200, cancel_behavioral.text)
            self.assertIsNone(cancel_behavioral.json()["official_score"])

            # 8. Start Technical Interview E2E (with mocked dynamic LLM generators to bypass external network calls)
            mock_persona = {"name": "Interviewer Bot", "personality": "Strict and rigorous coding examiner"}
            mock_knowledge_map = {
                "duration_minutes": 40,
                "battlegrounds": [
                    {
                        "topic": "System Design",
                        "questions": ["How do you design a high-performance database cluster?"],
                    }
                ],
                "rubrics": {}
            }

            start_payload = {
                "interview_mode": "mock",
                "interview_type": "technical",
                "profile_type": "mid_tier",
                "job_id": None,
                "job_profile_id": None,
                "technical_round_types": ["coding", "system_design", "debugging"],
                "question_count": 3,
                "camera_mode": "off",
            }

            # Mock the external AI service calls for persona and knowledge map generator
            with patch("interview.generate_persona", return_value=mock_persona), \
                 patch("interview.build_knowledge_map", new_callable=AsyncMock, return_value=mock_knowledge_map):
                
                start_response = client.post(
                    "/api/interview/start",
                    headers=auth_headers,
                    json=start_payload
                )
                self.assertEqual(start_response.status_code, 200)
                start_data = start_response.json()
                self.assertIsNotNone(start_data["interview_id"])
                self.assertEqual(start_data["mode"], "mock")
                self.assertEqual(start_data["settings"]["duration_minutes"], 50)
                self.assertEqual(start_data["settings"]["duration"], {"min_minutes": 45, "target_minutes": 50, "max_minutes": 60})
                self.assertEqual(start_data["settings"]["camera_mode"], "required")

            # 8. Prepare frozen typed technical rounds. A second read must
            # return the same durable specs rather than regenerate them.
            prepare_response = client.post(
                f"/api/technical/sessions/{start_data['interview_id']}/prepare",
                headers=auth_headers,
            )
            self.assertEqual(prepare_response.status_code, 200, prepare_response.text)
            prepared = prepare_response.json()
            self.assertEqual(
                [item["round_type"] for item in prepared["rounds"]],
                ["coding", "technical_concept"],
            )
            self.assertTrue(all(item["round_spec_id"] for item in prepared["rounds"]))
            # Only the active round owns a running deadline. Pending rounds get
            # their own authoritative deadline when activated, so preparation
            # cannot consume their time in advance.
            self.assertIsNotNone(prepared["rounds"][0]["expires_at"])
            self.assertTrue(all(item["expires_at"] is None for item in prepared["rounds"][1:]))
            self.assertNotIn("hidden_tests", prepared["rounds"][0]["metadata"])

            rounds_response = client.get(
                f"/api/technical/sessions/{start_data['interview_id']}/rounds",
                headers=auth_headers,
            )
            self.assertEqual(rounds_response.status_code, 200, rounds_response.text)
            self.assertEqual(
                [item["round_id"] for item in rounds_response.json()["rounds"]],
                [item["round_id"] for item in prepared["rounds"]],
            )

            first_round_id = prepared["rounds"][0]["round_id"]
            queued_payload = {
                "language": "python",
                "code": "print('YES')",
                "idempotency_key": "e2e-visible-test-0001",
            }
            with patch("technical_mode._require_executor_available", return_value=None):
                queued_response = client.post(
                    f"/api/technical/rounds/{first_round_id}/test",
                    headers=auth_headers,
                    json=queued_payload,
                )
                self.assertEqual(queued_response.status_code, 202, queued_response.text)
                queued_run = queued_response.json()
                self.assertEqual(queued_run["status"], "queued")
                self.assertEqual(queued_run["poll_after_ms"], 250)
                self.assertFalse(queued_run["idempotent_replay"])
                self.assertIsNone(queued_run["hidden_details"])

                replay_response = client.post(
                    f"/api/technical/rounds/{first_round_id}/test",
                    headers=auth_headers,
                    json=queued_payload,
                )
                self.assertEqual(replay_response.status_code, 202, replay_response.text)
                self.assertEqual(replay_response.json()["run_id"], queued_run["run_id"])
                self.assertTrue(replay_response.json()["idempotent_replay"])

            poll_response = client.get(
                f"/api/technical/runs/{queued_run['run_id']}",
                headers=auth_headers,
            )
            self.assertEqual(poll_response.status_code, 200, poll_response.text)
            self.assertEqual(poll_response.json()["status"], "queued")
            self.assertEqual(poll_response.json()["test_summary"], {"passed": 0, "total": 3})
            self.assertIsNone(poll_response.json()["hidden_details"])

            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    SELECT source_code, source_code_encrypted, cases_json, cases_encrypted
                    FROM TechnicalExecutionJobs
                    WHERE job_id = %s
                    """,
                    (queued_run["run_id"],),
                )
                durable_job = cursor.fetchone()
                cursor.close()
            self.assertEqual(durable_job[0], "[encrypted]")
            encrypted_source = durable_job[1].tobytes() if hasattr(durable_job[1], "tobytes") else durable_job[1]
            if isinstance(encrypted_source, bytes):
                encrypted_source = encrypted_source.decode("utf-8")
            self.assertEqual(decrypt_data(encrypted_source), queued_payload["code"])
            self.assertEqual(durable_job[2], [])
            self.assertIsNotNone(durable_job[3])

            # The isolated technical worker normally completes the coding job
            # and activates the next round. This test intentionally does not
            # execute candidate code, so advance that durable worker-owned
            # transition explicitly before exercising the concept endpoint.
            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    UPDATE TechnicalInterviewRounds
                    SET status = 'submitted', completed_at = NOW()
                    WHERE round_id = %s
                    """,
                    (first_round_id,),
                )
                cursor.execute(
                    """
                    UPDATE TechnicalInterviewRounds
                    SET status = 'active', started_at = NOW(),
                        deadline_at = NOW() + (duration_seconds * INTERVAL '1 second')
                    WHERE round_id = %s
                    """,
                    (prepared["rounds"][1]["round_id"],),
                )
                connection.commit()
                cursor.close()

            concept_round_id = prepared["rounds"][1]["round_id"]
            concept_payload = {
                "response_text": (
                    "I would clarify throughput and durability, use a partitioned queue with idempotent consumers, "
                    "persist delivery state, bound retries with a dead-letter queue, and monitor lag and failures."
                ),
                "response_payload": {"response_seconds": 42},
                "idempotency_key": "e2e-system-design-0001",
            }
            concept_assessment = {
                "version": "evaluation-v1",
                "overall_score": None,
                "insufficient_evidence": True,
                "semantic_status": {"state": "skipped", "reason": "test"},
            }
            with patch("technical_mode.evaluate_answer", new_callable=AsyncMock, return_value=concept_assessment):
                concept_response = client.post(
                    f"/api/technical/rounds/{concept_round_id}/response",
                    headers=auth_headers,
                    json=concept_payload,
                )
                self.assertEqual(concept_response.status_code, 200, concept_response.text)
                concept_result = concept_response.json()
                self.assertEqual(concept_result["status"], "committed")
                self.assertFalse(concept_result["duplicate"])

                concept_replay = client.post(
                    f"/api/technical/rounds/{concept_round_id}/response",
                    headers=auth_headers,
                    json=concept_payload,
                )
                self.assertEqual(concept_replay.status_code, 200, concept_replay.text)
                self.assertEqual(concept_replay.json()["response_id"], concept_result["response_id"])
                self.assertTrue(concept_replay.json()["duplicate"])

            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    SELECT user_response, answer_text_encrypted
                    FROM InterviewResponses
                    WHERE response_id = %s
                    """,
                    (concept_result["response_id"],),
                )
                stored_response = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM ResponseAssessments WHERE response_id = %s",
                    (concept_result["response_id"],),
                )
                assessment_count = cursor.fetchone()[0]
                cursor.close()
            self.assertEqual(stored_response[0], "[encrypted]")
            encrypted_answer = stored_response[1].tobytes() if hasattr(stored_response[1], "tobytes") else stored_response[1]
            if isinstance(encrypted_answer, bytes):
                encrypted_answer = encrypted_answer.decode("utf-8")
            self.assertEqual(decrypt_data(encrypted_answer), concept_payload["response_text"])
            self.assertEqual(assessment_count, 1)

            # 9. Check that legacy credits remain serialized and plan-limited starts do not decrement them.
            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT interviews_remaining FROM UserInfo WHERE user_id = %s", (user_id,))
                updated_credits = cursor.fetchone()[0]
                cursor.execute("SELECT settings FROM Interviews WHERE interview_id = %s", (start_data["interview_id"],))
                saved_settings = cursor.fetchone()[0]
                cursor.close()

            self.assertEqual(updated_credits, settings.FREE_CREDITS_ON_SIGNUP)
            if isinstance(saved_settings, str):
                saved_settings = json.loads(saved_settings)
            self.assertEqual(saved_settings["duration_policy"], "adaptive_target")
            self.assertEqual(saved_settings["duration_minutes"], 50)

            # 10. Voluntary exit preserves evidence but permanently marks the
            # attempt incomplete and never creates an official score.
            cancel_response = client.delete(
                f"/api/interview/cancel/{start_data['interview_id']}",
                headers=auth_headers,
            )
            self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
            self.assertEqual(cancel_response.json()["status"], "cancelled")
            self.assertIsNone(cancel_response.json()["official_score"])
            with get_db() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT status, overall_score, completed_at FROM Interviews WHERE interview_id = %s",
                    (start_data["interview_id"],),
                )
                cancelled_attempt = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM InterviewResponses WHERE interview_id = %s",
                    (start_data["interview_id"],),
                )
                preserved_response_count = cursor.fetchone()[0]
                cursor.close()
            self.assertEqual(cancelled_attempt[0], "cancelled")
            self.assertIsNone(cancelled_attempt[1])
            self.assertIsNotNone(cancelled_attempt[2])
            self.assertGreaterEqual(preserved_response_count, 1)


if __name__ == "__main__":
    unittest.main()
