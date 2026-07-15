"""Run the labelled answer-evaluation gates without external network calls."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import evaluation_engine


DATASET = Path(__file__).with_name("labelled_cases.json")


async def evaluate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        semantic_mode = case.get("semantic_mode")
        if semantic_mode == "fixture":
            semantic_call = AsyncMock(return_value=case["semantic_payload"])
            semantic_enabled = True
        elif semantic_mode == "failure":
            semantic_call = AsyncMock(side_effect=RuntimeError("labelled provider failure"))
            semantic_enabled = True
        else:
            semantic_call = AsyncMock()
            semantic_enabled = False
        with patch.object(evaluation_engine, "complete_json_async", semantic_call):
            result = await evaluation_engine.evaluate_answer(
                case["question"],
                case["answer"],
                case.get("rubric") or {},
                {
                    "question_type": case["question_type"],
                    "semantic_analysis_enabled": semantic_enabled,
                },
                45,
                [],
                user_id="labelled-user",
                interview_id="labelled-interview",
                response_id=case["id"],
            )
        results.append({"case": case, "result": result})
    return results


def gate_report(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(evaluated)
    followup_matches = sum(
        item["result"]["follow_up"]["action"] == item["case"]["expected_followup"]
        for item in evaluated
    )
    authoritative_matches = sum(
        bool(item["result"]["authoritative"]) == bool(item["case"]["authoritative_expected"])
        for item in evaluated
    )
    quotes = [
        (quote, item["case"]["answer"])
        for item in evaluated
        for quote in item["result"]["evidence"]["evidence_quotes"]
    ]
    valid_quotes = sum(quote in answer for quote, answer in quotes)
    high_confidence = [
        item for item in evaluated
        if item["case"].get("human_score") is not None
        and item["result"].get("overall_score") is not None
        and float(item["result"].get("confidence") or 0) >= 0.60
    ]
    score_agreements = sum(
        abs(float(item["result"]["overall_score"]) - float(item["case"]["human_score"])) <= 10
        for item in high_confidence
    )
    technical_without_semantics = [
        item for item in evaluated
        if item["case"]["question_type"] == "technical"
        and item["case"]["semantic_mode"] in {"disabled", "failure"}
    ]
    false_technical_authority = sum(bool(item["result"]["authoritative"]) for item in technical_without_semantics)
    handled = sum(
        item["result"]["semantic_status"]["state"] in {"completed", "skipped", "failed", "invalid"}
        for item in evaluated
    )
    metrics = {
        "case_count": total,
        "structured_or_fallback_handling_rate": handled / total if total else 0,
        "evidence_quote_precision": valid_quotes / len(quotes) if quotes else 1.0,
        "followup_agreement": followup_matches / total if total else 0,
        "authoritative_state_agreement": authoritative_matches / total if total else 0,
        "high_confidence_score_within_10": score_agreements / len(high_confidence) if high_confidence else 1.0,
        "high_confidence_case_count": len(high_confidence),
        "authoritative_technical_without_correctness": false_technical_authority,
    }
    metrics["passed"] = (
        metrics["structured_or_fallback_handling_rate"] == 1.0
        and metrics["evidence_quote_precision"] >= 0.95
        and metrics["followup_agreement"] >= 0.85
        and metrics["authoritative_state_agreement"] == 1.0
        and metrics["high_confidence_score_within_10"] >= 0.70
        and metrics["authoritative_technical_without_correctness"] == 0
    )
    return metrics


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    report = gate_report(await evaluate_cases(cases))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
