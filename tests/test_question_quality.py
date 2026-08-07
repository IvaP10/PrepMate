from knowledge_map import _followup_fallback, validate_presented_question
from interview import _live_answer_quality, _live_retry_question


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
