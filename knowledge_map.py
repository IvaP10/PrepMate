# ============================================================================
# MODULE: knowledge_map.py
# PURPOSE: Build the per-interview "battleground" map (topics, opening
#          questions, time budgets) from resume + job + profile-type; serve
#          next-question / follow-up generation against that map.
# STRUCTURE:
#   - In-process cache + size cap (lines 23-24)  << Phase 4: replace with llm_cache
#   - build_knowledge_map(...) main entry (lines 26-150)
#   - get_next_battleground / should_transition / generate_contextual_followup (later)
# ENDPOINTS: none (called from interview.py + websocket_manager flow controller)
# DEPENDS ON: config, llm_router, prompt_security, security_utils
# CONSUMED BY: interview.py, websocket_manager.InterviewFlowController
# DATA TABLES: none today (cache is in-process; Phase 4 → Redis L1 + Postgres L2)
# NOTE (Phase 4): the long inline prompt block here moves to
#   prompt_templates.knowledge_map(...) and the cache becomes content-hashed.
# ============================================================================

import json
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from interview_blueprint import compile_interview_blueprint, validate_blueprint
from llm_router import complete_json_async, complete_text_async
from prompt_security import SYSTEM_DATA_BOUNDARY, data_block
from redis_client import get_redis
from security_utils import redact_text, redact_pii_text

logger = logging.getLogger("knowledge_map")

_CACHE_TTL_SECONDS = 600  # 10 minutes


