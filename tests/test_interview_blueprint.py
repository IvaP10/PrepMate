from interview_blueprint import compile_interview_blueprint, validate_blueprint


def _resume():
    return {
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "projects": [
            {
                "name": "InterAI",
                "description": "An interview platform with retrieval and adaptive questions.",
            }
        ],
    }


def test_blueprint_is_deterministic_and_evidence_ready():
    kwargs = {
        "resume_data": _resume(),
        "job_title": "AI Backend Engineer",
        "job_description": "Build FastAPI services backed by PostgreSQL and Redis.",
        "interview_type": "Mock Interview",
        "duration_minutes": 45,
        "profile_type": "mid_tier",
        "focus": ["mixed"],
        "previous_weaknesses": [],
    }

    first = compile_interview_blueprint(**kwargs)
    second = compile_interview_blueprint(**kwargs)

    assert first["blueprint_hash"] == second["blueprint_hash"]
    assert first["selection_policy"] == "deterministic_evidence_first_v1"
    assert any("InterAI" in item["opening_question"] for item in first["battlegrounds"])
    assert all(item["expected_points"] for item in first["battlegrounds"])
    assert all(item["rubric"]["unknown_dimensions_are_null"] for item in first["battlegrounds"])
    assert validate_blueprint(first) is first


def test_prior_weakness_is_prioritized_and_duration_is_bounded():
    result = compile_interview_blueprint(
        resume_data=_resume(),
        job_title="Backend Engineer",
        job_description="Python APIs",
        interview_type="Mock Interview",
        duration_minutes=5,
        profile_type="startup",
        focus=["role-specific"],
        previous_weaknesses=[{"skill_key": "Graph traversal", "score": 34}],
    )

    first = result["battlegrounds"][0]
    assert first["section_id"] == "weakness-1"
    assert first["importance"] == "critical"
    assert result["total_time_budget"] == 10 * 60
    assert len(result["battlegrounds"]) >= 4


def test_blueprint_contains_no_placeholder_questions():
    result = compile_interview_blueprint(
        resume_data={"skills": [], "projects": []},
        job_title="Software Engineer",
        job_description="",
        interview_type="Mock Interview",
        duration_minutes=30,
        profile_type="mid_tier",
    )

    questions = [item["opening_question"] for item in result["battlegrounds"]]
    assert all("[relevant" not in question.lower() for question in questions)
    assert any("Software Engineer" in question for question in questions)
    assert all(question.endswith("?") and question.count("?") == 1 for question in questions)
    assert all(len(question.split()) <= 28 for question in questions)
    assert all(question.count(",") <= 1 and ";" not in question for question in questions)
    assert all("Engineer system" not in question for question in questions)


def test_project_evidence_precedes_and_anchors_skill_questions():
    result = compile_interview_blueprint(
        resume_data=_resume(),
        job_title="AI Backend Engineer",
        job_description="Python and FastAPI",
        interview_type="Mock Interview",
        duration_minutes=50,
        profile_type="mid_tier",
        focus=["mixed"],
    )

    sections = result["battlegrounds"]
    project_index = next(index for index, item in enumerate(sections) if item["section_id"] == "project-1")
    skill_index = next(index for index, item in enumerate(sections) if item["section_id"] == "critical-skill-1")
    assert project_index < skill_index
    assert "InterAI" in sections[skill_index]["opening_question"]
    assert "trade-off" in sections[skill_index]["opening_question"]
    assert sections[skill_index]["opening_question"] == (
        "What was the toughest Python trade-off you made in InterAI?"
    )
    assert "most important decision you made using Python" not in sections[skill_index]["opening_question"]
