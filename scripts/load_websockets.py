#!/usr/bin/env python3
"""Open many real authenticated interview controllers from disposable fixtures."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
import urllib.request
import uuid

import websockets


def create_ticket(base_url: str, fixture: dict) -> str:
    csrf = str(fixture["csrf_token"])
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/interview/ws-ticket",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Cookie": str(fixture["cookie"]),
            "X-CSRF-Token": csrf,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return str(json.load(response)["ticket"])


async def connect_one(base_url: str, ws_base_url: str, fixture: dict, hold_seconds: float) -> dict:
    started = time.perf_counter()
    ticket = await asyncio.to_thread(create_ticket, base_url, fixture)
    client_session_id = str(fixture.get("client_session_id") or uuid.uuid4())
    event_id = str(uuid.uuid4())
    async with websockets.connect(
        ws_base_url.rstrip("/") + f"/api/interview/ws/video/{ticket}",
        open_timeout=10,
        close_timeout=3,
        max_size=1024 * 1024,
    ) as socket:
        await socket.send(json.dumps({
            "type": "start_session",
            "event_id": event_id,
            "sequence": 1,
            "client_session_id": client_session_id,
            "interview_id": str(fixture["interview_id"]),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"interview_id": str(fixture["interview_id"])},
        }))
        first = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        connected_ms = (time.perf_counter() - started) * 1000
        await asyncio.sleep(hold_seconds)
        return {
            "connected_ms": connected_ms,
            "first_type": str(first.get("type") or ""),
            "passed": str(first.get("type") or "") in {"session_started", "question", "interview_already_finalized"},
        }


async def run(args) -> int:
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    if not isinstance(fixtures, list) or len(fixtures) < args.connections:
        raise SystemExit(f"Fixture file must contain at least {args.connections} unique accounts/interviews")
    selected = fixtures[:args.connections]
    results = await asyncio.gather(*[
        connect_one(args.base_url, args.ws_base_url, fixture, args.hold_seconds)
        for fixture in selected
    ], return_exceptions=True)
    successes = [item for item in results if isinstance(item, dict) and item.get("passed")]
    latencies = sorted(float(item["connected_ms"]) for item in successes)
    failures = [type(item).__name__ if isinstance(item, Exception) else item for item in results if not isinstance(item, dict) or not item.get("passed")]
    payload = {
        "requested_connections": args.connections,
        "successful_connections": len(successes),
        "failed_connections": len(failures),
        "hold_seconds": args.hold_seconds,
        "connect_p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "connect_p95_ms": round(latencies[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        "first_message_types": sorted({str(item.get("first_type")) for item in successes}),
        "passed": len(successes) == args.connections,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--base-url", required=True, help="HTTPS application origin")
    parser.add_argument("--ws-base-url", required=True, help="WSS application origin")
    parser.add_argument("--connections", type=int, default=100)
    parser.add_argument("--hold-seconds", type=float, default=30)
    args = parser.parse_args()
    if args.connections < 1:
        parser.error("connections must be positive")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
