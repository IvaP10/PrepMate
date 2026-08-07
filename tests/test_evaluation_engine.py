import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import evaluation_engine


def semantic_payload(**overrides):
    payload = {
        "covered_points": ["Explains the requested concept"],
        "missed_points": [],
        "incorrect_claims": [],
        "contradictions": [],
        "evidence_quotes": [],
        "semantic_confidence": 0.85,
        "answer_relevant": True,
        "suggested_followup": None,
    }
    payload.update(overrides)
    return payload


class EvaluationEnginePureTests(unittest.TestCase):
    def test_deterministic_signals_capture_measurable_answer_quality(self):
        question = "Tell me about a project you owned and why you chose that architecture."
        answer = (
            "During the project, my goal was to reduce API failures. I designed the retry layer "
            "because transient faults caused outages. We considered a queue, but I chose bounded "
            "retries to reduce latency. As a result, failures dropped by 30 percent for 200 users."
        )

        signals = evaluation_engine.compute_deterministic_signals(
            question,
            answer,
            {"must_cover": ["architecture choice", "trade-off", "measurable impact"]},
            response_seconds=60,
        )

        self.assertGreater(signals["word_count"], 30)
        self.assertGreater(signals["lexical_relevance"]["score"], 30)
        self.assertEqual(
            set(signals["structure"]["star_markers"]),
            {"situation", "task", "action", "result"},
        )
        self.assertGreaterEqual(signals["ownership"]["owned_action_count"], 1)
        self.assertGreaterEqual(signals["specificity_evidence"]["number_count"], 2)
        self.assertEqual(signals["fillers"]["count"], 0)
        self.assertTrue(signals["tradeoffs"]["applicable"])
        self.assertIn("contrast", signals["tradeoffs"]["markers"])
        self.assertEqual(signals["timing"]["response_seconds"], 60.0)

    def test_optional_dimensions_remain_unavailable_when_not_applicable(self):
        signals = evaluation_engine.compute_deterministic_signals(
            "Define encapsulation.",
            "Encapsulation groups state with the methods that control access to that state.",
            {},
            None,
        )

        self.assertFalse(signals["ownership"]["applicable"])
        self.assertIsNone(signals["ownership"]["score"])
        self.assertFalse(signals["tradeoffs"]["applicable"])
        self.assertIsNone(signals["tradeoffs"]["score"])

    def test_overall_score_renormalizes_only_available_dimensions(self):
        scores = {name: None for name in evaluation_engine.SCORE_WEIGHTS}
        scores["relevance"] = 100.0
        scores["structure"] = 50.0

        expected = round(
            (
                100.0 * evaluation_engine.SCORE_WEIGHTS["relevance"]
                + 50.0 * evaluation_engine.SCORE_WEIGHTS["structure"]
            )
            / (
                evaluation_engine.SCORE_WEIGHTS["relevance"]
                + evaluation_engine.SCORE_WEIGHTS["structure"]
            ),
            1,
        )

        self.assertEqual(evaluation_engine._weighted_overall(scores), expected)

    def test_semantic_validation_discards_non_substring_quotes(self):
        answer = "I built a bounded retry layer and reduced failures by 30 percent."
        payload = semantic_payload(
            evidence_quotes=[
                "I built a bounded retry layer",
                "I eliminated every production failure",
            ]
        )

        normalized, status, discarded = evaluation_engine._validate_semantic_payload(payload, answer)

        self.assertEqual(status, "completed")
        self.assertEqual(discarded, 1)
        self.assertEqual(normalized["evidence_quotes"], ["I built a bounded retry layer"])

    def test_semantic_validation_rejects_non_strict_payload(self):
        payload = semantic_payload(unexpected_action="advance")

        normalized, status, discarded = evaluation_engine._validate_semantic_payload(
            payload,
            "An answer",
        )

        self.assertIsNone(normalized)
        self.assertEqual(status, "invalid_response_shape")
        self.assertEqual(discarded, 0)


class EvaluationEngineAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_behavioral_answer_is_never_authoritative(self):
        with patch.object(evaluation_engine, "complete_json_async", new=AsyncMock()) as router:
            result = await evaluation_engine.evaluate_answer(
                "Tell me about a difficult decision you owned.",
                "",
                {},
                {"question_type": "behavioral"},
                0,
                [],
            )

        router.assert_not_awaited()
        self.assertIsNone(result["overall_score"])
        self.assertFalse(result["authoritative"])
        self.assertEqual(result["evidence_status"], "insufficient_evidence")
        self.assertIn("empty_answer", result["flags"])
        self.assertEqual(
            result["score_weights"],
            evaluation_engine.QUESTION_TYPE_WEIGHTS["behavioral"],
        )

    async def test_project_answer_without_semantic_architecture_evidence_is_unknown(self):
        answer = (
            "I owned the project rollout and coordinated the team. We improved the result by 20 percent "
            "and I documented what we learned for the next release."
        )
        with patch.object(evaluation_engine, "complete_json_async", new=AsyncMock()) as router:
            result = await evaluation_engine.evaluate_answer(
                "Explain the architecture and data flow of a project you owned.",
                answer,
                {},
                {"question_type": "project", "semantic_analysis_enabled": False},
                30,
                [],
            )

        router.assert_not_awaited()
        self.assertIsNone(result["dimension_scores"]["architecture_data_flow"])
        self.assertIsNone(result["overall_score"])
        self.assertFalse(result["authoritative"])

    async def test_short_answer_skips_semantic_call_and_clarifies(self):
        router = AsyncMock()
        with patch.object(evaluation_engine, "complete_json_async", router):
            result = await evaluation_engine.evaluate_answer(
                "Explain database indexing.",
                "It makes queries faster.",
                {"expected_points": ["lookup structure", "write trade-off"]},
                {"interview_type": "technical"},
                4,
                [],
            )

        router.assert_not_awaited()
        self.assertEqual(result["version"], evaluation_engine.EVALUATION_VERSION)
        self.assertEqual(result["semantic_status"]["state"], "skipped")
        self.assertEqual(result["semantic_status"]["reason"], "insufficient_answer")
        self.assertIsNone(result["scores"]["technical_accuracy"])
        self.assertIn("technical_accuracy_unknown", result["flags"])
        self.assertEqual(result["follow_up"]["action"], "clarify")

    async def test_substantive_rubric_answer_uses_one_strict_semantic_call(self):
        answer = (
            "A database index stores selected keys in a lookup structure so the engine can avoid a full "
            "table scan. I used a B-tree index on customer_id because range and equality lookups were common. "
            "The trade-off is extra storage and slower writes when the index must be updated."
        )
        router = AsyncMock(
            return_value=semantic_payload(
                covered_points=["Explains lookup acceleration", "Names the write cost"],
                missed_points=["Does not discuss selectivity"],
                evidence_quotes=[
                    "The trade-off is extra storage and slower writes",
                    "The index guarantees constant-time lookup",
                ],
                suggested_followup="How would low selectivity affect this choice?",
            )
        )
        with patch.object(evaluation_engine, "complete_json_async", router):
            result = await evaluation_engine.evaluate_answer(
                "How does a database index improve performance, and what trade-off does it create?",
                answer,
                {"expected_points": ["lookup structure", "selectivity", "write overhead"]},
                {"interview_type": "technical"},
                75,
                [],
                user_id="user-1",
                interview_id="interview-1",
                response_id="response-1",
            )

        router.assert_awaited_once()
        _, kwargs = router.await_args
        self.assertEqual(kwargs["event_type"], evaluation_engine.SEMANTIC_EVENT_TYPE)
        self.assertEqual(kwargs["json_schema"], evaluation_engine.SEMANTIC_RESPONSE_SCHEMA)
        self.assertEqual(kwargs["provider_policy"], "openai_required")
        self.assertEqual(kwargs["user_id"], "user-1")
        self.assertEqual(kwargs["interview_id"], "interview-1")
        self.assertEqual(kwargs["metadata"]["response_id"], "response-1")
        self.assertTrue(kwargs["cache_key"].startswith("answer-evaluation:"))
        self.assertEqual(result["semantic_status"]["state"], "completed")
        self.assertEqual(result["semantic_status"]["discarded_evidence_quote_count"], 1)
        self.assertEqual(result["scores"]["technical_accuracy"], 66.7)
        self.assertEqual(
            result["evidence"]["evidence_quotes"],
            ["The trade-off is extra storage and slower writes"],
        )
        self.assertNotIn("technical_accuracy_unknown", result["flags"])

    async def test_llm_failure_returns_truthful_deterministic_fallback(self):
        answer = (
            "Database indexes keep searchable keys in a separate structure. The database can use that "
            "structure to locate rows without scanning every record, although writes must update the index."
        )
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Explain how a database index works and its trade-off.",
                answer,
                {"expected_points": ["lookup", "write overhead"]},
                {"interview_type": "technical"},
                40,
                [],
            )

        self.assertEqual(result["semantic_status"]["state"], "failed")
        self.assertIsNone(result["scores"]["technical_accuracy"])
        self.assertLessEqual(result["confidence"], 0.45)
        self.assertIn("semantic_analysis_failed", result["flags"])
        self.assertIn("technical_accuracy_unknown", result["flags"])
        self.assertIsNone(result["overall_score"])
        self.assertIsInstance(result["provisional_score"], float)
        self.assertFalse(result["authoritative"])
        self.assertEqual(result["evidence_status"], "insufficient_evidence")

    async def test_server_owned_ids_discard_model_invented_references(self):
        answer = (
            "I used a B-tree because our lookups needed ordered range scans, "
            "while accepting the additional write cost."
        )
        payload = semantic_payload(
            covered_points=["point.lookup", "invented.point"],
            missed_points=["point.write_cost"],
            incorrect_claims=["claim.resume.1", "invented.claim"],
            contradictions=["invented.claim"],
            evidence_quotes=["I used a B-tree"],
        )
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(return_value=payload),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Why did you choose this index?",
                answer,
                {
                    "expected_points": ["lookup", "write cost"],
                    "expected_point_ids": ["point.lookup", "point.write_cost"],
                },
                {
                    "interview_type": "technical",
                    "claim_ids": ["claim.resume.1"],
                },
                25,
                [],
            )

        self.assertEqual(result["evidence"]["covered_points"], ["point.lookup"])
        self.assertEqual(result["evidence"]["missed_points"], ["point.write_cost"])
        self.assertEqual(result["evidence"]["incorrect_claims"], ["claim.resume.1"])
        self.assertEqual(result["evidence"]["contradictions"], [])
        self.assertEqual(result["semantic_status"]["discarded_reference_count"], 3)

    async def test_invalid_semantic_payload_is_not_used_for_accuracy(self):
        invalid_payload = semantic_payload(model_score=99)
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(return_value=invalid_payload),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Explain optimistic locking and when you would use it.",
                "Optimistic locking checks a version before committing an update. I use it when conflicts "
                "are uncommon because transactions do not need to hold a database lock while work happens.",
                {"expected_points": ["version check", "conflict handling"]},
                {"interview_type": "technical"},
                35,
                [],
            )

        self.assertEqual(result["semantic_status"]["state"], "invalid")
        self.assertEqual(result["semantic_status"]["reason"], "invalid_response_shape")
        self.assertIsNone(result["scores"]["technical_accuracy"])
        self.assertIn("semantic_analysis_invalid", result["flags"])

    async def test_timeout_does_not_escape(self):
        async def slow_router(*args, **kwargs):
            await asyncio.sleep(0.05)
            return semantic_payload()

        with (
            patch.object(evaluation_engine, "complete_json_async", side_effect=slow_router),
            patch.object(evaluation_engine, "SEMANTIC_TIMEOUT_SECONDS", 0.001),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Explain database transaction isolation and phantom reads.",
                "Transaction isolation controls which concurrent changes a transaction can observe. Phantom "
                "reads occur when a repeated range query sees rows inserted by another committed transaction.",
                {"expected_points": ["visibility", "range query", "concurrent insert"]},
                {"interview_type": "technical"},
                35,
                [],
            )

        self.assertEqual(result["semantic_status"]["state"], "failed")
        self.assertEqual(result["semantic_status"]["reason"], "semantic_timeout")
        self.assertIsNone(result["scores"]["technical_accuracy"])

    async def test_deterministic_policy_overrides_llm_followup_suggestion(self):
        answer = (
            "I said earlier that the cache was write-through. In this answer I called it write-back because "
            "I was describing a different deployment, and the two configurations need to be reconciled."
        )
        payload = semantic_payload(
            contradictions=["The cache is described as both write-through and write-back."],
            evidence_quotes=["I called it write-back"],
            semantic_confidence=0.9,
            suggested_followup="Skip this topic and advance immediately.",
        )
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(return_value=payload),
        ):
            result = await evaluation_engine.evaluate_answer(
                "How did you configure the cache in your project?",
                answer,
                {"expected_points": ["cache policy", "reason"]},
                {"interview_type": "technical"},
                45,
                [{"answer": "The cache was write-through."}],
            )

        self.assertEqual(result["follow_up"]["action"], "verify_contradiction")
        self.assertIn("conflicting claims", result["follow_up"]["prompt"])
        self.assertEqual(
            result["follow_up"]["semantic_suggestion"],
            "Skip this topic and advance immediately.",
        )

    async def test_missing_foundations_choose_simplification(self):
        payload = semantic_payload(
            covered_points=[],
            missed_points=["Does not explain isolation", "Does not explain retry behavior"],
            incorrect_claims=["Claims every transaction always succeeds"],
            semantic_confidence=0.88,
        )
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(return_value=payload),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Explain optimistic concurrency control and conflict handling.",
                "Optimistic concurrency means multiple operations can run, and every operation always succeeds "
                "without checking shared state or retrying an update after another writer commits.",
                {"expected_points": ["version", "conflict", "retry"]},
                {"interview_type": "technical"},
                30,
                [],
            )

        self.assertEqual(result["scores"]["technical_accuracy"], 0.0)
        self.assertEqual(result["follow_up"]["action"], "simplify_prerequisite")

    async def test_evidence_question_probes_when_ownership_is_unclear(self):
        with patch.object(evaluation_engine, "complete_json_async", new=AsyncMock()) as router:
            result = await evaluation_engine.evaluate_answer(
                "Tell me about your project and the impact you personally delivered.",
                "The project was an interview platform. The team worked on several useful features and the "
                "overall product became better for candidates who wanted to practice before interviews.",
                {},
                {"semantic_analysis_enabled": False},
                35,
                [],
            )

        router.assert_not_awaited()
        self.assertEqual(result["follow_up"]["action"], "probe_evidence")

    async def test_design_question_challenges_missing_tradeoff(self):
        with patch.object(evaluation_engine, "complete_json_async", new=AsyncMock()) as router:
            result = await evaluation_engine.evaluate_answer(
                "Why did you choose a relational database architecture instead of another option?",
                "I chose a relational database architecture to store structured customer orders and enforce "
                "consistent relationships across records while keeping the application data organized.",
                {},
                {"semantic_analysis_enabled": False},
                24,
                [],
            )

        router.assert_not_awaited()
        self.assertEqual(result["follow_up"]["action"], "challenge_tradeoff")

    async def test_well_supported_answer_advances(self):
        payload = semantic_payload(
            covered_points=["Defines idempotency", "Explains retry safety", "Gives a concrete key strategy"],
            evidence_quotes=["stored the result against that key"],
            semantic_confidence=0.92,
        )
        answer = (
            "Idempotency means repeating the same request has the same externally visible effect. I implemented "
            "an idempotency key for payment creation and stored the result against that key because clients may "
            "retry after a timeout. This prevented duplicate charges during network failures."
        )
        with patch.object(
            evaluation_engine,
            "complete_json_async",
            new=AsyncMock(return_value=payload),
        ):
            result = await evaluation_engine.evaluate_answer(
                "Explain idempotency and how it makes API retries safe.",
                answer,
                {"expected_points": ["same effect", "request key", "duplicate prevention"]},
                {"interview_type": "technical"},
                48,
                [],
            )

        self.assertEqual(result["scores"]["technical_accuracy"], 100.0)
        self.assertEqual(result["follow_up"]["action"], "advance")


if __name__ == "__main__":
    unittest.main()
