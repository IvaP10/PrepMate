# ============================================================================
# MODULE: persona_generator.py
# PURPOSE: Deterministically pick a synthetic interviewer persona (name,
#          company type, voice style) from a user-id hash + strictness, plus
#          generate the opening statement text.
# STRUCTURE:
#   - INTERVIEWER_NAMES / COMPANY_TYPES static lists (lines 14-44+)
#   - generate_persona(user_id, strictness, interview_type) (later in file)
#   - generate_opening_statement(persona, role) (later in file)
# ENDPOINTS: none
# DEPENDS ON: strictness_config (stdlib hashlib only otherwise)
# CONSUMED BY: interview.py
# DATA TABLES: none
# ============================================================================

import hashlib
from typing import Dict, List, Optional
from strictness_config import get_strictness_config

INTERVIEWER_NAMES = {
    "easy": [
        "Sarah Mitchell", "David Chen", "Emily Rodriguez", 
        "Michael Johnson", "Lisa Anderson"
    ],
    "medium": [
        "Robert Thompson", "Jennifer Lee", "James Wilson",
        "Patricia Davis", "Christopher Martin"
    ],
    "hard": [
        "Dr. Alexander Hawthorne", "Margaret Sinclair", "Richard Blackwood",
        "Catherine Montgomery", "Jonathan Sterling"
    ],
    "extreme": [
        "Dr. Victoria Cromwell", "Maximilian Frost", "Dr. Helena Ashford",
        "Sebastian Thorne", "Dr. Evelyn Blackstone"
    ]
}

INTERVIEWER_NAMES_INDIAN = {
    "easy": [
        "Priya Patel", "Amit Sharma", "Neha Gupta",
        "Rohan Mehta", "Ananya Rao"
    ],
    "medium": [
        "Siddharth Singh", "Deepika Iyer", "Vikram Malhotra",
        "Pooja Joshi", "Aditya Verma"
    ],
    "hard": [
        "Dr. Rajesh Kurup", "Dr. Shalini Mukherji", "Dr. Arvind Subramanian",
        "Dr. Meera Nair", "Dr. Sandeep Nair"
    ],
    "extreme": [
        "Dr. Vikram Sarabhai", "Dr. Arundhati Roy", "Dr. Homi Bhabha",
        "Dr. CV Raman", "Dr. APJ Kalam"
    ]
}

COMPANY_TYPES = [
    "Fortune 500 Technology Company",
    "Fast-Growing Startup",
    "Management Consulting Firm",
    "Investment Banking Institution",
    "Big Tech Company",
    "Healthcare Technology Company",
    "Fintech Unicorn",
    "E-commerce Giant",
    "AI Research Lab",
    "Cloud Services Provider"
]

ROLE_TITLES = {
    "easy": [
        "Junior Recruiter",
        "HR Associate",
        "Talent Acquisition Specialist",
        "Recruitment Coordinator"
    ],
    "medium": [
        "Senior Technical Recruiter",
        "Hiring Manager",
        "Team Lead",
        "Engineering Manager"
    ],
    "hard": [
        "Director of Engineering",
        "VP of Technology",
        "Chief Technology Officer",
        "Principal Engineer"
    ],
    "extreme": [
        "Executive VP of Engineering",
        "Chief Technical Officer",
        "Founder & CEO",
        "Distinguished Engineer"
    ]
}

def generate_persona(strictness_level: str, job_title: str, company_name: Optional[str] = None) -> Dict:
    config = get_strictness_config(strictness_level)
    seed = (strictness_level, job_title, company_name or "")
    from config import settings
    voice = getattr(settings, "KOKORO_VOICE", "af_heart")
    names_source = INTERVIEWER_NAMES_INDIAN
    interviewer_name = _pick(names_source.get(strictness_level, names_source["medium"]), "name", *seed)
    role_title = _pick(ROLE_TITLES.get(strictness_level, ROLE_TITLES["medium"]), "role", *seed)
    company = company_name or _pick(COMPANY_TYPES, "company", *seed)
    return {
        "name": interviewer_name,
        "role": role_title,
        "company": company,
        "strictness_level": strictness_level,
        "personality_traits": config["personality_traits"],
        "interview_style": config["interview_style"],
        "job_title": job_title,
        "background": generate_background(strictness_level, role_title, job_title, company),
        "expectations": generate_expectations(strictness_level),
        "communication_style": generate_communication_style(strictness_level)
    }

