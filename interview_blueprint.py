"""Deterministic interview blueprint compiler.

The compiler owns coverage, timing, taxonomy, rubrics, and fallback questions.
An LLM may later improve question wording, but it never chooses what the
interview covers or how evidence is scored.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional


BLUEPRINT_SCHEMA_VERSION = "interview_blueprint_v1"
BLUEPRINT_COMPILER_VERSION = "deterministic-blueprint-compiler-v3"

_STOP_WORDS = {
    "and", "the", "with", "for", "from", "that", "this", "your", "you",
    "are", "was", "were", "have", "has", "using", "used", "into", "about",
}

_TECH_ALIASES = {
    "postgresql": ("postgres", "postgresql"),
    "python": ("python",),
    "fastapi": ("fastapi",),
    "react": ("react", "reactjs", "next.js", "nextjs"),
    "machine-learning": ("machine learning", "ml", "model training"),
    "rag": ("rag", "retrieval augmented generation", "retrieval-augmented"),
    "redis": ("redis",),
    "system-design": ("system design", "architecture", "scalability"),
    "databases": ("database", "databases", "sql", "nosql"),
    "apis": ("api", "apis", "rest", "graphql"),
    "testing": ("testing", "pytest", "unit test", "integration test"),
    "dsa": ("dsa", "data structures", "algorithms"),
}


def _text(value: Any, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _skill_names(value: Any) -> List[str]:
    raw = value.split(",") if isinstance(value, str) else _list(value)
    result: List[str] = []
    seen = set()
    for item in raw:
        name = item.get("name") or item.get("skill") if isinstance(item, dict) else item
        cleaned = _text(name, 80)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def canonical_skill_key(value: str) -> str:
    lowered = _text(value, 120).lower()
    for key, aliases in _TECH_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered) for alias in aliases):
            return f"technical:{key}"
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-") or "general"
    return f"technical:{slug[:80]}"


def _jd_skill_names(job_description: str) -> List[str]:
    lowered = _text(job_description, 12000).lower()
    found: List[str] = []
    for key, aliases in _TECH_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered) for alias in aliases):
            found.append(key.replace("-", " ").title())
    return found


def _project_items(resume_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    projects = _list(resume_data.get("projects"))
    return [item for item in projects if isinstance(item, dict) and _text(item.get("name"))][:3]


def _rubric(kind: str) -> Dict[str, Any]:
    common = {
        "relevance": 0.20,
        "clarity": 0.15,
        "specificity": 0.15,
        "evidence": 0.15,
    }
    if kind == "behavioral":
        weights = {**common, "star_structure": 0.20, "ownership": 0.15}
    elif kind == "project":
        weights = {**common, "technical_depth": 0.20, "tradeoffs": 0.15}
    else:
        weights = {**common, "technical_depth": 0.25, "tradeoffs": 0.10}
    return {
        "version": "rubric_v1",
        "weights": weights,
        "score_requires_evidence": True,
        "unknown_dimensions_are_null": True,
    }


def _expected_points(kind: str) -> List[str]:
    if kind == "behavioral":
        return ["situation", "task", "personal action", "result", "learning"]
    if kind == "project":
        return [
            "problem being solved",
            "personal contribution",
            "architecture or data flow",
            "technology decision and trade-off",
            "measured or observable outcome",
            "limitation or failure mode",
        ]
    return [
        "direct answer",
        "practical application",
        "implementation detail",
        "decision trade-off",
        "edge case or failure mode",
    ]


def _expected_point_specs(section_id: str, labels: List[str]) -> List[Dict[str, str]]:
    return [
        {
            "expected_point_id": (
                "ep_" + hashlib.sha256(f"{section_id}:{index}:{label}".encode("utf-8")).hexdigest()[:18]
            ),
            "label": label,
        }
        for index, label in enumerate(labels, start=1)
    ]


def _source_tokens(*values: str) -> List[str]:
    tokens: List[str] = []
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", value or ""):
            lowered = token.lower().strip(".-")
            if lowered not in _STOP_WORDS and lowered not in tokens:
                tokens.append(lowered)
    return tokens[:20]


def _section(
    *,
    section_id: str,
    label: str,
    kind: str,
    anchor: str,
    question: str,
    importance: str,
    difficulty: str,
    selection_reason: str,
    weakness: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    taxonomy_key = (
        f"project:{re.sub(r'[^a-z0-9]+', '-', anchor.lower()).strip('-')[:70]}:{kind}"
        if kind == "project"
        else "behavioral:star" if kind == "behavioral" else canonical_skill_key(label)
    )
    expected_points = _expected_points(kind)
    return {
        "section_id": section_id,
        "label": label,
        "kind": kind,
        "importance": importance,
        "estimated_difficulty": difficulty,
        "opening_question": question,
        "taxonomy_keys": [taxonomy_key],
        "expected_points": expected_points,
        "expected_point_specs": _expected_point_specs(section_id, expected_points),
        "rubric": _rubric(kind),
        "rubric_version": "rubric_v1",
        "selection_reason": selection_reason,
        "source_anchors": [anchor] if anchor else [],
        "prior_weakness": weakness or None,
        "min_turns": 1,
        "max_turns": 2,
        "max_followups": 2,
        "current_turns": 0,
        "time_budget_seconds": 0,
        "transition_hint": "",
    }


def compile_interview_blueprint(
    *,
    resume_data: Dict[str, Any],
    job_title: str,
    job_description: str,
    interview_type: str,
    duration_minutes: int,
    profile_type: str,
    focus: Optional[Iterable[str]] = None,
    previous_weaknesses: Optional[List[Dict[str, Any]]] = None,
    difficulty_level: str = "adaptive",
    experience_level: Optional[str] = None,
    question_count: Optional[int] = None,
    round_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile a complete, executable blueprint without an LLM dependency."""

    duration_minutes = max(10, min(int(duration_minutes or 30), 120))
    requested_count = int(question_count or 0)
    desired_sections = (
        max(1, min(12, requested_count))
        if requested_count
        else max(4, min(8, duration_minutes // 6))
    )
    if desired_sections * 75 > duration_minutes * 60:
        raise ValueError("Requested question count cannot fit the interview duration")
    normalized_difficulty = str(difficulty_level or "adaptive").strip().lower()
    if normalized_difficulty not in {"adaptive", "easy", "medium", "hard"}:
        raise ValueError("Unsupported blueprint difficulty")
    focus_set = {str(item).strip().lower() for item in (focus or ["mixed"]) if str(item).strip()}
    mixed = not focus_set or "mixed" in focus_set
    skills = _skill_names(resume_data.get("skills"))
    for jd_skill in _jd_skill_names(job_description):
        if jd_skill.lower() not in {item.lower() for item in skills}:
            skills.append(jd_skill)
    weaknesses = [item for item in (previous_weaknesses or []) if isinstance(item, dict)]
    sections: List[Dict[str, Any]] = []
    projects = _project_items(resume_data)

    def add(section: Dict[str, Any]) -> None:
        key = tuple(section.get("taxonomy_keys") or [])
        if key and any(tuple(existing.get("taxonomy_keys") or []) == key for existing in sections):
            return
        sections.append(section)

    for index, weakness in enumerate(weaknesses[:2], start=1):
        label = _text(weakness.get("label") or weakness.get("skill_key") or "Priority weakness", 80)
        add(_section(
            section_id=f"weakness-{index}",
            label=label,
            kind="technical",
            anchor=label,
            question=f"Where did {label} matter most in a real project?",
            importance="critical",
            difficulty="diagnostic",
            selection_reason="Repeated or low-confidence weakness from prior evidence",
            weakness=weakness,
        ))

    if mixed or focus_set & {"resume", "project", "projects"}:
        for index, project in enumerate(projects[:2], start=1):
            name = _text(project.get("name"), 100)
            description = _text(project.get("description"), 240)
            add(_section(
                section_id=f"project-{index}",
                label=f"{name} project depth",
                kind="project",
                anchor=name,
                question=f"Walk me through what you personally built in {name}?",
                importance="critical" if index == 1 else "high",
                difficulty="matched",
                selection_reason="Resume project claim requires evidence and ownership",
            ))
            if description:
                sections[-1]["source_anchors"].append(description)

    # Skills are assessed through named work whenever project evidence exists.
    # This avoids generic trivia such as "what did you do with Python?" and
    # lets the interviewer verify ownership, an implementation decision, and a
    # trade-off against a claim the candidate actually made.
    if mixed or focus_set & {"role", "role-specific", "technical", "resume"}:
        for index, skill in enumerate(skills[:1], start=1):
            project = projects[0] if projects else None
            project_name = _text(project.get("name"), 100) if project else ""
            question = (
                f"In {project_name}, which {skill} design decision most affected reliability, latency, or accuracy, and what trade-off did you accept?"
                if project_name else
                f"Which {skill} design decision did you personally make for this role, and what trade-off did you accept?"
            )
            add(_section(
                section_id=f"critical-skill-{index}",
                label=skill,
                kind="technical",
                anchor=skill,
                question=question,
                importance="critical",
                difficulty="matched",
                selection_reason="Job-critical skill coverage is anchored to candidate evidence",
            ))
            if project_name:
                sections[-1]["source_anchors"].append(project_name)
                description = _text(project.get("description"), 240)
                if description:
                    sections[-1]["source_anchors"].append(description)

    if mixed or focus_set & {"role", "role-specific", "technical", "resume"}:
        for index, skill in enumerate(skills[1:5], start=2):
            project = projects[(index - 2) % len(projects)] if projects else None
            project_name = _text(project.get("name"), 100) if project else ""
            add(_section(
                section_id=f"skill-{index}",
                label=skill,
                kind="technical",
                anchor=skill,
                question=(
                    f"In {project_name}, why did you choose {skill}, what alternative did you reject, and how did you validate the choice?"
                    if project_name else
                    f"Why would you choose {skill} for this role, what alternative would you reject, and how would you validate the choice?"
                ),
                importance="high" if index <= 2 else "medium",
                difficulty="stretch" if profile_type == "top_tier" and index <= 2 else "matched",
                selection_reason="Resume or job-description skill alignment",
            ))
            if project_name:
                sections[-1]["source_anchors"].append(project_name)

    if mixed or focus_set & {"behavioral", "hr"}:
        add(_section(
            section_id="behavioral-ownership",
            label="Ownership under constraints",
            kind="behavioral",
            anchor=job_title,
            question=f"Tell me about a difficult decision you personally owned in your {job_title} work?",
            importance="high",
            difficulty="matched",
            selection_reason="Behavioral evidence and STAR structure coverage",
        ))

    fallback_labels = [
        "Problem solving",
        "System design",
        "Testing and reliability",
        "Communication",
        "Data modelling",
        "Observability",
        "Security",
        "Scalability",
        "Debugging",
        "Delivery trade-offs",
        "Cross-team collaboration",
        "Learning from failure",
    ]
    fallback_questions = {
        "Problem solving": f"How would you break down an ambiguous problem for a {job_title} system?",
        "System design": f"What would you clarify first when designing a {job_title} system?",
        "Testing and reliability": "What failure would you test first before shipping?",
        "Communication": "How do you explain a difficult technical trade-off to a teammate?",
        "Data modelling": "What access pattern would drive your data model first?",
        "Observability": "Which production signal would you monitor first?",
        "Security": "Which trust boundary would you examine first?",
        "Scalability": "Where would you expect the first scaling bottleneck?",
        "Debugging": "What evidence do you gather first during a production failure?",
        "Delivery trade-offs": "What trade-off have you accepted to ship something useful?",
        "Cross-team collaboration": "What cross-team dependency was hardest for you to unblock?",
        "Learning from failure": "What failure changed how you approach engineering work?",
    }
    for index, label in enumerate(fallback_labels, start=1):
        if len(sections) >= desired_sections:
            break
        add(_section(
            section_id=f"fallback-{index}",
            label=label,
            kind="technical" if label != "Communication" else "behavioral",
            anchor=job_title,
            question=fallback_questions[label],
            importance="medium",
            difficulty="matched",
            selection_reason="Minimum balanced interview coverage",
        ))

    sections = sections[:desired_sections]
    total_seconds = duration_minutes * 60
    weights = {"critical": 1.35, "high": 1.1, "medium": 0.8}
    total_weight = sum(weights.get(item["importance"], 1.0) for item in sections) or 1.0
    budgets = [
        max(75, int(total_seconds * weights.get(item["importance"], 1.0) / total_weight))
        for item in sections
    ]
    overflow = sum(budgets) - total_seconds
    while overflow > 0:
        changed = False
        for budget_index in sorted(range(len(budgets)), key=lambda value: budgets[value], reverse=True):
            reducible = budgets[budget_index] - 75
            if reducible <= 0:
                continue
            reduction = min(reducible, overflow)
            budgets[budget_index] -= reduction
            overflow -= reduction
            changed = True
            if overflow <= 0:
                break
        if not changed:
            raise ValueError("Requested question count cannot fit the interview duration")
    if budgets:
        budgets[0] += total_seconds - sum(budgets)

    for index, item in enumerate(sections, start=1):
        item["id"] = index
        item["question_id"] = (
            "q_" + hashlib.sha256(
                f"{BLUEPRINT_SCHEMA_VERSION}:{item['section_id']}:{item['opening_question']}".encode("utf-8")
            ).hexdigest()[:20]
        )
        item["time_budget_seconds"] = budgets[index - 1]
        item["max_turns"] = 3 if item["importance"] == "critical" else 2
        item["max_followups"] = min(2, max(0, item["max_turns"] - 1))
        if normalized_difficulty != "adaptive":
            item["estimated_difficulty"] = normalized_difficulty
        item["transition_hint"] = (
            f"Let's move from {item['label']} to {sections[index]['label']}."
            if index < len(sections) else ""
        )

    hash_input = {
        "job_title": job_title,
        "job_description_hash": hashlib.sha256((job_description or "").encode()).hexdigest(),
        "interview_type": interview_type,
        "profile_type": profile_type,
        "experience_level": experience_level,
        "difficulty_level": normalized_difficulty,
        "duration_minutes": duration_minutes,
        "question_count": len(sections),
        "round_config": round_config or {},
        "sections": sections,
    }
    blueprint_hash = hashlib.sha256(json.dumps(hash_input, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "schema_version": BLUEPRINT_SCHEMA_VERSION,
        "compiler_version": BLUEPRINT_COMPILER_VERSION,
        "blueprint_hash": blueprint_hash,
        "job_target": job_title,
        "interview_type": interview_type,
        "profile_type": profile_type,
        "experience_level": experience_level,
        "difficulty_level": normalized_difficulty,
        "total_time_budget": total_seconds,
        "round_config": round_config or {},
        "selection_policy": "deterministic_evidence_first_v1",
        "battlegrounds": sections,
        "source_summary": {
            "resume_skill_count": len(_skill_names(resume_data.get("skills"))),
            "project_count": len(_project_items(resume_data)),
            "jd_signal_count": len(_jd_skill_names(job_description)),
            "prior_weakness_count": len(weaknesses),
            "source_tokens": _source_tokens(job_title, job_description),
        },
    }


def validate_blueprint(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    sections = blueprint.get("battlegrounds") if isinstance(blueprint, dict) else None
    if not isinstance(sections, list) or not sections:
        raise ValueError("Blueprint must contain at least one section")
    seen_ids = set()
    seen_question_ids = set()
    seen_questions = set()
    allocated_seconds = 0
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Blueprint sections must be objects")
        section_id = str(section.get("section_id") or "").strip()
        if not section_id or section_id in seen_ids:
            raise ValueError("Blueprint section IDs must be unique")
        seen_ids.add(section_id)
        question_id = str(section.get("question_id") or "").strip()
        if not question_id or question_id in seen_question_ids:
            raise ValueError("Blueprint question IDs must be stable and unique")
        seen_question_ids.add(question_id)
        question = str(section.get("opening_question") or "").strip()
        if not question:
            raise ValueError(f"Blueprint section {section_id} has no question")
        normalized_question = re.sub(r"\W+", " ", question).strip().lower()
        if normalized_question in seen_questions:
            raise ValueError("Blueprint questions must be unique")
        seen_questions.add(normalized_question)
        if any(token in question.lower() for token in ("[placeholder]", "[relevant", "todo", "lorem ipsum")):
            raise ValueError(f"Blueprint section {section_id} contains a placeholder question")
        if question.count("?") != 1 or not question.endswith("?") or len(question.split()) > 45:
            raise ValueError(f"Blueprint section {section_id} must contain one concise question")
        if any(phrase in normalized_question for phrase in ("please explain", "discuss in detail", "write an essay")):
            raise ValueError(f"Blueprint section {section_id} is not naturally phrased")
        if not section.get("taxonomy_keys") or not section.get("expected_points") or not section.get("rubric"):
            raise ValueError(f"Blueprint section {section_id} is missing evidence contracts")
        point_specs = section.get("expected_point_specs") or []
        point_ids = [str(item.get("expected_point_id") or "") for item in point_specs if isinstance(item, dict)]
        if len(point_ids) != len(set(point_ids)) or not all(point_ids):
            raise ValueError(f"Blueprint section {section_id} has invalid expected-point IDs")
        time_budget = int(section.get("time_budget_seconds") or 0)
        if time_budget <= 0:
            raise ValueError(f"Blueprint section {section_id} has no time budget")
        if int(section.get("max_followups") or 0) > 2:
            raise ValueError(f"Blueprint section {section_id} exceeds the follow-up budget")
        allocated_seconds += time_budget
    if allocated_seconds > int(blueprint.get("total_time_budget") or 0):
        raise ValueError("Blueprint timing exceeds the interview duration")
    return blueprint


def build_blueprint_preview(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    validated = validate_blueprint(blueprint)
    return {
        "schema_version": validated.get("schema_version"),
        "compiler_version": validated.get("compiler_version"),
        "blueprint_hash": validated.get("blueprint_hash"),
        "job_target": validated.get("job_target"),
        "interview_type": validated.get("interview_type"),
        "profile_type": validated.get("profile_type"),
        "experience_level": validated.get("experience_level"),
        "difficulty_level": validated.get("difficulty_level"),
        "duration_minutes": int(validated.get("total_time_budget") or 0) // 60,
        "total_time_budget": validated.get("total_time_budget"),
        "round_config": validated.get("round_config") or {},
        "sections": [
            {
                "section_id": section["section_id"],
                "label": section["label"],
                "kind": section["kind"],
                "importance": section["importance"],
                "difficulty": section["estimated_difficulty"],
                "time_budget_seconds": section["time_budget_seconds"],
                "max_followups": section["max_followups"],
                "taxonomy_keys": section.get("taxonomy_keys") or [],
            }
            for section in validated["battlegrounds"]
        ],
    }
