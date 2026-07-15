#!/usr/bin/env python3
"""Run authenticated mixed-route HTTP load from a declarative scenario file."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))]


def expand(value):
    if isinstance(value, str):
        for key, replacement in os.environ.items():
            value = value.replace("${" + key + "}", replacement)
        return value
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


def execute(base_url: str, operation: dict, timeout: float) -> tuple[str, int, float]:
    method = str(operation.get("method") or "GET").upper()
    data = json.dumps(operation.get("body")).encode() if "body" in operation else None
    headers = {str(key): str(value) for key, value in (operation.get("headers") or {}).items()}
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/" + str(operation["path"]).lstrip("/"),
        data=data,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            response.read(2048)
            status = response.status
    except urllib.error.HTTPError as exc:
        exc.read(2048)
        status = exc.code
    except Exception:
        status = 0
    return str(operation["name"]), status, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--p95-ms", type=float, default=1500)
    args = parser.parse_args()
    document = expand(json.loads(args.scenario.read_text(encoding="utf-8")))
    operations = document.get("operations") or []
    if not operations:
        raise SystemExit("Scenario must declare at least one operation")
    weighted = [operation for operation in operations for _ in range(max(1, int(operation.get("weight", 1))))]
    jobs = [weighted[index % len(weighted)] for index in range(args.iterations)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda operation: execute(args.base_url, operation, args.timeout), jobs))
    elapsed = time.perf_counter() - started
    summary = {}
    passed = True
    for operation in operations:
        name = str(operation["name"])
        selected = [(status, latency) for result_name, status, latency in results if result_name == name]
        expected = {int(item) for item in operation.get("expected_statuses", [200])}
        statuses = {str(code): sum(1 for status, _ in selected if status == code) for code in sorted({item[0] for item in selected})}
        latencies = [item[1] for item in selected]
        operation_passed = all(status in expected for status, _ in selected)
        passed = passed and operation_passed
        summary[name] = {
            "requests": len(selected), "statuses": statuses, "passed": operation_passed,
            "p50_ms": round(percentile(latencies, 0.5), 2),
            "p95_ms": round(percentile(latencies, 0.95), 2),
            "p99_ms": round(percentile(latencies, 0.99), 2),
        }
        passed = passed and summary[name]["p95_ms"] <= args.p95_ms
    print(json.dumps({
        "passed": passed, "iterations": args.iterations, "concurrency": args.concurrency,
        "throughput_rps": round(args.iterations / elapsed, 2), "operations": summary,
    }, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
