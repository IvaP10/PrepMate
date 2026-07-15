#!/usr/bin/env python3
"""Small dependency-free HTTP latency/concurrency gate for deployed InterAI routes."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
import urllib.error
import urllib.request


# This probe targets an explicitly supplied deployment URL. Avoid the platform
# proxy auto-discovery performed by urllib's default opener: on macOS it is
# serialized across the first wave of worker threads and can add nearly a
# second of client-only latency to an otherwise local request.
HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(percentile_value * len(ordered)) - 1))
    return ordered[index]


def request_once(url: str, timeout: float, bearer: str | None, cookie: str | None) -> tuple[int, float]:
    headers = {"User-Agent": "interai-load-smoke/1.0"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            response.read(1024)
            status = response.status
    except urllib.error.HTTPError as exc:
        exc.read(1024)
        status = exc.code
    except Exception:
        status = 0
    return status, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--path", default="/live")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--p95-ms", type=float, default=500.0)
    parser.add_argument("--bearer")
    parser.add_argument("--cookie", help="Cookie header for an authenticated disposable load-test account")
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    url = f"{args.base_url.rstrip('/')}/{args.path.lstrip('/')}"
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(
            lambda _: request_once(url, args.timeout, args.bearer, args.cookie),
            range(args.requests),
        ))
    elapsed = time.perf_counter() - started
    statuses: dict[str, int] = {}
    latencies = []
    for status, latency in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        latencies.append(latency)
    payload = {
        "url": url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "throughput_rps": round(args.requests / elapsed, 2),
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
        },
        "statuses": statuses,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    healthy = statuses.get("200", 0) == args.requests and payload["latency_ms"]["p95"] <= args.p95_ms
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
