import os
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import analysis_pipeline
from analysis_pipeline import aggregate_cheating_risk, _valid_candidate_report


class AnalysisPipelinePureTests(unittest.TestCase):
    def test_report_pipeline_uses_explicit_production_stages(self):
        self.assertEqual(analysis_pipeline.ANALYSIS_STAGES, (
            "evidence_load",
            "transcript_analysis",
            "technical_analysis",
            "integrity_summary",
            "deterministic_report",
            "semantic_enhancement",
            "report_validation",
            "performance_projection",
            "weakness_update",
            "improve_update",
            "complete",
        ))

    def test_stage_provenance_distinguishes_deterministic_and_openai_outputs(self):
        deterministic = analysis_pipeline._stage_provenance("deterministic_report", {"ai_enhanced": False}, "input-1")
        enhanced = analysis_pipeline._stage_provenance("report_generation", {"ai_enhanced": True}, "input-2")

        self.assertEqual(deterministic["engine"], "deterministic_inter_pipeline")
        self.assertIsNone(deterministic["model"])
        self.assertEqual(enhanced["engine"], "openai_narrative_enhancement")
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

    def test_cheating_risk_escalates_large_paste_and_focus_events(self):
        result = aggregate_cheating_risk(
            Counter({"large_paste": 1, "tab_switch": 2, "fullscreen_exit": 1}),
            {"flags": []},
            {"authenticity_flags": []},
        )

        self.assertEqual(result["risk_level"], "High")
        self.assertGreaterEqual(result["risk_score"], 80)

    def test_cheating_risk_stays_low_without_events(self):
        result = aggregate_cheating_risk(Counter(), {"flags": []}, {"authenticity_flags": []})

        self.assertEqual(result["risk_level"], "Low")
        self.assertEqual(result["risk_score"], 0)


class MediaRetentionTests(unittest.IsolatedAsyncioTestCase):
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
