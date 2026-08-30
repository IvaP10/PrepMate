# ============================================================================
# MODULE: interview_profiles.py
# PURPOSE: Profile-type definitions (top_tier/mid_tier/startup) — labels and
#          strictness/follow-up/technical instructions used by the interviewer LLM.
# STRUCTURE:
#   - PROFILE_TYPES set + DEFAULT_PROFILE_TYPE (lines 14-15)
#   - PROFILE_CONFIGS dict (lines 17-66)
#   - normalize_profile_type / get_profile_config (lines 69-75)
# ENDPOINTS: none (read via /api/workspace/interview-profile in workspace_api.py)
# DEPENDS ON: (stdlib only)
# CONSUMED BY: workspace_api.py, interview.py, persona_generator, learning_engine
# DATA TABLES: none today (Phase 3 moves to `interview_profiles` DB table)
# ============================================================================

from typing import Any, Dict

PROFILE_TYPES = {"top_tier", "mid_tier", "startup", "custom"}
DEFAULT_PROFILE_TYPE = "top_tier"
TECHNICAL_CODING_QUESTION_COUNT = 2
TECHNICAL_MINUTES_PER_QUESTION = 40
TECHNICAL_TOTAL_DURATION_MINUTES = TECHNICAL_CODING_QUESTION_COUNT * TECHNICAL_MINUTES_PER_QUESTION