def _skill_names(raw_skills: Any, limit: int = 20) -> List[str]:
    if isinstance(raw_skills, str):
        raw_items: List[Any] = [part.strip() for part in raw_skills.split(",")]
    elif isinstance(raw_skills, list):
        raw_items = raw_skills
    else:
        raw_items = []

    names: List[str] = []
    seen = set()
    for item in raw_items:
        if isinstance(item, dict):
            value = item.get("name") or item.get("skill") or item.get("label") or item.get("title")
        else:
            value = item
        name = str(value or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= limit:
            break
    return names


def _cache_get(cache_key: str):
    """Read from Redis. Returns a deep copy via JSON deserialization (fixes F8.2)."""
    redis = get_redis()
    if not redis:
        return None
    raw = redis.get(f"km:{cache_key}")
    if raw:
        return json.loads(raw)
    return None


def _cache_set(cache_key: str, knowledge_map: dict):
    """Write to Redis with TTL. No manual eviction needed."""
    redis = get_redis()
    if not redis:
        return
    try:
        redis.setex(f"km:{cache_key}", _CACHE_TTL_SECONDS, json.dumps(knowledge_map, default=str))
    except Exception:
        logger.warning("Failed to cache knowledge map in Redis")

async def build_knowledge_map(
    resume_data: Dict,
    job_title: str,
    job_description: str,
    interview_type: str,
    duration_minutes: int = 30,
    profile_type: str = "mid_tier",
    profile_instruction: str = "",
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    focus: Optional[List[str]] = None,
    previous_weaknesses: Optional[List[Dict[str, Any]]] = None,
) -> Dict:
    skills = _skill_names(resume_data.get("skills", []), 20)
    raw_key = json.dumps({
        "name": resume_data.get("name", ""),
        "job_title": job_title,
        "interview_type": interview_type,
        "skills": skills,
        "projects": resume_data.get("projects", [])[:5],
        "external": resume_data.get("external_profile_signals", {}),
        "profile_type": profile_type,
        "interview_id": interview_id or "",
        "focus": focus or ["mixed"],
        "previous_weaknesses": previous_weaknesses or [],
    }, sort_keys=True, default=str)
    cache_key = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
    cached = _cache_get(cache_key)
    if cached:
        logger.info("Using cached knowledge map for key %s", cache_key[:8])
        return cached

    experience_years = calculate_experience_years(resume_data.get("experience", []))
    knowledge_map = validate_blueprint(compile_interview_blueprint(
        resume_data=resume_data,
        job_title=job_title,
        job_description=job_description,
        interview_type=interview_type,
        duration_minutes=duration_minutes,
        profile_type=profile_type,
        focus=focus,
        previous_weaknesses=previous_weaknesses,
    ))
    knowledge_map["experience_years"] = experience_years
    knowledge_map["candidate_name_hint"] = resume_data.get("name") or "the candidate"

    # The compiler owns coverage and rubrics. OpenAI may only improve the wording
    # of the already-selected questions; invalid or missing outputs are ignored.
    compact_sections = [
        {
            "section_id": item["section_id"],
            "label": item["label"],
            "kind": item["kind"],
            "opening_question": item["opening_question"],
            "source_anchors": item.get("source_anchors", [])[:2],
            "expected_points": item.get("expected_points", [])[:6],
        }
        for item in knowledge_map["battlegrounds"]
    ]
    schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string"},
                        "question": {"type": "string"},
                    },
                },
            }
        },
    }
    try:
        phrasing = await complete_json_async(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite only the supplied interview questions so they sound natural and specific. "
                        "Do not add, remove, merge, or change sections, rubrics, difficulty, or expected evidence. "
                        "When source anchors include a named project, the rewritten question must name that project. "
                        "Never replace a project-anchored question with a generic skill-only question. "
                        "Return one concise question per section. "
                        f"{SYSTEM_DATA_BOUNDARY}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Role: {job_title}\nProfile instruction: {profile_instruction}\n"
                        f"{data_block('candidate_and_job_context', json.dumps({'skills': skills[:15], 'projects': resume_data.get('projects', [])[:3], 'job_description': (job_description or '')[:1200]}, default=str), 4000)}\n"
                        f"Selected sections:\n{json.dumps(compact_sections, default=str)}"
                    ),
                },
            ],
            event_type="question_generator_knowledge_map",
            temperature=0.25,
            max_tokens=1200,
            user_id=user_id,
            interview_id=interview_id,
            metadata={
                "interview_type": interview_type,
                "job_title": job_title,
                "profile_type": profile_type,
                "duration_minutes": duration_minutes,
                "selection_policy": knowledge_map["selection_policy"],
            },
            json_schema=schema,
            cache_key=f"blueprint-phrasing:{knowledge_map['blueprint_hash']}",
        )
        replacements = {
            str(item.get("section_id")): str(item.get("question") or "").strip()
            for item in (phrasing.get("questions") or [])
            if isinstance(item, dict)
        }
        used = set()
        for item in knowledge_map["battlegrounds"]:
            candidate = replacements.get(item["section_id"], "")
            normalized = candidate.lower()
            anchors = [str(value).strip() for value in item.get("source_anchors", []) if str(value).strip()]
            required_anchor = (
                anchors[0] if item.get("kind") == "project" and anchors
                else anchors[1] if "anchored to candidate evidence" in str(item.get("selection_reason") or "").lower() and len(anchors) > 1
                else None
            )
            preserves_anchor = not required_anchor or required_anchor.lower() in normalized
            if 20 <= len(candidate) <= 360 and candidate.endswith("?") and normalized not in used and preserves_anchor:
                item["opening_question"] = candidate
                item["provenance"] = {"selection": "deterministic", "wording": "openai"}
                used.add(normalized)
            else:
                item["provenance"] = {"selection": "deterministic", "wording": "template"}
    except Exception as exc:
        logger.warning("Blueprint wording enhancement skipped: %s", redact_text(exc))
        for item in knowledge_map["battlegrounds"]:
            item["provenance"] = {"selection": "deterministic", "wording": "template"}

    _cache_set(cache_key, knowledge_map)
    logger.info("Evidence blueprint built with %d sections", len(knowledge_map.get("battlegrounds", [])))
    return knowledge_map

