"""Private API-compatible executor for untrusted candidate code.

Every submission is copied into a new non-root, network-disabled, read-only
container and executed with the configured gVisor OCI runtime. The controller
is trusted infrastructure and is never exposed on the public application
network; candidate code never runs in this service process.
"""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import tarfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import docker
from docker.errors import APIError, ImageNotFound
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator


RUNTIME_IMAGE = os.getenv("SANDBOX_RUNTIME_IMAGE", "interai-sandbox-runtime:2026-07-v1")
OCI_RUNTIME = os.getenv("SANDBOX_OCI_RUNTIME", "runsc")
# Keep the executor and application on the same internal credential when a
# deployment uses the documented JWT-secret fallback. `or` is deliberate:
# Compose may pass an empty SANDBOX_API_TOKEN after host-side interpolation.
API_TOKEN = (
    os.getenv("SANDBOX_API_TOKEN")
    or os.getenv("INTERNAL_SERVICE_TOKEN")
    or os.getenv("JWT_SECRET", "")
)
MAX_SOURCE_BYTES = int(os.getenv("SANDBOX_SOURCE_LIMIT_BYTES", "20480"))
MAX_STDIN_BYTES = int(os.getenv("SANDBOX_STDIN_LIMIT_BYTES", "65536"))
MAX_OUTPUT_BYTES = int(os.getenv("SANDBOX_OUTPUT_LIMIT_BYTES", "65536"))
MAX_MEMORY_BYTES = int(os.getenv("SANDBOX_MEMORY_LIMIT_BYTES", str(256 * 1024 * 1024)))
MAX_PIDS = int(os.getenv("SANDBOX_PROCESS_LIMIT", "32"))
MAX_TIMEOUT_MS = int(os.getenv("SANDBOX_TIMEOUT_MS", "2000"))
MAX_ABSOLUTE_TIMEOUT_MS = int(os.getenv("SANDBOX_ABSOLUTE_TIMEOUT_MS", "10000"))
MAX_CONCURRENT_EXECUTIONS = int(os.getenv("SANDBOX_MAX_CONCURRENT_EXECUTIONS", "4"))
MAX_QUEUE_WAIT_SECONDS = float(os.getenv("SANDBOX_QUEUE_WAIT_SECONDS", "1.0"))
EXECUTION_SLOTS = asyncio.Semaphore(max(1, MAX_CONCURRENT_EXECUTIONS))

RUNTIMES = [
    {"language": "python", "version": "3.12", "aliases": ["py", "python3"]},
    {"language": "javascript", "version": "18", "aliases": ["js", "node"]},
    {"language": "java", "version": "17", "aliases": []},
    {"language": "c++", "version": "12", "aliases": ["cpp", "gcc", "g++"]},
]
LANGUAGE_ALIASES = {
    "python": "python",
    "py": "python",
    "python3": "python",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "java": "java",
    "c++": "c++",
    "cpp": "c++",
    "gcc": "c++",
    "g++": "c++",
}
FILE_NAMES = {"python": "main.py", "javascript": "main.js", "java": "Main.java", "c++": "main.cpp"}


class SourceFile(BaseModel):
    name: str = Field(default="main", max_length=80)
    content: str


class ExecuteRequest(BaseModel):
    language: str
    version: str = "*"
    files: list[SourceFile] = Field(min_length=1, max_length=1)
    stdin: str = ""
    run_timeout: int = 2000
    compile_timeout: int = 10_000
    run_memory_limit: int = MAX_MEMORY_BYTES

    @field_validator("language")
    @classmethod
    def supported_language(cls, value: str) -> str:
        normalized = LANGUAGE_ALIASES.get(str(value or "").strip().lower())
        if not normalized:
            raise ValueError("Unsupported language")
        return normalized

    @field_validator("files")
    @classmethod
    def source_size(cls, value: list[SourceFile]) -> list[SourceFile]:
        if len(value[0].content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the 20 KB limit")
        return value

    @field_validator("stdin")
    @classmethod
    def stdin_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_STDIN_BYTES:
            raise ValueError("Standard input exceeds the 64 KB limit")
        return value


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN or len(API_TOKEN) < 32:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Executor token is not configured")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not secrets.compare_digest(supplied, API_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid executor token")


def docker_client():
    return docker.from_env()


def runtime_ready(client: Any) -> tuple[bool, dict[str, Any]]:
    info = client.info()
    runtimes = info.get("Runtimes") or {}
    available = OCI_RUNTIME in runtimes
    try:
        client.images.get(RUNTIME_IMAGE)
        image_ready = True
    except ImageNotFound:
        image_ready = False
    return available and image_ready, {
        "oci_runtime": OCI_RUNTIME,
        "oci_runtime_available": available,
        "runtime_image": RUNTIME_IMAGE,
        "runtime_image_available": image_ready,
    }


def stale_candidate_container_count(client: Any) -> int:
    return len(client.containers.list(all=True, filters={"label": "interai.ephemeral=true"}))


def command_for_language(language: str) -> list[str]:
    commands = {
        "python": "python3 /workspace/main.py < /workspace/stdin.txt",
        "javascript": "node /workspace/main.js < /workspace/stdin.txt",
        "java": "javac /workspace/Main.java && java -cp /workspace Main < /workspace/stdin.txt",
        "c++": "g++ -std=c++17 -O2 -pipe /workspace/main.cpp -o /workspace/main && /workspace/main < /workspace/stdin.txt",
    }
    return ["/bin/sh", "-c", commands[language]]


