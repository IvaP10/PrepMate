#!/usr/bin/env python3
"""Extract the version-specific public release notes from CHANGELOG.md."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^## (?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\s*$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    version = str(args.version).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"Invalid release version: {version}")

    lines = args.changelog.read_text(encoding="utf-8").splitlines()
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        match = VERSION_PATTERN.match(line)
        if not match:
            continue
        if match.group("version") == version:
            start = index + 1
            continue
        if start is not None:
            end = index
            break
    if start is None:
        raise SystemExit(f"CHANGELOG.md does not contain release notes for {version}")

    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md release section is empty for {version}")
    metadata = json.loads((ROOT / "PUBLICATION_METADATA.json").read_text(encoding="utf-8"))
    product_name = str(metadata.get("product_name") or "PrepMate").strip()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"# {product_name} {version} release notes\n\n{body}\n", encoding="utf-8")
    print(f"RELEASE_NOTES_OK version={version} output={output}")


if __name__ == "__main__":
    main()