def apply_dynamic_turns(knowledge_map: Dict, duration_minutes: int, experience_years: int, profile_type: str = "mid_tier") -> Dict:
    battlegrounds = knowledge_map.get("battlegrounds", [])
    total_time = duration_minutes * 60

    for bg in battlegrounds:
        base_turns = 2

        if bg["importance"] == "critical":
            base_turns += 1
        elif bg["importance"] == "medium":
            base_turns -= 1

        if bg.get("resume_mentions", 0) > 3:
            base_turns += 1

        if experience_years > 5:
            base_turns += 1
        elif experience_years < 2:
            base_turns = max(1, base_turns - 1)

        if profile_type == "top_tier" and bg.get("importance") in {"critical", "high"}:
            base_turns += 1
        elif profile_type == "startup" and "project" in str(bg.get("label", "")).lower():
            base_turns += 1

        bg["max_turns"] = max(1, min(base_turns, 5))
        bg["min_turns"] = 1

        time_weight = {"critical": 1.5, "high": 1.2, "medium": 0.8}.get(bg["importance"], 1.0)
        bg["time_budget_seconds"] = int((total_time / len(battlegrounds)) * time_weight)

    return knowledge_map

def calculate_experience_years(experience: List[Dict]) -> int:
    total_months = 0
    for exp in experience:
        duration = str(exp.get("duration", "") or "")
        if "year" in duration.lower():
            years = int(''.join(filter(str.isdigit, duration.split("year")[0])) or 0)
            total_months += years * 12
        if "month" in duration.lower():
            months = int(''.join(filter(str.isdigit, duration.split("month")[0])) or 0)
            total_months += months

    return max(0, total_months // 12)

def get_next_battleground(knowledge_map: Dict) -> Optional[Dict]:
    for bg in knowledge_map.get("battlegrounds", []):
        if bg["current_turns"] < bg["max_turns"]:
            return bg
    return None

def get_current_battleground(knowledge_map: Dict) -> Optional[Dict]:
    battlegrounds = knowledge_map.get("battlegrounds", [])
    for bg in battlegrounds:
        if 0 < bg["current_turns"] < bg["max_turns"]:
            return bg
    return get_next_battleground(knowledge_map)

def should_extend_probing(
    battleground: Dict,
    recent_scores: List[float],
    time_elapsed: int
) -> bool:
    if not recent_scores or battleground["current_turns"] >= battleground["max_turns"]:
        return False

    avg_score = sum(recent_scores) / len(recent_scores)
    time_remaining = battleground["time_budget_seconds"] - time_elapsed

    if avg_score < 60 and time_remaining > 60 and battleground["current_turns"] < 4:
        logger.info("Extending probing for topic due to low score %.1f", avg_score)
        battleground["max_turns"] = min(battleground["max_turns"] + 1, 5)
        return True

    if avg_score > 85 and battleground["importance"] == "critical" and battleground["current_turns"] < 3:
        logger.info("Extending probing to challenge high performer")
        battleground["max_turns"] = min(battleground["max_turns"] + 1, 4)
        return True

    return False

def should_transition(
    knowledge_map: Dict,
    battleground_id: int,
    time_elapsed: int,
    recent_scores: List[float]
) -> bool:
    for bg in knowledge_map.get("battlegrounds", []):
        if bg["id"] == battleground_id:
            if bg["current_turns"] >= bg["max_turns"]:
                return True

            if time_elapsed > bg["time_budget_seconds"] * 1.3:
                logger.info("Forcing transition due to time")
                return True

            if should_extend_probing(bg, recent_scores, time_elapsed):
                return False

            if recent_scores and sum(recent_scores) / len(recent_scores) > 90:
                if bg["current_turns"] >= 2:
                    logger.info("Early transition due to mastery")
                    return True

            return bg["current_turns"] >= bg["max_turns"]

    return False

def mark_turn_used(knowledge_map: Dict, battleground_id: int) -> Dict:
    for bg in knowledge_map["battlegrounds"]:
        if bg["id"] == battleground_id:
            bg["current_turns"] += 1
            break
    return knowledge_map

def is_interview_complete(knowledge_map: Dict) -> bool:
    critical_battlegrounds = [
        bg for bg in knowledge_map.get("battlegrounds", [])
        if bg["importance"] == "critical"
    ]

    for bg in critical_battlegrounds:
        if bg["current_turns"] < bg["min_turns"]:
            return False

    all_exhausted = all(
        bg["current_turns"] >= bg["max_turns"]
        for bg in knowledge_map.get("battlegrounds", [])
    )

    return all_exhausted

def get_transition_to_next(knowledge_map: Dict, current_battleground_id: int) -> Optional[str]:
    battlegrounds = knowledge_map.get("battlegrounds", [])
    found_current = False
    current_hint = None

    for bg in battlegrounds:
        if found_current and bg["current_turns"] < bg["max_turns"]:
            return current_hint or f"Let's move on to {bg['label']}."
        if bg["id"] == current_battleground_id:
            found_current = True
            current_hint = bg.get("transition_hint")

    return None


def _recent_history_text(conversation_history: List[Dict], limit: int = 4) -> str:
    history_text = ""
    for turn in conversation_history[-limit:]:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "interviewer":
            history_text += f"Interviewer: {content}\n"
        elif role == "candidate":
            history_text += f"Candidate: {content}\n"
    return history_text


def validate_presented_question(
    candidate: str,
    *,
    fallback: str,
    conversation_history: Optional[List[Dict]] = None,
) -> str:
    """Return only a concise, single, non-duplicative interviewer question."""
    cleaned = re.sub(r"\s+", " ", str(candidate or "")).strip()
    fallback_clean = re.sub(r"\s+", " ", str(fallback or "")).strip()
    if not fallback_clean.endswith("?"):
        fallback_clean = fallback_clean.rstrip(".! ") + "?"
    words = cleaned.split()
    normalized = re.sub(r"\W+", " ", cleaned).strip().lower()
    blocked_phrases = ("please explain", "discuss in detail", "describe all", "write an essay")
    valid = bool(
        12 <= len(cleaned) <= 280
        and 3 <= len(words) <= 35
        and cleaned.endswith("?")
        and cleaned.count("?") == 1
        and not any(phrase in normalized for phrase in blocked_phrases)
    )
    prior_questions = set()
    for item in conversation_history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        text = str(item.get("content") or item.get("text") or "").strip()
        if role not in {"assistant", "interviewer", "ai"} or not text:
            continue
        prior_questions.add(re.sub(r"\W+", " ", text).strip().lower())
    if not valid or normalized in prior_questions:
        return fallback_clean
    return cleaned


def _metadata_resume_anchors(resume_context: str) -> Dict[str, Any]:
    redacted = redact_pii_text(resume_context or "")
    anchors = [line.strip() for line in redacted.splitlines() if line.strip()]
    return {
        "resume_anchor_count": len(anchors),
        "resume_anchors": anchors[:8],
    }


async def generate_battleground_question(
    *,
    battleground: Dict,
    resume_context: str,
    conversation_history: List[Dict],
    interview_mode: str = "mock",
    profile_instruction: str = "",
    profile_type: str = "mid_tier",
    job_title: str = "",
    transition_hint: str = "",
    question_id: Optional[str] = None,
    parent_question_id: Optional[str] = None,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
) -> str:
    seed_question = str(battleground.get("opening_question") or "").strip()
    label = str(battleground.get("label") or "this topic").strip()
    # The blueprint already contains a validated, personalized main question.
    # Keep it stable so a reconnect, retry, or cache miss cannot change the
    # evidence contract. OpenAI is reserved for genuinely adaptive follow-ups.
    if seed_question:
        return seed_question
    recent_history = data_block("recent_conversation", _recent_history_text(conversation_history))
    resume_block = data_block("resume_context", resume_context or "Not provided", 1200)
    transition_text = transition_hint or battleground.get("transition_hint") or ""

    prompt = f"""You are generating the next live interview question, not a full question list.

Role target: {job_title or "General Interview"}
Company profile: {profile_type}
Interview mode: {interview_mode}
Active topic: {label}
Topic importance: {battleground.get("importance", "high")}
Estimated difficulty: {battleground.get("estimated_difficulty", "matched")}
Fallback seed question: {seed_question or "Ask a focused question on the active topic."}
Transition hint: {transition_text or "None"}

Candidate resume and job anchors:
{resume_block}

Recent conversation:
{recent_history}

Profile instruction:
{profile_instruction or "Run a balanced, skills-focused interview."}

STRICT RULES:
1. Ask exactly one question.
2. Personalize it to the role, resume, job context, or recent conversation when evidence exists.
3. Do not ask a generic textbook question unless no candidate-specific anchor exists.
4. Match the company profile pressure and depth.
5. Use at most 35 words and output one concise interviewer question.

Return only the question text."""

    try:
        result = await complete_text_async(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an expert technical interviewer generating one adaptive live question. "
                        f"{SYSTEM_DATA_BOUNDARY}"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            event_type="question_generator_main",
            temperature=0.55,
            max_tokens=180,
            user_id=user_id,
            interview_id=interview_id,
            metadata={
                "profile_type": profile_type,
                "question_id": question_id,
                "parent_question_id": parent_question_id,
                "job_title": job_title,
                "battleground_label": label,
                "interview_mode": interview_mode,
                **_metadata_resume_anchors(resume_context),
            },
        )
        fallback = seed_question or f"Walk me through your experience with {label}."
        return validate_presented_question(
            result.text,
            fallback=fallback,
            conversation_history=conversation_history,
        )
    except Exception as e:
        logger.error("Failed to generate battleground question: %s", redact_text(e))
        return seed_question or f"Walk me through your experience with {label}."

async def generate_contextual_followup(
    battleground_label: str,
    main_question: str,
    candidate_response: str,
    conversation_history: List[Dict],
    performance_score: float,
    interview_mode: str = "mock",
    profile_instruction: str = "",
    profile_type: str = "mid_tier",
    job_title: str = "",
    resume_context: str = "",
    question_id: Optional[str] = None,
    parent_question_id: Optional[str] = None,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
) -> str:
    history_text = _recent_history_text(conversation_history)

    if performance_score <= 10:
        difficulty_instruction = (
            "The candidate gave a COMPLETELY IRRELEVANT or nonsensical answer. "
            "Do NOT acknowledge their response as valid. "
            "Re-ask about the SAME topic using a different, simpler angle. "
            "For example, ask them to explain a basic concept related to the topic, "
            "or ask a concrete yes/no question to test baseline knowledge. "
            "Be direct - do not sugar-coat it."
        )
    elif performance_score < 50:
        difficulty_instruction = (
            "The candidate struggled with this topic. "
            "Ask a SIMPLER follow-up that breaks the topic into a more basic sub-question. "
            "Reference something specific they said (or failed to address) in their answer."
        )
    elif performance_score > 85:
        difficulty_instruction = (
            "The candidate answered well. "
            "Ask a HARDER follow-up to challenge their depth: edge cases, trade-offs, scalability, or real-world constraints. "
            "Directly reference a specific claim or detail from their answer and probe deeper into it."
        )
    else:
        difficulty_instruction = (
            "Ask a follow-up that probes for specific examples or deeper reasoning. "
            "Pick something specific the candidate mentioned in their answer and ask them to elaborate, "
            "explain the trade-offs, or describe how they would handle it differently."
        )

    history_text = data_block("recent_conversation", history_text)
    response_truncated = data_block("candidate_response", candidate_response, 600)

    prompt = f"""You are a technical interviewer conducting a live interview. Topic: {battleground_label}

Recent conversation:
{history_text}

The candidate's latest response scored {performance_score}/100:
{response_truncated}

{difficulty_instruction}

Company profile follow-up instruction:
{profile_instruction or "Keep the follow-up aligned with a balanced skills-focused interview."}
Company profile type: {profile_type}
Role target: {job_title or "General Interview"}

STRICT RULES:
1. Your follow-up MUST be based on what the candidate ACTUALLY said (or didn't say). Do NOT ask a pre-written or generic question.
2. If the candidate said something specific, reference it directly (e.g., "You mentioned X - can you explain how...")
3. If the candidate gave a poor or off-topic answer, address that directly and re-probe the same topic area.
4. Do NOT repeat a question that was already asked in the conversation history.
5. Use at most 35 words.
6. Ask one clear question without introductory commentary.

Return only the follow-up question as plain text."""

    try:
        result = await complete_text_async(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an expert technical interviewer. Generate adaptive follow-up questions that are ALWAYS "
                        "based on what the candidate actually said. Never ask generic or pre-planned questions. "
                        f"{SYSTEM_DATA_BOUNDARY}"
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            event_type="question_generator_followup",
            temperature=0.6,
            max_tokens=150,
            user_id=user_id,
            interview_id=interview_id,
            metadata={
                "profile_type": profile_type,
                "question_id": question_id,
                "parent_question_id": parent_question_id,
                "job_title": job_title,
                "battleground_label": battleground_label,
                "interview_mode": interview_mode,
                "performance_score": performance_score,
                **_metadata_resume_anchors(resume_context),
            },
        )

        if performance_score <= 10:
            fallback = f"What do you understand about {battleground_label} at a basic level?"
        elif performance_score < 50:
            fallback = "What was the first step in your reasoning?"
        else:
            fallback = "What specific example from your experience supports that answer?"
        followup = validate_presented_question(
            result.text,
            fallback=fallback,
            conversation_history=conversation_history,
        )
        logger.info("Generated adaptive follow-up for score %.1f", performance_score)
        return followup

    except Exception as e:
        logger.error("Failed to generate contextual follow-up: %s", redact_text(e))
        if performance_score <= 10:
            return f"What do you understand about {battleground_label} at a basic level?"
        elif performance_score < 50:
            return "What was the first step in your reasoning?"
        else:
            return "What specific example from your experience supports that answer?"

def _fallback_knowledge_map(
    job_title: str,
    skills: List[str],
    duration_minutes: int,
    experience_years: int,
    profile_type: str = "mid_tier"
) -> Dict:
    top_skills = skills[:5] if skills else ["Python", "System Design", "Algorithms", "APIs", "Databases"]

    battlegrounds = []
    fallback_questions = [
        "Which technically complex project best represents your own work?",
        f"How would you design a scalable service for a core {job_title} workflow?",
        "Tell me about a time you debugged a critical production issue under pressure.",
        "How do you evaluate trade-offs between technical solutions?",
        "How do you balance code quality with shipping speed?"
    ]
    fallback_transitions = [
        "Moving from that project, let's discuss system design.",
        "That's helpful. Now let's shift to production challenges.",
        "Good. Let's talk about technical decision-making.",
        "Interesting. Let's explore how you handle trade-offs.",
        "Last area—let's discuss engineering velocity."
    ]

    for i, skill in enumerate(top_skills):
        battlegrounds.append({
            "id": i + 1,
            "label": skill,
            "importance": "critical" if i < 3 else "medium",
            "opening_question": fallback_questions[i],
            "resume_mentions": 1,
            "estimated_difficulty": "matched",
            "min_turns": 1,
            "max_turns": 4 if profile_type == "top_tier" and i < 3 else 3 if i < 3 else 2,
            "current_turns": 0,
            "time_budget_seconds": int((duration_minutes * 60) / 5),
            "transition_hint": fallback_transitions[i]
        })

    return {
        "candidate_name_hint": "the candidate",
        "job_target": job_title,
        "experience_years": experience_years,
        "total_time_budget": duration_minutes * 60,
        "battlegrounds": battlegrounds
    }

def clear_cache():
    """Flush all knowledge map cache entries from Redis."""
    redis = get_redis()
    if redis:
        # Use SCAN to find and delete all km:* keys
        cursor = 0
        while True:
            cursor, keys = redis.scan(cursor, match="km:*", count=100)
            if keys:
                redis.delete(*keys)
            if cursor == 0:
                break
    logger.info("Knowledge map cache cleared")