def _pick(options: List[str], *parts: str) -> str:
    idx = int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest(), 16) % len(options)
    return options[idx]

def generate_background(strictness_level: str, role_title: str, job_title: str = "", company: str = "") -> str:
    backgrounds = {
        "easy": [
            f"I'm a {role_title} with 3-5 years of experience in recruitment and talent acquisition.",
            f"As a {role_title}, I focus on finding great talent and helping candidates succeed.",
            f"I've been working as a {role_title} and I'm passionate about connecting people with opportunities."
        ],
        "medium": [
            f"I'm a {role_title} with over 8 years of experience in building high-performing teams.",
            f"As a {role_title}, I've conducted hundreds of technical interviews and hired top talent.",
            f"I'm a {role_title} focused on identifying candidates who can deliver results and grow with the company."
        ],
        "hard": [
            f"I'm a {role_title} with 15+ years of experience leading engineering teams at top tech companies.",
            f"As a {role_title}, I've built and scaled engineering organizations from 10 to 500+ engineers.",
            f"I'm a {role_title} known for maintaining extremely high hiring standards and building world-class teams."
        ],
        "extreme": [
            f"I'm a {role_title} with 20+ years of experience at industry-leading companies. I've built multiple billion-dollar products.",
            f"As a {role_title}, I've personally interviewed thousands of candidates and hired only the top 1%.",
            f"I'm a {role_title} with a reputation for the most rigorous technical interviews in the industry."
        ]
    }
    return _pick(backgrounds.get(strictness_level, backgrounds["medium"]), "background", strictness_level, role_title, job_title, company)

def generate_expectations(strictness_level: str) -> List[str]:
    expectations = {
        "easy": [
            "Show genuine interest in the role",
            "Communicate clearly and honestly",
            "Ask thoughtful questions",
            "Demonstrate willingness to learn"
        ],
        "medium": [
            "Demonstrate solid technical knowledge",
            "Provide clear and structured answers",
            "Show problem-solving abilities",
            "Ask insightful questions about the role and company"
        ],
        "hard": [
            "Exhibit deep technical expertise",
            "Provide comprehensive and well-reasoned answers",
            "Demonstrate exceptional problem-solving skills",
            "Challenge assumptions and think critically",
            "Show leadership potential"
        ],
        "extreme": [
            "Demonstrate world-class technical expertise",
            "Provide flawless execution under pressure",
            "Show innovative thinking and unique insights",
            "Exceed expectations on every question",
            "Prove you're in the top 1% of candidates"
        ]
    }
    return expectations.get(strictness_level, expectations["medium"])

def generate_communication_style(strictness_level: str) -> str:
    styles = {
        "easy": "friendly, encouraging, and supportive. I want to help you showcase your best qualities.",
        "medium": "professional, balanced, and objective. I'll ask direct questions and expect clear answers.",
        "hard": "rigorous, challenging, and critical. I'll push you to demonstrate deep expertise and won't accept superficial answers.",
        "extreme": "intensely demanding and uncompromising. I expect perfection and will challenge every aspect of your responses."
    }
    return styles.get(strictness_level, styles["medium"])

