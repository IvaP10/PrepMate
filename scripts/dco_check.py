#!/usr/bin/env python3
"""Require a DCO sign-off on every non-merge commit in a review range."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGN_OFF = re.compile(
    r"^Signed-off-by:\s+[^<>\r\n]+\s+<[^<>\s]+@[^<>\s]+>$",
    re.IGNORECASE | re.MULTILINE,
)


def unsigned_commits(base: str, head: str) -> list[tuple[str, str]]:
    revision = f"{base}..{head}"
    output = subprocess.check_output(
        ["git", "log", "--no-merges", "--format=%H%x00%s%x00%B%x1e", revision],
        cwd=ROOT,
        text=True,
    )
    unsigned: list[tuple[str, str]] = []
    for record in output.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00", 2)
        if len(parts) != 3:
            raise RuntimeError("Could not parse the Git commit log")
        commit, subject, body = parts
        if not SIGN_OFF.search(body):
            unsigned.append((commit, subject))
    return unsigned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="base commit SHA")
    parser.add_argument("--head", default="HEAD", help="head commit SHA")
    args = parser.parse_args()

    missing = unsigned_commits(args.base, args.head)
    if missing:
        lines = "\n".join(f"- {commit[:12]} {subject}" for commit, subject in missing)
        raise SystemExit(
            "DCO_CHECK_FAILED\n"
            "Every non-merge commit must include `Signed-off-by: Name <email>`.\n"
            + lines
        )
    print("DCO_CHECK_OK")


if __name__ == "__main__":
    main()
