"""Pure readiness-contract helpers shared by the API and unit tests."""

from datetime import datetime, timezone


def build_flow_readiness_payload(
    flow: str,
    checks: dict,
    *,
    recovery_grace_seconds: int,
) -> dict:
    workers_jobs = checks.get("workers_jobs") or {}
    workers = workers_jobs.get("workers") or {}
    stuck_jobs = workers_jobs.get("stuck_jobs") or {}
    required_worker_types = ["analysis"] + (["technical"] if flow == "technical" else [])
    worker_health = {
        worker_type: {
            **(workers.get(worker_type) or {}),
            "stuck_jobs": stuck_jobs.get(worker_type) or {},
        }
        for worker_type in required_worker_types
    }
    workers_ready = all(
        bool(worker_health[worker_type].get("healthy"))
        and not any(int(value or 0) for value in worker_health[worker_type]["stuck_jobs"].values())
        for worker_type in required_worker_types
    )
    selected = {
        "database_migrations": checks.get("database_migrations") or {"healthy": False},
        "redis": checks.get("redis") or {"healthy": False},
        "openai": checks.get("openai") or {"healthy": False},
        "workers": {"healthy": workers_ready, "required": worker_health},
    }
    if flow == "technical":
        selected["technical_content"] = checks.get("technical_content") or {"healthy": False}
        selected["sandbox_executor"] = checks.get("sandbox_executor") or {"healthy": False}
    ready_value = all(bool(item.get("healthy")) for item in selected.values())
    server_time = datetime.now(timezone.utc).isoformat()
    return {
        "flow": flow,
        "ready": ready_value,
        "status": "ready" if ready_value else "not_ready",
        "message": (
            "All required services are ready."
            if ready_value
            else (
                "Technical code execution is temporarily unavailable. Try again when the secure executor is online."
                if flow == "technical"
                else "Interview services are temporarily unavailable. Please try again shortly."
            )
        ),
        "checks": selected,
        "recovery_grace_seconds": recovery_grace_seconds,
        "time": server_time,
        "server_time": server_time,
    }
