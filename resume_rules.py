from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resume_rules")

SKILL_TERMS = {
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "golang", "rust",
    "kotlin", "swift", "php", "ruby", "scala", "sql", "html", "css", "react", "next.js",
    "nextjs", "vue", "angular", "node.js", "nodejs", "express", "fastapi", "flask", "django",
    "spring", "spring boot", "graphql", "rest", "grpc", "postgresql", "postgres", "mysql",
    "mongodb", "redis", "elasticsearch", "dynamodb", "firebase", "supabase", "aws", "azure",
    "gcp", "docker", "kubernetes", "terraform", "ansible", "jenkins", "github actions",
    "gitlab ci", "ci/cd", "linux", "nginx", "apache", "microservices", "system design",
    "distributed systems", "machine learning", "deep learning", "nlp", "computer vision",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras", "opencv",
    "spark", "hadoop", "airflow", "kafka", "rabbitmq", "celery", "piston", "webrtc",
    "mediapipe", "pymupdf", "paddleocr", "monaco", "excalidraw", "langchain",
    "langfuse", "sentry", "posthog", "razorpay", "oauth", "jwt", "bcrypt", "websocket",
    "websockets", "tailwind", "shadcn", "figma", "git", "github", "jira", "agile",
    "data structures", "algorithms", "dsa", "oop", "dbms", "operating systems",
}

DEGREE_RE = re.compile(
    r"(?i)\b(B\.?\s?Tech|M\.?\s?Tech|B\.?\s?E\.?|M\.?\s?E\.?|BSc|MSc|Bachelor|Master|MBA|PhD|Diploma)\b"
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_RANGE_RE = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)?\.?\s*(?:19|20)?\d{2}\s*(?:-|–|to)\s*(?:present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)?\.?\s*(?:19|20)?\d{2})\b"
)

SECTION_ALIASES = {
    "summary": {"summary", "profile", "objective", "about", "professional summary"},
    "skills": {"skills", "technical skills", "technologies", "tools", "core competencies"},
    "education": {"education", "academic background", "academics"},
    "experience": {"experience", "work experience", "professional experience", "employment", "internship"},
    "projects": {"projects", "personal projects", "academic projects", "selected projects"},
    "certifications": {"certifications", "certificates", "licenses"},
    "languages": {"languages"},
}


def _clean_lines(text: str) -> List[str]:
    lines = []
    for raw in (text or "").replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip(" -•\t")
        if line:
            lines.append(line)
    return lines


def _section_key(line: str) -> Optional[str]:
    normalized = re.sub(r"[^a-zA-Z ]", "", line).strip().lower()
    if len(normalized.split()) > 4:
        return None
    for key, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _sections(lines: List[str]) -> Dict[str, List[str]]:
    current = "header"
    sections: Dict[str, List[str]] = {current: []}
    for line in lines:
        key = _section_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


_NLP = None
_NLP_LOADED = False


def _spacy_person(lines: List[str]) -> Optional[str]:
    global _NLP, _NLP_LOADED
    if not _NLP_LOADED:
        try:
            import spacy

            _NLP = spacy.load("en_core_web_sm")
        except Exception:
            _NLP = None
        _NLP_LOADED = True
    if not _NLP:
        return None
    try:
        doc = _NLP("\n".join(lines[:12]))
        for ent in doc.ents:
            if ent.label_ == "PERSON" and 1 <= len(ent.text.split()) <= 4:
                return ent.text.strip()
    except Exception:
        logger.debug("spaCy person extraction failed")
    return None


def _extract_name(lines: List[str]) -> Optional[str]:
    person = _spacy_person(lines)
    if person:
        return person
    for line in lines[:10]:
        lower = line.lower()
        if any(token in lower for token in ["@", "linkedin", "github", "phone", "email", "resume", "curriculum"]):
            continue
        if re.search(r"\d", line):
            continue
        words = line.split()
        if 1 < len(words) <= 4 and all(re.match(r"^[A-Za-z][A-Za-z.'-]*$", word) for word in words):
            return line
    return None


