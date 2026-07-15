#!/usr/bin/env python3
"""Restore an encrypted backup into a disposable database and verify it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from backup_database import decrypt_file, load_key


def query(database: str, sql: str) -> str:
    result = subprocess.run(
        ["psql", "--dbname", database, "--tuples-only", "--no-align", "--command", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--target-db", default=os.getenv("RESTORE_TARGET_DB", "interai_restore_drill"))
    parser.add_argument("--expected-revision", default=os.getenv("EXPECTED_ALEMBIC_REVISION", ""), required=False)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    source_db = os.getenv("PGDATABASE", "")
    if not args.target_db or args.target_db == source_db or "restore" not in args.target_db.lower():
        raise SystemExit("Restore target must be a distinct database name containing 'restore'")
    if not args.expected_revision:
        raise SystemExit("--expected-revision is required")

    key = load_key()
    subprocess.run(["dropdb", "--if-exists", args.target_db], check=True)
    subprocess.run(["createdb", args.target_db], check=True)
    try:
        with tempfile.TemporaryDirectory(prefix="interai-restore-") as temp_dir:
            raw = Path(temp_dir) / "database.dump"
            decrypt_file(args.backup, raw, key)
            subprocess.run(
                [
                    "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                    "--dbname", args.target_db, str(raw),
                ],
                check=True,
            )
        revision = query(args.target_db, "SELECT version_num FROM alembic_version LIMIT 1")
        if revision != args.expected_revision:
            raise RuntimeError(f"Restored revision {revision!r} does not match {args.expected_revision!r}")
        core_tables = int(query(
            args.target_db,
            "SELECT COUNT(*) FROM (VALUES "
            "(to_regclass('userinfo')), (to_regclass('interviews')), "
            "(to_regclass('analysisjobs')), (to_regclass('improvementmissions'))) AS required(name) "
            "WHERE name IS NOT NULL",
        ))
        if core_tables != 4:
            raise RuntimeError("Restored database is missing one or more core tables")
        print(json.dumps({
            "backup": str(args.backup),
            "target_database": args.target_db,
            "revision": revision,
            "core_tables": core_tables,
            "restore_verified": True,
        }, sort_keys=True))
        return 0
    finally:
        if not args.keep:
            subprocess.run(["dropdb", "--if-exists", args.target_db], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
