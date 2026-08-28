#!/usr/bin/env python3
"""Scan every reachable Git blob for credentials before a public release.

This intentionally reads Git objects instead of only the current checkout. A
history rewrite is not a substitute for rotating a credential that was ever
published, so the CI check reports the object and path without printing the
matching value.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_BLOB_BYTES = 8 * 1024 * 1024
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}"),
    "Slack token": re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{20,}"),
}


def reachable_blobs() -> list[tuple[str, str]]:
    output = subprocess.check_output(
        ["git", "rev-list", "--objects", "--all"],
        cwd=ROOT,
        text=True,
    )
    blobs: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        object_id, path = parts
        blob_type = subprocess.check_output(
            ["git", "cat-file", "-t", object_id],
            cwd=ROOT,
            text=True,
        ).strip()
        if blob_type == "blob":
            blobs.append((object_id, path))
    return blobs


def scan_blob(object_id: str) -> list[str]:
    blob = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT)
    if len(blob) > MAX_BLOB_BYTES or b"\x00" in blob[:8192]:
        return []
    return [label for label, pattern in PATTERNS.items() if pattern.search(blob)]


def main() -> int:
    blobs = reachable_blobs()
    findings: list[tuple[str, str, str]] = []
    for object_id, path in blobs:
        for label in scan_blob(object_id):
            findings.append((label, object_id[:12], path))
    if findings:
        print("WHOLE_HISTORY_SECRET_SCAN_FAILED", file=sys.stderr)
        for label, object_id, path in sorted(set(findings)):
            print(f"- possible {label} in {path} (git object {object_id})", file=sys.stderr)
        print("Rotate any exposed credential before publication; rewriting history alone is insufficient.", file=sys.stderr)
        return 1
    print(f"WHOLE_HISTORY_SECRET_SCAN_OK blobs_scanned={len(blobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
