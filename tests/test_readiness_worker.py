import asyncio
import json
import sys
import unittest
from unittest.mock import patch


class ReadinessContractTests(unittest.TestCase):
    @staticmethod
    def _app_module():
        # Some isolated analysis tests install a deliberately tiny database
        # module. Readiness is an integration boundary and must exercise the
        # physical module, independent of test collection order.
        database_module = sys.modules.get("database")
        if database_module is not None and not getattr(database_module, "__file__", None):
            del sys.modules["database"]
        import app

        return app

    def test_live_is_process_only(self):
        app_module = self._app_module()
        with patch.object(app_module, "collect_readiness", side_effect=AssertionError("must not probe dependencies")):
            payload = asyncio.run(app_module.live())
        self.assertEqual(payload["status"], "alive")
        self.assertIn("started_at", payload)

    def test_ready_returns_503_when_any_required_component_is_unhealthy(self):
        app_module = self._app_module()
        payload = {
            "status": "not_ready",
            "ready": False,
            "time": "2026-07-11T00:00:00+00:00",
            "checks": {"workers_jobs": {"healthy": False}},
        }
        with patch.object(app_module, "collect_readiness", return_value=payload):
            response = asyncio.run(app_module.ready())
        self.assertEqual(response.status_code, 503)
        self.assertFalse(json.loads(response.body)["ready"])

    def test_collect_readiness_requires_every_gate(self):
        app_module = self._app_module()

        async def safe(name, _awaitable):
            if asyncio.iscoroutine(_awaitable):
                _awaitable.close()
            return name, {"healthy": name != "workers_jobs"}

        with patch.object(app_module, "_safe_readiness_check", side_effect=safe):
            payload = asyncio.run(app_module.collect_readiness())
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "not_ready")

    def test_public_executor_is_rejected_without_network_probe(self):
        app_module = self._app_module()
        with patch.object(app_module.settings, "PISTON_API_URL", "https://example.com/api/v2"):
            result = asyncio.run(app_module._sandbox_executor_check())
        self.assertFalse(result["healthy"])
        self.assertFalse(result["private"])

    def test_private_sandbox_requires_every_configured_runtime(self):
        app_module = self._app_module()

        class FakeResponse:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return [
                    {"language": "python", "aliases": ["py"]},
                    {"language": "javascript", "aliases": ["js"]},
                    {"language": "java", "aliases": []},
                ]

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url, **_kwargs):
                return FakeResponse()

        with (
            patch.object(app_module.settings, "PISTON_API_URL", "http://sandbox:8080/api/v2"),
            patch.object(app_module.settings, "PISTON_EXPECTED_RUNTIMES", "python,javascript,java,c++"),
            patch.object(app_module.httpx, "AsyncClient", FakeClient),
        ):
            result = asyncio.run(app_module._sandbox_executor_check())
        self.assertFalse(result["healthy"])
        self.assertEqual(result["missing_runtimes"], ["c++"])

    def test_flow_preflight_keeps_internal_dependency_names_out_of_user_message(self):
        from readiness_contract import build_flow_readiness_payload

        checks = {
            "database_migrations": {"healthy": True},
            "redis": {"healthy": True},
            "openai": {"healthy": False},
            "sandbox_executor": {"healthy": False},
            "workers_jobs": {
                "workers": {
                    "analysis": {"healthy": True},
                    "technical": {"healthy": True},
                },
                "stuck_jobs": {"analysis": {}, "technical": {}},
            },
        }
        payload = build_flow_readiness_payload("technical", checks, recovery_grace_seconds=30)

        self.assertFalse(payload["ready"])
        self.assertEqual(
            payload["message"],
            "Technical round services are temporarily unavailable. Please try again shortly.",
        )
        self.assertNotIn("sandbox_executor", payload["message"])


class WorkerSupervisorTests(unittest.TestCase):
    def test_graceful_stop_cancels_both_consumers(self):
        from worker import supervise_workers

        async def scenario():
            stop_event = asyncio.Event()
            started = {"analysis": asyncio.Event(), "technical": asyncio.Event()}

            async def analysis_loop(_worker_id, *, stop_event, idle_seconds):
                started["analysis"].set()
                await stop_event.wait()

            async def technical_loop(_worker_id, *, poll_seconds):
                started["technical"].set()
                await asyncio.Event().wait()

            supervisor = asyncio.create_task(supervise_workers(
                stop_event=stop_event,
                analysis_worker_id="analysis-test",
                technical_worker_id="technical-test",
                analysis_loop=analysis_loop,
                technical_loop=technical_loop,
            ))
            await asyncio.gather(started["analysis"].wait(), started["technical"].wait())
            stop_event.set()
            await asyncio.wait_for(supervisor, timeout=1)

        asyncio.run(scenario())

    def test_consumer_crash_fails_combined_process(self):
        from worker import supervise_workers

        async def scenario():
            async def broken_analysis(_worker_id, **_kwargs):
                raise ValueError("boom")

            async def technical_loop(_worker_id, **_kwargs):
                await asyncio.Event().wait()

            with self.assertRaisesRegex(RuntimeError, "analysis_worker_crashed"):
                await supervise_workers(
                    stop_event=asyncio.Event(),
                    analysis_worker_id="analysis-test",
                    technical_worker_id="technical-test",
                    analysis_loop=broken_analysis,
                    technical_loop=technical_loop,
                )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
