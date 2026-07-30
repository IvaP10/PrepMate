# ============================================================================
# MODULE: strictness_config.py
# PURPOSE: Static strictness/interview-type/scoring-criteria tables + a handful
#          of derivation helpers (question count, time-per-question, weighted score).
# STRUCTURE:
#   - STRICTNESS_LEVELS dict (easy/medium/hard/extreme)  (lines 14-87)
#   - INTERVIEW_TYPES dict                               (lines 89-158)
#   - SCORING_CRITERIA weights                           (lines 160-181)
#   - getters + score helpers                            (lines 183-222)
# ENDPOINTS: none
# DEPENDS ON: (stdlib only)
# CONSUMED BY: persona_generator, interview.py
# DATA TABLES: none
# ============================================================================

STRICTNESS_LEVELS = {
    "easy": {
        "name": "Easy",
        "description": "Relaxed interview with basic questions",
        "difficulty_multiplier": 0.7,
        "time_pressure": "low",
        "follow_up_intensity": "minimal",
        "technical_depth": "surface",
        "personality_traits": [
            "friendly",
            "encouraging",
            "patient",
            "supportive"
        ],
        "interview_style": "conversational and relaxed",
        "scoring_strictness": 0.6,
        "question_complexity": "basic",
        "hint_availability": True
    },
    "medium": {
        "name": "Medium",
        "description": "Standard interview with moderate difficulty",
        "difficulty_multiplier": 1.0,
        "time_pressure": "moderate",
        "follow_up_intensity": "moderate",
        "technical_depth": "intermediate",
        "personality_traits": [
            "professional",
            "balanced",
            "fair",
            "objective"
        ],
        "interview_style": "professional and structured",
        "scoring_strictness": 0.75,
        "question_complexity": "intermediate",
        "hint_availability": False
    },
    "hard": {
        "name": "Hard",
        "description": "Challenging interview with tough questions",
        "difficulty_multiplier": 1.3,
        "time_pressure": "high",
        "follow_up_intensity": "aggressive",
        "technical_depth": "deep",
        "personality_traits": [
            "demanding",
            "critical",
            "detail-oriented",
            "skeptical"
        ],
        "interview_style": "rigorous and challenging",
        "scoring_strictness": 0.9,
        "question_complexity": "advanced",
        "hint_availability": False
    },
    "extreme": {
        "name": "Extreme",
        "description": "High-pressure interview with extreme difficulty",
        "difficulty_multiplier": 1.6,
        "time_pressure": "extreme",
        "follow_up_intensity": "relentless",
        "technical_depth": "expert",
        "personality_traits": [
            "intimidating",
            "highly critical",
            "uncompromising",
            "intense"
        ],
        "interview_style": "high-pressure and intense",
        "scoring_strictness": 1.0,
        "question_complexity": "expert",
        "hint_availability": False
    }
}

INTERVIEW_TYPES = {
    "technical": {
        "name": "Technical Round",
        "focus_areas": [
            "coding",
            "algorithms",
            "data structures",
            "system design",
            "problem solving"
        ],
        "question_categories": [
            "coding_challenge",
            "algorithm_design",
            "system_architecture",
            "debugging",
            "optimization"
        ]
    },
    "behavioral": {
        "name": "Interview Round",
        "focus_areas": [
            "past experiences",
            "teamwork",
            "leadership",
            "conflict resolution",
            "adaptability"
        ],
        "question_categories": [
            "situational",
            "experience_based",
            "competency",
            "motivation",
            "culture_fit"
        ]
    },
    "case_study": {
        "name": "Case Study Interview",
        "focus_areas": [
            "analytical thinking",
            "business acumen",
            "problem decomposition",
            "strategic thinking",
            "communication"
        ],
        "question_categories": [
            "market_sizing",
            "business_strategy",
            "process_improvement",
            "product_design",
            "financial_analysis"
        ]
    },
    "mixed": {
        "name": "Mixed Interview",
        "focus_areas": [
            "technical skills",
            "soft skills",
            "problem solving",
            "communication",
            "cultural fit"
        ],
        "question_categories": [
            "technical",
            "behavioral",
            "situational",
            "problem_solving",
            "general"
        ]
    }
}

SCORING_CRITERIA = {
    "technical_accuracy": {
        "weight": 0.3,
        "description": "Correctness and depth of technical knowledge"
    },
    "communication": {
        "weight": 0.2,
        "description": "Clarity and effectiveness of communication"
    },
    "problem_solving": {
        "weight": 0.25,
        "description": "Approach to solving problems"
    },
    "confidence": {
        "weight": 0.15,
        "description": "Confidence and composure during interview"
    },
    "relevance": {
        "weight": 0.1,
        "description": "Relevance of answers to questions"
    }
}

def get_strictness_config(level: str) -> dict:
    return STRICTNESS_LEVELS.get(level.lower(), STRICTNESS_LEVELS["medium"])
