import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import technical_mode
import technical_worker


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


class TechnicalModePureTests(unittest.TestCase):
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

    def test_judge0_verdict_mapping(self):
        self.assertEqual(technical_mode._judge0_verdict({"status_id": 3}), "Accepted")
        self.assertEqual(technical_mode._judge0_verdict({"status_id": 4}), "Wrong Answer")
        self.assertEqual(technical_mode._judge0_verdict({"status_id": 5}), "TLE")
        self.assertEqual(technical_mode._judge0_verdict({"status_id": 6}), "Runtime Error")

    def test_case_verdict_checks_output_after_judge0_accepts(self):
        result = {"status_id": 3, "stdout": "7\n"}

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
        with patch.object(technical_mode.settings, "ENVIRONMENT", "production"), patch.object(
            technical_mode.settings, "JUDGE0_API_URL", ""
        ), patch.object(technical_mode.settings, "PISTON_API_URL", ""):
            status_payload = technical_mode._executor_status_payload()

        self.assertEqual(status_payload["executor"], "unavailable")
        self.assertEqual(status_payload["executor_label"], "Unavailable")
        self.assertFalse(status_payload["executor_available"])
        self.assertEqual(status_payload["executor_status"], "unavailable")

    def test_public_piston_endpoint_is_rejected(self):
        self.assertFalse(technical_mode._is_private_piston_url("https://emkc.org/api/v2/piston"))
        self.assertFalse(technical_mode._is_private_piston_url("https://piston.example.com"))
        self.assertTrue(technical_mode._is_private_piston_url("http://piston:2000"))
        self.assertTrue(technical_mode._is_private_piston_url("http://10.0.0.8:2000"))

    def test_durable_enqueue_encrypts_source_and_cases(self):
        class Cursor:
            def __init__(self):
                self.fetchone_values = [
                    None,
                    ("active", "mock", 1, None),
                    (0,),
                    ("job-1", "round-1", "submit", "full", "python", "queued", {"status": "queued"}, None, 0),
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

    def test_worker_claim_uses_skip_locked_and_lease(self):
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

        claim_sql = next(query for query, _ in connection.cursor_value.queries if "SKIP LOCKED" in query)
        self.assertIn("FOR UPDATE SKIP LOCKED", claim_sql)
        self.assertIn("lease_expires_at", claim_sql)
        self.assertEqual(job["job_id"], "job-1")


class TechnicalModeAsyncTests(unittest.IsolatedAsyncioTestCase):
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
        with patch.object(technical_mode, "_load_active_problem_bank", new_callable=AsyncMock, return_value=[]), patch.object(
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
        with patch.object(technical_mode.settings, "JUDGE0_API_URL", "https://judge0.example"), patch.object(
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

    async def test_execute_code_uses_piston_when_judge0_missing(self):
        from unittest.mock import AsyncMock

        expected = {"status_id": 3, "stdout": "ok\n", "stderr": "", "runtime_ms": 1, "memory_kb": 0, "executor": "isolated_sandbox"}
        with patch.object(technical_mode.settings, "JUDGE0_API_URL", ""), patch.object(
            technical_mode.settings, "PISTON_API_URL", "http://piston:2000"
        ), patch.object(technical_mode, "_execute_piston", new_callable=AsyncMock, return_value=expected) as piston:
            result = await technical_mode._execute_code("python", "print('ok')", "")

        piston.assert_awaited_once()
        self.assertEqual(result["executor"], "isolated_sandbox")

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

    async def test_execute_code_ignores_judge0_and_uses_private_piston(self):
        from unittest.mock import AsyncMock

        expected = {"status_id": 3, "stdout": "ok\n", "stderr": "", "runtime_ms": 1, "memory_kb": 0, "executor": "isolated_sandbox"}
        with patch.object(technical_mode.settings, "JUDGE0_API_URL", "https://judge0.example"), patch.object(
            technical_mode.settings, "PISTON_API_URL", "http://piston:2000"
        ), patch.object(technical_mode, "_execute_piston", new_callable=AsyncMock, return_value=expected
        ) as piston:
            result = await technical_mode._execute_code("python", "print('ok')", "")

        self.assertFalse(hasattr(technical_mode, "_execute_judge0"))
        piston.assert_awaited_once()
        self.assertEqual(result["executor"], "isolated_sandbox")

    async def test_production_never_falls_back_to_local_execution(self):
        with patch.object(technical_mode.settings, "ENVIRONMENT", "production"), patch.object(
            technical_mode.settings, "JUDGE0_API_URL", ""
        ), patch.object(technical_mode.settings, "PISTON_API_URL", "http://piston:2000"), patch.object(
            technical_mode, "_execute_piston", new_callable=AsyncMock, side_effect=RuntimeError("offline")
        ):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode._execute_code("python", "print('ok')", "")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("temporarily unavailable", str(raised.exception.detail))
        self.assertFalse(hasattr(technical_mode, "_execute_locally"))

    async def test_unconfigured_production_executor_returns_clear_unavailable_error(self):
        with patch.object(technical_mode.settings, "ENVIRONMENT", "production"), patch.object(
            technical_mode.settings, "JUDGE0_API_URL", ""
        ), patch.object(technical_mode.settings, "PISTON_API_URL", ""):
            with self.assertRaises(technical_mode.HTTPException) as raised:
                await technical_mode._execute_code("python", "print('ok')", "")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("backend host execution are disabled", str(raised.exception.detail))
        self.assertFalse(hasattr(technical_mode, "_execute_locally"))

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
            return {"status_id": 3, "stdout": stdin, "stderr": "", "runtime_ms": 1, "memory_kb": 10}

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
