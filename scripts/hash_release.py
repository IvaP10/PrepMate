#!/usr/bin/env python3
"""Create a deterministic SHA-256 manifest for release assets."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    output = args.output.resolve()
    # Release storage contains only top-level installer and metadata files.
    # Hashing files inside unpacked app directories would produce manifest
    # entries that a downloader could never retrieve or verify.
    files = sorted(
        path for path in root.iterdir()
        if path.is_file() and path.resolve() != output and not path.name.startswith("SHA256SUMS")
    )
    if not files:
        raise SystemExit(f"No release assets found under {root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(f"{digest(path)}  {path.relative_to(root).as_posix()}\n" for path in files),
        encoding="utf-8",
    )
    print(f"WROTE_CHECKSUMS assets={len(files)} output={output.name}")


if __name__ == "__main__":
    main()