def generate_opening_statement(persona: Dict) -> str:
    strictness = persona["strictness_level"]
    openings = {
        "easy": (
            f"Hello and welcome! I'm {persona['name']}, and I'm a {persona['role']} here at {persona['company']}. "
            f"Thank you so much for taking the time to speak with us today about the {persona['job_title']} position. "
            f"Before we begin, let me quickly explain how this will work. I'll be asking you a series of questions "
            f"related to the role — some about your background and experience, and some more technical ones. "
            f"There's no need to be nervous. Just take your time with each answer and feel free to think out loud. "
            f"If you need me to repeat or clarify a question, just ask. Let's have a great conversation!"
        ),
        "medium": (
            f"Good day. I'm {persona['name']}, {persona['role']} at {persona['company']}. Welcome, and thank you for joining us. "
            f"I'll be conducting your interview today for the {persona['job_title']} position. "
            f"Here's how we'll proceed: I'll start with a few questions about your background, then we'll move into "
            f"more specific technical and situational questions. I may also ask follow-ups based on your answers to go deeper into certain topics. "
            f"Please give structured, clear answers — I'm looking for both what you know and how you think. "
            f"Feel free to take a moment to gather your thoughts before answering. Let's get started."
        ),
        "hard": (
            f"Welcome. I'm {persona['name']}, {persona['role']} at {persona['company']}. "
            f"I'll be evaluating you for the {persona['job_title']} role today, and I want to set expectations upfront. "
            f"This interview will be rigorous. I'll cover multiple areas including technical depth, problem-solving, "
            f"and real-world application of your skills. I expect detailed, well-reasoned responses — surface-level answers won't suffice. "
            f"I'll ask follow-up questions to probe deeper, so be prepared to defend and elaborate on your answers. "
            f"Let's see what you're capable of."
        ),
        "extreme": (
            f"I'm {persona['name']}, {persona['role']} at {persona['company']}. "
            f"Let me be clear about what you're walking into. This is an elite-level assessment for the {persona['job_title']} role, "
            f"and we only hire the absolute best. I will challenge every answer you give. "
            f"I expect you to demonstrate not just knowledge, but exceptional depth, clarity, and the ability to think on your feet. "
            f"Vague or rehearsed answers will be called out. If you don't know something, say so — but you'd better know most of it. "
            f"Let's begin."
        ),
    }
    return openings.get(strictness, openings["medium"])

def generate_closing_statement(persona: Dict, performance_score: float) -> str:
    strictness = persona["strictness_level"]
    if performance_score >= 85:
        closings = {
            "easy": f"That was wonderful! You did a great job today. Thank you for your time, and we'll be in touch soon!",
            "medium": f"Thank you for your time. You've demonstrated solid capabilities. We'll review your performance and get back to you.",
            "hard": f"You've shown strong competence today. While there's always room for improvement, you've met the high bar we set. We'll be in touch.",
            "extreme": f"Impressive. You've proven yourself to be in the top tier. Very few candidates perform at this level. We'll be moving forward with your application."
        }
    elif performance_score >= 70:
        closings = {
            "easy": f"Thank you so much for interviewing with us! You showed promise. We'll review everything and get back to you soon.",
            "medium": f"Thank you. You demonstrated adequate skills, though there are areas for improvement. We'll follow up after our review.",
            "hard": f"You've shown some competence, but frankly, I expected more depth in your answers. We'll discuss internally and decide.",
            "extreme": f"Your performance was below the exceptional standard we require. While you showed some capability, it's not sufficient for this role."
        }
    else:
        closings = {
            "easy": f"Thank you for your time today. We appreciate you coming in. We'll review your interview and let you know our decision.",
            "medium": f"Thank you. Unfortunately, your responses didn't meet the level we're looking for. We'll provide feedback and our decision soon.",
            "hard": f"I'll be direct: your performance today was not up to our standards. We need candidates who can demonstrate stronger technical depth.",
            "extreme": f"I'll be blunt: this was not acceptable. Your responses lacked the rigor and depth required. We cannot proceed with your application."
        }
    return closings.get(strictness, closings["medium"])

def adjust_persona_tone(persona: Dict, candidate_performance: str) -> str:
    strictness = persona["strictness_level"]
    if candidate_performance == "excellent":
        tones = {
            "easy": "even more encouraging and enthusiastic",
            "medium": "slightly more positive and approving",
            "hard": "marginally less critical but still demanding",
            "extreme": "fractionally less intense but still rigorous"
        }
    elif candidate_performance == "poor":
        tones = {
            "easy": "gently probing for better answers",
            "medium": "more direct and challenging",
            "hard": "increasingly critical and demanding",
            "extreme": "ruthlessly critical and dismissive"
        }
    else:
        return persona["communication_style"]

    return tones.get(strictness, persona["communication_style"]) or persona["communication_style"]
