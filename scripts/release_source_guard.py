#!/usr/bin/env python3
"""Fail closed when the source selected for deployment is incomplete or stale."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REQUIRED_DEPLOYMENT_SOURCES = (
    "Dockerfile.api",
    "Frontend/Dockerfile",
    "Frontend/package-lock.json",
    "Frontend/railway.toml",
    "RAILWAY_DEPLOYMENT.md",
    "alembic.ini",
    "infra/sandbox/Dockerfile.api",
    "infra/sandbox/Dockerfile.runtime",
    "infra/OPERATIONS_RUNBOOK.md",
    "infra/sandbox/docker-compose.executor.yml",
    "infra/sandbox/service.py",
    "railway.api.toml",
    "railway.worker.toml",
    "requirements.lock.txt",
    "scripts/openai_canary.py",
    "scripts/release_source_guard.py",
    "scripts/verify_sandbox.py",
)
SENSITIVE_LOCAL_FILES = (
    ".env",
    "Frontend/.env",
    "Frontend/.env.local",
    "key.env",
)


def git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that deployable source is tracked, clean, and synchronized with its upstream branch.",
    )
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    requested_repo = args.repo.resolve()

    try:
        root = Path(git(requested_repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("FAIL  deployment source: target is not a Git worktree", file=sys.stderr)
        return 1

    failures: list[str] = []
    missing = [path for path in REQUIRED_DEPLOYMENT_SOURCES if not (root / path).is_file()]
    if missing:
        failures.append("required deployment files are missing: " + ", ".join(missing))

    untracked_required = [
        path
        for path in REQUIRED_DEPLOYMENT_SOURCES
        if git(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode != 0
    ]
    if untracked_required:
        failures.append("required deployment files are not committed: " + ", ".join(untracked_required))

    tracked_secrets = [
        path
        for path in SENSITIVE_LOCAL_FILES
        if git(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode == 0
    ]
    if tracked_secrets:
        failures.append("local secret files are tracked: " + ", ".join(tracked_secrets))

    dirty_lines = [
        line
        for line in git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
        if line.strip()
    ]
    if dirty_lines:
        failures.append(f"worktree has {len(dirty_lines)} uncommitted or untracked path(s)")

    branch = git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        failures.append("HEAD is detached; deploy from an explicit release branch")

    upstream_result = git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    if not upstream:
        failures.append("current branch has no upstream remote")
    else:
        counts = git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}").stdout.split()
        ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (-1, -1)
        if ahead or behind:
            failures.append(
                f"HEAD does not match {upstream}: ahead={ahead}, behind={behind}; push the exact release commit",
            )

    revision = git(root, "rev-parse", "HEAD").stdout.strip()
    if failures:
        print(f"BLOCKED  deployment source revision {revision[:12]}", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        print("Run `git fetch --prune`, review the diff, commit the release source, and push it before deploying.", file=sys.stderr)
        return 1

    print(
        f"PASS  deployment source revision {revision} is clean, tracked, and synchronized "
        f"({branch} -> {upstream})",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