def source_archive(language: str, source: str, stdin: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, payload in ((FILE_NAMES[language], source), ("stdin.txt", stdin)):
            raw = payload.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            info.mode = 0o600
            info.uid = 65532
            info.gid = 65532
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def execute_isolated(request: ExecuteRequest) -> dict[str, Any]:
    client = docker_client()
    ready, details = runtime_ready(client)
    if not ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"executor_not_ready": details})

    run_timeout_ms = max(100, min(int(request.run_timeout or MAX_TIMEOUT_MS), MAX_TIMEOUT_MS))
    compile_timeout_ms = max(100, min(int(request.compile_timeout or 0), MAX_ABSOLUTE_TIMEOUT_MS))
    timeout_ms = min(
        MAX_ABSOLUTE_TIMEOUT_MS,
        run_timeout_ms + (compile_timeout_ms if request.language in {"java", "c++"} else 0),
    )
    memory_limit = max(32 * 1024 * 1024, min(int(request.run_memory_limit or MAX_MEMORY_BYTES), MAX_MEMORY_BYTES))
    name = f"interai-run-{uuid.uuid4().hex[:16]}"
    container = None
    started = time.monotonic()
    timed_out = False
    try:
        container = client.containers.create(
            RUNTIME_IMAGE,
            command=command_for_language(request.language),
            name=name,
            user="65532:65532",
            network_disabled=True,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            runtime=OCI_RUNTIME,
            mem_limit=memory_limit,
            memswap_limit=memory_limit,
            pids_limit=MAX_PIDS,
            nano_cpus=1_000_000_000,
            environment={"HOME": "/workspace", "TMPDIR": "/tmp"},
            tmpfs={
                "/workspace": "rw,exec,nosuid,nodev,size=32m,uid=65532,gid=65532,mode=0700",
                "/tmp": "rw,noexec,nosuid,nodev,size=8m,uid=65532,gid=65532,mode=0700",
            },
            log_config=docker.types.LogConfig(type="local", config={"max-size": "64k", "max-file": "1"}),
            labels={"interai.component": "candidate-sandbox", "interai.ephemeral": "true"},
        )
        if not container.put_archive("/workspace", source_archive(request.language, request.files[0].content, request.stdin)):
            raise RuntimeError("Could not stage submission files")
        container.start()
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            container.reload()
            if container.status in {"exited", "dead"}:
                break
            time.sleep(0.025)
        else:
            timed_out = True
            container.kill()
        result = container.wait(timeout=2)
        exit_code = 124 if timed_out else int(result.get("StatusCode") or 0)
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        combined = (stdout + stderr).encode("utf-8", errors="replace")
        if len(combined) > MAX_OUTPUT_BYTES:
            stdout_raw = stdout.encode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stdout = stdout_raw.decode("utf-8", errors="ignore")
            remaining = max(0, MAX_OUTPUT_BYTES - len(stdout.encode("utf-8")))
            stderr = stderr.encode("utf-8", errors="replace")[:remaining].decode("utf-8", errors="ignore")
            stderr = (stderr + "\n[output truncated at 64 KB]").strip()
        wall_time = int((time.monotonic() - started) * 1000)
        return {
            "language": request.language,
            "version": request.version,
            "compile": {"stdout": "", "stderr": "", "code": 0, "wall_time": 0, "memory": 0},
            "run": {
                "stdout": stdout,
                "stderr": stderr,
                "code": exit_code,
                "status": "TO" if timed_out else "",
                "wall_time": wall_time,
                "memory": 0,
            },
        }
    except HTTPException:
        raise
    except (APIError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Sandbox execution failed: {type(exc).__name__}") from None
    finally:
        if container is not None:
            try:
                container.remove(force=True, v=True)
            except Exception:
                pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    def cleanup() -> None:
        client = docker_client()
        for container in client.containers.list(all=True, filters={"label": "interai.ephemeral=true"}):
            try:
                container.remove(force=True, v=True)
            except Exception:
                pass

    await asyncio.to_thread(cleanup)
    yield


app = FastAPI(
    title="InterAI Private Sandbox",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health(_: None = Depends(require_token)):
    try:
        client = docker_client()
        ready, details = await asyncio.to_thread(runtime_ready, client)
        stale_count = await asyncio.to_thread(stale_candidate_container_count, client)
        details["stale_candidate_containers"] = stale_count
        ready = ready and stale_count == 0
    except Exception:
        ready, details = False, {"docker_available": False}
    if not ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=details)
    return {"ready": True, **details}


@app.get("/api/v2/runtimes")
async def runtimes(_: None = Depends(require_token)):
    ready, details = await asyncio.to_thread(runtime_ready, docker_client())
    if not ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=details)
    return RUNTIMES


@app.post("/api/v2/execute")
async def execute(request: ExecuteRequest, _: None = Depends(require_token)):
    acquired = False
    try:
        await asyncio.wait_for(EXECUTION_SLOTS.acquire(), timeout=max(0.05, MAX_QUEUE_WAIT_SECONDS))
        acquired = True
        return await asyncio.to_thread(execute_isolated, request)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Executor capacity is full; retry with backoff",
        ) from None
    finally:
        if acquired:
            EXECUTION_SLOTS.release()
