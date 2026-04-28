from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Optional, List
from datetime import datetime
import json
import logging

from auth import get_current_user
from database import get_db_connection, return_db_connection

router = APIRouter(tags=["Profile"])
logger = logging.getLogger("ai_interviewer.profile")

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    skills: Optional[List[str]] = None
    education: Optional[List[Dict]] = None
    experience: Optional[List[Dict]] = None
    projects: Optional[List[Dict]] = None

class ProfileResponse(BaseModel):
    user_id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    job_id: Optional[str]
    job_title: Optional[str]
    resume_text: Optional[str]
    resume_json: Optional[Dict]
    profile_json: Optional[Dict]
    profile_completed: bool
    mock_interview_count: int
    practice_interview_count: int
    date_created: datetime

@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                u.user_id,
                u.full_name,
                l.email,
                u.job_id,
                u.resume_json,
                u.profile_json,
                u.profile_completed,
                u.mock_interview_count,
                u.practice_interview_count,
                u.date_created,
                j.title
            FROM UserInfo u
            JOIN Login l ON u.user_id = l.user_id
            LEFT JOIN Jobs j ON u.job_id = j.job_id
            WHERE u.user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )

        return ProfileResponse(**{
            "user_id": row[0],
            "full_name": row[1],
            "email": row[2],
            "job_id": row[3],
            "job_title": row[10],
            "resume_text": None,
            "resume_json": row[4],
            "profile_json": row[5],
            "profile_completed": row[6],
            "mock_interview_count": row[7],
            "practice_interview_count": row[8],
            "date_created": row[9]
        })

    finally:
        cursor.close()
        return_db_connection(connection)

@router.put("/update")
async def update_profile(
    request: UpdateProfileRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT profile_json FROM UserInfo WHERE user_id = %s",
            (current_user["user_id"],)
        )

        row = cursor.fetchone()
        existing_profile = row[0] if row and row[0] else {}

        updates = request.model_dump(exclude_unset=True)
        existing_profile.update(updates)

        cursor.execute(
            """
            UPDATE UserInfo
            SET profile_json = %s,
                full_name = COALESCE(%s, full_name)
            WHERE user_id = %s
            """,
            (
                json.dumps(existing_profile),
                request.full_name,
                current_user["user_id"]
            )
        )

        connection.commit()
        logger.info("Profile updated for user: %s", current_user["user_id"])

        return {
            "message": "Profile updated successfully",
            "profile": existing_profile
        }

    except Exception:
        connection.rollback()
        logger.exception("Failed to update profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.delete("/resume")
async def delete_resume(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE UserInfo
            SET resume_json = NULL,
                resume_text_encrypted = NULL,
                resume_uploaded_at = NULL,
                profile_completed = FALSE
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        connection.commit()
        logger.info("Resume deleted for user: %s", current_user["user_id"])

        return {"message": "Resume deleted successfully"}

    except Exception:
        connection.rollback()
        logger.exception("Failed to delete resume")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete resume"
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/completion-status")
async def get_completion_status(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                profile_completed,
                resume_json,
                profile_json,
                job_id
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        profile_completed = row[0]
        has_resume = bool(row[1])
        profile_json = row[2] or {}
        has_job = bool(row[3])

        missing_fields = []

        if not profile_json.get("name"):
            missing_fields.append("name")

        if not profile_json.get("skills") or len(profile_json.get("skills", [])) == 0:
            missing_fields.append("skills")

        if not has_job:
            missing_fields.append("job_selection")

        return {
            "completed": len(missing_fields) == 0,
            "has_resume": has_resume,
            "has_job": has_job,
            "missing_fields": missing_fields
        }

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/interview-history")
async def get_interview_history(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                interview_id,
                interview_type,
                job_title,
                strictness_level,
                overall_score,
                feedback_summary,
                created_at,
                completed_at
            FROM Interviews
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (current_user["user_id"],)
        )

        rows = cursor.fetchall()

        interviews = []
        for row in rows:
            interviews.append({
                "interview_id": row[0],
                "interview_type": row[1],
                "job_title": row[2],
                "strictness_level": row[3],
                "overall_score": row[4],
                "feedback_summary": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None
            })

        return {
            "total_interviews": len(interviews),
            "interviews": interviews
        }

    finally:
        cursor.close()
        return_db_connection(connection)

@router.get("/statistics")
async def get_statistics(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT 
                mock_interview_count,
                practice_interview_count
            FROM UserInfo
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()
        mock_count = row[0] if row else 0
        practice_count = row[1] if row else 0

        cursor.execute(
            """
            SELECT 
                AVG(overall_score) as avg_score,
                COUNT(*) as completed_count
            FROM Interviews
            WHERE user_id = %s
            AND overall_score IS NOT NULL
            """,
            (current_user["user_id"],)
        )

        stats_row = cursor.fetchone()
        avg_score = float(stats_row[0]) if stats_row and stats_row[0] else 0.0
        completed_count = stats_row[1] if stats_row else 0

        return {
            "mock_interviews": mock_count,
            "practice_interviews": practice_count,
            "total_interviews": mock_count + practice_count,
            "completed_interviews": completed_count,
            "average_score": round(avg_score, 2)
        }

    finally:
        cursor.close()
        return_db_connection(connection)