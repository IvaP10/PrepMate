import asyncio
import json

from evaluation.run_gates import DATASET, evaluate_cases, gate_report


def test_labelled_evaluation_gates_pass_without_network_calls():
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    report = gate_report(asyncio.run(evaluate_cases(cases)))

    assert report["passed"], report
    assert report["structured_or_fallback_handling_rate"] == 1.0
    assert report["evidence_quote_precision"] >= 0.95
    assert report["followup_agreement"] >= 0.85
    assert report["authoritative_state_agreement"] == 1.0
    assert report["authoritative_technical_without_correctness"] == 0
