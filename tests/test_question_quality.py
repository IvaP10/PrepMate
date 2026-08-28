import asyncio
from types import SimpleNamespace

import knowledge_map
from knowledge_map import _followup_fallback, validate_presented_question
from interview import _build_opening_script, _build_personalized_opening, _live_answer_quality, _live_retry_question


def test_question_validator_accepts_one_natural_question():
    question = "You mentioned Redis. What problem did it solve in that project?"
    assert validate_presented_question(question, fallback="What did you build?") == question


def test_question_validator_rejects_combined_or_formal_prompts():
    fallback = "What part did you personally own?"
    assert validate_presented_question(
        "What did you build? Why did it fail?",
        fallback=fallback,
    ) == fallback
    assert validate_presented_question(
        "Please explain your project architecture in detail?",
        fallback=fallback,
    ) == fallback
    assert validate_presented_question(
        "Go one level deeper on reliability and provide a comprehensive answer?",
        fallback=fallback,
    ) == fallback
    assert validate_presented_question(
        "How would you design it, scale it, monitor it, and recover it?",
        fallback=fallback,
    ) == fallback


def test_question_validator_rejects_duplicate_conversation_question():
    fallback = "What trade-off mattered most?"
    repeated = "What part did you personally own?"
    assert validate_presented_question(
        repeated,
        fallback=fallback,
        conversation_history=[{"role": "interviewer", "content": repeated}],
    ) == fallback


def test_followup_fallback_stays_grounded_in_candidate_answer():
    followup = _followup_fallback(
        "probe_evidence",
        "Caching",
        "I used Redis to cache profile responses and reduced database load.",
    )

    assert "Redis" in followup
    assert followup.endswith("?")


def test_live_quality_gate_rejects_off_topic_answer():
    evaluation = {
        "signals": {
            "word_count": 18,
            "lexical_relevance": {"score": 0},
            "structure": {"score": 17},
            "specificity_evidence": {"score": 8},
            "ownership": {"score": 48},
            "directness": {"score": 16},
        },
        "semantic_status": {"state": "failed"},
    }

    assert _live_answer_quality(evaluation) == (False, "answer_not_relevant")


def test_live_quality_gate_allows_specific_answer_without_keyword_overlap():
    evaluation = {
        "signals": {
            "word_count": 24,
            "lexical_relevance": {"score": 0},
            "structure": {"score": 54},
            "specificity_evidence": {"score": 52},
            "ownership": {"score": 80},
            "directness": {"score": 16},
        },
        "semantic_status": {"state": "failed"},
    }

    assert _live_answer_quality(evaluation) == (True, "relevant_without_keyword_overlap")


def test_live_retry_keeps_the_original_question_instead_of_nesting_prompts():
    original = "Tell me about a project you owned and the result it produced?"
    first = _live_retry_question(original, "Project ownership", "answer_not_relevant", 1)
    second = _live_retry_question(first, "Project ownership", "answer_not_relevant", 2)

    assert first.endswith(original)
    assert second.endswith(original)
    assert "Please answer the question directly about Project ownership" not in second


def test_personalized_opening_anchors_to_frozen_resume_project():
    opening = _build_personalized_opening(
        {"name": "Maya", "job_title": "Backend Engineer"},
        {
            "name": "Synthetic Candidate",
            "target_role": "Backend Engineer",
            "projects": [{"name": "Payments Ledger"}],
        },
        {},
        "mock",
    )

    assert "Payments Ledger" in opening
    assert "personally owned" in opening
    assert "Backend Engineer" in opening


def test_personalized_opening_keeps_safe_fallback_without_resume_anchors():
    opening = _build_personalized_opening(
        {"name": "Maya", "job_title": "Backend Engineer"},
        {"name": "Synthetic Candidate"},
        {},
        "mock",
    )

    assert opening == (
        "Hi Synthetic Candidate, I am Maya. What should I know about your background and interest "
        "in the Backend Engineer role?"
    )


def test_realistic_opening_separates_greeting_from_non_scored_introduction():
    script = _build_opening_script(
        {"name": "Ava", "job_title": "Backend Engineer"},
        {"name": "Synthetic Candidate", "target_role": "Backend Engineer"},
    )

    assert script["greeting"].startswith("Hi Synthetic Candidate")
    assert "explain each step" in script["greeting"]
    assert "scoring starts with the first round question" in script["greeting"]
    assert script["intro_question"].endswith("?")
    assert "brief introduction" in script["intro_question"]


def test_adaptive_followup_receives_frozen_resume_and_job_context(monkeypatch):
    captured = {}

    async def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured["metadata"] = kwargs["metadata"]
        return SimpleNamespace(
            text="You mentioned Redis; how did you keep cache invalidation safe for payment updates?"
        )

    monkeypatch.setattr(knowledge_map, "complete_text_async", fake_complete)

    result = asyncio.run(knowledge_map.generate_contextual_followup(
        battleground_label="Caching",
        main_question="How did you reduce database load?",
        candidate_response="I used Redis to cache payment profiles and reduced database load by forty percent.",
        conversation_history=[],
        performance_score=74,
        resume_context="Project: Payments Ledger - Built idempotent transaction processing.",
        job_context={
            "role": "Backend Engineer",
            "company": "Acme",
            "jd_summary": "Own reliable payment services.",
        },
    ))

    prompt = captured["messages"][1]["content"]
    assert "Payments Ledger" in prompt
    assert "Backend Engineer" in prompt
    assert "Acme" in prompt
    assert "Redis" in prompt
    assert result.startswith("You mentioned Redis")
