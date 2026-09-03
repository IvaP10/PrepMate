#!/usr/bin/env python3
"""Scan release source and reachable Git blobs for likely personal fixtures."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_BLOB_BYTES = 8 * 1024 * 1024
HOME_PATH = re.compile(
    rb"(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\)"
)
EMAIL = re.compile(rb"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SAFE_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
}
SAFE_EMAIL_SUFFIXES = (".example", ".internal", ".invalid", ".localhost", ".test")
DEPENDENCY_LOCKS = {"package-lock.json", "npm-shrinkwrap.json"}
PRIVATE_FIXTURE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pdf", ".docx"}


def repository_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    return [ROOT / item for item in output.decode().split("\0") if item and (ROOT / item).is_file()]


def reachable_blobs() -> list[tuple[str, str]]:
    output = subprocess.check_output(
        ["git", "rev-list", "--objects", "--all"], cwd=ROOT, text=True
    )
    blobs: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        object_id, path = parts
        if subprocess.check_output(
            ["git", "cat-file", "-t", object_id], cwd=ROOT, text=True
        ).strip() == "blob":
            blobs.append((object_id, path))
    return blobs


def inspect(path: str, data: bytes, *, object_id: str = "working-tree") -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    suffix = Path(path).suffix.lower()
    if suffix in PRIVATE_FIXTURE_SUFFIXES:
        findings.append(("private fixture file requires explicit removal or review", object_id, path))
    if len(data) > MAX_BLOB_BYTES or b"\x00" in data[:8192]:
        return findings
    if HOME_PATH.search(data):
        findings.append(("absolute developer home path", object_id, path))
    if Path(path).name not in DEPENDENCY_LOCKS:
        for match in EMAIL.finditer(data):
            domain = match.group(1).decode("ascii", errors="ignore").lower()
            if domain not in SAFE_EMAIL_DOMAINS and not domain.endswith(SAFE_EMAIL_SUFFIXES):
                findings.append(("non-synthetic email address", object_id, path))
                break
    return findings


def main() -> int:
    findings: list[tuple[str, str, str]] = []
    files = repository_files()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        findings.extend(inspect(relative, path.read_bytes()))

    blobs = reachable_blobs()
    for object_id, path in blobs:
        data = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT)
        findings.extend(inspect(path, data, object_id=object_id[:12]))

    if findings:
        print("PERSONAL_DATA_SCAN_FAILED", file=sys.stderr)
        for label, object_id, path in sorted(set(findings)):
            print(f"- {label}: {path} ({object_id})", file=sys.stderr)
        return 1
    print(
        "PERSONAL_DATA_SCAN_OK "
        f"working_files={len(files)} history_blobs={len(blobs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
