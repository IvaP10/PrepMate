import asyncio
import sys

import pytest

import local_execution
import technical_mode


def test_bundled_fallback_bank_has_complete_unique_case_contracts():
    problems = technical_mode._fallback_problem_candidates(
        {"role": "Backend Engineer", "skills": "Python", "project": "Local Ledger"},
        [1000, 1200],
        "mid_tier",
    )

    assert len(problems) == 2
    assert len({problem["title"] for problem in problems}) == 2
    for problem in problems:
        assert len(problem["visible_tests"]) == 3
        assert len(problem["hidden_tests"]) == 7
        all_inputs = [case["stdin"] for case in [*problem["visible_tests"], *problem["hidden_tests"]]]
        assert len(all_inputs) == len(set(all_inputs))
        assert len(problem["reference_solution"].strip()) >= 40
        assert "Local Ledger" in problem["statement"]


def test_bundled_fallback_bank_passes_the_same_normalizer_as_provider_content():
    problem = technical_mode._fallback_problem_candidates(
        {"role": "Engineer", "skills": "arrays", "project": ""},
        [1000, 1200],
        "mid_tier",
    )[0]

    normalized = asyncio.run(technical_mode._normalize_generated_problem(
        problem,
        profile_type="mid_tier",
        profile_label="Mid Tier Companies",
        expected_difficulty="Easy",
        expected_rating=1000,
        round_number=1,
        generated_source="fallback",
        validate_reference=False,
    ))

    assert normalized["generated_source"] == "fallback"
    assert len(normalized["visible_tests"]) == 3
    assert len(normalized["hidden_tests"]) == 7


def test_execution_verdict_uses_local_process_result_contract():
    assert technical_mode._execution_verdict({"exit_code": 0}) == "Accepted"
    assert technical_mode._execution_verdict({"exit_code": 1}) == "Runtime Error"
    assert technical_mode._execution_verdict({"exit_code": -1, "timed_out": True}) == "TLE"
    assert technical_mode._execution_verdict({"exit_code": 1, "compile_failed": True}) == "Compile Error"


def test_local_runner_fails_closed_when_the_os_sandbox_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        local_execution,
        "_sandbox_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no sandbox")),
    )

    result = asyncio.run(local_execution.execute_local("python", "print('must not run')", ""))

    assert result["exit_code"] == -1
    assert result["executor"] == "unavailable"
    assert "no sandbox" in result["stderr"]


def test_frozen_backend_does_not_reuse_itself_as_the_python_runtime(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("PREPMATE_EMBEDDED_PYTHON", raising=False)

    result = asyncio.run(local_execution.execute_local("python", "print(42)", ""))

    assert result["executor"] == "unavailable"
    assert "separate Python runtime" in result["stderr"]


@pytest.mark.skipif(
    not local_execution.executor_status().get("healthy"),
    reason="supported local OS sandbox is unavailable",
)
def test_supported_local_runner_executes_inside_the_reported_sandbox():
    result = asyncio.run(local_execution.execute_local("python", "print(42)", ""))

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "42"
    assert result["executor"] in {"macos-seatbelt", "linux-bubblewrap"}
