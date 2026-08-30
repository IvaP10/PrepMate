import json
import os
import inspect
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import technical_mode
import technical_worker


def _loaded_round(*, status="active", starter_code="def solve():\n    pass\n"):
    row = [None] * 21
    row[0] = "round-1"
    row[1] = "interview-1"
    row[2] = "coding"
    row[3] = "Prompt"
    row[4] = {}
    row[5] = status
    row[8] = "in_progress"
    row[9] = {}
    row[10] = {}
    row[12] = "mock"
    row[13] = 1
    row[14] = "python"
    row[15] = 2400
    row[20] = starter_code
    return tuple(row)


class _DraftCursor:
    def __init__(self, fetchone_values):
        self.fetchone_values = list(fetchone_values)
        self.executions = []
        self.closed = False

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchone(self):
        return self.fetchone_values.pop(0)

    def close(self):
        self.closed = True


class _DraftConnection:
    def __init__(self, fetchone_values):
        self.cursor_value = _DraftCursor(fetchone_values)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _valid_problem(title="Pair Sum"):
    return {
        "title": title,
        "difficulty": "Easy",
        "cf_rating": 1000,
        "algorithm_pattern": "hash map",
        "statement": "Given a list of integers and a target value, determine whether any pair sums to the target.",
        "input_format": "n target, followed by n integers.",
        "output_format": "YES or NO.",
        "constraints": "1 <= n <= 200000",
        "visible_tests": [
            {"stdin": "4 5\n1 2 3 9\n", "expected": "YES\n", "explanation": "2 + 3 = 5."},
            {"stdin": "3 8\n1 2 4\n", "expected": "NO\n", "explanation": "No pair works."},
            {"stdin": "2 10\n5 5\n", "expected": "YES\n", "explanation": "Both elements are used."},
        ],
        "hidden_tests": [
            {"stdin": f"2 {i}\n1 {i - 1}\n", "expected": "YES\n"}
            for i in range(11, 18)
        ],
        "expected_time_complexity": "O(n)",
        "expected_space_complexity": "O(n)",
        "hint": "Track previously seen values.",
        "reference_solution": "import sys\nprint('YES')\n# deliberately long enough for validation shape",
    }


def _valid_bank_entry(title="Pair Sum"):
    problem = _valid_problem(title)
    return {
        "problem_id": f"bank-{title.lower().replace(' ', '-')}",
        "problem_family_id": f"family-{title.lower().replace(' ', '-')}",
        "version": 1,
        "round_type": "coding",
        "taxonomy_keys": ["technical:arrays", "technical:hashing"],
        "prerequisite_keys": [],
        "difficulty": "easy",
        "title": problem["title"],
        "statement": problem["statement"],
        "spec_json": {"profile_types": ["mid_tier", "startup", "custom"]},
        "visible_tests": problem["visible_tests"],
        "hidden_tests": problem["hidden_tests"],
        "expected_time_complexity": problem["expected_time_complexity"],
        "expected_space_complexity": problem["expected_space_complexity"],
        "supported_languages": ["python"],
        "validator_version": "test",
        "validation_result": {"passed": True, "sandbox_execution_verified": True},
        "source": "problem_bank",
    }


