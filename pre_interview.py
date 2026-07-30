# ============================================================================
# MODULE: pre_interview.py
# PURPOSE: Resume upload + parse + AI enrichment, profile confirm/edit/reset.
#          Owns /api/pre-interview routes (router carries its own prefix).
# STRUCTURE:
#   - Background profile-enrichment worker (lines 49-55)
#   - Resume parsing + retry helpers
#   - Route handlers (lines 364-700)
# ENDPOINTS (prefix /api/pre-interview):
#   - POST   /upload-resume    -> parse PDF/DOCX + enrich (line 364)
#   - POST   /confirm-profile  -> persist edited profile_json (435)
#   - GET    /form             -> current profile + resume snapshot (504)
#   - POST   /submit-form      -> save form-completed profile (531)
#   - GET    /profile-status   -> {profile_completed, resume_uploaded} (577)
#   - DELETE /reset-profile    -> wipe profile_json/resume (616)
# DEPENDS ON: auth, database, resume_parser, profile_enrichment, llm_router,
#             prompt_security, security_utils, config
# CONSUMED BY: app.py, Frontend/lib/api.ts (uploadResume, submitResume, getResume)
# DATA TABLES: UserInfo (resume_json/profile_json), ResumeUploadLogs (audit log)
# ============================================================================

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Request
from pydantic import BaseModel, Field, field_validator
from typing import Any, Iterable, Literal, Optional
import json
import os
import logging
import re
import asyncio
import tempfile
import time
import hashlib
import uuid

from auth import get_current_user
from database import get_db, transaction
from resume_parser import parse_resume_structured

from profile_enrichment import enrich_profile_for_user
from config import settings
from llm_router import complete_json_async
from prompt_security import SYSTEM_DATA_BOUNDARY, data_block
from security_utils import (
    EMAIL_PATTERN,
    PHONE_PATTERNS,
    SOCIAL_PATTERNS,
    decrypt_data,
    decrypt_json,
    encrypt_data,
    encrypt_json,
    redact_pii_text,
    redact_text,
    stable_hash,
)

router = APIRouter(prefix="/api/pre-interview", tags=["Pre-Interview"])
logger = logging.getLogger("pre_interview")


def _decrypt_text_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return decrypt_data(value) if isinstance(value, str) else ""

MAX_RESUME_TEXT_LENGTH = settings.MAX_RESUME_TEXT_LENGTH
RESUME_MAX_FILE_BYTES = settings.RESUME_MAX_FILE_SIZE_MB * 1024 * 1024

AI_MAX_RETRIES = settings.AI_MAX_RETRIES
AI_RETRY_DELAY_SECONDS = settings.AI_RETRY_DELAY_SECONDS

ALLOWED_EXTENSIONS = {".pdf", ".docx"}

RESUME_VERSION_SELECT = """
    SELECT resume_id, version_number, resume_payload_encrypted, facts_encrypted,
           derived_taxonomy, is_active, confirmation_status, content_hash,
           parser_version, source_filename, created_at, updated_at, resume_json,
           parent_resume_id, superseded_at, immutable_at,
           immutable_at IS NOT NULL
               OR EXISTS (SELECT 1 FROM Interviews interview WHERE interview.resume_id = ResumeVersions.resume_id)
               OR EXISTS (SELECT 1 FROM InterviewBlueprints blueprint WHERE blueprint.resume_id = ResumeVersions.resume_id)
               OR EXISTS (SELECT 1 FROM AttemptContextSnapshots snapshot WHERE snapshot.resume_id = ResumeVersions.resume_id)
               AS referenced
    FROM ResumeVersions
"""

REVIEWABLE_RESUME_FIELDS = (
    "name",
    "summary",
    "target_role",
    "skills",
    "education",
    "experience",
    "projects",
    "languages",
    "certifications",
    "achievements",
)


class ResumeFactDecision(BaseModel):
    fact_id: str = Field(min_length=8, max_length=80)
    action: Literal["confirm", "correct", "reject"]
    corrected_value: Any = None

    @field_validator("corrected_value")
    @classmethod
    def validate_corrected_value(cls, value: Any) -> Any:
        if value is None:
            return value
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except Exception as exc:
            raise ValueError("Corrected value must be JSON serializable") from exc
        if len(serialized) > 12_000:
            raise ValueError("Corrected value is too large")
        return value


class ResumeFactsPatch(BaseModel):
    decisions: list[ResumeFactDecision] = Field(min_length=1, max_length=40)


def _encrypted_json_blob(value: Any) -> bytes:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return encrypt_data(serialized).encode("utf-8")


