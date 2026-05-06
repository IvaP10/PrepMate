from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Request
from typing import Any
import json
import os
import logging
import re
import asyncio
import tempfile

from auth import get_current_user
from database import get_db, transaction
from resume_parser import parse_resume_structured
from resume_rules import extract_rule_based_profile
from profile_enrichment import enrich_profile_for_user
from config import settings
from llm_router import complete_json_sync
from prompt_security import SYSTEM_DATA_BOUNDARY, data_block
from security_utils import redact_text, stable_hash

router = APIRouter(prefix="/api/pre-interview", tags=["Pre-Interview"])
logger = logging.getLogger("pre_interview")

MAX_FILE_SIZE_MB = settings.MAX_FILE_SIZE_MB
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_RESUME_TEXT_LENGTH = settings.MAX_RESUME_TEXT_LENGTH

MAX_UPLOADS_PER_DAY = settings.MAX_UPLOADS_PER_DAY
UPLOAD_COOLDOWN_MINUTES = settings.UPLOAD_COOLDOWN_MINUTES

AI_MAX_RETRIES = settings.AI_MAX_RETRIES
AI_RETRY_DELAY_SECONDS = settings.AI_RETRY_DELAY_SECONDS

ALLOWED_EXTENSIONS = {".pdf", ".docx"}

async def _run_profile_enrichment(user_id: str, profile: dict[str, Any]) -> None:
    try:
        await enrich_profile_for_user(user_id, profile)
    except Exception:
        logger.error("Profile enrichment failed for %s", stable_hash(user_id, "user"))

def schedule_profile_enrichment(user_id: str, profile: dict[str, Any]) -> None:
    asyncio.create_task(_run_profile_enrichment(user_id, profile))

EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    re.IGNORECASE,
)

