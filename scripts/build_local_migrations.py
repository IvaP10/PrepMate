#!/usr/bin/env python3
"""Validate the immutable, numbered SQLite migration history.

Applied migrations must never be regenerated from ``local_schema.sql``. New
schema work gets a new numbered migration and a reviewed checksum here. The
``--check`` flag remains accepted for CI compatibility; validation is always
read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIRECTORY = ROOT / "local_migrations"
IMMUTABLE_MIGRATIONS = {
    "001-local-schema-base.sql": "c75f93210662b74b922c3d402dac8ab2217769f727c89af1895c159a7063b5de",
    "002-encrypted-evidence-columns.sql": "a111b74d3a73dafe4854eb54d3380e466c757d17ed02a5fa69528a34ea864c69",
    "003-prepmate-alpha-local-runtime.sql": "1ac40c96d945e48f6bb9fa323e3dabb4f5a1d2feb8b430e8564c8e57d18f3401",
    "004-sensitive-analysis-encryption.sql": "876de1ed7be304a46d8a204cb8deebaf4f049e53a64de972cad549d492454855",
    "005-sensitive-session-state-encryption.sql": "7bf0cdf6e13d047aa8b5a46a15988739d13b0bf50608db288b384559b3d37474",
    "006-desktop-runtime-compatibility.sql": "cd233a6c7c7f32b07b853aa643e54351280436066ac5f24eb8e4fc556490741b",
}


def statements(source: str) -> list[str]:
    complete: list[str] = []
    pending: list[str] = []
    for line in source.splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("--")):
            continue
        pending.append(line)
        candidate = "\n".join(pending).strip()
        if sqlite3.complete_statement(candidate):
            complete.append(candidate)
            pending = []
    if pending and "\n".join(pending).strip():
        raise SystemExit("A local SQLite migration contains an incomplete statement")
    return complete


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate immutable migrations (retained for CI compatibility)",
    )
    parser.parse_args()

    discovered = sorted(path.name for path in MIGRATION_DIRECTORY.glob("*.sql"))
    expected = list(IMMUTABLE_MIGRATIONS)
    if discovered != expected:
        missing = sorted(set(expected) - set(discovered))
        unexpected = sorted(set(discovered) - set(expected))
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise SystemExit("Local migration set changed without review: " + " ".join(details))

    versions = []
    statement_count = 0
    for filename, expected_checksum in IMMUTABLE_MIGRATIONS.items():
        match = re.fullmatch(r"(\d{3})-[a-z0-9-]+\.sql", filename)
        if not match:
            raise SystemExit(f"Invalid local migration filename: {filename}")
        versions.append(int(match.group(1)))
        source = (MIGRATION_DIRECTORY / filename).read_text(encoding="utf-8")
        actual_checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if actual_checksum != expected_checksum:
            raise SystemExit(
                f"Applied local migration changed: {filename}; add a new numbered migration instead"
            )
        parsed = statements(source)
        if not parsed:
            raise SystemExit(f"Local SQLite migration is empty: {filename}")
        statement_count += len(parsed)

    if versions != list(range(1, len(versions) + 1)):
        raise SystemExit("Local SQLite migrations must be contiguous and start at version 1")

    print(
        "LOCAL_MIGRATIONS_OK "
        f"versions={len(versions)} statements={statement_count} immutable_checksums=verified"
    )


if __name__ == "__main__":
    main()
