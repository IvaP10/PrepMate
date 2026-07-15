#!/usr/bin/env python3
"""Adversarial deployment probe for the private candidate-code sandbox."""

from __future__ import annotations

import json
import os
import sys
import concurrent.futures
import urllib.error
import urllib.request


BASE_URL = os.getenv("SANDBOX_URL", "http://127.0.0.1:8080/api/v2").rstrip("/")
TOKEN = os.getenv("SANDBOX_API_TOKEN", "")


def execute(source: str, *, timeout: int = 2000) -> dict:
    payload = json.dumps(
        {
            "language": "python",
            "version": "3.12",
            "files": [{"name": "main.py", "content": source}],
            "stdin": "",
            "run_timeout": timeout,
        }
    ).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/execute",
        data=payload,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def health() -> dict:
    request = urllib.request.Request(
        BASE_URL.removesuffix("/api/v2") + "/health",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def run_output(source: str, *, timeout: int = 2000) -> tuple[str, str, int, str]:
    result = execute(source, timeout=timeout)
    run = result.get("run") or {}
    return (
        str(run.get("stdout") or ""),
        str(run.get("stderr") or ""),
        int(run.get("code") or 0),
        str(run.get("status") or ""),
    )


def main() -> int:
    if len(TOKEN) < 32:
        print("SANDBOX_API_TOKEN must contain at least 32 characters", file=sys.stderr)
        return 2

    checks: list[tuple[str, bool, str]] = []

    stdout, stderr, code, _ = run_output("print(6 * 7)")
    checks.append(("normal execution", stdout.strip() == "42" and code == 0, stderr))

    stdout, stderr, code, _ = run_output("def broken(:\n pass")
    checks.append(("syntax error truthful", code != 0 and "SyntaxError" in stderr, stderr))

    stdout, stderr, code, _ = run_output("raise RuntimeError('candidate failure')")
    checks.append(("runtime error truthful", code != 0 and "candidate failure" in stderr, stderr))

    stdout, stderr, code, _ = run_output(
        "import socket\n"
        "try:\n socket.create_connection(('1.1.1.1', 53), timeout=.5); print('NETWORK_OPEN')\n"
        "except OSError: print('NETWORK_BLOCKED')\n"
    )
    checks.append(("network disabled", stdout.strip() == "NETWORK_BLOCKED" and code == 0, stderr))

    stdout, stderr, code, _ = run_output(
        "from pathlib import Path\n"
        "try:\n Path('/escape').write_text('x'); print('ROOT_WRITABLE')\n"
        "except OSError: print('ROOT_READ_ONLY')\n"
    )
    checks.append(("root filesystem read-only", stdout.strip() == "ROOT_READ_ONLY" and code == 0, stderr))

    stdout, stderr, code, _ = run_output(
        "from pathlib import Path\n"
        "data=Path('/proc/1/cmdline').read_bytes().decode(errors='replace')\n"
        "print('PROC_ISOLATED' if 'dockerd' not in data and 'uvicorn' not in data else 'HOST_PROC_VISIBLE')\n"
    )
    checks.append(("process namespace isolated", stdout.strip() == "PROC_ISOLATED" and code == 0, stderr))

    stdout, stderr, code, _ = run_output(
        "import os\nchildren=[]\n"
        "try:\n"
        " while len(children) < 128:\n  pid=os.fork()\n  if pid == 0: os._exit(0)\n  children.append(pid)\n"
        " print('LIMIT_MISSING')\n"
        "except OSError:\n print('PROCESS_LIMITED')\n"
    )
    checks.append(("process limit", "PROCESS_LIMITED" in stdout and code == 0, stderr))

    stdout, stderr, code, _ = run_output(
        "chunks=[]\n"
        "try:\n"
        " while True: chunks.append(bytearray(16 * 1024 * 1024))\n"
        "except MemoryError: print('MEMORY_LIMITED')\n",
        timeout=1500,
    )
    checks.append(("memory bounded", code != 0 or "MEMORY_LIMITED" in stdout, stderr or stdout))

    stdout, stderr, code, status = run_output("while True: pass", timeout=250)
    checks.append(("wall timeout", code == 124 and status == "TO", stderr or stdout))

    stdout, stderr, code, _ = run_output("print('x' * 100000)")
    combined = (stdout + stderr).encode()
    checks.append(("output bounded", len(combined) <= 65580 and "output truncated" in stderr, str(len(combined))))

    try:
        details = health()
        stale = int(details.get("stale_candidate_containers", -1))
        checks.append(("container teardown", stale == 0, f"stale={stale}"))
    except Exception as exc:
        checks.append(("container teardown", False, type(exc).__name__))

    def saturated_request(_: int) -> int:
        try:
            execute("import time\ntime.sleep(2)\nprint('done')", timeout=2000)
            return 200
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        saturation_statuses = list(pool.map(saturated_request, range(12)))
    checks.append((
        "bounded concurrent admission",
        429 in saturation_statuses and all(status in {200, 429} for status in saturation_statuses),
        json.dumps({str(code): saturation_statuses.count(code) for code in set(saturation_statuses)}),
    ))

    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f" ({detail[:120]})" if detail else ""))
    return 0 if all(passed for _, passed, _ in checks) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"Sandbox returned HTTP {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        raise SystemExit(1) from None
    except urllib.error.URLError as exc:
        print(f"Sandbox is unreachable: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from None