PHONE_PATTERNS = [
    re.compile(r'\+\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),
    re.compile(r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}'),
    re.compile(r'\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b'),
    re.compile(r'\b\d{10}\b'),
    re.compile(r'\+\d{1,3}[-.\s]?\d{4,5}[-.\s]?\d{5,6}'),
]

SOCIAL_PATTERNS = [
    re.compile(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'https?://(?:www\.)?twitter\.com/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'https?://(?:www\.)?x\.com/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'https?://(?:www\.)?facebook\.com/[A-Za-z0-9_./-]+/?', re.I),
    re.compile(r'https?://(?:www\.)?instagram\.com/[A-Za-z0-9_./-]+/?', re.I),
    re.compile(r'linkedin\.com/in/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'github\.com/[A-Za-z0-9_-]+/?', re.I),
    re.compile(r'https?://[A-Za-z0-9_-]+\.(?:me|dev|io|com|org|net)/[^\s]*', re.I),
]

CREDIT_CARD_PATTERNS = [
    re.compile(r'\b4\d{3}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
    re.compile(r'\b5[1-5]\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
    re.compile(r'\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b'),
    re.compile(r'\b6(?:011|5\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
    re.compile(r'\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b'),
]

SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

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

def remove_pii(text: str) -> str:
    text = EMAIL_PATTERN.sub('[EMAIL_REMOVED]', text)

    for pat in PHONE_PATTERNS:
        text = pat.sub('[PHONE_REMOVED]', text)

    for pat in SOCIAL_PATTERNS:
        text = pat.sub('[LINK_REMOVED]', text)

    for pat in CREDIT_CARD_PATTERNS:
        text = pat.sub('[CARD_REMOVED]', text)

    text = SSN_PATTERN.sub('[SSN_REMOVED]', text)

    return text

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
        "links": normalized_links,
        "profile_sources": profile_sources,
        "evidence": evidence,
        "confidence": confidence,
    }

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


async def extract_with_ai(resume_text: str) -> dict[str, Any]:
    prompt = EXTRACTION_PROMPT.format(resume_text=data_block("resume_text", resume_text))
    messages = [
        {
            "role": "system",
            "content": (
                "You are the low-confidence fallback for a deterministic resume parser. "
                "Extract structured resume data only from the provided text. Return valid JSON only. "
                f"{SYSTEM_DATA_BOUNDARY}"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            loop = asyncio.get_running_loop()
            parsed = await loop.run_in_executor(
                None,
                lambda: complete_json_sync(
                    messages,
                    event_type="resume_ai_fallback",
                    temperature=0.0,
                    max_tokens=4096,
                    metadata={"reason": "low_rule_confidence"},
                ),
            )
            return validate_resume_json(parsed)

        except HTTPException:
            raise

        except Exception as exc:
            logger.error("AI extraction attempt %d failed: [%s] %s", attempt + 1, type(exc).__name__, redact_text(exc))
            if attempt >= AI_MAX_RETRIES:
                logger.error("All AI extraction attempts exhausted. Last error: [%s] %s", type(exc).__name__, redact_text(exc))
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Failed to process resume. Please try again.",
                )
            await asyncio.sleep(AI_RETRY_DELAY_SECONDS * (2 ** attempt))

    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to process resume with AI")


def _merge_profile_data(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary or {})
    for key, value in (fallback or {}).items():
        if key == "confidence":
            continue
        if value in (None, "", [], {}):
            continue
        if not merged.get(key):
            merged[key] = value
        elif key in {"skills", "education", "experience", "projects", "languages", "certifications", "profile_sources"}:
            existing = merged.get(key) if isinstance(merged.get(key), list) else []
            incoming = value if isinstance(value, list) else []
            combined = []
            seen = set()
            for item in existing + incoming:
                marker = json.dumps(item, sort_keys=True, default=str) if isinstance(item, dict) else str(item).lower()
                if marker in seen:
                    continue
                seen.add(marker)
                combined.append(item)
            merged[key] = combined
    confidence = dict(primary.get("confidence") or {})
    if fallback.get("confidence"):
        confidence["ai_fallback"] = fallback["confidence"]
    confidence["fallback_used"] = True
    merged["confidence"] = confidence
    return merged

def check_rate_limit(user_id: str, conn: Any) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM ResumeUploadLogs
            WHERE user_id = %s AND uploaded_at > NOW() - INTERVAL '24 hours'
            """,
            (user_id,),
        )
        count_row = cur.fetchone()
        if count_row and count_row[0] >= MAX_UPLOADS_PER_DAY:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Daily upload limit reached ({MAX_UPLOADS_PER_DAY} uploads per day)",
            )
    finally:
        cur.close()

@router.post("/upload-resume")
async def upload_resume(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any] | None:
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Resume file is required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid file type. Allowed: PDF, DOCX")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File too large. Maximum: {MAX_FILE_SIZE_MB} MB")

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as out_file:
            temp_path = out_file.name
            out_file.write(content)

        loop = asyncio.get_running_loop()
        try:
            parsed_resume = await loop.run_in_executor(None, parse_resume_structured, temp_path)
            resume_text = parsed_resume.get("text", "")
        except Exception:
            logger.error("Resume parsing failed")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to read resume. Ensure it's a valid PDF or DOCX.")

        contact = extract_contact_info(resume_text)
        social = extract_social_links(resume_text)

        redacted_text = remove_pii(resume_text)
        if len(redacted_text) > MAX_RESUME_TEXT_LENGTH:
            redacted_text = redacted_text[:MAX_RESUME_TEXT_LENGTH]

        resume_json = extract_rule_based_profile(
            redacted_text,
            links=parsed_resume.get("links", []),
            parser_name=parsed_resume.get("parser", "resume_parser"),
        )

        confidence = (resume_json.get("confidence") or {}).get("overall", 0)
        if confidence < settings.RESUME_AI_FALLBACK_CONFIDENCE:
            logger.info("Rule resume confidence %.2f below threshold; using AI fallback", confidence)
            fallback_profile = await extract_with_ai(redacted_text)
            resume_json = _merge_profile_data(resume_json, fallback_profile)
        else:
            resume_json.setdefault("confidence", {})["fallback_used"] = False

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
        resume_json.setdefault("confidence", {})
        resume_json["confidence"]["parser"] = parsed_resume.get("parser")

        return {
            "success": True,
            "message": "Resume parsed. Please review your details.",
            "extracted_profile": resume_json,
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unexpected error during resume upload")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "An error occurred while processing your resume")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

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
                    (job_id, json.dumps(validated), json.dumps(validated), current_user["user_id"]),
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
                "SELECT COALESCE(profile_json, resume_json), job_id FROM UserInfo WHERE user_id = %s",
                (current_user["user_id"],),
            )
            row = cur.fetchone()

            if not row or not row[0]:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found. Please upload your resume first.")

            validated = validate_resume_json(row[0])

            job_info = None
            if row[1]:
                cur.execute("SELECT job_id, title, description FROM Jobs WHERE job_id = %s", (row[1],))
                job_row = cur.fetchone()
                if job_row:
                    job_info = {"job_id": job_row[0], "title": job_row[1], "description": job_row[2]}

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
                    (json.dumps(form_data), current_user["user_id"]),
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
                SELECT job_id, resume_json, profile_json, profile_completed, resume_uploaded_at
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

            job_id, resume_json, profile_json, profile_completed, uploaded_at = row

            return {
                "resume_uploaded": resume_json is not None,
                "job_selected": job_id is not None,
                "profile_completed": profile_completed or False,
                "resume_uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
                "current_step": (
                    "interview_ready" if profile_completed
                    else "edit_form" if resume_json
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
                        profile_completed = FALSE, job_id = NULL,
                        resume_uploaded_at = NULL
                    WHERE user_id = %s
                    """,
                    (current_user["user_id"],),
                )

            return {"success": True, "message": "Profile reset. You can now upload a new resume."}

        except Exception:
            logger.error("Error in reset_profile")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to reset profile")
        finally:
            cur.close()