def _decrypted_json_blob(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return value
    try:
        decoded = decrypt_data(value)
        parsed = json.loads(decoded)
        return parsed
    except Exception:
        return fallback


def _resume_taxonomy(resume: dict[str, Any]) -> dict[str, Any]:
    skills = _normalize_string_list(resume.get("skills"))[:40]
    project_names = [
        str(item.get("name") or "").strip()[:120]
        for item in (resume.get("projects") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ][:12]
    roles = [
        str(item.get("role") or item.get("title") or "").strip()[:120]
        for item in (resume.get("experience") or [])
        if isinstance(item, dict) and str(item.get("role") or item.get("title") or "").strip()
    ][:12]
    return {
        "taxonomy_version": "resume-taxonomy-v1",
        "skills": skills,
        "project_names": project_names,
        "experience_roles": roles,
        "target_role": str(resume.get("target_role") or "").strip()[:160] or None,
    }


def _source_excerpt(source_text: str, value: Any) -> Optional[str]:
    candidate = ""
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            candidate = first
        elif isinstance(first, dict):
            candidate = str(first.get("name") or first.get("title") or first.get("role") or "")
    candidate = re.sub(r"\s+", " ", candidate).strip()
    normalized_source = re.sub(r"\s+", " ", source_text or "")
    if not candidate or not normalized_source:
        return None
    index = normalized_source.lower().find(candidate.lower()[:100])
    if index < 0:
        return None
    start = max(0, index - 80)
    return normalized_source[start:index + min(len(candidate), 180) + 120][:380]


def _resume_fact_payload(
    resume: dict[str, Any],
    *,
    source_text: str,
    parser_version: str,
) -> dict[str, Any]:
    confidence = resume.get("confidence") if isinstance(resume.get("confidence"), dict) else {}
    overall = str(confidence.get("overall") or "medium").strip().lower()
    default_status = "confirmed" if overall == "high" else "pending"
    facts: list[dict[str, Any]] = []
    for field_name in REVIEWABLE_RESUME_FIELDS:
        value = resume.get(field_name)
        if value in (None, "", [], {}):
            continue
        fact_id = "fact_" + hashlib.sha256(f"resume:{field_name}".encode("utf-8")).hexdigest()[:20]
        facts.append({
            "fact_id": fact_id,
            "field": field_name,
            "original_value": value,
            "corrected_value": None,
            "status": default_status,
            "confidence": overall,
            "source_text": _source_excerpt(source_text, value),
            "parser_version": parser_version,
        })
    return {
        "review_version": "resume-facts-v1",
        "facts": facts,
    }


def _confirmation_status(facts_payload: dict[str, Any]) -> str:
    facts = facts_payload.get("facts") if isinstance(facts_payload, dict) else []
    return "needs_review" if any(item.get("status") == "pending" for item in facts or []) else "confirmed"


def _materialize_resume(resume: dict[str, Any], facts_payload: dict[str, Any]) -> dict[str, Any]:
    materialized = dict(resume or {})
    for fact in (facts_payload.get("facts") or [] if isinstance(facts_payload, dict) else []):
        field_name = str(fact.get("field") or "")
        if field_name not in REVIEWABLE_RESUME_FIELDS:
            continue
        if fact.get("status") == "corrected":
            materialized[field_name] = fact.get("corrected_value")
        elif fact.get("status") == "rejected":
            materialized.pop(field_name, None)
    return validate_resume_json(materialized)


def _resume_version_payload(row: Any) -> dict[str, Any]:
    encrypted_resume = _decrypted_json_blob(row[2], None)
    if not isinstance(encrypted_resume, dict):
        encrypted_resume = decrypt_json(row[12]) if row[12] is not None else {}
    if not isinstance(encrypted_resume, dict):
        encrypted_resume = {}
    facts = _decrypted_json_blob(row[3], {"review_version": "resume-facts-v1", "facts": []})
    if not isinstance(facts, dict):
        facts = {"review_version": "resume-facts-v1", "facts": []}
    taxonomy = row[4] or {}
    if isinstance(taxonomy, str):
        try:
            taxonomy = json.loads(taxonomy)
        except Exception:
            taxonomy = {}
    materialized = _materialize_resume(encrypted_resume, facts)
    return {
        "resume_id": row[0],
        "version_number": int(row[1]),
        "resume_payload": materialized,
        "facts": facts.get("facts") or [],
        "derived_taxonomy": taxonomy if isinstance(taxonomy, dict) else {},
        "is_active": bool(row[5]),
        "confirmation_status": row[6] or _confirmation_status(facts),
        "content_hash": row[7],
        "parser_version": row[8],
        "source_filename": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
        "updated_at": row[11].isoformat() if row[11] else None,
        "parent_resume_id": row[13] if len(row) > 13 else None,
        "superseded_at": row[14].isoformat() if len(row) > 14 and row[14] else None,
        "immutable": bool(row[15]) if len(row) > 15 else False,
        "referenced": bool(row[16]) if len(row) > 16 else bool(row[15]) if len(row) > 15 else False,
    }


def _load_resume_version(cursor: Any, user_id: str, resume_id: str) -> Optional[dict[str, Any]]:
    cursor.execute(
        RESUME_VERSION_SELECT + " WHERE user_id = %s AND resume_id = %s",
        (user_id, resume_id),
    )
    row = cursor.fetchone()
    return _resume_version_payload(row) if row else None

_enrichment_tasks = set()
RESUME_UPLOAD_AI_TIMEOUT_SECONDS = 20.0
RESUME_PARSE_TIMEOUT_SECONDS = 15.0

async def _run_profile_enrichment(user_id: str, profile: dict[str, Any]) -> None:
    try:
        await enrich_profile_for_user(user_id, profile)
    except Exception:
        logger.error("Profile enrichment failed for %s", stable_hash(user_id, "user"))

def schedule_profile_enrichment(user_id: str, profile: dict[str, Any]) -> None:
    task = asyncio.create_task(_run_profile_enrichment(user_id, profile))
    _enrichment_tasks.add(task)
    task.add_done_callback(_enrichment_tasks.discard)

def extract_contact_info(text: str) -> dict[str, Any]:
    email_match = EMAIL_PATTERN.search(text)
    email = email_match.group(0) if email_match else None

    phone = None
    for pat in PHONE_PATTERNS:
        match = pat.search(text)
        if match:
            phone = match.group(0)
            break

    return {"email": email, "phone": phone}

def extract_social_links(text: str) -> dict[str, Any]:
    linkedin = None
    github = None
    portfolio = None

    li_match = re.search(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', text, re.I)
    if not li_match:
        li_match = re.search(r'linkedin\.com/in/[A-Za-z0-9_-]+/?', text, re.I)
    if li_match:
        raw_url = li_match.group(0)
        linkedin = raw_url if raw_url.startswith('http') else f'https://{raw_url}'

    gh_match = re.search(r'https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+/?', text, re.I)
    if not gh_match:
        gh_match = re.search(r'github\.com/[A-Za-z0-9_-]+/?', text, re.I)
    if gh_match:
        raw_url = gh_match.group(0)
        github = raw_url if raw_url.startswith('http') else f'https://{raw_url}'

    for pat in SOCIAL_PATTERNS:
        for hit in pat.finditer(text):
            url = hit.group(0).lower()
            if 'linkedin.com' in url or 'github.com' in url:
                continue
            if any(x in url for x in ['twitter.com', 'x.com', 'facebook.com', 'instagram.com']):
                continue
            portfolio = hit.group(0)
            break
        if portfolio:
            break

    return {"linkedin": linkedin, "github": github, "portfolio": portfolio}

def remove_pii(text: str, *, extra_values: Iterable[str] | None = None) -> str:
    return redact_pii_text(text, extra_values=extra_values)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if item and str(item).strip()]
    if isinstance(value, str) and value.strip():
        parts = re.split(r"[,;\n]+", value)
        return [part.strip() for part in parts if part.strip()]
    return []

def validate_resume_json(data: dict[str, Any]) -> dict[str, Any]:
    name = None
    if isinstance(data.get("name"), str) and data["name"].strip():
        name = data["name"].strip()

    email = None
    if isinstance(data.get("email"), str) and data["email"].strip():
        email = data["email"].strip()

    phone = None
    if isinstance(data.get("phone"), str) and data["phone"].strip():
        phone = data["phone"].strip()

    string_fields: dict[str, Any] = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "summary": None,
        "target_role": None,
    }
    for field_name in string_fields:
        raw = data.get(field_name)
        if isinstance(raw, str) and raw.strip():
            string_fields[field_name] = raw.strip()

    skills: list[str] = []
    if isinstance(data.get("skills"), list):
        skills = [str(s).strip() for s in data["skills"] if s and str(s).strip()]

    education: list[dict[str, Any]] = []
    if isinstance(data.get("education"), list):
        for edu in data["education"]:
            if not isinstance(edu, dict):
                continue
            education.append({
                "degree": str(edu.get("degree", "")).strip() or None,
                "institution": str(edu.get("institution", "")).strip() or None,
                "year": str(edu.get("year", "")).strip() or None,
                "field": str(edu.get("field", "")).strip() or None,
            })

    experience: list[dict[str, Any]] = []
    if isinstance(data.get("experience"), list):
        for exp in data["experience"]:
            if not isinstance(exp, dict):
                continue
            experience.append({
                "title": str(exp.get("title", "")).strip() or None,
                "company": str(exp.get("company", "")).strip() or None,
                "duration": str(exp.get("duration", "")).strip() or None,
                "description": str(exp.get("description", "")).strip() or None,
            })

    projects: list[dict[str, Any]] = []
    if isinstance(data.get("projects"), list):
        for proj in data["projects"]:
            if not isinstance(proj, dict):
                continue
            tech = proj.get("technologies", [])
            if not isinstance(tech, list):
                tech = []
            projects.append({
                "name": str(proj.get("name", "")).strip() or None,
                "description": str(proj.get("description", "")).strip() or None,
                "technologies": [str(t).strip() for t in tech if t],
            })

    languages: list[str] = []
    if isinstance(data.get("languages"), list):
        languages = [str(lang).strip() for lang in data["languages"] if lang and str(lang).strip()]

    certifications: list[str] = []
    if isinstance(data.get("certifications"), list):
        certifications = [str(cert).strip() for cert in data["certifications"] if cert and str(cert).strip()]

    soft_skills = _normalize_string_list(data.get("soft_skills"))
    achievements = _normalize_string_list(data.get("achievements"))
    interests = _normalize_string_list(data.get("interests"))

    links = data.get("links") if isinstance(data.get("links"), dict) else {}
    normalized_links = {
        "linkedin": string_fields["linkedin"] or links.get("linkedin"),
        "github": string_fields["github"] or links.get("github"),
        "portfolio": string_fields["portfolio"] or links.get("portfolio"),
    }

    profile_sources = data.get("profile_sources") if isinstance(data.get("profile_sources"), list) else []
    evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    confidence = data.get("confidence") if isinstance(data.get("confidence"), dict) else {}

    return {
        "name": name,
        "email": email,
        "phone": phone,
        **string_fields,
        "skills": skills,
        "education": education,
        "experience": experience,
        "projects": projects,
        "languages": languages,
        "certifications": certifications,
        "soft_skills": soft_skills,
        "achievements": achievements,
        "interests": interests,
        "links": normalized_links,
        "profile_sources": profile_sources,
        "evidence": evidence,
        "confidence": confidence,
    }


COMMON_SKILL_PATTERNS: list[tuple[str, str]] = [
    ("JavaScript", r"\b(?:javascript|js)\b"),
    ("TypeScript", r"\btypescript\b"),
    ("Python", r"\bpython\b"),
    ("Java", r"\bjava\b"),
    ("C++", r"\bc\+\+\b"),
    ("C", r"\bc\b"),
    ("Go", r"\bgolang\b|\bgo\b"),
    ("Rust", r"\brust\b"),
    ("React", r"\breact(?:\.js)?\b"),
    ("Next.js", r"\bnext(?:\.js)?\b"),
    ("Node.js", r"\bnode(?:\.js)?\b"),
    ("Express", r"\bexpress(?:\.js)?\b"),
    ("FastAPI", r"\bfastapi\b"),
    ("Django", r"\bdjango\b"),
    ("Flask", r"\bflask\b"),
    ("Spring Boot", r"\bspring boot\b"),
    ("HTML", r"\bhtml5?\b"),
    ("CSS", r"\bcss3?\b"),
    ("Tailwind CSS", r"\btailwind(?: css)?\b"),
    ("SQL", r"\bsql\b"),
    ("PostgreSQL", r"\bpostgres(?:ql)?\b"),
    ("MySQL", r"\bmysql\b"),
    ("MongoDB", r"\bmongodb\b"),
    ("Redis", r"\bredis\b"),
    ("Docker", r"\bdocker\b"),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("AWS", r"\baws\b|amazon web services"),
    ("Azure", r"\bazure\b"),
    ("Google Cloud", r"\bgcp\b|google cloud"),
    ("Git", r"\bgit\b"),
    ("Linux", r"\blinux\b"),
    ("REST API", r"\brest(?:ful)? api\b|\bapis?\b"),
    ("GraphQL", r"\bgraphql\b"),
    ("Microservices", r"\bmicroservices?\b"),
    ("Machine Learning", r"\bmachine learning\b|\bml\b"),
    ("Deep Learning", r"\bdeep learning\b"),
    ("NLP", r"\bnlp\b|natural language processing"),
    ("Computer Vision", r"\bcomputer vision\b"),
    ("Pandas", r"\bpandas\b"),
    ("NumPy", r"\bnumpy\b"),
    ("TensorFlow", r"\btensorflow\b"),
    ("PyTorch", r"\bpytorch\b"),
    ("scikit-learn", r"\bscikit[- ]learn\b|\bsklearn\b"),
]

SECTION_ALIASES: dict[str, str] = {
    "skills": "skills",
    "technical skills": "skills",
    "technologies": "skills",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "projects": "projects",
    "project experience": "projects",
    "education": "education",
    "certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
    "summary": "summary",
    "profile": "summary",
    "objective": "summary",
}


def _resume_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t|-*•")
        if line:
            lines.append(line)
    return lines


def _clean_list_item(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t,;:-|")


def _split_inline_items(value: str) -> list[str]:
    normalized = value.replace("•", ",").replace("|", ",").replace(";", ",")
    return [_clean_list_item(item) for item in normalized.split(",") if _clean_list_item(item)]


def _looks_like_section_header(line: str) -> str | None:
    key = re.sub(r"[^a-z ]", "", line.lower()).strip()
    if key in SECTION_ALIASES:
        return SECTION_ALIASES[key]
    if len(key.split()) <= 3:
        for alias, section in SECTION_ALIASES.items():
            if key == alias:
                return section
    return None


def _section_map(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        header = _looks_like_section_header(line)
        if header:
            current = header
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return sections


def _extract_name_from_lines(lines: list[str]) -> str | None:
    for line in lines[:12]:
        lower = line.lower()
        if EMAIL_PATTERN.search(line) or any(pat.search(line) for pat in SOCIAL_PATTERNS):
            continue
        if any(token in lower for token in ("resume", "curriculum", "github", "linkedin", "http", "www.")):
            continue
        if any(char.isdigit() for char in line):
            continue
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z'.-]*", line) if len(word) > 1]
        if 2 <= len(words) <= 5 and len(line) <= 80:
            return " ".join(word.capitalize() if word.isupper() else word for word in words)
    return None


def _extract_skills_from_text(text: str, sections: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(skill: str) -> None:
        cleaned = _clean_list_item(skill)
        if not cleaned or len(cleaned) > 40:
            return
        if cleaned.lower() in {"skills", "technical skills", "tools", "and", "or"}:
            return
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            found.append(cleaned)

    for label, pattern in COMMON_SKILL_PATTERNS:
        if re.search(pattern, text or "", re.I):
            add(label)

    for line in sections.get("skills", [])[:12]:
        for item in _split_inline_items(line):
            if len(item.split()) <= 5:
                add(item)

    return found[:30]


def _extract_summary(lines: list[str], sections: dict[str, list[str]]) -> str | None:
    summary_lines = sections.get("summary", [])
    if summary_lines:
        return " ".join(summary_lines[:4])[:1200] or None

    candidates: list[str] = []
    for line in lines[:18]:
        lower = line.lower()
        if EMAIL_PATTERN.search(line) or any(pat.search(line) for pat in SOCIAL_PATTERNS):
            continue
        if _looks_like_section_header(line):
            continue
        if any(token in lower for token in ("linkedin", "github", "phone", "email")):
            continue
        if len(line.split()) >= 6:
            candidates.append(line)
        if len(candidates) >= 3:
            break
    return " ".join(candidates)[:1200] or None


def _extract_target_role(text: str, sections: dict[str, list[str]]) -> str | None:
    role_keywords = (
        r"engineer|developer|analyst|manager|designer|architect|scientist|"
        r"intern|consultant|lead|director|specialist|associate|administrator|"
        r"coordinator|recruiter|marketer|accountant"
    )
    for line in sections.get("experience", [])[:10]:
        cleaned = re.sub(r"^\s*[-•*]\s*", "", line).strip()
        if not cleaned or len(cleaned) > 140:
            continue
        for sep in (" at ", " @ ", " | ", " — ", " – ", " - "):
            if sep in cleaned:
                title = cleaned.split(sep, 1)[0].strip(" -|,")
                if 3 <= len(title) <= 70 and re.search(role_keywords, title, re.I):
                    return title
        if re.search(rf"\b({role_keywords})\b", cleaned, re.I):
            return cleaned[:70]
    objective_lines = sections.get("summary", [])[:4]
    for line in objective_lines:
        match = re.search(
            rf"\b((?:senior |lead |staff |principal )?(?:{role_keywords}))\b",
            line,
            re.I,
        )
        if match:
            return match.group(1).title()
    match = re.search(
        rf"\b((?:senior |lead |staff |principal )?(?:{role_keywords}))\b",
        text[:2500],
        re.I,
    )
    return match.group(1).title() if match else None


def _extract_education(sections: dict[str, list[str]]) -> list[dict[str, Any]]:
    education: list[dict[str, Any]] = []
    edu_lines = sections.get("education", [])
    if not edu_lines:
        return education

    degree_pattern = re.compile(r"\b(b\.?tech|m\.?tech|bachelor|master|mba|b\.?e\.?|m\.?e\.?|bsc|msc|phd|diploma)\b", re.I)
    year_pattern = re.compile(r"\b(19|20)\d{2}\b")
    for line in edu_lines[:8]:
        if not (degree_pattern.search(line) or year_pattern.search(line)):
            continue
        year_match = year_pattern.search(line)
        education.append({
            "degree": line,
            "institution": None,
            "year": year_match.group(0) if year_match else None,
            "field": None,
        })
        if len(education) >= 3:
            break
    return education


def _extract_projects(sections: dict[str, list[str]]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    project_lines = sections.get("projects", [])
    if not project_lines:
        return projects

    current: dict[str, Any] | None = None
    for line in project_lines[:24]:
        if len(line) <= 90 and not line.endswith(".") and len(line.split()) <= 8:
            if current:
                projects.append(current)
                if len(projects) >= 4:
                    break
            current = {"name": line, "description": "", "technologies": []}
        else:
            if not current:
                current = {"name": "Project", "description": "", "technologies": []}
            current["description"] = _clean_list_item(f"{current.get('description', '')} {line}")
    if current and len(projects) < 4:
        projects.append(current)
    return projects


def _extract_experience(sections: dict[str, list[str]]) -> list[dict[str, Any]]:
    exp_lines = sections.get("experience", [])
    if not exp_lines:
        return []

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    year_pattern = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|[01]?[0-9])[./\s-]*(?:19|20)\d{2}\b", re.I)

    def flush() -> None:
        nonlocal current
        if current and (current.get("title") or current.get("company") or current.get("description")):
            entries.append(current)
        current = None

    for line in exp_lines[:28]:
        cleaned = re.sub(r"^\s*[-•*]\s*", "", line).strip()
        if not cleaned:
            continue
        looks_like_header = (
            year_pattern.search(cleaned)
            or " at " in cleaned.lower()
            or " @ " in cleaned.lower()
            or (
                len(cleaned) <= 90
                and re.search(r"\b(engineer|developer|analyst|manager|intern|consultant|lead|director)\b", cleaned, re.I)
            )
        )
        if looks_like_header and current and current.get("description"):
            flush()
        if looks_like_header and not current:
            title = cleaned
            company = None
            duration = None
            for sep in (" at ", " @ "):
                if sep in cleaned.lower():
                    parts = re.split(sep, cleaned, maxsplit=1, flags=re.I)
                    title = parts[0].strip()
                    company = parts[1].strip() if len(parts) > 1 else None
                    break
            if year_pattern.search(cleaned):
                duration = year_pattern.findall(cleaned)
                duration = " - ".join(duration[:2]) if duration else cleaned
            current = {
                "title": title[:120] if title else None,
                "company": company[:120] if company else None,
                "duration": duration[:80] if isinstance(duration, str) else None,
                "description": "",
            }
            continue
        if not current:
            current = {"title": None, "company": None, "duration": None, "description": ""}
        current["description"] = _clean_list_item(f"{current.get('description', '')} {cleaned}")

    flush()
    if entries:
        return entries[:6]

    description = " ".join(exp_lines[:12])[:1600]
    title = None
    company = None
    for line in exp_lines[:8]:
        if not title and re.search(r"\b(engineer|developer|analyst|manager|intern|consultant|lead)\b", line, re.I):
            title = line[:120]
        elif not company and len(line.split()) <= 8:
            company = line[:120]
    return [{
        "title": title,
        "company": company,
        "duration": None,
        "description": description or None,
    }]


def extract_resume_with_rules(
    resume_text: str,
    contact: dict[str, Any],
    social: dict[str, Any],
    parsed_resume: dict[str, Any],
) -> dict[str, Any]:
    lines = _resume_lines(resume_text)
    sections = _section_map(lines)
    skills = _extract_skills_from_text(resume_text, sections)
    fallback = {
        "name": _extract_name_from_lines(lines),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin": social.get("linkedin"),
        "github": social.get("github"),
        "portfolio": social.get("portfolio"),
        "summary": _extract_summary(lines, sections),
        "target_role": _extract_target_role(resume_text, sections),
        "skills": skills,
        "education": _extract_education(sections),
        "experience": _extract_experience(sections),
        "projects": _extract_projects(sections),
        "languages": [],
        "certifications": sections.get("certifications", [])[:8],
        "links": {
            "linkedin": social.get("linkedin"),
            "github": social.get("github"),
            "portfolio": social.get("portfolio"),
            "all": parsed_resume.get("links", []),
        },
        "profile_sources": [parsed_resume.get("parser", "resume_parser"), "rule_fallback"],
        "evidence": {"skills": skills[:8], "projects": sections.get("projects", [])[:4]},
        "confidence": {
            "overall": "medium" if skills else "low",
            "notes": "Rule-based extraction used because AI extraction was unavailable or incomplete.",
        },
    }
    return validate_resume_json(fallback)


def _merge_resume_profiles(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = validate_resume_json(primary or {})
    for key, fallback_value in fallback.items():
        current_value = merged.get(key)
        if key == "links":
            links = current_value if isinstance(current_value, dict) else {}
            fallback_links = fallback_value if isinstance(fallback_value, dict) else {}
            merged[key] = {**fallback_links, **{k: v for k, v in links.items() if v}}
            continue
        if key in {"profile_sources"}:
            values = []
            for item in (current_value or []) + (fallback_value or []):
                if item and item not in values:
                    values.append(item)
            merged[key] = values
            continue
        if not current_value and fallback_value:
            merged[key] = fallback_value
    return validate_resume_json(merged)

EXTRACTION_PROMPT = """\
Extract ALL information from this resume. Be thorough and comprehensive. Do NOT summarize or shorten anything.

Required JSON structure:
{{
  "name": "Full Name",
  "links": {{"linkedin": null, "github": null, "portfolio": null}},
  "summary": "Find and copy verbatim any introductory or biographical text about the candidate — their professional summary, about section, objective, or any opening paragraph. If none exists, use null.",
  "target_role": "Infer the most likely target job role from the resume content (e.g. 'Software Engineer', 'Data Scientist'). Use the most recent job title or objective if available.",
  "skills": ["skill1", "skill2", "skill3"],
  "education": [
    {{
      "degree": "B.Tech/M.Tech/MBA/etc",
      "institution": "University/College Name",
      "year": "2020 or 2018-2020",
      "field": "Computer Science/Mechanical/etc"
    }}
  ],
  "experience": [
    {{
      "title": "Job Title",
      "company": "Company Name",
      "duration": "Jan 2020 - Dec 2022",
      "description": "COMPLETE description with ALL bullet points combined into a single string, separated by semicolons"
    }}
  ],
  "projects": [
    {{
      "name": "Project Name",
      "description": "COMPLETE and DETAILED description. Include EVERY bullet point separated by semicolons. Do NOT truncate.",
      "technologies": ["Python", "FastAPI", "React"]
    }}
  ],
  "languages": ["English", "Hindi"],
  "certifications": ["AWS Solutions Architect", "Google Cloud Professional"],
  "profile_sources": ["resume"],
  "evidence": {{"skills": ["short snippets that support extracted skills"], "projects": ["short snippets that support extracted projects"]}},
  "confidence": {{"overall": "high|medium|low", "notes": "brief extraction caveats"}}
}}

- Extract ALL skills (technical, soft skills, languages, frameworks, tools, databases)
- Include ALL work experience with FULL descriptions
- Include ALL projects with EVERY detail
- For the summary field: find ANY introductory or about text from the resume, copy it exactly
- target_role: infer from the most recent job title or objective statement
- If a field is not found, use [] or null
- Return ONLY valid JSON, no markdown
- Ignore [EMAIL_REMOVED], [PHONE_REMOVED], [LINK_REMOVED], [CARD_REMOVED], [SSN_REMOVED] placeholders

Resume Text:
{resume_text}"""

RESUME_FORM_JSON_SPEC = """\
{
  "name": "Full legal name",
  "email": null,
  "phone": null,
  "linkedin": null,
  "github": null,
  "portfolio": null,
  "summary": "Professional summary / about / objective (verbatim when present)",
  "target_role": "Best-fit next job title (2-5 words)",
  "skills": ["technical skills, tools, frameworks"],
  "soft_skills": ["communication", "leadership"],
  "education": [
    {"degree": "...", "institution": "...", "year": "2020", "field": "Computer Science", "cgpa": "8.5"}
  ],
  "experience": [
    {"title": "...", "company": "...", "duration": "Jan 2020 - Dec 2022", "description": "full bullets joined with semicolons"}
  ],
  "projects": [
    {"name": "...", "description": "full detail", "technologies": ["Python", "React"]}
  ],
  "languages": ["English"],
  "certifications": ["AWS Solutions Architect"],
  "achievements": ["award or measurable outcome"],
  "interests": ["optional hobbies"],
  "links": {"linkedin": null, "github": null, "portfolio": null},
  "profile_sources": ["resume_ai"],
  "evidence": {"skills": [], "projects": []},
  "confidence": {"overall": "high|medium|low", "notes": "brief caveats"}
}"""

RESUME_UPLOAD_EXTRACTION_PROMPT = """\
Parse the resume text into JSON that exactly matches the profile edit form below.

Rules:
- Return ONLY valid JSON (no markdown).
- Copy experience and project descriptions completely; join bullet points with semicolons.
- Extract every skill you can find (technical + tools). Put interpersonal skills in soft_skills.
- Use null or [] when a field is missing.
- Ignore placeholders such as [EMAIL_REMOVED], [PHONE_REMOVED], [LINK_REMOVED], [CARD_REMOVED], [SSN_REMOVED], [DOB_REMOVED].
- Do not invent employers, degrees, or projects that are not supported by the text.

Form JSON schema to populate:
{form_schema}

Resume text:
{resume_text}"""


EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": ["string", "null"]},
        "links": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "linkedin": {"type": ["string", "null"]},
                "github": {"type": ["string", "null"]},
                "portfolio": {"type": ["string", "null"]}
            },
            "required": ["linkedin", "github", "portfolio"]
        },
        "summary": {"type": ["string", "null"]},
        "target_role": {"type": ["string", "null"]},
        "skills": {
            "type": "array",
            "items": {"type": "string"}
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "degree": {"type": ["string", "null"]},
                    "institution": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]}
                },
                "required": ["degree", "institution", "year", "field"]
            }
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "company": {"type": ["string", "null"]},
                    "duration": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]}
                },
                "required": ["title", "company", "duration", "description"]
            }
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["name", "description", "technologies"]
            }
        },
        "languages": {
            "type": "array",
            "items": {"type": "string"}
        },
        "certifications": {
            "type": "array",
            "items": {"type": "string"}
        },
        "soft_skills": {
            "type": "array",
            "items": {"type": "string"}
        },
        "achievements": {
            "type": "array",
            "items": {"type": "string"}
        },
        "interests": {
            "type": "array",
            "items": {"type": "string"}
        },
        "profile_sources": {
            "type": "array",
            "items": {"type": "string"}
        },
        "evidence": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["skills", "projects"]
        },
        "confidence": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "overall": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]}
            },
            "required": ["overall", "notes"]
        }
    },
    "required": [
        "name", "links", "summary", "target_role", "skills",
        "education", "experience", "projects", "languages", "certifications",
        "soft_skills", "achievements", "interests",
        "profile_sources", "evidence", "confidence"
    ]
}


