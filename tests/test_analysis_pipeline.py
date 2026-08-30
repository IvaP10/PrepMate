import asyncio
import inspect
import json
import os
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import analysis_pipeline
from analysis_pipeline import summarize_self_review_signals, _turn_observations, _valid_candidate_report


class AnalysisPipelinePureTests(unittest.TestCase):
    def test_failed_final_case_becomes_an_improve_topic_even_at_eighty_percent(self):
        weak_topics = analysis_pipeline._technical_weak_topics([
            {
                "round_id": "round-1",
                "title": "First unique character",
                "visible_passed": 2,
                "visible_total": 2,
                "hidden_passed": 2,
                "hidden_total": 3,
            },
        ])

        self.assertEqual(len(weak_topics), 1)
        self.assertEqual(weak_topics[0]["pass_rate"], 80.0)
        self.assertEqual(weak_topics[0]["round_ids"], ["round-1"])

    def test_technical_reasoning_is_recovered_for_the_report_transcript(self):
        with patch.object(
            analysis_pipeline,
            "_decrypt_storage_text",
            return_value=json.dumps({"stage": "explanation", "content": "I handled the empty-input edge case."}),
        ):
            entry = analysis_pipeline._technical_reasoning_transcript_entry(
                "workflow_explanation",
                b"encrypted",
            )

        self.assertEqual(entry, {
            "role": "candidate",
            "text": "I handled the empty-input edge case.",
            "label": "Final explanation",
        })

    def test_untouched_starter_snapshot_is_not_candidate_draft_evidence(self):
        starter = "def solve():\n    pass\n"

        self.assertFalse(
            analysis_pipeline._candidate_authored_technical_draft(
                starter,
                starter,
                {"event": "save_draft"},
            )
        )
        self.assertFalse(
            analysis_pipeline._candidate_authored_technical_draft(
                "print('edited')\n",
                starter,
                {"candidate_edited": False},
            )
        )
        self.assertTrue(
            analysis_pipeline._candidate_authored_technical_draft(
                "print('edited')\n",
                starter,
                {"candidate_edited": True},
            )
        )

    def test_analysis_job_identity_is_scoped_to_the_interview(self):
        first = analysis_pipeline._analysis_job_idempotency_key(
            "interview-1",
            "same-evidence",
        )
        second = analysis_pipeline._analysis_job_idempotency_key(
            "interview-2",
            "same-evidence",
        )

        self.assertNotEqual(first, second)
        self.assertIn("interview-1", first)

    def test_report_pipeline_uses_explicit_production_stages(self):
        self.assertEqual(analysis_pipeline.ANALYSIS_STAGES, (
            "evidence_load",
            "transcript_analysis",
            "technical_analysis",
            "self_review_summary",
            "deterministic_report",
            "report_validation",
        ))
        self.assertEqual(
            analysis_pipeline.ANALYSIS_EXECUTION_STAGES,
            ("assessment_completion", *analysis_pipeline.ANALYSIS_STAGES),
        )

    def test_production_runner_visits_assessment_preflight_and_refreshes_cached_repair(self):
        async def exercise(cached_assessment: bool):
            executed_stages = []
            progress_updates = []

            async def fake_execute(query, params=None, **kwargs):
                if "SELECT evidence_hash, manifest_id FROM AnalysisJobs" in query:
                    return ("sealed-evidence", "manifest-1")
                if "UPDATE AnalysisJobs SET progress" in query:
                    progress_updates.append((params[0], params[1]))
                return None

            async def fake_load_completed(_job_id, stage, _evidence_hash):
                if cached_assessment and stage == "assessment_completion":
                    return {"missing_count": 1, "repaired_count": 1}
                return None

            async def fake_run_stage(stage, interview_id, _user_id, _outputs):
                executed_stages.append(stage)
                if stage == "assessment_completion":
                    return {"missing_count": 1, "repaired_count": 1}
                return {
                    "interview_id": interview_id,
                    "report_type": "behavioral",
                    "overall_score": None,
                    "summary": "Recorded evidence was insufficient for a score.",
                    "evidence_status": {"status": "insufficient_evidence"},
                    "ai_enhanced": False,
                }

            with patch.object(
                analysis_pipeline,
                "ANALYSIS_EXECUTION_STAGES",
                ("assessment_completion", "complete"),
            ), patch.object(
                analysis_pipeline,
                "ANALYSIS_STAGES",
                ("complete",),
            ), patch.object(
                analysis_pipeline,
                "async_execute",
                new=AsyncMock(side_effect=fake_execute),
            ), patch.object(
                analysis_pipeline,
                "_load_completed_stage",
                new=AsyncMock(side_effect=fake_load_completed),
            ), patch.object(
                analysis_pipeline,
                "_run_stage",
                new=AsyncMock(side_effect=fake_run_stage),
            ), patch.object(
                analysis_pipeline,
                "_renew_analysis_lease",
                new=AsyncMock(),
            ), patch.object(
                analysis_pipeline,
                "_refresh_analysis_job_manifest",
                new=AsyncMock(return_value=("manifest-2", "refreshed-evidence")),
            ) as refresh_manifest, patch.object(
                analysis_pipeline,
                "_validate_report_for_publication",
                new=AsyncMock(),
            ), patch.object(
                analysis_pipeline,
                "_stage_canonical_performance",
                new=AsyncMock(return_value={
                    "analysis_id": "analysis-1",
                    "mode": "mock",
                    "observations": [],
                }),
            ), patch.object(
                analysis_pipeline,
                "_stage_candidate_report_artifact",
                new=AsyncMock(return_value={
                    "artifact_id": "artifact-1",
                    "publication_key": "report:analysis-1:candidate",
                }),
            ), patch.object(
                analysis_pipeline,
                "_publish_staged_report",
                new=AsyncMock(),
            ), patch.object(
                analysis_pipeline,
                "_schedule_media_cleanup",
                new=AsyncMock(),
            ), patch.object(
                analysis_pipeline,
                "_encrypted_bytes",
                return_value=b"encrypted",
            ):
                await analysis_pipeline.run_analysis_job(
                    "job-1",
                    worker_id="worker-1",
                    claimed_job=("job-1", "interview-1", "user-1"),
                )

            return executed_stages, progress_updates, refresh_manifest.await_count

        executed, progress, refresh_count = asyncio.run(exercise(False))
        self.assertEqual(executed, ["assessment_completion", "complete"])
        self.assertEqual(progress, [(50, "assessment_completion"), (100, "complete")])
        self.assertEqual(refresh_count, 1)

        executed, progress, refresh_count = asyncio.run(exercise(True))
        self.assertEqual(executed, ["complete"])
        self.assertEqual(progress, [(50, "assessment_completion"), (100, "complete")])
        self.assertEqual(refresh_count, 1)

    def test_stage_provenance_distinguishes_deterministic_and_openai_outputs(self):
        deterministic = analysis_pipeline._stage_provenance("deterministic_report", {"ai_enhanced": False}, "input-1")
        enhanced = analysis_pipeline._stage_provenance("report_generation", {"ai_enhanced": True}, "input-2")

        self.assertEqual(deterministic["engine"], "deterministic_inter_pipeline")
        self.assertIsNone(deterministic["model"])
        self.assertEqual(enhanced["engine"], "local_provider_narrative_enhancement")
        self.assertEqual(enhanced["prompt_version"], "report-narrative-v1")

    def test_every_non_null_report_score_gets_evidence_provenance(self):
        report = {
            "overall_score": 78,
            "dimension_scores": {"communication": 80, "code_quality": None},
            "findings": [{"evidence_ids": ["response-1"]}],
        }

        provenance = analysis_pipeline._score_provenance(report, "evidence-hash")

        self.assertEqual(set(provenance), {"overall_score", "dimension_scores.communication"})
        self.assertEqual(provenance["overall_score"]["evidence_ids"], ["response-1"])
        self.assertEqual(provenance["dimension_scores.communication"]["evidence_hash"], "evidence-hash")

    def test_hidden_detail_leak_detector_allows_aggregates_but_rejects_case_payloads(self):
        self.assertFalse(analysis_pipeline._contains_hidden_detail_leak({
            "hidden_passed": 4,
            "hidden_total": 5,
            "hidden_details": None,
        }))
        self.assertTrue(analysis_pipeline._contains_hidden_detail_leak({
            "hidden_cases": [{"stdin": "secret", "expected": "secret"}],
        }))
        self.assertTrue(analysis_pipeline._contains_hidden_detail_leak({
            "technical": {"all_submissions": [{"result_json": {"cases": []}}]},
        }))

    def test_manifest_hash_normalization_is_stable_for_encrypted_bytes(self):
        first = analysis_pipeline._manifest_hashable((memoryview(b"encrypted-answer"), {"score": 80}))
        second = analysis_pipeline._manifest_hashable((memoryview(b"encrypted-answer"), {"score": 80}))

        self.assertEqual(first, second)
        self.assertNotIn("encrypted-answer", str(first))

    def test_candidate_report_must_be_valid_and_bound_to_the_session(self):
        valid = {
            "interview_id": "interview-1",
            "report_type": "behavioral",
            "evidence_status": {"status": "sufficient"},
            "overall_score": 78,
        }

        self.assertTrue(_valid_candidate_report(valid, "interview-1"))
        self.assertFalse(_valid_candidate_report({"error": "stage_failed"}, "interview-1"))
        self.assertFalse(_valid_candidate_report({**valid, "interview_id": "interview-2"}, "interview-1"))
        self.assertFalse(_valid_candidate_report({**valid, "evidence_status": None}, "interview-1"))

    def test_technical_provenance_accepts_canonical_and_legacy_round_keys(self):
        self.assertEqual(analysis_pipeline._technical_round_id({"round_id": "round-1"}), "round-1")
        self.assertEqual(analysis_pipeline._technical_round_id({"technical_round_id": "round-2"}), "round-2")
        self.assertIsNone(analysis_pipeline._technical_round_id({}))

    def test_evidence_manifest_seals_frozen_technical_round_identity(self):
        source = inspect.getsource(analysis_pipeline._seal_evidence_manifest)

        self.assertIn('"technical_round", "technical-round-v1"', source)
        self.assertIn("FROM TechnicalInterviewRounds", source)

    def test_technical_stage_safe_payload_never_persists_decrypted_source(self):
        safe = analysis_pipeline._safe_stage_payload(
            "technical_code",
            {
                "round_count": 1,
                "test_matrix": [{
                    "round_id": "round-1",
                    "source_code": "private code",
                    "source_excerpt": "private excerpt",
                    "result_json": {"cases": ["private"]},
                    "evidence_state": "final_submission",
                }],
                "source_code": "private code",
            },
        )

        assert safe["test_matrix"] == [{"round_id": "round-1", "evidence_state": "final_submission"}]
        assert "source_code" not in safe

    def test_candidate_report_payload_keeps_only_safe_finding_fields(self):
        safe = analysis_pipeline._safe_report_payload({
            "summary": "Evidence-backed result.",
            "findings": [{
                "finding_key": "ownership",
                "title": "Ownership",
                "what_happened": "The answer named the candidate's contribution.",
                "why_matters": "Ownership is part of the rubric.",
                "evidence_ids": ["response-1"],
                "response": "private transcript",
                "hidden_tests": ["private test"],
            }],
        })

        assert safe["findings"] == [{
            "finding_key": "ownership",
            "title": "Ownership",
            "what_happened": "The answer named the candidate's contribution.",
            "why_matters": "Ownership is part of the rubric.",
            "evidence_ids": ["response-1"],
        }]

    def test_interview_and_technical_turns_do_not_cross_contaminate_weaknesses(self):
        turn = {
            "response_id": "response-1",
            "question": "Explain the Python decision you owned.",
            "topic": "Python ownership",
            "question_type": "technical_concept",
            "taxonomy_keys": ["technical:python"],
            "overall_score": 62,
            "provenance": {},
        }

        interview_observations = _turn_observations([turn], "mock")
        technical_observations = _turn_observations([turn], "technical")

        self.assertEqual(interview_observations[0]["skill_key"], "interview:technical-python")
        self.assertEqual(interview_observations[0]["source_kind"], "interview_response")
        self.assertEqual(interview_observations[0]["question"], "Explain the Python decision you owned.")
        self.assertEqual(technical_observations, [])

    def test_openai_report_fallback_is_published_as_partial(self):
        report = {
            "overall_score": 78,
            "ai_enhanced": False,
            "ai_fallback_reason": "report_generation_llm_failed",
        }

        self.assertTrue(
            analysis_pipeline._report_has_noncritical_degradation(
                report,
                {"semantic_enhancement": report},
            )
        )

    def test_no_candidate_evidence_is_ungradable_not_partial(self):
        report = {
            "overall_score": None,
            "ai_enhanced": False,
            "ai_fallback_reason": "no_candidate_evidence",
        }

        self.assertFalse(
            analysis_pipeline._report_has_noncritical_degradation(
                report,
                {"semantic_enhancement": report},
            )
        )

    def test_failed_noncritical_stage_marks_report_partial(self):
        self.assertTrue(
            analysis_pipeline._report_has_noncritical_degradation(
                {"overall_score": 72},
                {"audio_features": {"error": "stage_failed"}},
            )
        )

    def test_self_review_signals_counts_events_without_scoring_the_user(self):
        result = summarize_self_review_signals(
            Counter({"large_paste": 1, "tab_switch": 2, "fullscreen_exit": 1}),
            {"flags": []},
            {"authenticity_flags": []},
        )

        self.assertFalse(result["scored"])
        self.assertEqual(result["signal_count"], 4)
        self.assertNotIn("risk_score", result)
        self.assertNotIn("risk_level", result)

    def test_self_review_signals_is_empty_without_events(self):
        result = summarize_self_review_signals(Counter(), {"flags": []}, {"authenticity_flags": []})

        self.assertFalse(result["scored"])
        self.assertEqual(result["signal_count"], 0)


class MediaRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcript_stage_merges_interview_and_coding_reasoning_evidence(self):
        execute = AsyncMock(side_effect=[
            [
                (
                    "Explain a difficult production incident.",
                    1,
                    None,
                    None,
                    "I owned the rollback and reduced recovery time.",
                    None,
                ),
            ],
            None,
            [
                (
                    "round-1",
                    "Implement a rate limiter.",
                    1,
                    "workflow_explanation",
                    b"encrypted-reasoning",
                ),
            ],
        ])
        with (
            patch.object(analysis_pipeline, "async_execute", execute),
            patch.object(
                analysis_pipeline,
                "_technical_reasoning_transcript_entry",
                return_value={
                    "role": "candidate",
                    "text": "I used a token bucket and handled clock skew.",
                    "label": "Final explanation",
                },
            ),
        ):
            output = await analysis_pipeline._run_stage(
                "transcription_diarization",
                "interview-1",
                "user-1",
                {},
            )

        self.assertEqual(output["transcript"], [
            {"role": "interviewer", "text": "Explain a difficult production incident."},
            {"role": "candidate", "text": "I owned the rollback and reduced recovery time."},
            {"role": "interviewer", "text": "Implement a rate limiter.", "label": "Technical problem"},
            {"role": "candidate", "text": "I used a token bucket and handled clock skew.", "label": "Final explanation"},
        ])
        self.assertEqual(output["candidate_word_count"], 17)

    async def test_report_publication_rejects_unsealed_evidence_reference(self):
        report = {
            "interview_id": "interview-1",
            "report_type": "behavioral",
            "overall_score": 80,
            "evidence_hash": "sealed-hash",
            "evidence_manifest_id": "manifest-1",
            "evidence_status": {"status": "sufficient"},
            "question_breakdown": [{"response_id": "response-not-in-manifest"}],
        }
        execute = AsyncMock(side_effect=[
            ("completed", "natural", "sealed-hash"),
            ({"items": [{"evidence_id": "different-response"}]},),
        ])
        with patch.object(analysis_pipeline, "async_execute", execute):
            with self.assertRaisesRegex(RuntimeError, "unsealed_evidence"):
                await analysis_pipeline._validate_report_for_publication(
                    report,
                    interview_id="interview-1",
                    user_id="user-1",
                    evidence_hash="sealed-hash",
                    manifest_id="manifest-1",
                )

    async def test_zero_retention_schedules_audio_and_video_immediately(self):
        execute = AsyncMock(return_value=None)
        with (
            patch.object(analysis_pipeline, "async_execute", execute),
            patch.object(analysis_pipeline.settings, "RAW_VIDEO_RETENTION_HOURS", 0),
            patch.object(analysis_pipeline.settings, "AUDIO_RETENTION_DAYS", 0),
        ):
            await analysis_pipeline._schedule_media_cleanup("interview-1")

        self.assertEqual(execute.await_count, 2)
        self.assertEqual({call.args[1][3] for call in execute.await_args_list}, {"audio", "video"})

    async def test_retention_sweep_removes_disabled_local_manifest_media(self):
        execute = AsyncMock(return_value=[("asset-1",), ("asset-2",)])
        with (
            patch.object(analysis_pipeline, "async_execute", execute),
            patch.object(analysis_pipeline.settings, "RAW_VIDEO_RETENTION_HOURS", 0),
            patch.object(analysis_pipeline.settings, "AUDIO_RETENTION_DAYS", 0),
        ):
            deleted = await analysis_pipeline._purge_expired_media_assets()

        self.assertEqual(deleted, 2)
        self.assertEqual(execute.await_args.args[1], (True, True))


if __name__ == "__main__":
    unittest.main()
