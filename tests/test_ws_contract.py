from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ws_contract import (
    CONTROLLER_LEASE_SECONDS,
    WSContractError,
    acquire_controller_lease,
    canonical_integrity_event,
    claim_event_sequence,
    parse_client_event,
    release_controller_lease,
    renew_controller_lease,
)


class FakeLocalCache:
    def __init__(self):
        self.values = {}
        self.expiries = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiries[key] = ex
        return True

    def expire(self, key, seconds):
        if key not in self.values:
            return 0
        self.expiries[key] = seconds
        return 1

    def compare_and_expire(self, key, expected, seconds):
        if self.values.get(key) != expected:
            return False
        self.expiries[key] = seconds
        return True

    def compare_and_delete(self, key, expected):
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True

    def claim_sequence(self, event_key, sequence_key, incoming, ttl):
        if event_key in self.values:
            return 0
        last = int(self.values.get(sequence_key, 0))
        if int(incoming) <= last:
            return -1
        self.values[event_key] = "1"
        self.values[sequence_key] = int(incoming)
        self.expiries[event_key] = int(ttl)
        self.expiries[sequence_key] = int(ttl)
        return 1


def _event(**overrides):
    event = {
        "event_id": str(uuid4()),
        "sequence": 1,
        "client_session_id": str(uuid4()),
        "interview_id": str(uuid4()),
        "type": "start_session",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"interview_id": str(uuid4())},
    }
    event.update(overrides)
    return event


def test_parse_client_event_requires_complete_versioned_envelope():
    parsed = parse_client_event(_event())
    assert parsed.sequence == 1
    assert parsed.event_type == "start_session"
    assert parsed.legacy is False


@pytest.mark.parametrize("field,value", [
    ("event_id", "not-a-uuid"),
    ("client_session_id", "bad"),
    ("interview_id", "bad"),
    ("sequence", 0),
    ("payload", "not-an-object"),
])
def test_parse_client_event_rejects_invalid_envelope(field, value):
    with pytest.raises(WSContractError):
        parse_client_event(_event(**{field: value}))


def test_legacy_events_are_allowed_only_by_explicit_compatibility_policy():
    with pytest.raises(WSContractError):
        parse_client_event({"type": "start_session", "interview_id": "old"})
    parsed = parse_client_event(
        {"type": "start_session", "interview_id": "old"},
        allow_legacy=True,
    )
    assert parsed.legacy is True


def test_integrity_aliases_are_normalized_without_inventing_observations():
    assert canonical_integrity_event("tab_switch") == "visibility_hidden"
    assert canonical_integrity_event("camera_track_ended") == "camera_stopped"
    with pytest.raises(WSContractError):
        canonical_integrity_event("candidate_cheated")


def test_controller_lease_is_short_renewable_and_owner_released():
    cache = FakeLocalCache()
    assert acquire_controller_lease(cache, "attempt-controller:1", "connection-1") is True
    assert cache.expiries["attempt-controller:1"] == CONTROLLER_LEASE_SECONDS
    assert acquire_controller_lease(cache, "attempt-controller:1", "connection-2") is False
    assert renew_controller_lease(cache, "attempt-controller:1", "connection-1") is True
    assert renew_controller_lease(cache, "attempt-controller:1", "connection-2") is False
    assert release_controller_lease(cache, "attempt-controller:1", "connection-2") is False
    assert release_controller_lease(cache, "attempt-controller:1", "connection-1") is True


def test_event_claim_deduplicates_and_rejects_non_monotonic_sequence():
    cache = FakeLocalCache()
    session_id = str(uuid4())
    interview_id = str(uuid4())
    first = parse_client_event(_event(client_session_id=session_id, interview_id=interview_id, sequence=1))
    duplicate = first
    stale = parse_client_event(_event(client_session_id=session_id, interview_id=interview_id, sequence=1))
    second = parse_client_event(_event(client_session_id=session_id, interview_id=interview_id, sequence=2))

    assert claim_event_sequence(cache, first) == "accepted"
    assert claim_event_sequence(cache, duplicate) == "duplicate"
    assert claim_event_sequence(cache, stale) == "out_of_order"
    assert claim_event_sequence(cache, second) == "accepted"
