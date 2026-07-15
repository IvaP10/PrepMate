import json
from unittest.mock import patch

import pytest

from observability import _post_json, observe_http_request, observe_readiness, prometheus_metrics


def test_prometheus_payload_contains_privacy_safe_route_metrics():
    observe_http_request("GET", "/api/interview/{interview_id}", 200, 0.025)

    payload, content_type = prometheus_metrics()

    text = payload.decode("utf-8")
    assert "interai_http_requests_total" in text
    assert '/api/interview/{interview_id}' in text
    assert "text/plain" in content_type


def test_readiness_metrics_include_dependencies_workers_and_durable_queues():
    observe_readiness({
        "checks": {
            "database_migrations": {"healthy": True},
            "redis": {"healthy": True},
            "openai": {"healthy": True},
            "sandbox_executor": {"healthy": False},
            "workers_jobs": {
                "healthy": False,
                "workers": {"analysis": {"heartbeat_age_seconds": 7, "max_age_seconds": 45}},
                "queues": {"analysis": {"depth": 2, "oldest_age_seconds": 11}},
                "stuck_jobs": {"analysis": {"expired_leases": 1}},
            },
        }
    })

    text = prometheus_metrics()[0].decode("utf-8")
    assert 'interai_dependency_healthy{dependency="sandbox_executor"} 0.0' in text
    assert 'interai_job_queue_depth{worker_type="analysis"} 2.0' in text
    assert 'interai_stuck_jobs{reason="expired_leases",worker_type="analysis"} 1.0' in text


def test_sync_telemetry_transport_posts_json_over_https():
    response = type("Response", (), {"close": lambda self: None})()
    with patch("observability.urllib.request.urlopen", return_value=response) as urlopen:
        _post_json("https://telemetry.example.test/events", {"event": "report_ready"}, {"X-Test": "1"})

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://telemetry.example.test/events"
    assert json.loads(request.data.decode("utf-8")) == {"event": "report_ready"}


@pytest.mark.parametrize("url", ["http://telemetry.example.test", "file:///tmp/events"])
def test_sync_telemetry_transport_rejects_non_https(url):
    with patch("observability.urllib.request.urlopen") as urlopen:
        _post_json(url, {"event": "ignored"}, {})

    urlopen.assert_not_called()
