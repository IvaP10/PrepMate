import asyncio
from unittest.mock import AsyncMock, patch

import analysis
from analysis import _analysis_trigger_decision


def test_analysis_trigger_rejects_active_and_cancelled_attempts():
    assert _analysis_trigger_decision("in_progress", False) == "reject"
    assert _analysis_trigger_decision("recovering", False) == "reject"
    assert _analysis_trigger_decision("cancelled", False) == "reject"


def test_analysis_trigger_is_monotonic_for_ready_and_running_reports():
    assert _analysis_trigger_decision("completed", True) == "ready"
    assert _analysis_trigger_decision("partial", True) == "ready"
    assert _analysis_trigger_decision("analysis_running", False) == "enqueue"
    assert _analysis_trigger_decision("failed", False) == "enqueue"


def test_performance_reconciliation_requeues_missing_canonical_analyses():
    enqueue = AsyncMock(side_effect=["job-1", "job-2"])
    with patch.object(analysis, "async_execute", AsyncMock(return_value=[("interview-1",), ("interview-2",)])), patch.object(
        analysis,
        "enqueue_analysis",
        enqueue,
    ):
        result = asyncio.run(analysis.reconcile_performance(current_user={"user_id": "user-1"}))

    assert result["queued_count"] == 2
    assert all(call.kwargs["force_canonical_rebuild"] is True for call in enqueue.await_args_list)
