from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def normalize_client_metrics(payload: Dict[str, Any], interview_mode: str = "mock") -> Dict[str, Any]:
    confidence = _bounded_number(payload.get("confidence") or payload.get("engagementScore"), 0, 100, 50)
    eye_contact = bool(payload.get("eye_contact") or payload.get("eyeContact") or payload.get("centered"))
    posture = str(payload.get("posture") or payload.get("cameraContactLevel") or "unknown")[:40]
    fidget_level = str(payload.get("fidget_level") or payload.get("fidgetLevel") or "unknown")[:40]

    feedback = []
    if interview_mode == "practice":
        if not eye_contact:
            feedback.append("Keep your face centered and look toward the camera.")
        if confidence < 45:
            feedback.append("Slow down and reset your posture before answering.")

    return {
        "face_detected": bool(payload.get("facePresent", True)),
        "confidence": confidence,
        "emotion": str(payload.get("emotion") or "not_tracked")[:40],
        "eye_contact": eye_contact,
        "posture": posture,
        "engagement": confidence,
        "fidget_level": fidget_level,
        "analysis_method": "browser_mediapipe",
        "timestamp": datetime.utcnow().isoformat(),
        "feedback": feedback,
    }


async def analyze_frame(*args, **kwargs) -> Dict[str, Any]:
    return {
        "face_detected": False,
        "confidence": None,
        "emotion": "not_processed",
        "eye_contact": False,
        "posture": "server_video_disabled",
        "engagement": None,
        "analysis_method": "server_video_disabled",
        "feedback": [],
    }


def _bounded_number(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def cleanup():
    return None