def _extract_skills(text: str) -> List[str]:
    lowered = text.lower()
    found: List[str] = []
    for skill in sorted(SKILL_TERMS, key=len, reverse=True):
        pattern = r"(?<![A-Za-z0-9+#.-])" + re.escape(skill) + r"(?![A-Za-z0-9+#.-])"
        if re.search(pattern, lowered):
            display = {
                "nextjs": "Next.js",
                "nodejs": "Node.js",
                "postgres": "PostgreSQL",
                "golang": "Go",
                "dsa": "Data Structures",
                "ci/cd": "CI/CD",
            }.get(skill, skill)
            found.append(display.upper() if display in {"sql", "aws", "gcp", "jwt"} else display.title())
    return list(dict.fromkeys(found))[:40]


def _extract_summary(sections: Dict[str, List[str]]) -> Optional[str]:
    candidates = sections.get("summary") or sections.get("header") or []
    clean = [
        line for line in candidates[:5]
        if len(line.split()) >= 8 and not any(token in line.lower() for token in ["@", "linkedin", "github"])
    ]
    return " ".join(clean)[:900] or None


def _extract_education(sections: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    lines = sections.get("education", [])[:20]
    items: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for line in lines:
        degree = DEGREE_RE.search(line)
        years = YEAR_RE.findall(line)
        if degree and current:
            items.append(current)
            current = {}
        if degree:
            current["degree"] = degree.group(0)
            current["field"] = _field_from_line(line)
        if years:
            current["year"] = years[-1]
        if not current.get("institution") and not degree:
            current["institution"] = line[:160]
        elif degree and not current.get("institution"):
            tail = line[degree.end():].strip(" ,|-")
            if tail:
                current["institution"] = tail[:160]
    if current:
        items.append(current)
    return [
        {
            "degree": item.get("degree"),
            "institution": item.get("institution"),
            "year": item.get("year"),
            "field": item.get("field"),
        }
        for item in items[:6]
    ]


def _field_from_line(line: str) -> Optional[str]:
    match = re.search(r"(?i)(computer science|information technology|data science|electronics|mechanical|civil|ai|artificial intelligence|machine learning)", line)
    return match.group(0) if match else None


def _extract_experience(sections: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    lines = sections.get("experience", [])[:80]
    items: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    bullets: List[str] = []

    def flush() -> None:
        nonlocal current, bullets
        if current or bullets:
            description = "; ".join(bullets)[:1600]
            if current or description:
                items.append({
                    "title": current.get("title"),
                    "company": current.get("company"),
                    "duration": current.get("duration"),
                    "description": description or current.get("description"),
                })
        current = {}
        bullets = []

    for line in lines:
        date_range = DATE_RANGE_RE.search(line)
        looks_like_title = (
            date_range
            or bool(re.search(r"(?i)\b(engineer|developer|intern|manager|analyst|consultant|lead|architect)\b", line))
        ) and len(line.split()) <= 14
        if looks_like_title:
            if current or bullets:
                flush()
            if date_range:
                current["duration"] = date_range.group(0)
                line = (line[:date_range.start()] + line[date_range.end():]).strip(" ,|-")
            parts = re.split(r"\s+(?:at|@|\|)\s+|,| - ", line, maxsplit=1, flags=re.I)
            current["title"] = parts[0].strip()[:120] if parts else line[:120]
            if len(parts) > 1:
                current["company"] = parts[1].strip()[:120]
        else:
            bullets.append(line)
    flush()
    return [item for item in items if any(item.values())][:8]


def _extract_projects(sections: Dict[str, List[str]], full_text: str) -> List[Dict[str, Any]]:
    lines = sections.get("projects", [])[:80]
    if not lines:
        return []
    projects: List[Dict[str, Any]] = []
    current_name: Optional[str] = None
    bullets: List[str] = []

    def flush() -> None:
        nonlocal current_name, bullets
        if current_name or bullets:
            description = "; ".join(bullets)[:1800]
            techs = [skill for skill in _extract_skills(f"{current_name or ''} {description}")[:12]]
            projects.append({
                "name": current_name or (bullets[0][:80] if bullets else None),
                "description": description,
                "technologies": techs,
            })
        current_name = None
        bullets = []

    for line in lines:
        is_heading = len(line.split()) <= 8 and not line.endswith(".") and not line.lower().startswith(("built", "created", "implemented", "designed"))
        if is_heading:
            if current_name or bullets:
                flush()
            current_name = re.sub(r"\s*\|.*$", "", line).strip()
        else:
            bullets.append(line)
    flush()
    return projects[:8]


def _extract_simple_list(sections: Dict[str, List[str]], key: str) -> List[str]:
    text = " ".join(sections.get(key, []))
    if not text:
        return []
    pieces = re.split(r"[,;|•\n]+", text)
    return [piece.strip() for piece in pieces if piece.strip()][:20]


def _target_role(experience: List[Dict[str, Any]], skills: List[str]) -> Optional[str]:
    if experience and experience[0].get("title"):
        return str(experience[0]["title"])
    if any(skill.lower() in {"react", "next.js", "node.js", "typescript"} for skill in skills):
        return "Full Stack Developer"
    if any(skill.lower() in {"machine learning", "deep learning", "pytorch", "tensorflow"} for skill in skills):
        return "Machine Learning Engineer"
    if any(skill.lower() in {"python", "fastapi", "django", "postgresql"} for skill in skills):
        return "Backend Engineer"
    return None


def _confidence(profile: Dict[str, Any], parser_name: str) -> Dict[str, Any]:
    components = {
        "name": 1.0 if profile.get("name") else 0.0,
        "skills": min(1.0, len(profile.get("skills") or []) / 6),
        "education": 1.0 if profile.get("education") else 0.0,
        "experience_or_projects": 1.0 if (profile.get("experience") or profile.get("projects")) else 0.0,
        "parser": 0.9 if "paddleocr" not in parser_name else 0.78,
    }
    overall = round(sum(components.values()) / len(components), 2)
    return {
        "overall": overall,
        "source": "rule_based",
        "components": components,
        "notes": "AI fallback recommended" if overall < 0.72 else "Rule extraction confidence is sufficient",
    }


def extract_rule_based_profile(
    resume_text: str,
    *,
    links: Optional[List[str]] = None,
    parser_name: str = "resume_parser",
) -> Dict[str, Any]:
    lines = _clean_lines(resume_text)
    sections = _sections(lines)
    full_text = "\n".join(lines)
    skills = _extract_skills(full_text)
    experience = _extract_experience(sections)
    projects = _extract_projects(sections, full_text)
    links = links or []

    normalized_links = {
        "linkedin": next((url for url in links if "linkedin.com/in" in url.lower()), None),
        "github": next((url for url in links if "github.com" in url.lower()), None),
        "portfolio": next((url for url in links if "linkedin.com" not in url.lower() and "github.com" not in url.lower()), None),
    }

    profile = {
        "name": _extract_name(lines),
        "email": None,
        "phone": None,
        "linkedin": normalized_links["linkedin"],
        "github": normalized_links["github"],
        "portfolio": normalized_links["portfolio"],
        "summary": _extract_summary(sections),
        "target_role": _target_role(experience, skills),
        "skills": skills,
        "education": _extract_education(sections),
        "experience": experience,
        "projects": projects,
        "languages": _extract_simple_list(sections, "languages"),
        "certifications": _extract_simple_list(sections, "certifications"),
        "links": normalized_links,
        "profile_sources": ["resume_rules", parser_name],
        "evidence": {
            "skills": skills[:12],
            "projects": [project.get("name") for project in projects[:5] if project.get("name")],
        },
    }
    profile["confidence"] = _confidence(profile, parser_name)
    return profile
