import io
import asyncio
import sys
import tarfile
import types

import pytest
from pydantic import ValidationError


docker_stub = types.ModuleType("docker")
docker_errors_stub = types.ModuleType("docker.errors")


class APIError(Exception):
    pass


class ImageNotFound(Exception):
    pass


class LogConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


docker_errors_stub.APIError = APIError
docker_errors_stub.ImageNotFound = ImageNotFound
docker_stub.errors = docker_errors_stub
docker_stub.types = types.SimpleNamespace(LogConfig=LogConfig)
docker_stub.from_env = lambda: None
sys.modules.setdefault("docker", docker_stub)
sys.modules.setdefault("docker.errors", docker_errors_stub)

from infra.sandbox import service


class FakeImages:
    def get(self, image):
        assert image == service.RUNTIME_IMAGE
        return object()


class FakeContainer:
    def __init__(self):
        self.status = "created"
        self.archive = b""
        self.removed = False
        self.events = []
        self.id = "container-1"

    def put_archive(self, path, archive):
        assert path == "/workspace"
        assert self.status == "running"
        self.events.append("put_archive")
        self.archive = archive
        return True

    def start(self):
        self.events.append("start")
        self.status = "running"

    def reload(self):
        self.status = "exited"

    def wait(self, timeout):
        return {"StatusCode": 0}

    def logs(self, *, stdout, stderr):
        return b"ok\n" if stdout else b""

    def remove(self, **kwargs):
        self.removed = True


class FakeContainers:
    def __init__(self):
        self.created_kwargs = None
        self.container = FakeContainer()

    def create(self, image, **kwargs):
        assert image == service.RUNTIME_IMAGE
        self.created_kwargs = kwargs
        return self.container

    def list(self, **kwargs):
        return []


class FakeSocket:
    def __init__(self, container):
        self._sock = self
        self.container = container

    def sendall(self, archive):
        self.container.events.append("stage_archive")
        self.container.archive = archive

    def shutdown(self, _direction):
        self.container.events.append("stage_eof")

    def recv(self, _size):
        return b""

    def close(self):
        self.container.events.append("stage_close")


class FakeAPI:
    def __init__(self, container):
        self.container = container

    def exec_create(self, container_id, command, **kwargs):
        assert container_id == self.container.id
        assert command == ["/bin/tar", "-x", "-C", "/workspace", "--no-same-owner"]
        assert kwargs["user"] == "65532:65532"
        self.container.events.append("stage_create")
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, **kwargs):
        assert exec_id == "exec-1"
        assert kwargs["socket"] is True
        self.container.events.append("stage_start")
        return FakeSocket(self.container)

    def exec_inspect(self, exec_id):
        assert exec_id == "exec-1"
        return {"Running": False, "ExitCode": 0}


class FakeClient:
    def __init__(self):
        self.images = FakeImages()
        self.containers = FakeContainers()
        self.api = FakeAPI(self.containers.container)

    def info(self):
        return {"Runtimes": {"runsc": {"path": "runsc"}, "runc": {"path": "runc"}}}


def request(language="python", source="print('ok')", stdin=""):
    return service.ExecuteRequest(
        language=language,
        version="1",
        files=[{"name": "ignored", "content": source}],
        stdin=stdin,
    )


def test_submission_is_staged_as_data_and_command_is_fixed():
    source = "print('safe'); __import__('os').system('id')"
    archive = service.source_archive("python", source, "input")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as bundle:
        assert bundle.extractfile("main.py").read().decode() == source
        assert bundle.extractfile("stdin.txt").read().decode() == "input"
        assert bundle.extractfile(".interai-ready").read().decode() == "ready"
    assert source not in " ".join(service.command_for_language("python"))


def test_executor_enforces_gvisor_and_defence_in_depth(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(service, "docker_client", lambda: client)

    result = service.execute_isolated(request())

    options = client.containers.created_kwargs
    assert options["runtime"] == "runsc"
    assert options["user"] == "65532:65532"
    assert options["network_disabled"] is True
    assert options["read_only"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["pids_limit"] <= 32
    assert options["mem_limit"] <= 256 * 1024 * 1024
    assert options["tmpfs"]["/workspace"].startswith("rw,exec,nosuid,nodev")
    assert options["log_config"].kwargs["type"] == "json-file"
    assert options["log_config"].kwargs["config"] == {
        "max-size": "128k",
        "max-file": "1",
    }
    assert client.containers.container.events == [
        "start", "stage_create", "stage_start", "stage_archive", "stage_eof", "stage_close",
    ]
    assert result["run"]["stdout"] == "ok\n"
    assert result["run"]["truncated"] is False
    assert client.containers.container.removed is True


def test_executor_rejects_unsupported_language_and_oversized_source():
    with pytest.raises(ValidationError):
        request(language="bash")
    with pytest.raises(ValidationError):
        request(source="x" * (service.MAX_SOURCE_BYTES + 1))


def test_output_truncation_marker_is_inside_the_response_cap():
    stdout, stderr, truncated = service.bound_execution_output("x" * 100_000, "candidate stderr")

    assert truncated is True
    assert stderr.endswith("[output truncated at 64 KB]")
    assert len((stdout + stderr).encode("utf-8")) <= service.MAX_OUTPUT_BYTES


def test_output_bound_preserves_utf8_and_both_streams_when_small():
    stdout, stderr, truncated = service.bound_execution_output("ok ✅", "warning")

    assert (stdout, stderr, truncated) == ("ok ✅", "warning", False)


def test_readiness_fails_without_required_oci_runtime():
    client = FakeClient()
    client.info = lambda: {"Runtimes": {"runc": {"path": "runc"}}}
    ready, details = service.runtime_ready(client)
    assert ready is False
    assert details["oci_runtime_available"] is False


def test_stale_candidate_container_count_uses_ephemeral_label_filter():
    client = FakeClient()
    assert service.stale_candidate_container_count(client) == 0


def test_controller_requires_a_strong_bearer_token(monkeypatch):
    token = "sandbox-test-token-that-is-longer-than-32-characters"
    monkeypatch.setattr(service, "API_TOKEN", token)

    with pytest.raises(service.HTTPException) as missing:
        service.require_token(None)
    assert missing.value.status_code == 401

    service.require_token(f"Bearer {token}")


def test_executor_rejects_when_admission_queue_is_full(monkeypatch):
    class FullSemaphore:
        async def acquire(self):
            await asyncio.Future()

        def release(self):
            raise AssertionError("A slot that was not acquired must not be released")

    monkeypatch.setattr(service, "EXECUTION_SLOTS", FullSemaphore())
    monkeypatch.setattr(service, "MAX_QUEUE_WAIT_SECONDS", 0.01)

    with pytest.raises(service.HTTPException) as saturated:
        asyncio.run(service.execute(request(), None))
    assert saturated.value.status_code == 429


def test_timeout_kill_race_accepts_container_that_just_exited():
    class ExitedAtDeadline:
        status = "running"

        def kill(self):
            self.status = "exited"
            error = service.APIError("container is not running")
            error.status_code = 409
            raise error

        def reload(self):
            return None

    assert service.kill_timed_out_container(ExitedAtDeadline()) is False