async def extract_with_ai_upload(resume_text: str) -> dict[str, Any]:
    trimmed = resume_text[:MAX_RESUME_TEXT_LENGTH]
    prompt = RESUME_UPLOAD_EXTRACTION_PROMPT.format(
        form_schema=RESUME_FORM_JSON_SPEC,
        resume_text=data_block("resume_text", trimmed),
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You extract structured resume data for a profile edit form. "
                "Return valid JSON only that matches the provided schema. "
                f"{SYSTEM_DATA_BOUNDARY}"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    parsed = await asyncio.wait_for(
        complete_json_async(
            messages,
            event_type="resume_parse_fast",
            temperature=0.0,
            max_tokens=4096,
            json_schema=EXTRACTION_SCHEMA,
            provider_policy="openai_required",
            metadata={"reason": "resume_upload"},
        ),
        timeout=RESUME_UPLOAD_AI_TIMEOUT_SECONDS,
    )
    if not isinstance(parsed.get("profile_sources"), list):
        parsed["profile_sources"] = ["resume_ai"]
    if not isinstance(parsed.get("evidence"), dict):
        parsed["evidence"] = {"skills": [], "projects": []}
    if not isinstance(parsed.get("confidence"), dict):
        parsed["confidence"] = {"overall": "high", "notes": "Resume autofill"}
    return validate_resume_json(parsed)






@router.post("/upload-resume")
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any] | None:
    request_id = str(getattr(request.state, "request_id", "") or "unknown")
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Resume file is required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid file type. Allowed: PDF, DOCX")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Resume file is empty")
    if len(content) > RESUME_MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Resume file too large. Maximum: {settings.RESUME_MAX_FILE_SIZE_MB} MB",
        )

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as out_file:
            temp_path = out_file.name
            out_file.write(content)

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        try:
            logger.info("resume_upload_stage request_id=%s stage=parse_started", request_id)
            parsed_resume = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: parse_resume_structured(temp_path, fast=False),
                ),
                timeout=RESUME_PARSE_TIMEOUT_SECONDS,
            )
            resume_text = parsed_resume.get("text", "")
            logger.info(
                "resume_upload_stage request_id=%s stage=parse_completed latency_ms=%s",
                request_id,
                round((time.perf_counter() - started) * 1000, 2),
            )
        except asyncio.TimeoutError:
            logger.warning("resume_upload_stage request_id=%s stage=parse_timeout", request_id)
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Resume parsing timed out. Try a text-based PDF or DOCX.")
        except Exception:
            logger.exception("resume_upload_stage request_id=%s stage=parse_failed", request_id)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to read resume. Ensure it's a valid PDF or DOCX.")

        if not resume_text or len(resume_text.strip()) < 40:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Could not extract enough text from this resume. Try a text-based PDF or DOCX.",
            )

        contact = extract_contact_info(resume_text)
        social = extract_social_links(resume_text)

        redacted_text = remove_pii(resume_text)
        if len(redacted_text) > MAX_RESUME_TEXT_LENGTH:
            redacted_text = redacted_text[:MAX_RESUME_TEXT_LENGTH]

        fallback_json = extract_resume_with_rules(resume_text, contact, social, parsed_resume)
        resume_json = fallback_json
        try:
            logger.info("resume_upload_stage request_id=%s stage=ai_enrichment_started", request_id)
            ai_json = await extract_with_ai_upload(redacted_text)
            resume_json = _merge_resume_profiles(ai_json, fallback_json)
            logger.info("resume_upload_stage request_id=%s stage=ai_enrichment_completed", request_id)
        except asyncio.TimeoutError:
            logger.warning("resume_upload_stage request_id=%s stage=ai_timeout fallback=rules", request_id)
        except Exception as exc:
            logger.warning(
                "resume_upload_stage request_id=%s stage=ai_failed error=%s fallback=rules",
                request_id,
                type(exc).__name__,
            )

        if not resume_json.get("target_role") and fallback_json.get("target_role"):
            resume_json["target_role"] = fallback_json["target_role"]

        resume_json["email"] = contact["email"] or current_user.get("email")
        resume_json["phone"] = contact["phone"]
        resume_json["linkedin"] = social["linkedin"]
        resume_json["github"] = social["github"]
        resume_json["portfolio"] = social["portfolio"]
        resume_json["links"] = {
            "linkedin": social["linkedin"],
            "github": social["github"],
            "portfolio": social["portfolio"],
            "all": parsed_resume.get("links", []),
        }
        resume_json["profile_sources"] = list(dict.fromkeys(
            (resume_json.get("profile_sources") or []) + [parsed_resume.get("parser", "resume_parser")]
        ))
        resume_json = validate_resume_json(resume_json)
        resume_json["links"] = {
            "linkedin": social["linkedin"],
            "github": social["github"],
            "portfolio": social["portfolio"],
            "all": parsed_resume.get("links", []),
        }

        profile_completed = bool(resume_json.get("name") and resume_json.get("skills"))
        parser_version = str(parsed_resume.get("parser") or "resume_parser")[:40]
        content_hash = hashlib.sha256(content).hexdigest()
        facts_payload = _resume_fact_payload(
            resume_json,
            source_text=resume_text,
            parser_version=parser_version,
        )
        confirmation_status = _confirmation_status(facts_payload)
        taxonomy = _resume_taxonomy(resume_json)
        active_profile = resume_json
        resume_version: Optional[dict[str, Any]] = None
        version_created = False
        with get_db() as conn:
            cur = conn.cursor()
            try:
                with transaction(conn):
                    cur.execute(
                        "SELECT 1 FROM UserInfo WHERE user_id = %s FOR UPDATE",
                        (current_user["user_id"],),
                    )
                    user_exists = cur.fetchone() is not None
                    if not user_exists:
                        cur.execute(
                            """
                            INSERT INTO UserInfo (
                                user_id, full_name, resume_json, profile_json,
                                profile_completed, resume_uploaded_at, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                            """,
                            (
                                current_user["user_id"],
                                resume_json.get("name"),
                                json.dumps(encrypt_json(resume_json)),
                                json.dumps(encrypt_json(resume_json)),
                                profile_completed,
                            ),
                        )

                    cur.execute(
                        RESUME_VERSION_SELECT
                        + " WHERE user_id = %s AND content_hash = %s ORDER BY version_number DESC LIMIT 1",
                        (current_user["user_id"], content_hash),
                    )
                    duplicate_row = cur.fetchone()
                    cur.execute(
                        "UPDATE ResumeVersions SET is_active = FALSE, updated_at = NOW() WHERE user_id = %s AND is_active = TRUE",
                        (current_user["user_id"],),
                    )
                    if duplicate_row:
                        resume_id = duplicate_row[0]
                        duplicate_payload = _resume_version_payload(duplicate_row)
                        active_profile = duplicate_payload["resume_payload"]
                        profile_completed = bool(active_profile.get("name") and active_profile.get("skills"))
                        cur.execute(
                            "UPDATE ResumeVersions SET is_active = TRUE, updated_at = NOW() WHERE resume_id = %s AND user_id = %s",
                            (resume_id, current_user["user_id"]),
                        )
                    else:
                        cur.execute(
                            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM ResumeVersions WHERE user_id = %s",
                            (current_user["user_id"],),
                        )
                        version_number = int((cur.fetchone() or [1])[0] or 1)
                        resume_id = str(uuid.uuid4())
                        cur.execute(
                            """
                            INSERT INTO ResumeVersions (
                                resume_id, user_id, version_number, resume_text_encrypted,
                                resume_payload_encrypted,
                                facts_encrypted, derived_taxonomy, is_active,
                                confirmation_status, resume_json, content_hash,
                                parser_version, source_filename, created_at, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s, NOW(), NOW())
                            """,
                            (
                                resume_id,
                                current_user["user_id"],
                                version_number,
                                encrypt_data(resume_text).encode("utf-8"),
                                _encrypted_json_blob(resume_json),
                                _encrypted_json_blob(facts_payload),
                                json.dumps(taxonomy),
                                confirmation_status,
                                json.dumps(encrypt_json(resume_json)),
                                content_hash,
                                parser_version,
                                os.path.basename(file.filename)[:255],
                            ),
                        )
                        version_created = True

                    cur.execute(
                        """
                        UPDATE UserInfo
                        SET resume_json = %s,
                            profile_json = %s,
                            active_resume_id = %s,
                            profile_completed = %s,
                            full_name = COALESCE(NULLIF(full_name, ''), %s),
                            resume_uploaded_at = NOW(),
                            updated_at = NOW()
                        WHERE user_id = %s
                        """,
                        (
                            json.dumps(encrypt_json(active_profile)),
                            json.dumps(encrypt_json(active_profile)),
                            resume_id,
                            profile_completed,
                            active_profile.get("name"),
                            current_user["user_id"],
                        ),
                    )
                    cur.execute(
                        "INSERT INTO ResumeUploadLogs (user_id, uploaded_at) VALUES (%s, NOW())",
                        (current_user["user_id"],),
                    )
                    resume_version = _load_resume_version(cur, current_user["user_id"], resume_id)
            finally:
                cur.close()

        if profile_completed:
            schedule_profile_enrichment(current_user["user_id"], active_profile)
        logger.info(
            "resume_upload_stage request_id=%s stage=stored total_latency_ms=%s",
            request_id,
            round((time.perf_counter() - started) * 1000, 2),
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("Resume upload processed in %sms (parser=%s)", elapsed_ms, parsed_resume.get("parser"))

        return {
            "success": True,
            "message": "Resume parsed and saved. Please review your details.",
            "extracted_profile": active_profile,
            "profile_completed": profile_completed,
            "parse_ms": elapsed_ms,
            "resume": resume_version,
            "version_created": version_created,
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unexpected error during resume upload")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "An error occurred while processing your resume")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/resumes")
async def list_resume_versions(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                RESUME_VERSION_SELECT
                + " WHERE user_id = %s ORDER BY version_number DESC, created_at DESC",
                (current_user["user_id"],),
            )
            resumes = [_resume_version_payload(row) for row in cur.fetchall()]
            active = next((item["resume_id"] for item in resumes if item["is_active"]), None)
            return {"resumes": resumes, "active_resume_id": active}
        finally:
            cur.close()


@router.delete("/resumes/{resume_id}")
async def delete_resume_version(
    resume_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            with transaction(conn):
                cur.execute(
                    """
                    SELECT version.resume_id
                    FROM ResumeVersions version
                    WHERE version.user_id = %s AND version.resume_id = %s
                    FOR UPDATE
                    """,
                    (current_user["user_id"], resume_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")
                cur.execute(
                    "DELETE FROM ResumeVersions WHERE user_id = %s AND resume_id = %s",
                    (current_user["user_id"], resume_id),
                )
            return {"success": True, "message": "Resume version deleted"}
        finally:
            cur.close()


@router.patch("/resumes/{resume_id}/facts")
async def review_resume_facts(
    resume_id: str,
    request: ResumeFactsPatch,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            with transaction(conn):
                cur.execute(
                    RESUME_VERSION_SELECT
                    + " WHERE user_id = %s AND resume_id = %s FOR UPDATE",
                    (current_user["user_id"], resume_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")

                original_resume = _decrypted_json_blob(row[2], None)
                if not isinstance(original_resume, dict):
                    original_resume = decrypt_json(row[12]) if row[12] is not None else {}
                if not isinstance(original_resume, dict):
                    raise HTTPException(status.HTTP_409_CONFLICT, "Resume version payload is unavailable")
                facts_payload = _decrypted_json_blob(
                    row[3],
                    {"review_version": "resume-facts-v1", "facts": []},
                )
                facts = facts_payload.get("facts") if isinstance(facts_payload, dict) else []
                by_id = {
                    str(item.get("fact_id")): item
                    for item in (facts or [])
                    if isinstance(item, dict) and item.get("fact_id")
                }
                requested_ids: set[str] = set()
                for decision in request.decisions:
                    if decision.fact_id in requested_ids:
                        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each fact may be reviewed once per request")
                    requested_ids.add(decision.fact_id)
                    fact = by_id.get(decision.fact_id)
                    if not fact:
                        raise HTTPException(
                            status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Unknown resume fact: {decision.fact_id}",
                        )
                    if decision.action == "correct":
                        if decision.corrected_value is None:
                            raise HTTPException(
                                status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "A corrected value is required for correction",
                            )
                        fact["status"] = "corrected"
                        fact["corrected_value"] = decision.corrected_value
                    elif decision.action == "reject":
                        fact["status"] = "rejected"
                        fact["corrected_value"] = None
                    else:
                        fact["status"] = "confirmed"
                        fact["corrected_value"] = None

                facts_payload = {
                    "review_version": str(facts_payload.get("review_version") or "resume-facts-v1"),
                    "facts": list(by_id.values()),
                }
                materialized = _materialize_resume(original_resume, facts_payload)
                confirmation_status = _confirmation_status(facts_payload)
                taxonomy = _resume_taxonomy(materialized)
                cur.execute(
                    """
                    SELECT EXISTS(SELECT 1 FROM Interviews WHERE resume_id = %s)
                        OR EXISTS(SELECT 1 FROM InterviewBlueprints WHERE resume_id = %s AND status = 'consumed')
                        OR EXISTS(SELECT 1 FROM AttemptContextSnapshots WHERE resume_id = %s)
                    """,
                    (resume_id, resume_id, resume_id),
                )
                referenced = bool((cur.fetchone() or [False])[0]) or bool(row[15])
                result_resume_id = resume_id
                if referenced:
                    result_resume_id = str(uuid.uuid4())
                    cur.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM ResumeVersions WHERE user_id = %s", (current_user["user_id"],))
                    next_version = int((cur.fetchone() or [1])[0] or 1)
                    child_hash = hashlib.sha256(
                        f"{row[7]}:{json.dumps(facts_payload, sort_keys=True, default=str)}".encode("utf-8")
                    ).hexdigest()
                    cur.execute(
                        """
                        INSERT INTO ResumeVersions (
                            resume_id, user_id, version_number, resume_text_encrypted,
                            resume_json, content_hash, parser_version, source_filename,
                            resume_payload_encrypted, facts_encrypted, derived_taxonomy,
                            is_active, confirmation_status, encryption_status,
                            created_at, updated_at, parent_resume_id
                        )
                        SELECT %s, user_id, %s, resume_text_encrypted, resume_json, %s,
                               parser_version, source_filename, resume_payload_encrypted, %s,
                               %s, FALSE, %s, encryption_status, NOW(), NOW(), resume_id
                        FROM ResumeVersions WHERE resume_id = %s AND user_id = %s
                        """,
                        (
                            result_resume_id, next_version, child_hash,
                            _encrypted_json_blob(facts_payload), json.dumps(taxonomy),
                            confirmation_status, resume_id, current_user["user_id"],
                        ),
                    )
                    cur.execute(
                        "UPDATE ResumeVersions SET superseded_at = COALESCE(superseded_at, NOW()) WHERE resume_id = %s",
                        (resume_id,),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE ResumeVersions
                        SET facts_encrypted = %s, derived_taxonomy = %s,
                            confirmation_status = %s, updated_at = NOW()
                        WHERE resume_id = %s AND user_id = %s
                        """,
                        (
                            _encrypted_json_blob(facts_payload), json.dumps(taxonomy),
                            confirmation_status, resume_id, current_user["user_id"],
                        ),
                    )
                if bool(row[5]) and not referenced:
                    profile_completed = bool(materialized.get("name") and materialized.get("skills"))
                    cur.execute(
                        """
                        UPDATE UserInfo
                        SET resume_json = %s,
                            profile_json = %s,
                            profile_completed = %s,
                            full_name = COALESCE(NULLIF(%s, ''), full_name),
                            updated_at = NOW()
                        WHERE user_id = %s
                        """,
                        (
                            json.dumps(encrypt_json(materialized)),
                            json.dumps(encrypt_json(materialized)),
                            profile_completed,
                            materialized.get("name"),
                            current_user["user_id"],
                        ),
                    )
                resume = _load_resume_version(cur, current_user["user_id"], result_resume_id)
            return {
                "success": True,
                "resume": resume,
                "copy_on_write": referenced,
                "source_resume_id": resume_id if referenced else None,
            }
        finally:
            cur.close()


@router.patch("/resumes/{resume_id}/activate")
async def activate_resume_version(
    resume_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            with transaction(conn):
                cur.execute(
                    RESUME_VERSION_SELECT
                    + " WHERE user_id = %s AND resume_id = %s FOR UPDATE",
                    (current_user["user_id"], resume_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")
                resume = _resume_version_payload(row)
                if resume["confirmation_status"] != "confirmed":
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "Review all uncertain resume facts before activating this version",
                    )
                profile = resume["resume_payload"]
                profile_completed = bool(profile.get("name") and profile.get("skills"))
                cur.execute(
                    "UPDATE ResumeVersions SET is_active = FALSE, updated_at = NOW() WHERE user_id = %s AND is_active = TRUE",
                    (current_user["user_id"],),
                )
                cur.execute(
                    "UPDATE ResumeVersions SET is_active = TRUE, updated_at = NOW() WHERE user_id = %s AND resume_id = %s",
                    (current_user["user_id"], resume_id),
                )
                cur.execute(
                    """
                    UPDATE UserInfo
                    SET resume_json = %s,
                        profile_json = %s,
                        active_resume_id = %s,
                        profile_completed = %s,
                        full_name = COALESCE(NULLIF(%s, ''), full_name),
                        resume_uploaded_at = COALESCE(resume_uploaded_at, NOW()),
                        updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (
                        json.dumps(encrypt_json(profile)),
                        json.dumps(encrypt_json(profile)),
                        resume_id,
                        profile_completed,
                        profile.get("name"),
                        current_user["user_id"],
                    ),
                )
                activated = _load_resume_version(cur, current_user["user_id"], resume_id)
            return {"success": True, "resume": activated}
        finally:
            cur.close()

@router.post("/confirm-profile")
async def confirm_profile(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any] | None:
    body = await request.json()

    job_id = body.get("job_id")
    profile = body.get("profile", {})

    missing: list[str] = []
    if not profile.get("name", "").strip():
        missing.append("Full name")
    if not profile.get("email", "").strip():
        missing.append("Email")
    if not profile.get("skills") or len(profile.get("skills", [])) == 0:
        missing.append("At least one skill")

    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing required fields: {', '.join(missing)}")

    validated = validate_resume_json(profile)
    validated["email"] = profile.get("email", "").strip()
    validated["phone"] = profile.get("phone", "").strip() or None

    with get_db() as conn:
        cur = conn.cursor()
        try:
            if job_id:
                cur.execute("SELECT job_id FROM Jobs WHERE job_id = %s", (job_id,))
                if not cur.fetchone():
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

            with transaction(conn):
                cur.execute(
                    """
                    UPDATE UserInfo
                    SET job_id = %s,
                        resume_json = %s,
                        profile_json = %s,
                        profile_completed = TRUE,
                        resume_uploaded_at = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (job_id, json.dumps(encrypt_json(validated)), json.dumps(encrypt_json(validated)), current_user["user_id"]),
                )

                cur.execute(
                    RESUME_VERSION_SELECT
                    + " WHERE user_id = %s AND is_active = TRUE ORDER BY version_number DESC LIMIT 1 FOR UPDATE",
                    (current_user["user_id"],),
                )
                active_version_row = cur.fetchone()
                if active_version_row:
                    facts_payload = _decrypted_json_blob(
                        active_version_row[3],
                        {"review_version": "resume-facts-v1", "facts": []},
                    )
                    facts = facts_payload.get("facts") if isinstance(facts_payload, dict) else []
                    for fact in facts or []:
                        if not isinstance(fact, dict):
                            continue
                        field_name = str(fact.get("field") or "")
                        if field_name not in REVIEWABLE_RESUME_FIELDS:
                            continue
                        accepted_value = validated.get(field_name)
                        if accepted_value in (None, "", [], {}):
                            fact["status"] = "rejected"
                            fact["corrected_value"] = None
                        elif accepted_value != fact.get("original_value"):
                            fact["status"] = "corrected"
                            fact["corrected_value"] = accepted_value
                        else:
                            fact["status"] = "confirmed"
                            fact["corrected_value"] = None
                    updated_facts = {
                        "review_version": str(facts_payload.get("review_version") or "resume-facts-v1"),
                        "facts": facts or [],
                    }
                    cur.execute(
                        """
                        UPDATE ResumeVersions
                        SET facts_encrypted = %s,
                            derived_taxonomy = %s,
                            confirmation_status = 'confirmed',
                            updated_at = NOW()
                        WHERE resume_id = %s AND user_id = %s
                        """,
                        (
                            _encrypted_json_blob(updated_facts),
                            json.dumps(_resume_taxonomy(validated)),
                            active_version_row[0],
                            current_user["user_id"],
                        ),
                    )

                cur.execute(
                    "INSERT INTO ResumeUploadLogs (user_id, uploaded_at) VALUES (%s, NOW())",
                    (current_user["user_id"],),
                )

            logger.info("Profile confirmed for %s", stable_hash(current_user["user_id"], "user"))
            schedule_profile_enrichment(current_user["user_id"], validated)

            return {
                "success": True,
                "message": "Profile saved! You can now start your interview.",
            }

        except HTTPException:
            raise
        except Exception:
            logger.error("Failed to confirm profile")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save profile")
        finally:
            cur.close()

@router.get("/form")
async def get_form(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any] | None:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COALESCE(profile_json, resume_json), job_id
                FROM UserInfo WHERE user_id = %s
                """,
                (current_user["user_id"],),
            )
            row = cur.fetchone()

            if not row or not row[0]:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found. Please upload your resume first.")

            validated = validate_resume_json(decrypt_json(row[0]))

            job_info = None
            if row[1]:
                cur.execute("SELECT job_id, title, description FROM Jobs WHERE job_id = %s", (row[1],))
                job_row = cur.fetchone()
                if job_row:
                    job_info = {"job_id": job_row[0], "title": job_row[1], "description": job_row[2]}
            if job_info is None:
                cur.execute(
                    """
                    SELECT profile_id, role, job_description_encrypted
                    FROM JobProfiles
                    WHERE user_id = %s AND is_selected = TRUE
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (current_user["user_id"],),
                )
                job_row = cur.fetchone()
                if job_row:
                    job_info = {
                        "job_profile_id": job_row[0],
                        "title": job_row[1],
                        "description": _decrypt_text_blob(job_row[2]),
                    }

            return {"success": True, "form_data": validated, "job_info": job_info}
        finally:
            cur.close()


@router.post("/submit-form")
async def submit_form(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any] | None:
    form_data = await request.json()

    missing: list[str] = []
    if not form_data.get("name", "").strip():
        missing.append("Full name")
    if not form_data.get("skills") or len(form_data.get("skills", [])) == 0:
        missing.append("At least one skill")

    if missing:
        return {
            "success": False,
            "status": "incomplete",
            "missing_fields": missing,
            "message": "Please fill in all required fields",
        }

    with get_db() as conn:
        cur = conn.cursor()
        try:

            with transaction(conn):
                cur.execute(
                    """
                    UPDATE UserInfo
                    SET profile_json = %s, profile_completed = TRUE, updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (json.dumps(encrypt_json(form_data)), current_user["user_id"]),
                )

            schedule_profile_enrichment(current_user["user_id"], form_data)
            return {"success": True, "status": "complete", "message": "Profile saved! You can now start your interview."}

        except HTTPException:
            raise
        except Exception:
            logger.error("Error in submit_form")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save profile")
        finally:
            cur.close()

@router.get("/profile-status")
async def get_profile_status(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any] | None:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT job_id, resume_json, profile_json, profile_completed, resume_uploaded_at,
                       EXISTS (
                           SELECT 1 FROM ResumeVersions
                           WHERE user_id = UserInfo.user_id AND is_active = TRUE
                       ) AS has_active_resume,
                       EXISTS (
                           SELECT 1 FROM JobProfiles
                           WHERE user_id = UserInfo.user_id AND is_selected = TRUE
                       ) AS has_selected_job_profile
                FROM UserInfo
                WHERE user_id = %s
                """,
                (current_user["user_id"],),
            )
            row = cur.fetchone()

            if not row:
                return {
                    "resume_uploaded": False,
                    "job_selected": False,
                    "profile_completed": False,
                    "current_step": "upload_resume",
                }

            job_id, resume_json, profile_json, profile_completed, uploaded_at, has_active_resume, has_selected_job = row
            resume_uploaded = resume_json is not None or bool(has_active_resume)
            job_selected = job_id is not None or bool(has_selected_job)

            return {
                "resume_uploaded": resume_uploaded,
                "job_selected": job_selected,
                "profile_completed": profile_completed or False,
                "resume_uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
                "current_step": (
                    "interview_ready" if profile_completed and resume_uploaded and job_selected
                    else "edit_form" if resume_uploaded
                    else "upload_resume"
                ),
            }
        finally:
            cur.close()

@router.delete("/reset-profile")
async def reset_profile(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any] | None:
    with get_db() as conn:
        cur = conn.cursor()
        try:
            with transaction(conn):
                cur.execute(
                    """
                    UPDATE UserInfo
                    SET resume_json = NULL, profile_json = NULL,
                        active_resume_id = NULL,
                        profile_completed = FALSE, job_id = NULL,
                        resume_uploaded_at = NULL
                    WHERE user_id = %s
                    """,
                    (current_user["user_id"],),
                )
                cur.execute(
                    "UPDATE ResumeVersions SET is_active = FALSE, updated_at = NOW() WHERE user_id = %s AND is_active = TRUE",
                    (current_user["user_id"],),
                )

            return {"success": True, "message": "Profile reset. You can now upload a new resume."}

        except Exception:
            logger.error("Error in reset_profile")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to reset profile")
        finally:
            cur.close()
