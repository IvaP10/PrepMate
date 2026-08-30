"""Versioned client event contract for official Interview WebSockets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


CONTROLLER_LEASE_SECONDS = 15
CONTROLLER_RENEWAL_SECONDS = 5
EVENT_DEDUP_TTL_SECONDS = 24 * 60 * 60

ALLOWED_CLIENT_EVENT_TYPES = {
    "start_session",
    "question_ack",
    "init_pipeline",
    "audio_stream",
    "audio_chunk",
    "vad_speech_start",
    "vad_speech_end",
    "interrupt",
    "avatar_sdp_answer",
    "avatar_ice",
    "video_frame",
    "body_language_metrics",
    "self_review_signal",
    "response_complete",
    "text_answer",
    "end_interview",
    "ping",
}

CANONICAL_INTEGRITY_EVENTS = {
    "camera_started", "camera_stopped", "microphone_started", "microphone_stopped",
    "screen_share_started", "screen_share_stopped", "visibility_hidden", "visibility_visible",
    "window_blur", "window_focus", "fullscreen_exit", "back_navigation_attempt",
    "route_navigation_attempt", "refresh_attempt", "copy", "paste", "paste_blocked",
    "duplicate_controller_rejected", "connection_interrupted", "connection_restored",
    "inactivity_warning", "recovery_expired", "voluntary_exit",
}

INTEGRITY_EVENT_ALIASES = {
    "camera_track_ended": "camera_stopped",
    "tab_switch": "visibility_hidden",
    "recording_failed": "microphone_stopped",
    "interview_permission_failed": "screen_share_stopped",
    "fullscreen_request_failed": "fullscreen_exit",
    "background_audio_detected": "inactivity_warning",
}


class WSContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ClientEvent:
    event_id: str
    sequence: int
    client_session_id: str
    interview_id: str
    event_type: str
    sent_at: str
    payload: dict[str, Any]


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise WSContractError("invalid_event_envelope", f"{field} must be a UUID") from exc


def parse_client_event(message: Any) -> ClientEvent:
    if not isinstance(message, dict):
        raise WSContractError("invalid_event_envelope", "WebSocket event must be an object")
    event_type = str(message.get("type") or "").strip()
    if event_type not in ALLOWED_CLIENT_EVENT_TYPES:
        raise WSContractError("unknown_event_type", "Unsupported WebSocket event type")

    required = ("event_id", "sequence", "client_session_id", "interview_id", "sent_at", "payload")
    if any(field not in message for field in required):
        raise WSContractError("invalid_event_envelope", "WebSocket event envelope is incomplete")

    event_id = _uuid(message.get("event_id"), "event_id")
    client_session_id = _uuid(message.get("client_session_id"), "client_session_id")
    interview_id = _uuid(message.get("interview_id"), "interview_id")
    try:
        sequence = int(message.get("sequence"))
    except (TypeError, ValueError) as exc:
        raise WSContractError("invalid_event_envelope", "sequence must be an integer") from exc
    if sequence < 1:
        raise WSContractError("invalid_event_envelope", "sequence must be positive")
    sent_at = str(message.get("sent_at") or "")
    try:
        datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WSContractError("invalid_event_envelope", "sent_at must be an ISO timestamp") from exc
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise WSContractError("invalid_event_envelope", "payload must be an object")
    return ClientEvent(
        event_id=event_id,
        sequence=sequence,
        client_session_id=client_session_id,
        interview_id=interview_id,
        event_type=event_type,
        sent_at=sent_at,
        payload=payload,
    )


def canonical_integrity_event(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    canonical = INTEGRITY_EVENT_ALIASES.get(normalized, normalized)
    if canonical not in CANONICAL_INTEGRITY_EVENTS:
        raise WSContractError("unknown_integrity_event", "Unsupported integrity event type")
    return canonical


def acquire_controller_lease(local_cache: Any, key: str, connection_id: str) -> bool:
    existing = local_cache.get(key)
    if isinstance(existing, bytes):
        existing = existing.decode("utf-8", errors="ignore")
    if existing == connection_id:
        return bool(local_cache.expire(key, CONTROLLER_LEASE_SECONDS))
    return bool(local_cache.set(key, connection_id, nx=True, ex=CONTROLLER_LEASE_SECONDS))


def renew_controller_lease(local_cache: Any, key: str, connection_id: str) -> bool:
    return bool(local_cache.compare_and_expire(key, connection_id, CONTROLLER_LEASE_SECONDS))


def release_controller_lease(local_cache: Any, key: str, connection_id: str) -> bool:
    return bool(local_cache.compare_and_delete(key, connection_id))


def claim_event_sequence(local_cache: Any, event: ClientEvent) -> str:
    """Atomically deduplicate an event and advance one client session sequence."""
    event_key = f"attempt-event:{event.interview_id}:{event.event_id}"
    sequence_key = f"attempt-sequence:{event.interview_id}:{event.client_session_id}"
    result = int(local_cache.claim_sequence(
        event_key,
        sequence_key,
        event.sequence,
        EVENT_DEDUP_TTL_SECONDS,
    ))
    return "accepted" if result == 1 else "duplicate" if result == 0 else "out_of_order"
