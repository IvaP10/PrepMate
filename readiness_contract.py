"""Pure readiness-contract helpers shared by the API and unit tests."""

from datetime import datetime, timezone


def build_feature_capabilities(checks: dict) -> list[dict]:
    """Return independent, user-facing capability states for local setup.

    A missing provider or code sandbox should explain only the feature it
    affects. Typed practice, local data controls, and optional coaching remain
    discoverable instead of being hidden behind one global readiness failure.
    """
    storage = checks.get("database") or checks.get("storage") or {}
    provider = checks.get("provider") or {}
    workers = checks.get("workers") or {}
    content = checks.get("technical_content") or {}
    runner = checks.get("code_runner") or {}
    storage_ready = bool(storage.get("healthy"))
    workers_ready = bool(workers.get("healthy"))
    provider_ready = bool(provider.get("healthy"))
    voice_ready = provider_ready and bool(provider.get("voice_transcription"))
    runner_ready = bool(runner.get("healthy"))

    def item(name: str, label: str, state: str, reason: str) -> dict:
        return {"id": name, "label": label, "status": state, "reason": reason}

    return [
        item(
            "local_storage",
            "Local storage",
            "available" if storage_ready else "unavailable",
            "SQLite is ready. Secure storage is requested only when a sensitive save needs it." if storage_ready else "Local SQLite storage is unavailable.",
        ),
        item(
            "text_generation",
            "AI text generation",
            "available" if provider_ready else "setup_required",
            "The selected provider is configured." if provider_ready else "Choose a provider, model, and key (or a loopback endpoint) in Settings.",
        ),
        item(
            "typed_practice",
            "Typed interview and coaching",
            "available" if storage_ready and workers_ready else "unavailable",
            "Typed practice is ready." if storage_ready and workers_ready else "The local storage or worker service is unavailable.",
        ),
        item(
            "voice_transcription",
            "Voice transcription",
            "available" if voice_ready else "setup_required",
            "The selected provider supports transcription." if voice_ready else "Voice transcription needs a configured provider with transcription support; typed input remains available.",
        ),
        item(
            "reports_and_coaching",
            "Reports, Performance, and Improve",
            "available" if storage_ready and workers_ready and provider_ready else "setup_required",
            "Reports and coaching can run locally." if storage_ready and workers_ready and provider_ready else "Configure a provider and keep the local worker available.",
        ),
        item(
            "technical_questions",
            "Technical questions",
            "available" if storage_ready and workers_ready and bool(content.get("healthy")) else "unavailable",
            "Technical content is available." if storage_ready and workers_ready and bool(content.get("healthy")) else "Technical content is not available in this source checkout.",
        ),
        item(
            "technical_execution",
            "Technical code execution",
            "available" if runner_ready else "unavailable",
            "The OS sandbox and a supported runtime are available." if runner_ready else str(runner.get("reason") or "A supported OS sandbox and runtime are required; execution is disabled until detected."),
        ),
        item("camera_coaching", "Optional camera coaching", "available", "Enabled only after you choose the camera coaching control."),
        item("screen_coaching", "Optional screen coaching", "available", "Enabled only after you choose the screen coaching control."),
        item(
            "data_controls",
            "Export and local deletion",
            "available" if storage_ready else "unavailable",
            "Export, selective deletion, cache clearing, and complete wipe are available." if storage_ready else "Local storage is unavailable.",
        ),
    ]


def build_flow_readiness_payload(
    flow: str,
    checks: dict,
    *,
    recovery_grace_seconds: int,
) -> dict:
    workers_payload = checks.get("workers") or {}
    workers = workers_payload.get("workers") or {}
    stuck_jobs = workers_payload.get("stuck_jobs") or {}
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
        "storage": checks.get("storage") or {"healthy": False},
        "provider": checks.get("provider") or {"healthy": False},
        "workers": {
            "healthy": workers_ready,
            "required": worker_health,
            "process": workers_payload.get("process") or {},
        },
    }
    if flow == "technical":
        selected["technical_content"] = checks.get("technical_content") or {"healthy": False}
        selected["code_runner"] = {
            **(checks.get("code_runner") or {"healthy": False}),
            "required": False,
        }
    required_checks = ["storage", "provider", "workers"] + (["technical_content"] if flow == "technical" else [])
    ready_value = all(bool(selected[name].get("healthy")) for name in required_checks)
    server_time = datetime.now(timezone.utc).isoformat()
    return {
        "flow": flow,
        "ready": ready_value,
        "status": "ready" if ready_value else "not_ready",
        "message": (
            "Local runtime is ready."
            if ready_value
            else (
                "Technical questions are unavailable until their required setup is complete."
                if flow == "technical"
                else "Choose an AI provider and API key in Settings to begin."
            )
        ),
        "checks": selected,
        "recovery_grace_seconds": recovery_grace_seconds,
        "time": server_time,
        "server_time": server_time,
    }
