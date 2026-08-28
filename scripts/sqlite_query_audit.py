#!/usr/bin/env python3
"""Find hosted PostgreSQL-only SQL that still needs a native SQLite rewrite.

This is a release gate, not a query translator. Local runtime queries must be
valid sqlite3 SQL at their call sites so a broad compatibility shim cannot hide
an untested PostgreSQL dependency.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    ("psycopg placeholder", re.compile(r"%s")),
    ("PostgreSQL NOW function", re.compile(r"\bNOW\s*\(\s*\)", re.I)),
    ("PostgreSQL interval", re.compile(r"\bINTERVAL\b", re.I)),
    ("PostgreSQL cast", re.compile(r"::\s*[A-Za-z_]", re.I)),
    ("PostgreSQL case-insensitive comparison", re.compile(r"\bILIKE\b", re.I)),
    ("PostgreSQL trim function", re.compile(r"\bBTRIM\s*\(", re.I)),
    ("PostgreSQL greatest function", re.compile(r"\bGREATEST\s*\(", re.I)),
    ("PostgreSQL least function", re.compile(r"\bLEAST\s*\(", re.I)),
    ("PostgreSQL power function", re.compile(r"\bPOWER\s*\(", re.I)),
    ("PostgreSQL extract function", re.compile(r"\bEXTRACT\s*\(", re.I)),
    ("PostgreSQL update alias", re.compile(r"\bUPDATE\s+[A-Za-z_][A-Za-z0-9_]*\s+(?!AS\b)[A-Za-z_][A-Za-z0-9_]*\s+SET\b", re.I)),
    ("PostgreSQL advisory lock", re.compile(r"\bpg_advisory(?:_xact)?_lock\b|\bhashtext\s*\(", re.I)),
    ("LATERAL join", re.compile(r"\bLATERAL\b", re.I)),
    ("DISTINCT ON", re.compile(r"\bDISTINCT\s+ON\b", re.I)),
    ("PostgreSQL JSON function", re.compile(r"\bjsonb_(?:set|build_object|insert|strip)\b", re.I)),
    ("PostgreSQL JSON operator", re.compile(r"(?:->>|->)|\|\|\s*%s", re.I)),
    ("PostgreSQL array comparison", re.compile(r"\bANY\s*\(\s*%s\s*\)", re.I)),
    ("PostgreSQL row lock", re.compile(r"\bFOR\s+UPDATE(?:\s+OF\b|\s+SKIP\s+LOCKED)?", re.I)),
    ("PostgreSQL DELETE USING", re.compile(r"\bDELETE\s+FROM\b[\s\S]*?\bUSING\b", re.I)),
    (
        "data-modifying CTE",
        re.compile(r"\bWITH\s+[A-Za-z_][A-Za-z0-9_]*\s+AS\s*\(\s*(?:INSERT|UPDATE|DELETE)\b", re.I),
    ),
)


def python_string_literals(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            value = "".join(
                part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "{expression}"
                for part in node.values
            )
            item = (node.lineno, value)
            if item not in seen:
                seen.add(item)
                yield item
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            item = (node.lineno, node.value)
            if item not in seen:
                seen.add(item)
                yield item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    findings: list[str] = []
    for path in sorted(ROOT.glob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for line_number, value in python_string_literals(path):
            if not re.search(
                r"\b(?:SELECT\b[\s\S]*?\bFROM\b|INSERT\s+INTO\b|UPDATE\s+[A-Za-z_][A-Za-z0-9_]*[\s\S]*?\bSET\b|DELETE\s+FROM\b|WITH\s+[A-Za-z_][A-Za-z0-9_]*\s+AS\s*\()",
                value,
                re.I,
            ):
                continue
            for label, pattern in PATTERNS:
                if pattern.search(value):
                    findings.append(f"{relative}:{line_number}: {label}")

    if findings:
        print("SQLITE_QUERY_AUDIT_REVIEW_REQUIRED findings=" + str(len(findings)))
        for finding in findings:
            print(f"- {finding}")
        return 1 if args.strict else 0
    print("SQLITE_QUERY_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