class TechnicalModePureTests(unittest.TestCase):
    def test_persisted_bank_contract_rejects_bad_case_shape_and_duplicate_inputs(self):
        valid = _valid_bank_entry()
        self.assertEqual(technical_mode._bank_entry_contract_errors(valid), [])

        invalid = {**valid, "visible_tests": [*valid["visible_tests"]]}
        invalid["visible_tests"][1] = {
            **invalid["visible_tests"][1],
            "stdin": invalid["visible_tests"][0]["stdin"],
        }
        errors = technical_mode._bank_entry_contract_errors(invalid)

        self.assertIn("duplicate_test_input", errors)

    def test_context_scoring_uses_domain_terms_not_generic_job_description_words(self):
        context = {
            "job_title": "Backend Software Engineer",
            "job_description": "Build reliable services with Redis caching and idempotent queues.",
            "target_skills": ["Redis", "queues"],
        }
        relevant = {
            **_valid_bank_entry("Cache Queue"),
            "statement": _valid_problem()["statement"] + " Use Redis-style caching and queue semantics.",
            "taxonomy_keys": ["technical:redis", "technical:queue"],
        }
        unrelated = {
            **_valid_bank_entry("Graph Path"),
            "statement": _valid_problem()["statement"] + " Traverse an unweighted graph.",
            "taxonomy_keys": ["technical:graphs", "technical:bfs"],
        }

        relevant_score = technical_mode._bank_candidate_score(
            relevant, profile_type="mid_tier", context=context, round_number=1
        )
        unrelated_score = technical_mode._bank_candidate_score(
            unrelated, profile_type="mid_tier", context=context, round_number=1
        )

        self.assertGreater(relevant_score[0], unrelated_score[0])
        self.assertNotIn("software", technical_mode._selection_terms(context))
        self.assertNotIn("engineer", technical_mode._selection_terms(context))

    def test_problem_reservation_conflict_respects_explicit_bank_exhaustion(self):
        template = {
            "problem_id": "bank-1",
            "round_spec": {"problem_family_id": "family-1", "history_reuse_required": False},
        }
        exhausted = {
            "problem_id": "bank-1",
            "round_spec": {"problem_family_id": "family-1", "history_reuse_required": True},
        }
        history = [("older-id", "family-1")]

        self.assertEqual(technical_mode._problem_reservation_conflicts([template], history), ["bank-1"])
        self.assertEqual(technical_mode._problem_reservation_conflicts([exhausted], history), [])

    def test_initial_untouched_starter_is_not_persisted_as_candidate_evidence(self):
        starter = "def solve():\n    pass\n"
        connection = _DraftConnection([None])
        request = technical_mode.DraftSaveRequest(
            language="python",
            code=starter,
            editor_revision=0,
        )

        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            result = technical_mode._persist_draft_snapshot_sync(
                _loaded_round(starter_code=starter),
                "user-1",
                request,
            )

        self.assertFalse(result["saved"])
        self.assertFalse(result["candidate_edited"])
        self.assertTrue(connection.committed)
        self.assertFalse(any("INSERT INTO TechnicalCodeSnapshots" in query for query, _ in connection.cursor_value.executions))

    def test_edited_draft_persists_revision_hash_and_candidate_marker(self):
        connection = _DraftConnection([None, (None,)])
        request = technical_mode.DraftSaveRequest(
            language="python",
            code="print('candidate')\n",
            editor_revision=3,
        )

        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            result = technical_mode._persist_draft_snapshot_sync(
                _loaded_round(),
                "user-1",
                request,
            )

        insert_params = next(
            params for query, params in connection.cursor_value.executions
            if "INSERT INTO TechnicalCodeSnapshots" in query
        )
        metadata = json.loads(insert_params[-1])
        self.assertTrue(result["saved"])
        self.assertTrue(result["candidate_edited"])
        self.assertEqual(metadata["editor_revision"], 3)
        self.assertEqual(metadata["editor_hash"], result["editor_hash"])
        self.assertTrue(metadata["candidate_edited"])

    def test_stale_draft_revision_is_rejected_under_round_lock(self):
        connection = _DraftConnection([
            ("snapshot-1", "older-hash", {"editor_revision": 5}, None),
        ])
        request = technical_mode.DraftSaveRequest(
            language="python",
            code="print('stale')\n",
            editor_revision=4,
        )

        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                technical_mode._persist_draft_snapshot_sync(
                    _loaded_round(),
                    "user-1",
                    request,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(connection.rolled_back)

    def test_noncoding_questions_sound_spoken_instead_of_exposing_the_rubric(self):
        context = {
            "job_title": "Backend Engineer",
            "technical_topics": ["API reliability"],
            "profile_type": "top_tier",
        }

        for round_type in ("technical_concept", "system_design", "ml", "backend", "database", "os", "network", "oop"):
            question = technical_mode._noncoding_authored_spec(round_type, context)["statement"]
            self.assertTrue(question.endswith("?"))
            self.assertEqual(question.count("?"), 1)
            self.assertLessEqual(len(question.split()), 18)
            self.assertNotIn("Cover ", question)
            self.assertNotIn("Assume ", question)
            self.assertNotIn("Walk through", question)

    def test_noncoding_followup_targets_one_missing_point(self):
        decision = technical_mode._technical_response_decision(
            {
                "overall_score": 60,
                "evidence": {"missed_points": ["backend:failures"]},
            },
            [{"point_id": "backend:failures", "label": "failure modes and mitigations"}],
            phase="initial",
        )

        self.assertEqual(decision["action"], "targeted_followup")
        self.assertEqual(
            decision["followup_prompt"],
            "How would your design recover from its most likely failure?",
        )
        self.assertNotIn("Go one level deeper", decision["followup_prompt"])

    def test_execution_poll_contract_never_exposes_hidden_case_details(self):
        row = (
            "job-hidden", "round-1", "submit", "full", "python", "completed",
            {
                "visible_passed": 1,
                "visible_total": 1,
                "hidden_passed": 1,
                "hidden_total": 2,
                "pass_count": 2,
                "total_count": 3,
                "cases": [
                    {"index": 0, "hidden": False, "stdin": "1", "expected": "1", "actual": "1", "passed": True},
                    {"index": 1, "hidden": True, "stdin": "SECRET", "expected": "SECRET", "actual": "SECRET", "stderr": "private", "passed": True, "runtime_ms": 9},
                    {"index": 2, "hidden": True, "passed": False, "verdict": "Wrong Answer"},
                ],
                "runtime_ms": 12,
                "memory_kb": 64,
            },
            None, 0, "source-hash",
        )

        public = technical_mode._execution_job_public_from_row(row)

        self.assertEqual(public["cases"], [
            {"index": 0, "stdin": "1", "expected": "1", "actual": "1", "passed": True}
        ])
        self.assertEqual(public["hidden_passed"], 1)
        self.assertEqual(public["hidden_total"], 2)
        self.assertIsNone(public["hidden_details"])
        self.assertEqual(public["test_summary"], {"passed": 2, "total": 3})
        self.assertEqual(public["poll_after_ms"], 250)
        self.assertNotIn("SECRET", str(public))
        self.assertNotIn("private", str(public))

    def test_idempotent_replay_is_explicit_in_enqueue_response(self):
        row = (
            "job-1", "round-1", "test", "visible", "python", "queued",
            {"pass_count": 0, "total_count": 2}, None, 0, "source-hash",
        )

        with patch.object(technical_mode, "async_execute", new_callable=AsyncMock, return_value=row):
            replay = __import__("asyncio").run(technical_mode._existing_execution_job(
                "user-1", "idempotency-key", round_id="round-1", action="test", source_hash="source-hash"
            ))

        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["status"], "queued")

    def test_later_practice_submission_cannot_replace_first_committed_final(self):
        first = {"committed": True, "execution_job_id": "job-1", "source_hash": "hash-1"}
        second = {"committed": True, "execution_job_id": "job-2", "source_hash": "hash-2"}

        initial = technical_worker._record_committed_submission({}, first)
        updated = technical_worker._record_committed_submission(initial, second)

        self.assertEqual(updated["final_submission"], first)
        self.assertEqual(updated["latest_submission"], second)
        self.assertEqual([item["execution_job_id"] for item in updated["submission_history"]], ["job-1", "job-2"])

    def test_all_execution_enqueue_routes_use_202_contract(self):
        enqueue_paths = {
            "/api/technical/rounds/{round_id}/run",
            "/api/technical/rounds/{round_id}/test",
            "/api/technical/rounds/{round_id}/custom-run",
            "/api/technical/rounds/{round_id}/submit",
        }
        statuses = {
            route.path: route.status_code
            for route in technical_mode.router.routes
            if getattr(route, "path", None) in enqueue_paths
        }
        self.assertEqual(set(statuses), enqueue_paths)
        self.assertTrue(all(value == 202 for value in statuses.values()))

    def test_execution_errors_are_retry_aware_and_do_not_expose_worker_details(self):
        failed_row = (
            "job-1", "round-1", "submit", "full", "python", "failed",
            {"error": "container mount /private/secret failed"},
            "runc: internal host path leaked", 3, "source-hash",
        )
        queued_row = (
            "job-2", "round-1", "run", "visible", "python", "queued",
            {}, "executor connection refused", 1, "source-hash",
        )

        failed = technical_mode._execution_job_public_from_row(failed_row)
        queued = technical_mode._execution_job_public_from_row(queued_row)

        self.assertEqual(failed["error"], "Execution could not be completed after retrying. Your code is still saved.")
        self.assertNotIn("runc", failed["error"])
        self.assertEqual(queued["error"], "Execution is being retried.")

    def test_tier_rating_mapping(self):
        self.assertEqual(technical_mode.CODEFORCES_RATING_TARGETS["top_tier"], [1800, 2000])
        self.assertEqual(technical_mode.CODEFORCES_RATING_TARGETS["mid_tier"], [1000, 1200])
        self.assertEqual(technical_mode.CODEFORCES_RATING_TARGETS["startup"], [800, 1000])

    def test_public_metadata_strips_private_fields(self):
        metadata = _valid_problem()
        metadata["generated_source"] = "ai"
        metadata["company_profile"] = "mid_tier"
        metadata["job_title"] = "Backend Engineer"
        metadata["personalization_anchors"] = {"projects": [{"name": "RAG Pipeline"}]}
        metadata["target_skills"] = ["FastAPI", "PostgreSQL"]
        metadata["tier_followup_prompts"] = {"technical": "Probe backend fundamentals."}

        public = technical_mode._public_round_metadata(metadata)

        self.assertIn("visible_tests", public)
        self.assertEqual(public["job_title"], "Backend Engineer")
        self.assertIn("target_skills", public)
        self.assertNotIn("hidden_tests", public)
        self.assertNotIn("reference_solution", public)
        self.assertEqual(len(public["visible_tests"]), 3)

    def test_generation_messages_include_resume_job_and_mistake_context(self):
        context = {
            "job_title": "AI Backend Engineer",
            "job_description": "Build multimodal RAG services.",
            "target_skills": ["FastAPI", "FAISS", "PostgreSQL"],
            "personalization_anchors": {
                "projects": [{"name": "Multimodal RAG", "description": "PDF and chart retrieval"}],
                "skills": ["Python", "LLMs"],
            },
            "mistake_history": [{"type": "edge_case", "key": "empty_input", "count": 3}],
        }

        messages = technical_mode._generation_messages("top_tier", "interview-1", 1, context)
        prompt = messages[1]["content"]

        self.assertIn("AI Backend Engineer", prompt)
        self.assertIn("Multimodal RAG", prompt)
        self.assertIn("empty_input", prompt)
        self.assertIn("FastAPI", prompt)

    def test_local_execution_verdict_mapping(self):
        self.assertEqual(technical_mode._execution_verdict({"exit_code": 0}), "Accepted")
        self.assertEqual(technical_mode._execution_verdict({"exit_code": 1}), "Runtime Error")
        self.assertEqual(technical_mode._execution_verdict({"exit_code": -1, "timed_out": True}), "TLE")
        self.assertEqual(technical_mode._execution_verdict({"exit_code": 1, "compile_failed": True}), "Compile Error")

    def test_case_verdict_checks_output_after_judge0_accepts(self):
        result = {"exit_code": 0, "stdout": "7\n"}

        self.assertEqual(technical_mode._case_verdict(result, {"expected": "7\n"}), "Accepted")
        self.assertEqual(technical_mode._case_verdict(result, {"expected": "8\n"}), "Wrong Answer")

    def test_fallback_rounds_are_reusable(self):
        rows = [
            ("round-1", "coding", "python", "Prompt", "", {}, "active", {"spec_version": technical_mode.ROUND_SPEC_VERSION}),
            ("round-2", "debugging", "python", "Prompt", "", {}, "active", {"spec_version": technical_mode.ROUND_SPEC_VERSION}),
        ]

        self.assertFalse(technical_mode._should_regenerate_rounds(rows, "python", ["coding", "debugging"]))

    def test_fallback_personalization_preserves_validated_problem_contract(self):
        base = {"role": "Backend Engineer", "skills": "Python, PostgreSQL", "project": "Ledger API"}
        alternate = {**base, "project": "Search Platform"}

        first = technical_mode._fallback_problem_candidates(base, [1000, 1200], "mid_tier")
        second = technical_mode._fallback_problem_candidates(alternate, [1000, 1200], "mid_tier")

        self.assertEqual([problem["title"] for problem in first], [problem["title"] for problem in second])
        self.assertEqual(first[0]["visible_tests"], second[0]["visible_tests"])
        self.assertEqual(first[0]["hidden_tests"], second[0]["hidden_tests"])
        self.assertEqual(first[0]["reference_solution"], second[0]["reference_solution"])
        self.assertIn("Backend Engineer", first[0]["statement"])
        self.assertIn("Ledger API", first[0]["statement"])
        self.assertIn("Search Platform", second[0]["statement"])

    def test_executor_status_is_truthful_when_production_runner_is_unconfigured(self):
        with patch("local_execution.executor_status", return_value={
            "healthy": False,
            "isolated": False,
            "executor": "unavailable",
            "reason": "No supported sandbox",
        }):
            status_payload = technical_mode._executor_status_payload()

        self.assertEqual(status_payload["executor"], "unavailable")
        self.assertEqual(status_payload["executor_label"], "Unavailable")
        self.assertFalse(status_payload["executor_available"])
        self.assertEqual(status_payload["executor_status"], "unavailable")

    def test_hosted_executor_configuration_is_absent(self):
        self.assertFalse(hasattr(technical_mode.settings, "JUDGE0_API_URL"))
        self.assertFalse(hasattr(technical_mode.settings, "PISTON_API_URL"))
        self.assertFalse(hasattr(technical_mode, "_execute_piston"))
        self.assertFalse(hasattr(technical_mode, "_execute_judge0"))

    def test_durable_enqueue_encrypts_source_and_cases(self):
        class Cursor:
            def __init__(self):
                self.fetchone_values = [
                    None,
                    ("active", "mock", 1, None, {}, None),
                    (0,),
                    ("job-1", "round-1", "submit", "full", "python", "queued", {"status": "queued"}, None, 0, "source-hash"),
                ]
                self.executions = []

            def execute(self, query, params=None):
                self.executions.append((query, params))

            def fetchone(self):
                return self.fetchone_values.pop(0)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

        connection = Connection()
        request = technical_mode.TechnicalTestRequest(
            language="python",
            code="print(input())",
            idempotency_key="submit-key-123",
        )
        round_row = ("round-1", "interview-1")
        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            row = technical_mode._enqueue_execution_job_sync(
                round_row=round_row,
                user_id="user-1",
                request=request,
                action="submit",
                suite="full",
                cases=[{"stdin": "1\n", "expected": "1\n", "visible": False}],
                idempotency_key="submit-key-123",
                lock_submission=True,
                visible_total=0,
                hidden_total=1,
            )

        self.assertEqual(row[0], "job-1")
        self.assertFalse(row[-1])
        self.assertEqual(connection.cursor_value.executions[0][0], "BEGIN IMMEDIATE")
        insert_query, insert_params = next(
            item for item in connection.cursor_value.executions if "INSERT INTO TechnicalExecutionJobs" in item[0]
        )
        self.assertIn("source_code_encrypted", insert_query)
        self.assertEqual(insert_params[8], "[encrypted]")
        self.assertIsInstance(insert_params[9], bytes)
        self.assertNotIn(b"print(input())", insert_params[9])
        self.assertIsInstance(insert_params[11], bytes)
        self.assertNotIn(b'"stdin"', insert_params[11])
        self.assertTrue(connection.committed)

    def test_concurrent_execution_replay_is_serialized_before_round_mutation(self):
        code = "print(input())"
        source_hash = technical_mode.hashlib.sha256(code.encode("utf-8")).hexdigest()

        class Cursor:
            def __init__(self):
                self.values = [
                    ("job-1", "round-1", "test", "visible", "python", "queued", {}, None, 0, source_hash),
                    (source_hash, "interview-1"),
                ]
                self.executions = []

            def execute(self, query, params=None):
                self.executions.append((query, params))

            def fetchone(self):
                return self.values.pop(0)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

        connection = Connection()
        request = technical_mode.TechnicalTestRequest(
            language="python",
            code=code,
            idempotency_key="same-run-key-123",
        )
        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            row = technical_mode._enqueue_execution_job_sync(
                round_row=("round-1", "interview-1"),
                user_id="user-1",
                request=request,
                action="test",
                suite="visible",
                cases=[{"stdin": "1\n", "expected": "1\n", "visible": True}],
                idempotency_key="same-run-key-123",
                lock_submission=False,
                visible_total=1,
                hidden_total=0,
            )

        self.assertTrue(row[-1])
        self.assertTrue(connection.committed)
        self.assertFalse(any("INSERT INTO TechnicalExecutionJobs" in query for query, _ in connection.cursor_value.executions))
        self.assertFalse(any("FROM TechnicalInterviewRounds tir" in query for query, _ in connection.cursor_value.executions))

    def test_concurrent_attempt_reservation_rechecks_history_under_user_lock(self):
        class Cursor:
            def __init__(self):
                self.fetchall_values = [[], [("older-problem", "family-1")]]
                self.executions = []

            def execute(self, query, params=None):
                self.executions.append((query, params))

            def fetchall(self):
                return self.fetchall_values.pop(0)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()
                self.rolled_back = False

            def cursor(self):
                return self.cursor_value

            def commit(self):
                pass

            def rollback(self):
                self.rolled_back = True

        connection = Connection()
        templates = [{
            "problem_id": "bank-1",
            "round_spec": {"problem_family_id": "family-1", "history_reuse_required": False},
        }]
        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            with self.assertRaises(technical_mode.TechnicalProblemReservationConflict):
                technical_mode._persist_frozen_round_templates_sync(
                    "interview-2",
                    "user-1",
                    templates,
                )

        self.assertEqual(connection.cursor_value.executions[0][0], "BEGIN IMMEDIATE")
        self.assertTrue(connection.rolled_back)
        self.assertFalse(any("INSERT INTO TechnicalInterviewRounds" in query for query, _ in connection.cursor_value.executions))

    def test_new_attempt_freezes_every_question_pending_before_activation(self):
        class Cursor:
            def __init__(self):
                self.fetchall_values = [[], [], []]
                self.fetchone_values = [(technical_mode.datetime(2030, 1, 1),)]
                self.executions = []

            def execute(self, query, params=None):
                self.executions.append((query, params))

            def fetchall(self):
                return self.fetchall_values.pop(0)

            def fetchone(self):
                return self.fetchone_values.pop(0)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

        templates = [
            {
                "round_type": "coding",
                "language": "python",
                "prompt": f"Prompt {index}",
                "starter_code": "pass\n",
                "metadata": {},
                "round_spec_id": f"spec-{index}",
                "problem_id": f"problem-{index}",
                "round_number": index,
                "round_spec": {"problem_family_id": f"family-{index}"},
                "duration_seconds": 2400,
                "mode": "mock",
                "max_submissions": 1,
                "problem_version": 1,
            }
            for index in (1, 2)
        ]
        connection = Connection()
        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            technical_mode._persist_frozen_round_templates_sync(
                "interview-1", "user-1", templates
            )

        insert_params = [
            params
            for query, params in connection.cursor_value.executions
            if "INSERT INTO TechnicalInterviewRounds" in query
        ]
        self.assertEqual(len(insert_params), 2)
        self.assertTrue(all(params[18] == "pending" for params in insert_params))
        self.assertTrue(all(params[14] is None for params in insert_params))
        self.assertTrue(all(params[19] is None for params in insert_params))
        self.assertEqual(len({params[20] for params in insert_params}), 1)
        self.assertTrue(connection.committed)

    def test_activation_route_starts_the_clock_and_is_explicit(self):
        paths = {getattr(route, "path", "") for route in technical_mode.router.routes}
        self.assertIn("/api/technical/sessions/{interview_id}/activate", paths)
        source = inspect.getsource(technical_mode._activate_technical_session_sync)
        self.assertIn("status = 'active'", source)
        self.assertIn("technical_activation_version", source)
        self.assertIn("datetime.now(timezone.utc)", source)

    def test_workflow_round_update_has_one_owner_scoped_where_clause(self):
        class Cursor:
            def __init__(self):
                self.values = [
                    ("round-1", "interview-1", "coding", "active", None, {}, 1),
                    None,
                ]
                self.executions = []

            def execute(self, query, params=None):
                self.executions.append((query, params))

            def fetchone(self):
                return self.values.pop(0)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

        connection = Connection()
        request = technical_mode.TechnicalWorkflowRequest(
            stage="approach",
            content="Use a hash set to track complements.",
            idempotency_key="workflow-key-123",
        )
        with patch.object(technical_mode, "get_db_connection", return_value=connection), patch.object(
            technical_mode, "return_db_connection"
        ):
            result = technical_mode._persist_workflow_evidence_sync(
                "round-1", "user-1", request
            )

        update_query, update_params = next(
            (query, params)
            for query, params in connection.cursor_value.executions
            if "UPDATE TechnicalInterviewRounds" in query and "workflow_state" in query
        )
        self.assertEqual(update_query.upper().count("WHERE"), 1)
        self.assertEqual(update_params[-2:], ("round-1", "user-1"))
        self.assertTrue(connection.committed)
        self.assertEqual(result["status"], "committed")

    def test_worker_claim_uses_atomic_sqlite_claim_and_lease(self):
        class Cursor:
            def __init__(self):
                self.queries = []
                self.current = 0

            def execute(self, query, params=None):
                self.queries.append((query, params))
                self.current += 1

            def fetchall(self):
                return []

            def fetchone(self):
                return (
                    "job-1", "key-1", "user-1", "interview-1", "round-1",
                    "test", "visible", "python", b"encrypted", "hash",
                    b"encrypted-cases", 0, {"visible_total": 1},
                )

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()

            def cursor(self):
                return self.cursor_value

            def commit(self):
                pass

            def rollback(self):
                pass

        connection = Connection()
        with patch.object(technical_worker, "get_db_connection", return_value=connection), patch.object(
            technical_worker, "return_db_connection"
        ):
            job = technical_worker.claim_execution_job("worker-1")

        claim_sql = next(query for query, _ in connection.cursor_value.queries if "UPDATE TechnicalExecutionJobs" in query)
        self.assertIn("WHERE job_id = (", claim_sql)
        self.assertIn("SELECT job_id", claim_sql)
        self.assertNotIn("FOR UPDATE", claim_sql)
        self.assertNotIn("SKIP LOCKED", claim_sql)
        self.assertIn("lease_expires_at", claim_sql)
        self.assertEqual(job["job_id"], "job-1")


class TechnicalModeAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        languages = {
            language: {"available": True, "runtime": language, "reason": "Ready"}
            for language in ("python", "javascript", "cpp", "java")
        }
        self.executor_status_patcher = patch(
            "local_execution.executor_status",
            return_value={
                "healthy": True,
                "executor": "test-sandbox",
                "isolated": True,
                "languages": languages,
                "available_languages": list(languages),
            },
        )
        self.executor_status_patcher.start()
        self.addCleanup(self.executor_status_patcher.stop)

    async def test_attempt_aggregate_reload_is_revisioned_and_owner_scoped(self):
        aggregate_row = (
            "active", 7, 2, 1, 1,
            [{"round_id": "round-1", "status": "submitted"}, {"round_id": "round-2", "status": "active"}],
            None, None, None,
        )
        execute = AsyncMock(return_value=aggregate_row)
        with patch.object(technical_mode, "async_execute", execute):
            result = await technical_mode._load_technical_attempt_state(
                "interview-1", "user-1", []
            )

        self.assertTrue(result["persisted"])
        self.assertEqual(result["lifecycle_revision"], 7)
        self.assertEqual(result["open_round_count"], 1)
        self.assertEqual(execute.await_args.args[1], ("interview-1", "user-1"))

    async def test_prepare_has_no_remote_capacity_or_plan_gate(self):
        self.assertFalse(hasattr(technical_mode, "TECHNICAL_PREPARE_RATE_LIMITER"))
        self.assertFalse(hasattr(technical_mode, "_require_technical_prepare_capacity"))

    async def test_run_poll_fallback_never_reads_another_users_job(self):
        execute = AsyncMock(side_effect=[None, None])

        with patch.object(technical_mode, "async_execute", execute):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode.get_run_status("foreign-run", {"user_id": "user-1"})

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(len(execute.await_args_list), 2)
        self.assertEqual(execute.await_args_list[0].args[1], ("foreign-run", "user-1"))
        self.assertEqual(execute.await_args_list[1].args[1], ("foreign-run", "user-1"))

    async def test_enqueue_replay_marker_does_not_duplicate_queued_telemetry(self):
        request = technical_mode.TechnicalTestRequest(
            language="python",
            code="print(input())",
            idempotency_key="same-run-key-123",
        )
        source_hash = technical_mode.hashlib.sha256(request.code.encode("utf-8")).hexdigest()
        replay_row = (
            "job-1", "round-1", "test", "visible", "python", "queued",
            {}, None, 0, source_hash, True,
        )

        with patch.object(
            technical_mode, "_existing_execution_job", new_callable=AsyncMock, return_value=None
        ), patch.object(
            technical_mode, "_enqueue_execution_job_sync", return_value=replay_row
        ), patch.object(
            technical_mode, "_record_technical_event", new_callable=AsyncMock
        ) as record:
            result = await technical_mode._queue_execution_job(
                round_row=("round-1", "interview-1"),
                user_id="user-1",
                request=request,
                action="test",
                suite="visible",
                cases=[{"stdin": "1\n", "expected": "1\n", "visible": True}],
                lock_submission=False,
                visible_total=1,
                hidden_total=0,
            )

        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["run_id"], "job-1")
        record.assert_not_awaited()

    async def test_production_bank_loader_excludes_unverified_or_invalid_entries(self):
        valid = _valid_bank_entry("Verified Pair")
        invalid = _valid_bank_entry("Broken Pair")
        invalid["visible_tests"] = invalid["visible_tests"][:2]

        def row_for(entry, *, verified):
            return (
                entry["problem_id"], entry["problem_family_id"], entry["version"],
                entry["round_type"], entry["taxonomy_keys"], entry["prerequisite_keys"],
                entry["difficulty"], entry["title"], entry["statement"], entry["spec_json"],
                entry["visible_tests"], "encrypted-hidden", entry["expected_time_complexity"],
                entry["expected_space_complexity"], entry["supported_languages"],
                entry["validator_version"],
                {"passed": True, "sandbox_execution_verified": verified},
            )

        rows = [row_for(valid, verified=False), row_for(invalid, verified=True)]
        execute = AsyncMock(return_value=rows)
        with patch.object(technical_mode.settings, "ENVIRONMENT", "production"), patch.object(
            technical_mode, "async_execute", execute
        ), patch.object(
            technical_mode,
            "_decrypt_storage_blob",
            return_value=json.dumps(valid["hidden_tests"]),
        ):
            bank = await technical_mode._load_active_problem_bank()

        self.assertEqual(bank, [])

    async def test_exhausted_bank_reuses_distinct_families_with_explicit_metadata(self):
        bank = []
        for index in range(1, 3):
            item = _valid_bank_entry(f"Hard Problem {index}")
            item.update({
                "problem_id": f"bank-{index}",
                "problem_family_id": f"family-{index}",
                "difficulty": "hard",
                "spec_json": {"profile_types": ["top_tier"]},
            })
            bank.append(item)

        with patch.object(
            technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=bank
        ), patch.object(
            technical_mode,
            "async_execute",
            new_callable=AsyncMock,
            return_value=[("bank-1", "family-1"), ("bank-2", "family-2")],
        ), patch.object(
            technical_mode, "_authored_coding_specs", new_callable=AsyncMock
        ) as authored:
            templates = await technical_mode._round_templates_for_profile(
                "top_tier",
                "interview-2",
                "user-1",
                {"programming_language": "python", "question_count": 2, "duration_minutes": 80},
            )

        self.assertEqual({item["problem_id"] for item in templates}, {"bank-1", "bank-2"})
        self.assertTrue(all(item["metadata"]["history_reuse_required"] for item in templates))
        authored.assert_not_awaited()

    async def test_validated_bank_path_does_not_eagerly_build_authored_fallback(self):
        bank = []
        for index, difficulty in enumerate(("easy", "medium"), start=1):
            item = _valid_bank_entry(f"Bank Problem {index}")
            item.update({
                "problem_id": f"bank-{index}",
                "problem_family_id": f"family-{index}",
                "difficulty": difficulty,
            })
            bank.append(item)

        with patch.object(
            technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=bank
        ), patch.object(
            technical_mode, "async_execute", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            technical_mode, "_authored_coding_specs", new_callable=AsyncMock
        ) as authored:
            templates = await technical_mode._round_templates_for_profile(
                "mid_tier",
                "interview-1",
                "user-1",
                {"programming_language": "python", "question_count": 2, "duration_minutes": 80},
            )

        self.assertEqual([item["problem_id"] for item in templates], ["bank-1", "bank-2"])
        authored.assert_not_awaited()

    async def test_generation_failure_response_does_not_leak_internal_exception(self):
        with patch.object(
            technical_mode, "_load_cached_generation", new_callable=AsyncMock, return_value=None
        ), patch.object(
            technical_mode,
            "complete_json_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider-secret-detail"),
        ), patch.object(
            technical_mode,
            "_fallback_problem_set",
            new_callable=AsyncMock,
            side_effect=RuntimeError("filesystem-secret-detail"),
        ):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode._generate_ai_problem_set(
                    "mid_tier", "interview-1", "user-1", {}
                )

        self.assertEqual(raised.exception.status_code, 502)
        public_detail = str(raised.exception.detail)
        self.assertNotIn("provider-secret", public_detail)
        self.assertNotIn("filesystem-secret", public_detail)

    async def test_event_round_must_belong_to_the_owned_interview(self):
        execute = AsyncMock(return_value=None)
        request = technical_mode.TechnicalEventRequest(
            interview_id="interview-1",
            round_id="round-from-another-interview",
            event_type="code_activity",
            payload={},
        )

        with patch.object(technical_mode, "async_execute", execute), patch.object(
            technical_mode,
            "_record_technical_event",
            AsyncMock(),
        ) as record:
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode.record_technical_event(request, {"user_id": "user-1"})

        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("round.interview_id = interview.interview_id", execute.await_args.args[0])
        record.assert_not_awaited()

    async def test_pending_question_requires_explicit_briefing_activation(self):
        pending = _loaded_round(status="pending")
        for action in ("save_draft", "run"):
            execute = AsyncMock(return_value=("round-1",))
            with patch.object(technical_mode, "async_execute", execute):
                with self.assertRaises(technical_mode.HTTPException) as raised:
                    await technical_mode._ensure_round_action_allowed(pending, "user-1", action)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("Activate the Technical round", str(raised.exception.detail))
            execute.assert_not_awaited()

    async def test_pending_draft_still_respects_expired_attempt_deadline(self):
        pending = list(_loaded_round(status="pending"))
        pending[19] = "2000-01-01T00:00:00+00:00"
        execute = AsyncMock(return_value=None)

        with patch.object(technical_mode, "async_execute", execute):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode._ensure_round_action_allowed(tuple(pending), "user-1", "save_draft")

        self.assertEqual(raised.exception.status_code, 410)
        execute.assert_awaited_once()

    async def test_post_submission_explanation_state_freezes_editor_drafts(self):
        awaiting_explanation = _loaded_round(status="awaiting_explanation")

        with self.assertRaises(technical_mode.HTTPException) as raised:
            await technical_mode._ensure_round_action_allowed(
                awaiting_explanation,
                "user-1",
                "save_draft",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("final code is locked", str(raised.exception.detail).lower())

    async def test_round_hydration_returns_latest_owned_draft_revision_and_run(self):
        starter = "def solve():\n    pass\n"
        rows = [(
            "round-1", "coding", "python", "Prompt", starter, {}, "active", {},
            None, None, "spec-1", "problem-1", 1, {}, 2400, None, "mock", 1,
            1, {}, None, None,
        )]
        draft_rows = [(
            "round-1", "python", "encrypted-draft", None,
            {"event": "save_draft", "editor_revision": 7, "candidate_edited": True},
            19, "draft-hash",
        )]
        latest_jobs = [(
            "job-1", "round-1", "test", "visible", "python", "completed",
            {"pass_count": 2, "total_count": 3}, None, 0, "draft-hash",
        )]
        execute = AsyncMock(side_effect=[draft_rows, latest_jobs])

        with patch.object(technical_mode, "async_execute", execute), patch.object(
            technical_mode,
            "_decrypt_storage_blob",
            return_value="print('candidate')\n",
        ):
            result = await technical_mode._serialize_round_rows_with_candidate_state(rows, "user-1")

        self.assertEqual(result[0]["draft_code"], "print('candidate')\n")
        self.assertEqual(result[0]["draft_editor_revision"], 7)
        self.assertEqual(result[0]["draft_editor_hash"], "draft-hash")
        self.assertEqual(result[0]["latest_run"]["run_id"], "job-1")
        self.assertEqual(execute.await_args_list[0].args[1][0], "user-1")
        self.assertEqual(execute.await_args_list[1].args[1][0], "user-1")

    async def test_latest_starter_snapshot_does_not_restore_or_fall_back_to_older_edit(self):
        starter = "def solve():\n    pass\n"
        rows = [(
            "round-1", "coding", "python", "Prompt", starter, {}, "active", {},
            None, None, "spec-1", "problem-1", 1, {}, 2400, None, "mock", 1,
            1, {}, None, None,
        )]
        draft_rows = [
            ("round-1", "python", "latest-starter", None, {"editor_revision": 2}, len(starter), "starter-hash"),
            ("round-1", "python", "older-edit", None, {"editor_revision": 1}, 12, "edit-hash"),
        ]
        execute = AsyncMock(side_effect=[draft_rows, []])

        with patch.object(technical_mode, "async_execute", execute), patch.object(
            technical_mode,
            "_decrypt_storage_blob",
            side_effect=[starter, "print('older')\n"],
        ):
            result = await technical_mode._serialize_round_rows_with_candidate_state(rows, "user-1")

        self.assertNotIn("draft_code", result[0])
        self.assertEqual(result[0]["draft_editor_revision"], 2)
        self.assertFalse(result[0]["draft_candidate_edited"])

    async def test_top_tier_rounds_require_hard_bank_content_and_fixed_round_timing(self):
        first = _valid_problem("Hard Tree").copy()
        first["difficulty"] = "hard"
        second = _valid_problem("Hard Graph").copy()
        second["difficulty"] = "hard"
        bank = []
        for index, problem in enumerate((first, second), start=1):
            bank.append({
                "problem_id": f"bank-{index}",
                "problem_family_id": f"family-{index}",
                "version": 1,
                "round_type": "coding",
                "taxonomy_keys": ["technical:trees"],
                "prerequisite_keys": [],
                "difficulty": "hard",
                "title": problem["title"],
                "statement": problem["statement"],
                "spec_json": {"profile_types": ["top_tier"]},
                "visible_tests": problem["visible_tests"],
                "hidden_tests": problem["hidden_tests"],
                "expected_time_complexity": problem["expected_time_complexity"],
                "expected_space_complexity": problem["expected_space_complexity"],
                "supported_languages": ["python"],
                "validator_version": "test",
                "validation_result": {"passed": True},
                "source": "problem_bank",
            })

        with patch.object(technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=bank), patch.object(
            technical_mode, "async_execute", new_callable=AsyncMock, return_value=[]
        ):
            templates = await technical_mode._round_templates_for_profile(
                "top_tier",
                "interview-1",
                "user-1",
                {"programming_language": "python", "question_count": 2, "duration_minutes": 80},
            )

        self.assertEqual([template["duration_seconds"] for template in templates], [2400, 2400])
        self.assertEqual([template["metadata"]["tier_expected_difficulty"] for template in templates], ["hard", "hard"])
        self.assertEqual([template["metadata"]["tier_target_rating"] for template in templates], [1800, 2000])
        self.assertTrue(all(template["metadata"]["difficulty"] == "hard" for template in templates))

    async def test_round_templates_rotate_away_from_prior_problem_families(self):
        bank = []
        for index in range(1, 5):
            problem = _valid_problem(f"Hard Problem {index}")
            problem["difficulty"] = "hard"
            bank.append({
                "problem_id": f"bank-{index}",
                "problem_family_id": f"family-{index}",
                "version": 1,
                "round_type": "coding",
                "taxonomy_keys": ["technical:arrays"],
                "prerequisite_keys": [],
                "difficulty": "hard",
                "title": problem["title"],
                "statement": problem["statement"],
                "spec_json": {"profile_types": ["top_tier"]},
                "visible_tests": problem["visible_tests"],
                "hidden_tests": problem["hidden_tests"],
                "expected_time_complexity": problem["expected_time_complexity"],
                "expected_space_complexity": problem["expected_space_complexity"],
                "supported_languages": ["python"],
                "validator_version": "test",
                "validation_result": {"passed": True},
                "source": "problem_bank",
            })

        with patch.object(technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=bank), patch.object(
            technical_mode,
            "async_execute",
            new_callable=AsyncMock,
            return_value=[("bank-1", "family-1"), ("bank-2", "family-2")],
        ):
            templates = await technical_mode._round_templates_for_profile(
                "top_tier",
                "interview-2",
                "user-1",
                {"programming_language": "python", "question_count": 2, "duration_minutes": 80},
            )

        selected_ids = [template["problem_id"] for template in templates]
        self.assertEqual(len(selected_ids), 2)
        self.assertNotIn("bank-1", selected_ids)
        self.assertNotIn("bank-2", selected_ids)
        self.assertEqual(len(set(selected_ids)), 2)

    async def test_duplicate_pending_noncoding_response_resumes_and_commits(self):
        round_row = (
            "round-1", "interview-1", "system_design", "Design a queue", {}, "active",
            None, None, "in_progress", {},
            {"rubric": {"version": "technical-concept-v1"}, "expected_points": []},
            None, "mock", 1, "python", 900, "spec-1",
        )
        raw = {
            "response_id": "response-1",
            "question_id": "spec-1",
            "duplicate": True,
            "assessment": None,
            "evidence_hash": "evidence-1",
            "rubric": {"version": "technical-concept-v1"},
            "expected_points": [],
            "taxonomy_keys": ["technical:system-design"],
        }
        evaluated = {"version": "evaluation-v1", "overall_score": None}
        request = technical_mode.TechnicalResponseRequest(
            response_text="I would start with requirements, queues, retries, storage, and observability.",
            idempotency_key="response-key-123",
        )
        with patch.object(technical_mode, "_load_round_for_user", new_callable=AsyncMock, return_value=round_row), patch.object(
            technical_mode, "_persist_technical_response_raw_sync", return_value=raw
        ), patch.object(technical_mode, "evaluate_answer", new_callable=AsyncMock, return_value=evaluated) as evaluate, patch.object(
            technical_mode, "_commit_technical_response_assessment_sync", side_effect=lambda *args: args[-2]
        ):
            result = await technical_mode.submit_technical_response(
                "round-1",
                request,
                {"user_id": "user-1"},
            )

        evaluate.assert_awaited_once()
        self.assertEqual(result["status"], "committed")
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["response_id"], "response-1")

    async def test_generation_context_includes_profile_projects_skills_and_prior_weaknesses(self):
        async def fake_async_execute(query, *args, **kwargs):
            if "FROM UserInfo" in query:
                return (
                    {
                        "summary": "Builds reliable services.",
                        "skills": ["Python", "PostgreSQL"],
                        "projects": [{"name": "Ledger API", "description": "Double-entry ledger"}],
                    },
                    {
                        "targetRole": "Platform Engineer",
                        "skills": ["Go", "Redis"],
                        "projects": [{"name": "Queue Worker", "description": "Async processing"}],
                    },
                    {"github": {"repositories": [{"name": "scheduler", "language": "Go"}]}},
                )
            if "FROM TechnicalMistakeClusters" in query:
                return [("edge_case", "empty_input", 3, [{"verdict": "Wrong Answer"}])]
            if "FROM ImprovementMissions" in query:
                return [("technical_failure", "technical:complexity", "Reduce complexity", "Timed out on large input", 91)]
            raise AssertionError(query)

        with patch.object(technical_mode, "async_execute", side_effect=fake_async_execute):
            context = await technical_mode._load_technical_generation_context(
                "interview-1",
                "user-1",
                {"profile_type": "mid_tier", "programming_language": "C++17"},
                "Backend Engineer",
            )

        self.assertEqual(context["programming_language"], "cpp")
        self.assertIn("Python", context["target_skills"])
        self.assertIn("Go", context["target_skills"])
        self.assertEqual(
            [project["name"] for project in context["personalization_anchors"]["projects"]],
            ["Ledger API", "Queue Worker"],
        )
        self.assertEqual(context["mistake_history"][0]["key"], "empty_input")
        self.assertEqual(context["mistake_history"][1]["key"], "technical:complexity")

    async def test_live_round_templates_are_typed_authored_and_never_call_ai(self):
        context = {
            "programming_language": "java",
            "technical_round_types": ["coding", "debugging", "system_design"],
            "question_count": 3,
            "duration_minutes": 45,
        }
        with patch.object(technical_mode.settings, "TECHNICAL_CODING_ONLY", False), patch.object(
            technical_mode.settings, "TECHNICAL_ALLOW_AUTHORED_FALLBACK", True
        ), patch.object(technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=[]), patch.object(
            technical_mode, "_generate_ai_problem_set", new_callable=AsyncMock
        ) as generate:
            templates = await technical_mode._round_templates_for_profile(
                "mid_tier", "interview-1", "user-1", context
            )

        generate.assert_not_awaited()
        self.assertEqual([item["round_type"] for item in templates], ["coding", "debugging", "system_design"])
        self.assertTrue(all(item["language"] == "java" for item in templates))
        self.assertIn("public class Main", templates[0]["starter_code"])
        self.assertEqual(templates[2]["starter_code"], "")
        self.assertNotIn("hidden_tests", templates[0]["metadata"])
        self.assertTrue(templates[0]["round_spec"]["hidden_tests_encrypted"])

    async def test_generated_problem_validation_rejects_bad_test_counts(self):
        problem = _valid_problem()
        problem["visible_tests"] = problem["visible_tests"][:2]

        with self.assertRaises(ValueError):
            await technical_mode._normalize_generated_problem(
                problem,
                profile_type="mid_tier",
                profile_label="Mid Tier Companies",
                expected_difficulty="Easy",
                expected_rating=1000,
                round_number=1,
            )

    async def test_generation_falls_back_after_invalid_problem(self):
        payload = {"problems": [_valid_problem("A"), _valid_problem("B")]}
        calls = {"count": 0}

        async def fake_normalize(problem, **kwargs):
            calls["count"] += 1
            if kwargs.get("generated_source") != "fallback" and calls["count"] == 1:
                raise ValueError("bad reference")
            return {
                "title": problem["title"],
                "statement": problem.get("statement", ""),
                "generated_source": kwargs.get("generated_source", "ai"),
            }

        from unittest.mock import AsyncMock
        with patch.object(
            technical_mode, "complete_json_async", new_callable=AsyncMock, return_value=payload
        ), patch.object(technical_mode, "_normalize_generated_problem", side_effect=fake_normalize):
            result = await technical_mode._generate_ai_problem_set("mid_tier", "interview-1", "user-1")

        self.assertEqual(len(result), 2)
        self.assertTrue(all(problem["generated_source"] == "fallback" for problem in result))
        self.assertGreaterEqual(calls["count"], 3)

    async def test_generation_falls_back_when_llm_fails(self):
        from unittest.mock import AsyncMock

        context = {
            "job_title": "AI Backend Engineer",
            "target_skills": ["FastAPI", "PostgreSQL"],
            "personalization_anchors": {
                "projects": [{"name": "Resume Parser"}],
                "skills": ["Python", "LLMs"],
            },
        }

        with patch.object(technical_mode, "complete_json_async", new_callable=AsyncMock, side_effect=RuntimeError("llm unavailable")):
            result = await technical_mode._generate_ai_problem_set("mid_tier", "interview-1", "user-1", context)

        self.assertEqual(len(result), 2)
        self.assertTrue(all(problem["generated_source"] == "fallback" for problem in result))
        self.assertIn("AI Backend Engineer", result[0]["statement"])
        self.assertIn("Resume Parser", result[0]["statement"])

    async def test_execute_code_delegates_to_the_local_os_sandbox(self):
        expected = {"exit_code": 0, "stdout": "ok\n", "stderr": "", "runtime_ms": 1, "executor": "macos-seatbelt"}
        with patch("local_execution.execute_local", new_callable=AsyncMock, return_value=expected) as execute_local:
            result = await technical_mode._execute_code("python", "print('ok')", "")

        execute_local.assert_awaited_once_with("python", "print('ok')", "")
        self.assertEqual(result["executor"], "macos-seatbelt")

    def test_execution_output_cap_includes_truncation_marker(self):
        stdout, stderr, truncated = technical_mode._bound_execution_output(
            "x" * 100_000,
            "candidate stderr",
        )

        self.assertTrue(truncated)
        self.assertTrue(stderr.endswith("[output truncated at 64 KB]"))
        self.assertLessEqual(
            len((stdout + stderr).encode("utf-8")),
            technical_mode.MAX_EXECUTION_OUTPUT_BYTES,
        )

    def test_executor_truncation_flag_restores_missing_marker(self):
        stdout, stderr, truncated = technical_mode._bound_execution_output(
            "partial output",
            "",
            executor_truncated=True,
        )

        self.assertTrue(truncated)
        self.assertEqual(stdout, "partial output")
        self.assertTrue(stderr.endswith("[output truncated at 64 KB]"))

    async def test_execute_code_has_no_hosted_executor_fallback(self):
        self.assertFalse(hasattr(technical_mode, "_execute_judge0"))
        self.assertFalse(hasattr(technical_mode, "_execute_piston"))
        self.assertFalse(hasattr(technical_mode.settings, "JUDGE0_API_URL"))
        self.assertFalse(hasattr(technical_mode.settings, "PISTON_API_URL"))

    async def test_unavailable_os_sandbox_returns_a_fail_closed_result(self):
        expected = {
            "exit_code": -1,
            "stdout": "",
            "stderr": "Local runtime is unavailable: no supported sandbox",
            "executor": "unavailable",
        }
        with patch("local_execution.execute_local", new_callable=AsyncMock, return_value=expected):
            result = await technical_mode._execute_code("python", "print('must not run')", "")

        self.assertEqual(result["exit_code"], -1)
        self.assertEqual(result["executor"], "unavailable")
        self.assertIn("no supported sandbox", result["stderr"])

    async def test_full_submit_masks_hidden_cases(self):
        cases = [
            {"stdin": "1\n", "expected": "1\n", "visible": True},
            {"stdin": "2\n", "expected": "2\n", "visible": True},
            {"stdin": "3\n", "expected": "3\n", "visible": True},
            {"stdin": "99\n", "expected": "99\n", "visible": False},
        ]
        job = {
            "job_id": "run-1",
            "round_id": "round-1",
            "interview_id": "interview-1",
            "user_id": "user-1",
            "action": "submit",
            "suite": "full",
            "language": "python",
            "source_hash": "hash",
            "source_code_encrypted": technical_mode.encrypt_data("print(input())").encode("utf-8"),
            "cases_encrypted": technical_mode.encrypt_data(technical_mode.json.dumps(cases)).encode("utf-8"),
            "initial_result": {"visible_total": 3, "hidden_total": 1, "total_count": 4, "locked": True},
        }

        async def fake_execute(language, code, stdin):
            return {"exit_code": 0, "stdout": stdin, "stderr": "", "runtime_ms": 1, "memory_kb": 10}

        with patch.object(technical_worker, "_execute_code", side_effect=fake_execute), patch.object(
            technical_worker, "refresh_lease", return_value=True
        ):
            result = await technical_worker.execute_claimed_job(job, "worker-1")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["pass_count"], 4)
        self.assertFalse(result["cases"][0]["hidden"])
        self.assertIn("expected", result["cases"][0])
        self.assertTrue(result["cases"][3]["hidden"])
        self.assertNotIn("stdin", result["cases"][3])
        self.assertNotIn("expected", result["cases"][3])


if __name__ == "__main__":
    unittest.main()
