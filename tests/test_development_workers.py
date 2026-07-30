import asyncio
import importlib
import sys


def _fresh_app_module():
    sys.modules.pop("app", None)
    sys.modules.pop("database", None)
    return importlib.import_module("app")


def test_development_lifespan_starts_managed_durable_worker_process(monkeypatch):
    app_module = _fresh_app_module()
    started = asyncio.Event()
    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        process.args = args
        process.kwargs = kwargs
        started.set()
        return process

    monkeypatch.setattr(app_module.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(app_module.settings, "DEVELOPMENT_AUTO_WORKER", True)
    monkeypatch.setattr(app_module, "init_connection_pool", lambda: None)
    monkeypatch.setattr(app_module, "ensure_runtime_schema", lambda: None)
    monkeypatch.setattr(app_module, "init_redis_client", lambda: None)
    monkeypatch.setattr(app_module, "close_connection_pool", lambda: None)
    monkeypatch.setattr(app_module, "close_redis", lambda: None)
    monkeypatch.setattr(app_module, "check_expired_subscriptions", _wait_forever)
    monkeypatch.setattr(app_module, "process_notification_reminders", _wait_forever)
    monkeypatch.setattr(app_module, "periodic_connection_cleanup", _wait_forever)
    monkeypatch.setattr(app_module, "cleanup_stale_interviews", _wait_forever)
    monkeypatch.setattr(app_module, "prewarm_speech_pipeline", _complete)
    monkeypatch.setattr(app_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def run():
        async with app_module.lifespan(app_module.app):
            await asyncio.wait_for(started.wait(), timeout=1)

    asyncio.run(run())
    assert process.args[0] == sys.executable
    assert str(process.args[1]).endswith("worker.py")
    assert process.terminated is True


def test_development_server_reload_is_opt_in(monkeypatch):
    app_module = _fresh_app_module()
    monkeypatch.setattr(app_module.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(app_module.settings, "DEVELOPMENT_AUTO_RELOAD", False)

    assert app_module._development_auto_reload_enabled() is False

    monkeypatch.setattr(app_module.settings, "DEVELOPMENT_AUTO_RELOAD", True)
    assert app_module._development_auto_reload_enabled() is True

    monkeypatch.setattr(app_module.settings, "ENVIRONMENT", "production")
    assert app_module._development_auto_reload_enabled() is False


async def _wait_forever(*_args, **_kwargs):
    await asyncio.Event().wait()


async def _complete(*_args, **_kwargs):
    return None


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.args = ()
        self.kwargs = {}

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    async def wait(self):
        return self.returncode
