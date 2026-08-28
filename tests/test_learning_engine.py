import unittest
import os
import sys
import types
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

database_stub = types.ModuleType("database")


async def _stub_async_execute(*args, **kwargs):
    raise AssertionError("async_execute should be patched in tests that touch persistence")


def _stub_get_db_connection(*args, **kwargs):
    raise AssertionError("get_db_connection should be patched in persistence tests")


def _stub_return_db_connection(*args, **kwargs):
    return None


def _stub_get_db(*args, **kwargs):
    raise AssertionError("get_db should be patched in persistence tests")


class _StubTransaction:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


database_stub.async_execute = _stub_async_execute
database_stub.get_db_connection = _stub_get_db_connection
database_stub.return_db_connection = _stub_return_db_connection
database_stub.get_db = _stub_get_db
database_stub.transaction = _StubTransaction
sys.modules.setdefault("database", database_stub)

import learning_engine


class _GateCursor:
    def __init__(self, ready: bool):
        self.ready = ready
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return (self.ready,)

    def close(self):
        return None


class _GateConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.commits = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None


class LearningEnginePureTests(unittest.IsolatedAsyncioTestCase):
    def test_improve_gate_requires_current_sufficient_performance(self):
        cursor = _GateCursor(True)
        assert learning_engine._has_current_performance_analysis(
            cursor,
            "user-1",
            interview_id="interview-1",
            analysis_id="analysis-1",
        ) is True
        query = cursor.queries[0][0]
        assert "evidence_status = 'sufficient'" in query
        assert "analysis.analysis_id = ?" in query
        assert "analysis.evidence_status = 'sufficient'" in query
        assert "FROM ReportArtifacts artifact" in query
        assert "artifact.payload_encrypted IS NOT NULL" in query
        assert "HAVING COUNT(*) >= 2" not in query

    def test_response_assessment_cannot_create_improve_before_performance(self):
        cursor = _GateCursor(False)
        connection = _GateConnection(cursor)
        with patch.object(learning_engine, "get_db_connection", return_value=connection), patch.object(
            learning_engine, "return_db_connection"
        ):
            result = learning_engine._ensure_mission_from_response_assessment_sync(
                "user-1", "interview-1"
            )
        assert result is None
        assert connection.commits == 1
        assert len(cursor.queries) == 1

    def test_skill_key_uses_project_anchor_for_project_questions(self):
        turn = {
            "question": "Can you explain the project you built and your exact part?",
            "question_type": "main",
            "topic": "Projects",
        }
        profile = {"projects": [{"name": "Interview Copilot"}]}

        self.assertEqual(
            learning_engine.skill_key_from_turn(turn, profile),
            "project:interview-copilot:defense",
        )

    async def test_code_mistake_identifier_fallback_is_specific(self):
        with patch.object(learning_engine, "complete_json_async", side_effect=RuntimeError("model unavailable")):
            diagnosis = await learning_engine.classify_code_mistake(
                language="python",
                code="print(total)",
                stdout="",
                stderr="NameError: name 'total' is not defined",
                exit_code=1,
                round_type="debugging",
                prompt="Fix the snippet.",
            )

        self.assertEqual(diagnosis["mistake_type"], "identifier-mismatch")
        self.assertIn("debugging:python", diagnosis["mistake_key"])
        self.assertIn("consistent name", diagnosis["repair_action"])

    def test_text_attempt_scoring_rewards_specific_interview_answer(self):
        answer = (
            "I built the API layer for my interview platform because the model calls needed reliable "
            "latency. My role was designing the request flow, database logging, and retry behavior. "
            "The trade-off was keeping fallback limited while preserving user experience. We reduced "
            "failed sessions by 30% and used tests around cache, runtime, and edge cases."
        )

        result = learning_engine._score_text_attempt({"question": "Explain the API project."}, answer)

        self.assertGreaterEqual(result["score"], learning_engine.PASS_SCORE)
        self.assertTrue(result["mastery_passed"])


class LearningEngineAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_skill_state_creates_new_state(self):
        calls = []

        async def fake_execute(query, params=None, fetchone=False, fetchall=False):
            calls.append((query, params, fetchone, fetchall))
            if fetchone:
                return None
            return None

        with patch.object(learning_engine, "async_execute", side_effect=fake_execute):
            result = await learning_engine._upsert_skill_state(
                "user-1",
                "technical:arrays",
                "technical",
                42,
            )

        self.assertEqual(result["mastery_score"], 42)
        self.assertEqual(result["evidence_count"], 1)
        self.assertTrue(any("INSERT INTO LearnerSkillStates" in call[0] for call in calls))

    async def test_unbound_legacy_exercise_cannot_fabricate_score_or_mastery(self):
        calls = []

        async def fake_execute(query, params=None, fetchone=False, fetchall=False):
            calls.append((query, params, fetchone, fetchall))
            if "FROM GeneratedExercises" in query and fetchone:
                return (
                    "exercise-1",
                    "project:demo:defense",
                    "project_defense",
                    {
                        "title": "Defend Demo",
                        "prompt": "Explain Demo.",
                        "question": "Explain Demo.",
                    },
                    {"pass_score": learning_engine.PASS_SCORE},
                    "queued",
                )
            if "FROM LearnerSkillStates" in query and fetchone:
                return None
            return None

        answer = (
            "I built the API and database layer because the dashboard needed reliable feedback. "
            "My role was designing request flow, tests, and failure handling. The trade-off was "
            "latency versus strict local model fallback, and the result was 25% fewer failed runs. "
            "I also added runtime checks, cache behavior, and edge-case tests so interview reports "
            "could show a clear signal instead of vague metrics."
        )

        with patch.object(learning_engine, "async_execute", side_effect=fake_execute), patch.object(
            learning_engine,
            "complete_json_async",
            side_effect=RuntimeError("model unavailable"),
        ) as model_call:
            with self.assertRaisesRegex(ValueError, "active improvement mission"):
                await learning_engine.submit_exercise_attempt("user-1", "exercise-1", answer, {})

        model_call.assert_not_called()
        self.assertFalse(any("INSERT INTO ExerciseAttempts" in call[0] for call in calls))
        self.assertFalse(any("UPDATE GeneratedExercises" in call[0] for call in calls))
        self.assertFalse(any("LearnerSkillStates" in call[0] for call in calls))


if __name__ == "__main__":
    unittest.main()