PROFILE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "top_tier": {
        "config_version": "profile-2026-08-v4",
        "label": "Top Tier",
        "strictness_level": "hard",
        "duration": {"min_minutes": 45, "target_minutes": 60, "max_minutes": 60},
        "technical_rounds": ["coding", "system_design", "debugging"],
        "interview_instruction": (
            "Run an intellectually demanding top-tier interview from the first question. Treat every "
            "candidate claim as something to decompose: why that approach, what failed first, how it was "
            "measured, which trade-offs were accepted, and what would break at scale. Keep branching based "
            "on the answer instead of moving linearly. Introduce ambiguity and production failure scenarios "
            "to test system internals, uncertainty handling, decomposition, and real ownership."
        ),
        "followup_instruction": (
            "Push for top-tier depth. Break answers apart and ask why, what failed, how they evaluated it, "
            "how it behaves under scale, where latency or memory bottlenecks appear, and what they would "
            "redesign under stricter constraints. Do not reward memorized answers; force live reasoning."
        ),
        "behavioral_instruction": (
            "Make behavioral questions analytical: ask what exactly failed, which metric exposed it, what "
            "they tried first, why it did not work, which trade-off they accepted, what decision was wrong, "
            "and how they proved the final solution was better."
        ),
        "adaptive_policy": {
            "progression": "depth_first",
            "strong_answer_action": "challenge_tradeoff",
            "allow_strong_depth_probe": True,
            "missing_evidence_action": "probe_evidence",
        },
        "technical_instruction": (
            "Generate original problems matching a high-bar global technology interview. Never imply that a "
            "problem is leaked, exact, guaranteed, or currently used by a named company. Focus on multi-step "
            "algorithmic challenges requiring optimal time/space "
            "complexity analysis. Prefer: graph traversals (BFS/DFS/Dijkstra), dynamic programming (1D/2D/bitmask), "
            "advanced data structures (segment trees, tries, monotonic stacks/queues), binary search on answer, "
            "topological sort, union-find, sliding window with constraints, and string matching (KMP, Rabin-Karp). "
            "Problems should require clarifying questions, multiple approaches (brute-force → optimized), edge-case "
            "reasoning, and formal complexity proofs. Avoid trivial array/string problems."
        ),
    },
    "mid_tier": {
        "config_version": "profile-2026-08-v4",
        "label": "Mid Tier",
        "strictness_level": "medium",
        "duration": {"min_minutes": 45, "target_minutes": 50, "max_minutes": 60},
        "technical_rounds": ["coding", "technical_concept"],
        "interview_instruction": (
            "Run a structured, practical, balanced interview. Validate exact contribution, API behavior, "
            "database choice, testing, collaboration, bugs, and production readiness. Ask meaningful "
            "follow-ups, but do not aggressively challenge every statement. Adjust pacing when the candidate "
            "gets stuck without giving hints, coaching, corrections, or answer content."
        ),
        "followup_instruction": (
            "Probe for practical understanding: exact contribution, implementation details, trade-offs, "
            "debugging steps, tests, team collaboration, edge cases, and moderate scalability. Keep the "
            "tone fair and structured."
        ),
        "behavioral_instruction": (
            "Focus on teamwork and execution: conflict, prioritization, deadline management, failed "
            "features, communication with teammates, and what they learned."
        ),
        "adaptive_policy": {
            "progression": "balanced_coverage",
            "strong_answer_action": "advance",
            "allow_strong_depth_probe": False,
            "missing_evidence_action": "probe_evidence",
        },
        "technical_instruction": (
            "Generate original practical coding questions for an established product engineering team. Never "
            "claim that a problem is exact, leaked, guaranteed, or currently used by a named company. Focus on "
            "clean implementation over trick-based optimization. "
            "Prefer: arrays, strings, hash maps, sorting, linked lists, stacks, queues, basic trees (BST, "
            "level-order traversal), simple graphs (connected components, shortest path), binary search, "
            "two-pointer, and prefix sums. Problems should test practical coding ability: clean readable code, "
            "proper edge-case handling, basic time complexity awareness, and testing mindset. Avoid problems "
            "requiring advanced DP, segment trees, or obscure algorithms."
        ),
    },
    "startup": {
        "config_version": "profile-2026-08-v4",
        "label": "Startup",
        "strictness_level": "medium",
        "duration": {"min_minutes": 45, "target_minutes": 45, "max_minutes": 60},
        "technical_rounds": ["coding", "debugging"],
        "interview_instruction": (
            "Run a fast, direct, execution-focused startup interview. Prioritize whether the candidate can "
            "build independently, adapt to changing requirements, debug quickly, reduce costs, ship MVPs, "
            "iterate from user feedback, and take ownership without much supervision."
        ),
        "followup_instruction": (
            "Probe practical ownership and speed: how long it took, what they built themselves, what broke "
            "in production, how users responded, how they iterated, what they postponed, cost reductions, "
            "and the highest-impact feature."
        ),
        "behavioral_instruction": (
            "Focus on initiative, speed, adaptability, uncertainty, ownership, shipping under pressure, "
            "changing requirements, and knowingly accepted trade-offs."
        ),
        "adaptive_policy": {
            "progression": "speed_first",
            "strong_answer_action": "advance",
            "allow_strong_depth_probe": False,
            "missing_evidence_action": "probe_evidence",
        },
        "technical_instruction": (
            "Generate original practical, fast-paced coding questions for an early-stage team. Focus on working "
            "solutions under time pressure over algorithmic perfection. "
            "Prefer: arrays, hash maps, string manipulation, sorting, basic recursion, simple tree/graph "
            "traversals, stack/queue operations, and greedy approaches. Problems should be solvable in "
            "15-20 minutes with clean working code. Emphasize: real-world constraints (changing input shape, "
            "API integration points), debugging ability, and iterative improvement. Avoid obscure algorithms, "
            "heavy DP, or problems requiring 45+ minutes of thinking."
        ),
    },
    "custom": {
        "config_version": "profile-2026-08-v4",
        "label": "Custom",
        "strictness_level": "medium",
        "duration": {"min_minutes": 45, "target_minutes": 50, "max_minutes": 60},
        "technical_rounds": ["coding", "system_design"],
        "interview_instruction": (
            "Run a customized interview based on the provided job description and target role. Validate "
            "exact fit for the role requirements, API design, trade-offs, DB options, system requirements, "
            "and relevant technical depth. Keep follow-ups aligned to the job description requirements."
        ),
        "followup_instruction": (
            "Probe aligned with the role description and target skills. Ask how they would implement "
            "requirements from the job description, what trade-offs are relevant to this specific role, "
            "and what edge cases matter for the system described in the JD."
        ),
        "behavioral_instruction": (
            "Focus on execution, collaboration, and decision-making relevant to the job requirements."
        ),
        "adaptive_policy": {
            "progression": "job_aligned_coverage",
            "strong_answer_action": "advance",
            "allow_strong_depth_probe": False,
            "missing_evidence_action": "probe_evidence",
        },
        "technical_instruction": (
            "Generate DSA coding challenges tailored specifically to the provided job description and company. "
            "Match difficulty to the seniority level implied by the role title. For the specific company and JD: "
            "focus on data structures and algorithms that directly relate to the described responsibilities. "
            "If the JD mentions backend/API work, include problems with data processing, caching, or system "
            "patterns. If the JD mentions frontend, include string/DOM-like manipulation. If ML/AI, include "
            "matrix operations or optimization. Choose a deterministic, testable task format that fits the role; "
            "use stdin/stdout only when it is a natural match, and otherwise model production-oriented inputs "
            "without requiring external services or network access."
        ),
    },
}

def normalize_profile_type(value: str | None) -> str:
    normalized = (value or DEFAULT_PROFILE_TYPE).strip().lower()
    return normalized if normalized in PROFILE_TYPES else DEFAULT_PROFILE_TYPE


def get_profile_config(profile_type: str | None) -> Dict[str, Any]:
    return PROFILE_CONFIGS[normalize_profile_type(profile_type)]


def get_profile_duration(profile_type: str | None) -> Dict[str, int]:
    config = get_profile_config(profile_type)
    return dict(config["duration"])
