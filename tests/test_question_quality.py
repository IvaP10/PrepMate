from knowledge_map import validate_presented_question


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


def test_question_validator_rejects_duplicate_conversation_question():
    fallback = "What trade-off mattered most?"
    repeated = "What part did you personally own?"
    assert validate_presented_question(
        repeated,
        fallback=fallback,
        conversation_history=[{"role": "interviewer", "content": repeated}],
    ) == fallback
