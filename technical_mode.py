from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth import get_current_user
from config import settings
from database import async_execute

router = APIRouter(prefix="/api/technical", tags=["Technical Interview"])


class CodeRunRequest(BaseModel):
    language: str = Field(pattern="^(python|javascript|java)$")
    code: str = Field(min_length=1, max_length=20000)
    stdin: Optional[str] = Field(default="", max_length=4000)


class WhiteboardSaveRequest(BaseModel):
    whiteboard_json: Dict[str, Any]


class AntiCheatEventRequest(BaseModel):
    interview_id: str
    event_type: str = Field(max_length=50)
    payload: Dict[str, Any] = Field(default_factory=dict)


ROUND_TEMPLATES = [
    {
        "round_type": "dsa",
        "language": "python",
        "prompt": (
            "Solve a data-structures problem in the editor. Explain the approach, complexity, "
            "edge cases, and then run the code."
        ),
        "starter_code": "def solve(nums):\n    return nums\n\nprint(solve([1, 2, 3]))\n",
    },
    {
        "round_type": "system_design",
        "language": None,
        "prompt": (
            "Design the system on the whiteboard. Cover requirements, APIs, data model, "
            "scaling path, bottlenecks, and failure handling."
        ),
        "starter_code": None,
    },
    {
        "round_type": "debugging",
        "language": "javascript",
        "prompt": (
            "Debug the broken snippet. Identify the bug, fix it, run the code, and explain "
            "why the original failed."
        ),
        "starter_code": "function twoSum(nums, target) {\n  const seen = new Map();\n  for (let i = 0; i <= nums.length; i++) {\n    const need = target - nums[i];\n    if (seen.has(need)) return [seen.get(need), i];\n    seen.set(nums[i], i);\n  }\n}\n",
    },
]

FILE_NAMES = {
    "python": "main.py",
    "javascript": "main.js",
    "java": "Main.java",
}


@router.get("/sessions/{interview_id}/rounds")
async def get_or_create_rounds(interview_id: str, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        """
        SELECT interview_id
        FROM Interviews
        WHERE interview_id = %s AND user_id = %s
        """,
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    existing = await async_execute(
        """
        SELECT round_id, round_type, language, prompt, starter_code, whiteboard_json, status
        FROM TechnicalInterviewRounds
        WHERE interview_id = %s AND user_id = %s
        ORDER BY created_at
        """,
        (interview_id, current_user["user_id"]),
        fetchall=True,
    )
    if not existing:
        for template in ROUND_TEMPLATES:
            await async_execute(
                """
                INSERT INTO TechnicalInterviewRounds (
                    round_id, interview_id, user_id, round_type, language,
                    prompt, starter_code, whiteboard_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    interview_id,
                    current_user["user_id"],
                    template["round_type"],
                    template["language"],
                    template["prompt"],
                    template["starter_code"],
                    json.dumps({}),
                ),
            )
        existing = await async_execute(
            """
            SELECT round_id, round_type, language, prompt, starter_code, whiteboard_json, status
            FROM TechnicalInterviewRounds
            WHERE interview_id = %s AND user_id = %s
            ORDER BY created_at
            """,
            (interview_id, current_user["user_id"]),
            fetchall=True,
        )

    return {
        "rounds": [
            {
                "round_id": row[0],
                "round_type": row[1],
                "language": row[2],
                "prompt": row[3],
                "starter_code": row[4],
                "whiteboard_json": row[5] or {},
                "status": row[6],
            }
            for row in existing
        ]
    }


@router.post("/rounds/{round_id}/run")
async def run_code(round_id: str, request: CodeRunRequest, current_user: Dict = Depends(get_current_user)):
    round_row = await async_execute(
        """
        SELECT round_id
        FROM TechnicalInterviewRounds
        WHERE round_id = %s AND user_id = %s
        """,
        (round_id, current_user["user_id"]),
        fetchone=True,
    )
    if not round_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")

    started = time.time()
    runtime = await _resolve_runtime(request.language)
    payload = {
        "language": runtime["language"],
        "version": runtime["version"],
        "files": [{"name": FILE_NAMES[request.language], "content": request.code}],
        "stdin": request.stdin or "",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.PISTON_TIMEOUT_SECONDS)) as session:
            async with session.post(settings.PISTON_API_URL.rstrip("/") + "/execute", json=payload) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail="Code execution service failed")
                result = await response.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Code execution service unavailable")

    run = result.get("run") or {}
    run_id = str(uuid.uuid4())
    runtime_ms = int((time.time() - started) * 1000)
    await async_execute(
        """
        INSERT INTO TechnicalRunEvents (
            run_id, round_id, user_id, language, source_chars,
            stdout, stderr, exit_code, runtime_ms
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id,
            round_id,
            current_user["user_id"],
            request.language,
            len(request.code),
            run.get("stdout"),
            run.get("stderr"),
            run.get("code"),
            runtime_ms,
        ),
    )
    return {
        "run_id": run_id,
        "language": request.language,
        "stdout": run.get("stdout") or "",
        "stderr": run.get("stderr") or "",
        "exit_code": run.get("code"),
        "runtime_ms": runtime_ms,
    }


@router.post("/rounds/{round_id}/whiteboard")
async def save_whiteboard(round_id: str, request: WhiteboardSaveRequest, current_user: Dict = Depends(get_current_user)):
    updated = await async_execute(
        """
        UPDATE TechnicalInterviewRounds
        SET whiteboard_json = %s
        WHERE round_id = %s AND user_id = %s
        RETURNING round_id
        """,
        (json.dumps(request.whiteboard_json), round_id, current_user["user_id"]),
        fetchone=True,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")
    return {"success": True}


@router.post("/anti-cheat")
async def record_anti_cheat_event(request: AntiCheatEventRequest, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = %s AND user_id = %s",
        (request.interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    await async_execute(
        """
        INSERT INTO AntiCheatEvents (interview_id, user_id, event_type, payload)
        VALUES (%s, %s, %s, %s)
        """,
        (
            request.interview_id,
            current_user["user_id"],
            request.event_type,
            json.dumps(request.payload),
        ),
    )
    return {"success": True}


async def _resolve_runtime(language: str) -> Dict[str, str]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
        async with session.get(settings.PISTON_API_URL.rstrip("/") + "/runtimes") as response:
            if response.status >= 400:
                raise HTTPException(status_code=502, detail="Could not load code runtimes")
            runtimes = await response.json()
    aliases = {
        "python": {"python", "py"},
        "javascript": {"javascript", "js", "node"},
        "java": {"java"},
    }[language]
    for runtime in runtimes:
        names = {runtime.get("language"), *(runtime.get("aliases") or [])}
        if aliases & {str(name).lower() for name in names if name}:
            return {"language": runtime["language"], "version": runtime["version"]}
    raise HTTPException(status_code=502, detail=f"No Piston runtime for {language}")
