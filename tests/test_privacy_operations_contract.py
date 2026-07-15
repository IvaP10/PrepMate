from pathlib import Path


def test_account_export_covers_attempt_and_evidence_domains():
    source = Path("user_profile.py").read_text(encoding="utf-8")
    required_tables = {
        "AttemptPreflightChecks",
        "AttemptContextSnapshots",
        "AttemptIntegrityEvents",
        "EvidenceManifests",
        "EvidenceCorrections",
        "MissionValidationEvidence",
    }
    assert all(table in source for table in required_tables)


def test_production_compose_has_no_application_host_docker_socket():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "/var/run/docker.sock" not in compose
    assert "dedicated gVisor controller" in compose


def test_release_runbook_has_restore_canary_rollback_and_chaos_gates():
    runbook = Path("infra/OPERATIONS_RUNBOOK.md").read_text(encoding="utf-8").lower()
    for term in ("restore", "canary", "rollback", "load and chaos", "gvisor", "openai"):
        assert term in runbook
