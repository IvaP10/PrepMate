# ============================================================================
# MODULE: body_language.py
# PURPOSE: Normalize browser-side body-language payloads (eye contact, posture,
#          fidget, engagement) into a consistent record + optional coach feedback.
# STRUCTURE:
#   - normalize_client_metrics(payload, interview_mode) (lines 19-43)
#   - _bounded_number helper (lines 46-51)
# ENDPOINTS: none (called by interview.py during WS frames)
# DEPENDS ON: (stdlib only)
# CONSUMED BY: interview.py (writes raw payloads to ClientBodyLanguageMetrics)
# DATA TABLES: none directly
# ============================================================================

from __future__ import annotations

from datetime import datetime, timezone
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
        "analysis_method": "browser_local_camera_coaching",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feedback": feedback,
    }


def _bounded_number(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))
