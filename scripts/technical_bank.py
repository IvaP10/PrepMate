#!/usr/bin/env python3
"""Author, validate, and seed the persisted Technical coding problem bank."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "key.env")

from config import settings  # noqa: E402
from database import close_connection_pool, get_db_connection, init_connection_pool, return_db_connection  # noqa: E402
from llm_router import _responses_kwargs  # noqa: E402
from security_utils import encrypt_data  # noqa: E402

from openai import AsyncOpenAI  # noqa: E402


BATCH_TAXONOMIES = [
    ["arrays", "arrays", "arrays", "arrays"],
    ["hashing", "hashing", "prefix-sum", "prefix-sum"],
    ["sliding-window", "sliding-window", "two-pointers", "two-pointers"],
    ["intervals", "intervals", "greedy", "greedy"],
    ["binary-search", "binary-search", "binary-search", "stack"],
    ["stack", "queue", "queue", "linked-list"],
    ["linked-list", "trees", "trees", "trees"],
    ["heaps", "heaps", "graphs", "graphs"],
    ["graphs", "backtracking", "backtracking", "strings"],
    ["strings", "tries", "tries", "dynamic-programming"],
    ["dynamic-programming", "dynamic-programming", "bit-manipulation", "bit-manipulation"],
    ["arrays", "hashing", "graphs", "dynamic-programming"],
]

HIDDEN_TAGS = {
    "empty_input",
    "single_element",
    "duplicate_values",
    "negative_values",
    "large_input",
    "already_sorted",
    "boundary_value",
    "disconnected_graph",
    "cycle",
    "repeated_prefix",
}

DIFFICULTIES = {"easy", "medium", "hard"}


def _problem_schema(taxonomies: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["problems"],
        "properties": {
            "problems": {
                "type": "array",
                "minItems": len(taxonomies),
                "maxItems": len(taxonomies),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title",
                        "difficulty",
                        "taxonomy",
                        "algorithm_pattern",
                        "statement",
                        "input_format",
                        "output_format",
                        "constraints",
                        "visible_tests",
                        "hidden_tests",
                        "expected_time_complexity",
                        "expected_space_complexity",
                        "hint",
                        "reference_solution",
                    ],
                    "properties": {
                        "title": {"type": "string", "maxLength": 80},
                        "difficulty": {"type": "string", "enum": sorted(DIFFICULTIES)},
                        "taxonomy": {"type": "string", "enum": sorted(set(taxonomies))},
                        "algorithm_pattern": {"type": "string", "maxLength": 100},
                        "statement": {"type": "string", "minLength": 80},
                        "input_format": {"type": "string", "minLength": 10},
                        "output_format": {"type": "string", "minLength": 5},
                        "constraints": {"type": "string", "minLength": 10},
                        "visible_tests": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["stdin", "expected", "explanation"],
                                "properties": {
                                    "stdin": {"type": "string"},
                                    "expected": {"type": "string"},
                                    "explanation": {"type": "string", "minLength": 5},
                                },
                            },
                        },
                        "hidden_tests": {
                            "type": "array",
                            "minItems": 7,
                            "maxItems": 7,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["stdin", "expected", "tag"],
                                "properties": {
                                    "stdin": {"type": "string"},
                                    "expected": {"type": "string"},
                                    "tag": {"type": "string", "enum": sorted(HIDDEN_TAGS)},
                                },
                            },
                        },
                        "expected_time_complexity": {"type": "string", "minLength": 2},
                        "expected_space_complexity": {"type": "string", "minLength": 2},
                        "hint": {"type": "string", "minLength": 10},
                        "reference_solution": {"type": "string", "minLength": 40},
                    },
                },
            }
        },
    }


def _author_messages(taxonomies: list[str], batch_number: int, feedback: str = "") -> list[dict[str, str]]:
    requested = ", ".join(f"{index + 1}: {taxonomy}" for index, taxonomy in enumerate(taxonomies))
    feedback_block = f"\nA previous attempt failed validation: {feedback}\nCorrect that failure in this attempt.\n" if feedback else ""
    return [
        {
            "role": "system",
            "content": (
                "You are InterAI's offline DSA problem-bank author. Return only JSON matching the schema. "
                "Write original, company-style interview problems; do not copy, quote, or name a company, "
                "coding platform, or known proprietary question. These prompts are a broad representative "
                "coverage of common real-company DSA patterns, not a claim to reproduce private interview banks. "
                "Every problem must be solvable from ordinary stdin and must have a deterministic Python 3.12 "
                "reference solution that reads stdin and writes the exact expected stdout."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Create exactly {len(taxonomies)} distinct coding problems for batch {batch_number}. "
                f"The required taxonomy in each array position is: {requested}.\n"
                "Requirements:\n"
                "- Preserve the requested order and set taxonomy exactly to that position's value.\n"
                "- Use a clear interview-ready title, statement, input/output format, constraints, and hint.\n"
                "- Use one or more core DSA patterns appropriate to the requested taxonomy.\n"
                "- Include exactly 3 visible and exactly 7 hidden tests per problem. All ten stdin values "
                "must be unique within that problem. Hidden tags must cover meaningful edge cases; do not "
                "invent a tag outside the schema.\n"
                "- Expected output must be exact stdout. The reference solution must solve every supplied case, "
                "not hardcode the examples, and use only the Python standard library.\n"
                "- Every supplied case must produce at least one non-whitespace output character; do not use "
                "tasks whose correct answer is an empty stdout.\n"
                "- Avoid interactive tasks, external files, randomness, probabilistic answers, ambiguous input, "
                "and functions-only prompts. Keep max tests runnable within a few seconds.\n"
                "- Vary the problem shape across the batch; do not return renamed textbook examples."
                + feedback_block
            ),
        },
    ]


def _text(value: Any, field: str, minimum: int = 1) -> str:
    result = str(value or "").strip()
    if len(result) < minimum:
        raise ValueError(f"{field} is required")
    return result


def _complexity(value: Any, field: str) -> str:
    result = _text(value, field, 2)
    return result if len(result) <= 80 else result[:77].rstrip() + "..."


def _run_reference(source: str, stdin: str) -> str:
    with tempfile.TemporaryDirectory(prefix="interai-bank-case-") as directory:
        script = Path(directory) / "main.py"
        script.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-I", str(script)],
            input=stdin,
            text=True,
            capture_output=True,
            cwd=directory,
            env={"PATH": os.environ.get("PATH", "")},
            timeout=4,
            check=False,
        )
    if completed.returncode != 0:
        raise ValueError(f"reference solution exited {completed.returncode}: {completed.stderr[:240]}")
    if len(completed.stdout.encode("utf-8")) > settings.PISTON_OUTPUT_LIMIT_BYTES:
        raise ValueError("reference solution output exceeds the bank output limit")
    return completed.stdout


def _validate_problem(raw: dict[str, Any], expected_taxonomy: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"problem {index} is not an object")
    taxonomy = _text(raw.get("taxonomy"), f"problem {index}.taxonomy").lower().replace("_", "-")
    if taxonomy != expected_taxonomy:
        raise ValueError(f"problem {index} taxonomy is {taxonomy!r}, expected {expected_taxonomy!r}")
    difficulty = _text(raw.get("difficulty"), f"problem {index}.difficulty").lower()
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"problem {index} has unsupported difficulty")
    visible = raw.get("visible_tests")
    hidden = raw.get("hidden_tests")
    if not isinstance(visible, list) or len(visible) != 3:
        raise ValueError(f"problem {index} must have exactly 3 visible tests")
    if not isinstance(hidden, list) or len(hidden) != 7:
        raise ValueError(f"problem {index} must have exactly 7 hidden tests")
    normalized_visible: list[dict[str, str]] = []
    normalized_hidden: list[dict[str, str]] = []
    for case_index, case in enumerate(visible):
        if not isinstance(case, dict):
            raise ValueError(f"problem {index} visible test {case_index} is not an object")
        normalized_visible.append({
            "stdin": _text(case.get("stdin"), f"problem {index}.visible[{case_index}].stdin"),
            "expected": str(case.get("expected") or ""),
            "explanation": _text(case.get("explanation"), f"problem {index}.visible[{case_index}].explanation", 5),
        })
    for case_index, case in enumerate(hidden):
        if not isinstance(case, dict):
            raise ValueError(f"problem {index} hidden test {case_index} is not an object")
        tag = _text(case.get("tag"), f"problem {index}.hidden[{case_index}].tag").lower().replace(" ", "_")
        if tag not in HIDDEN_TAGS:
            raise ValueError(f"problem {index} has unsupported hidden tag {tag!r}")
        normalized_hidden.append({
            "stdin": _text(case.get("stdin"), f"problem {index}.hidden[{case_index}].stdin"),
            "expected": str(case.get("expected") or ""),
            "tag": tag,
        })
    all_cases = [*normalized_visible, *normalized_hidden]
    if len({case["stdin"] for case in all_cases}) != len(all_cases):
        raise ValueError(f"problem {index} contains duplicate stdin cases")
    reference = _text(raw.get("reference_solution"), f"problem {index}.reference_solution", 40)
    if "input(" not in reference and "sys.stdin" not in reference:
        raise ValueError(f"problem {index} reference solution does not read stdin")
    for case_index, case in enumerate(all_cases):
        actual = _run_reference(reference, case["stdin"])
        if not actual.strip():
            raise ValueError(f"problem {index} reference solution returned empty output on case {case_index}")
        case["expected"] = actual.strip() + "\n"
    algorithm_pattern = _text(raw.get("algorithm_pattern"), f"problem {index}.algorithm_pattern")
    statement = _text(raw.get("statement"), f"problem {index}.statement", 80)
    title = _text(raw.get("title"), f"problem {index}.title", 3)
    if len(title) > 80:
        raise ValueError(f"problem {index} title is too long")
    return {
        "title": title,
        "difficulty": difficulty,
        "taxonomy": taxonomy,
        "algorithm_pattern": algorithm_pattern,
        "statement": statement,
        "input_format": _text(raw.get("input_format"), f"problem {index}.input_format", 10),
        "output_format": _text(raw.get("output_format"), f"problem {index}.output_format", 5),
        "constraints": _text(raw.get("constraints"), f"problem {index}.constraints", 10),
        "visible_tests": normalized_visible,
        "hidden_tests": normalized_hidden,
        "expected_time_complexity": _complexity(raw.get("expected_time_complexity"), f"problem {index}.expected_time_complexity"),
        "expected_space_complexity": _complexity(raw.get("expected_space_complexity"), f"problem {index}.expected_space_complexity"),
        "hint": _text(raw.get("hint"), f"problem {index}.hint", 10),
        "reference_solution": reference,
    }


async def _author_batch(taxonomies: list[str], batch_number: int) -> list[dict[str, Any]]:
    feedback = ""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=120.0)
    for attempt in range(1, 7):
        try:
            response = await client.responses.create(
                timeout=120.0,
                **_responses_kwargs(
                    model=settings.OPENAI_TECHNICAL_MODEL,
                    messages=_author_messages(taxonomies, batch_number, feedback),
                    temperature=0.0,
                    max_tokens=16000,
                    json_mode=True,
                    json_schema=_problem_schema(taxonomies),
                ),
                reasoning={"effort": "low"},
            )
            payload = json.loads((response.output_text or "").strip())
            raw_problems = payload.get("problems") if isinstance(payload, dict) else None
            if not isinstance(raw_problems, list) or len(raw_problems) != len(taxonomies):
                raise ValueError("model returned the wrong problem count")
            return [
                _validate_problem(problem, taxonomy, index)
                for index, (problem, taxonomy) in enumerate(zip(raw_problems, taxonomies), start=1)
            ]
        except Exception as exc:
            feedback = str(exc)[:500]
            if attempt == 6:
                raise
            delay = 15 if type(exc).__name__ == "RateLimitError" else 2 * attempt
            print(f"Batch {batch_number} retry {attempt}/5 after {type(exc).__name__}; waiting {delay}s", flush=True)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


async def author(output: Path) -> None:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    output.parent.mkdir(parents=True, exist_ok=True)
    problems: list[dict[str, Any]] = []
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        saved = json.loads(partial.read_text(encoding="utf-8"))
        saved_problems = saved.get("problems") if isinstance(saved, dict) else None
        if isinstance(saved_problems, list) and len(saved_problems) % 4 == 0:
            problems = saved_problems
            print(f"Resuming after {len(problems)} validated problems", flush=True)
    start_batch = len(problems) // 4 + 1
    for batch_number, taxonomies in list(enumerate(BATCH_TAXONOMIES, start=1))[start_batch - 1:]:
        print(f"Authoring batch {batch_number}/{len(BATCH_TAXONOMIES)}: {', '.join(taxonomies)}", flush=True)
        batch = await _author_batch(taxonomies, batch_number)
        problems.extend(batch)
        partial.write_text(
            json.dumps({"bank_version": settings.TECHNICAL_BANK_VERSION, "model": settings.OPENAI_TECHNICAL_MODEL, "problems": problems}, indent=2),
            encoding="utf-8",
        )
        await asyncio.sleep(1)
    manifest = {
        "bank_version": settings.TECHNICAL_BANK_VERSION,
        "model": settings.OPENAI_TECHNICAL_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "problems": problems,
    }
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if partial.exists():
        partial.unlink()
    print(f"Validated {len(problems)} coding problems with {settings.OPENAI_TECHNICAL_MODEL}")


def _problem_id(problem: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        "|".join([problem["taxonomy"], problem["title"], problem["statement"]]).encode("utf-8")
    ).hexdigest()
    return f"tb-{digest[:24]}"


def _taxonomy_keys(problem: dict[str, Any]) -> list[str]:
    taxonomy = problem["taxonomy"]
    pattern = problem["algorithm_pattern"].lower().replace("_", "-").replace(" ", "-")
    return [f"technical:{taxonomy}", f"technical:{pattern}", "technical:dsa"]


def _spec_json(problem: dict[str, Any], problem_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "bank_version": settings.TECHNICAL_BANK_VERSION,
        "generation_model": manifest.get("model") or settings.OPENAI_TECHNICAL_MODEL,
        "generation_source": "original_interai_offline_authoring",
        "problem_id": problem_id,
        "algorithm_pattern": problem["algorithm_pattern"],
        "input_format": problem["input_format"],
        "output_format": problem["output_format"],
        "constraints": problem["constraints"],
        "hint": problem["hint"],
        "profile_types": ["top_tier", "mid_tier", "startup", "custom"],
        "expected_points": [
            {"point_id": "coding:approach", "label": "explains a correct approach"},
            {"point_id": "coding:complexity", "label": "justifies time and space complexity"},
            {"point_id": "coding:edge-cases", "label": "handles boundary and adversarial cases"},
            {"point_id": "coding:implementation", "label": "produces a clear working implementation"},
        ],
        "rubric": {
            "version": "coding-v1",
            "weights": {
                "passed_tests": 0.35,
                "approach": 0.15,
                "efficiency": 0.15,
                "edge_cases": 0.10,
                "debugging": 0.10,
                "explanation": 0.10,
                "code_quality": 0.05,
            },
            "coding_correctness_owner": "deterministic_sandbox_tests",
            "unknown_dimensions_are_null": True,
        },
    }


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    problems = manifest.get("problems")
    if not isinstance(problems, list):
        raise ValueError("manifest problems must be an array")
    if len(problems) < settings.TECHNICAL_MIN_CODING_PROBLEMS:
        raise ValueError(
            f"manifest has {len(problems)} problems; at least {settings.TECHNICAL_MIN_CODING_PROBLEMS} are required"
        )
    seen_ids: set[str] = set()
    seen_taxonomies: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, problem in enumerate(problems, start=1):
        taxonomy = str(problem.get("taxonomy") or "").lower().replace("_", "-")
        normalized_problem = _validate_problem(problem, taxonomy, index)
        problem_id = _problem_id(normalized_problem)
        if problem_id in seen_ids:
            raise ValueError(f"duplicate problem id generated for problem {index}")
        seen_ids.add(problem_id)
        seen_taxonomies.add(taxonomy)
        normalized.append(normalized_problem)
    required = {
        item.strip().lower().replace("_", "-")
        for item in str(settings.TECHNICAL_REQUIRED_TAXONOMIES or "").split(",")
        if item.strip()
    }
    missing = sorted(required - seen_taxonomies)
    if missing:
        raise ValueError(f"manifest is missing taxonomy coverage: {', '.join(missing)}")
    return normalized


def seed(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = _validate_manifest(manifest)
    init_connection_pool()
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        for problem in problems:
            problem_id = _problem_id(problem)
            family_id = hashlib.sha256(
                f"{problem['taxonomy']}|{problem['title']}".encode("utf-8")
            ).hexdigest()[:32]
            validation_result = {
                "passed": True,
                "status": "passed",
                "validator_version": settings.TECHNICAL_BANK_VERSION,
                "reference_solution_verified": True,
                "sandbox_execution_verified": False,
                "validation_scope": "offline_bank_authoring",
            }
            hidden_encrypted = encrypt_data(
                json.dumps(problem["hidden_tests"], separators=(",", ":"), ensure_ascii=False)
            ).encode("utf-8")
            reference_encrypted = encrypt_data(problem["reference_solution"]).encode("utf-8")
            cursor.execute(
                """
                INSERT INTO TechnicalProblemBank (
                    problem_id, problem_family_id, version, status, round_type,
                    taxonomy_keys, prerequisite_keys, difficulty, title,
                    problem_statement, license_source, spec_json, visible_tests,
                    hidden_tests_encrypted, reference_solution_encrypted,
                    expected_time_complexity, expected_space_complexity,
                    supported_languages, validator_version, validation_result,
                    activated_at, created_at, updated_at
                )
                VALUES (
                    %s, %s, 1, 'active', 'coding', %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s,
                    %s::jsonb, %s, %s::jsonb, NOW(), NOW(), NOW()
                )
                ON CONFLICT (problem_id, version) DO UPDATE SET
                    problem_family_id = EXCLUDED.problem_family_id,
                    status = EXCLUDED.status,
                    round_type = EXCLUDED.round_type,
                    taxonomy_keys = EXCLUDED.taxonomy_keys,
                    prerequisite_keys = EXCLUDED.prerequisite_keys,
                    difficulty = EXCLUDED.difficulty,
                    title = EXCLUDED.title,
                    problem_statement = EXCLUDED.problem_statement,
                    license_source = EXCLUDED.license_source,
                    spec_json = EXCLUDED.spec_json,
                    visible_tests = EXCLUDED.visible_tests,
                    hidden_tests_encrypted = EXCLUDED.hidden_tests_encrypted,
                    reference_solution_encrypted = EXCLUDED.reference_solution_encrypted,
                    expected_time_complexity = EXCLUDED.expected_time_complexity,
                    expected_space_complexity = EXCLUDED.expected_space_complexity,
                    supported_languages = EXCLUDED.supported_languages,
                    validator_version = EXCLUDED.validator_version,
                    validation_result = EXCLUDED.validation_result,
                    activated_at = EXCLUDED.activated_at,
                    updated_at = NOW()
                """,
                (
                    problem_id,
                    family_id,
                    json.dumps(_taxonomy_keys(problem)),
                    json.dumps(["technical:arrays", "technical:hashing", "technical:problem-solving"]),
                    problem["difficulty"],
                    problem["title"],
                    problem["statement"],
                    "original_interai_problem_authoring",
                    json.dumps(_spec_json(problem, problem_id, manifest), ensure_ascii=False),
                    json.dumps(problem["visible_tests"], ensure_ascii=False),
                    hidden_encrypted,
                    reference_encrypted,
                    problem["expected_time_complexity"],
                    problem["expected_space_complexity"],
                    json.dumps(["python", "javascript", "cpp", "java"]),
                    settings.TECHNICAL_BANK_VERSION,
                    json.dumps(validation_result),
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)
        close_connection_pool()
    print(f"Seeded {len(problems)} active coding problems into TechnicalProblemBank")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    author_parser = subparsers.add_parser("author")
    author_parser.add_argument("--output", type=Path, required=True)
    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "author":
        asyncio.run(author(args.output))
    else:
        seed(args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
