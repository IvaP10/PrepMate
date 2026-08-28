"""Sandboxed local code execution for desktop Technical Round practice.

Execution is fail-closed. macOS uses Seatbelt and Linux uses bubblewrap; a
platform without a verified isolation primitive reports the runner as
unavailable instead of executing candidate code on the user's host.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


MAX_SOURCE_BYTES = 20 * 1024
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10


def _limit_process() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS + 1))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    except (ImportError, OSError, ValueError):
        pass


def _process_env(workdir: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "LANG": "C.UTF-8",
    }


def _language_runtime(language: str) -> tuple[str | None, str]:
    """Find a language runtime without treating a frozen backend as Python."""
    normalized = str(language or "").strip().lower()
    if normalized == "python":
        if getattr(sys, "frozen", False):
            configured = os.getenv("PREPMATE_EMBEDDED_PYTHON", "").strip()
            if configured and Path(configured).is_file() and Path(configured) != Path(sys.executable):
                return configured, ""
            return None, "Python execution is disabled in the packaged alpha until a separate Python runtime is bundled."
        # Run the real interpreter binary, not a virtual-environment shim that
        # may live under a user-writable project or temporary directory.  This
        # also keeps the Seatbelt allowlist independent of the checkout path.
        return str(Path(sys.executable).resolve()), ""
    if normalized == "javascript":
        command = shutil.which("node")
        return (command, "") if command else (None, "Node.js is not installed.")
    if normalized == "cpp":
        command = shutil.which("g++")
        return (command, "") if command else (None, "A C++ compiler (g++) is not installed.")
    if normalized == "java":
        compiler = shutil.which("javac")
        runtime = shutil.which("java")
        return (runtime, "") if compiler and runtime else (None, "A Java runtime and compiler are not installed.")
    return None, "This language is not supported by the local runner."


def _macos_profile(workdir: Path) -> Path:
    allowed_roots = [
        Path("/System"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/Library"),
        Path("/Applications/Xcode.app/Contents/Developer"),
        Path("/opt"),
        Path("/private/var/db/timezone"),
        Path("/dev"),
        workdir,
    ]
    readable = "\n".join(
        f'    (subpath "{str(path.resolve()).replace(chr(34), "")}")'
        for path in allowed_roots
        if path.exists()
    )
    profile = workdir / "prepmate.sb"
    profile.write_text(
        "\n".join(
            [
                "(version 1)",
                "(deny default)",
                '(import "system.sb")',
                "(allow process*)",
                "(allow signal (target self))",
                "(allow file-read* file-test-existence file-map-executable",
                readable,
                ")",
                f'(allow file-write* (subpath "{str(workdir.resolve())}"))',
            ]
        ),
        encoding="utf-8",
    )
    return profile


def _sandbox_command(command: list[str], workdir: Path) -> tuple[list[str], str]:
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        profile = _macos_profile(workdir)
        return ["sandbox-exec", "-f", str(profile), "--", *command], "macos-seatbelt"

    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        roots: list[str] = []
        for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/alternatives"):
            if Path(path).exists():
                roots.extend(["--ro-bind", path, path])
        return [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            *roots,
            "--bind", str(workdir), str(workdir),
            "--chdir", str(workdir),
            "--setenv", "HOME", str(workdir),
            "--setenv", "TMPDIR", str(workdir),
            "--",
            *command,
        ], "linux-bubblewrap"

    raise RuntimeError("No supported local code sandbox is available on this system")


def executor_status() -> dict[str, Any]:
    sandbox = ""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        sandbox = "macos-seatbelt"
    elif sys.platform.startswith("linux") and shutil.which("bwrap"):
        sandbox = "linux-bubblewrap"
    if sandbox:
        languages = {}
        for language in ("python", "javascript", "cpp", "java"):
            runtime, reason = _language_runtime(language)
            languages[language] = {
                "available": bool(runtime),
                "runtime": Path(runtime).name if runtime else None,
                "reason": reason or "Ready",
            }
        return {
            "healthy": True,
            "executor": sandbox,
            "isolated": True,
            "languages": languages,
            "available_languages": [name for name, item in languages.items() if item["available"]],
        }
    return {
        "healthy": False,
        "executor": "unavailable",
        "isolated": False,
        "reason": "Install a supported OS sandbox to enable Technical code execution.",
        "languages": {},
        "available_languages": [],
    }


def _run(command: list[str], *, cwd: Path, stdin: bytes, timeout: float, sandbox: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    process = None
    try:
        isolated_command, executor = _sandbox_command(command, cwd) if sandbox else (command, "host-compiler")
        process = subprocess.Popen(
            isolated_command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_process_env(cwd),
            start_new_session=True,
            preexec_fn=_limit_process if os.name != "nt" else None,
        )
        stdout, stderr = process.communicate(input=stdin[:MAX_INPUT_BYTES], timeout=timeout)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": process.returncode,
            "runtime_ms": int((time.monotonic() - started) * 1000),
            "timed_out": False,
            "executor": executor,
        }
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        try:
            if process is not None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                stdout, stderr = process.communicate(timeout=2)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
        return {
            "stdout": (stdout or b"")[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout or "")[:MAX_OUTPUT_BYTES],
            "stderr": "Execution timed out.",
            "exit_code": -1,
            "runtime_ms": int(timeout * 1000),
            "timed_out": True,
            "executor": "local-sandbox",
        }
    except (OSError, RuntimeError) as exc:
        return {
            "stdout": "",
            "stderr": f"Local runtime is unavailable: {exc}",
            "exit_code": -1,
            "runtime_ms": int((time.monotonic() - started) * 1000),
            "timed_out": False,
            "executor": "unavailable",
        }


async def execute_local(language: str, source: str, stdin: str) -> dict[str, Any]:
    language = str(language or "").strip().lower()
    source = str(source or "")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return {"stdout": "", "stderr": "Source code is too large.", "exit_code": -1, "timed_out": False}
    runtime, runtime_reason = _language_runtime(language)
    if runtime is None:
        return {
            "stdout": "",
            "stderr": f"Local runtime is unavailable: {runtime_reason}",
            "exit_code": -1,
            "timed_out": False,
            "executor": "unavailable",
        }

    def run() -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="prepmate-run-") as temporary:
            cwd = Path(temporary)
            if language == "python":
                script = cwd / "main.py"
                script.write_text(source, encoding="utf-8")
                command = [runtime, "-I", str(script)]
            elif language == "javascript":
                script = cwd / "main.js"
                script.write_text(source, encoding="utf-8")
                command = [runtime, "--max-old-space-size=256", str(script)]
            elif language == "cpp":
                script = cwd / "main.cpp"
                binary = cwd / "main"
                script.write_text(source, encoding="utf-8")
                compiled = _run([runtime, "-std=c++17", "-O2", str(script), "-o", str(binary)], cwd=cwd, stdin=b"", timeout=TIMEOUT_SECONDS)
                if compiled.get("exit_code") != 0:
                    return {**compiled, "compile_failed": True}
                command = [str(binary)]
            elif language == "java":
                script = cwd / "Main.java"
                script.write_text(source, encoding="utf-8")
                compiler = shutil.which("javac")
                if not compiler:
                    return {
                        "stdout": "",
                        "stderr": "Local runtime is unavailable: A Java runtime and compiler are not installed.",
                        "exit_code": -1,
                        "timed_out": False,
                        "executor": "unavailable",
                    }
                compiled = _run([compiler, str(script)], cwd=cwd, stdin=b"", timeout=TIMEOUT_SECONDS)
                if compiled.get("exit_code") != 0:
                    return {**compiled, "compile_failed": True}
                command = [runtime, "-cp", str(cwd), "Main"]
            else:
                return {"stdout": "", "stderr": "Unsupported language.", "exit_code": -1, "timed_out": False}
            result = _run(command, cwd=cwd, stdin=str(stdin or "").encode("utf-8"), timeout=TIMEOUT_SECONDS)
            result["source_hash"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
            return result

    return await asyncio.to_thread(run)
