#!/usr/bin/env python3
"""Validate that the frozen backend and standalone renderer can be packaged."""

from __future__ import annotations

import argparse
import json
import platform
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
SECRET_PATTERNS = (
    re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-|ant-)[A-Za-z0-9_-]{20,}"),
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(
        rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?\n"
        rb"(?:[A-Za-z0-9+/]{64}\r?\n)+[A-Za-z0-9+/=]+\r?\n"
        rb"-----END (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----$"
    ),
)
CHECKOUT_PATH_PATTERN = re.compile(
    rb"(?:/Users/|/home/|[A-Za-z]:[\\/]+Users[\\/]+)[^\x00\r\n]{0,240}"
    rb"(?:PrepMate|Frontend)"
)


def validate_packaged_application(app_path: Path) -> None:
    if not app_path.is_dir() or app_path.suffix != ".app":
        raise SystemExit(f"Packaged application is not a .app directory: {app_path}")
    resources = app_path / "Contents" / "Resources"
    if not resources.is_dir():
        raise SystemExit(f"Packaged application resources are missing: {resources}")

    metadata = json.loads((ROOT / "PUBLICATION_METADATA.json").read_text(encoding="utf-8"))
    executable = str(metadata.get("backend_executable") or "prepmate-backend")
    required = (
        resources / "app.asar",
        resources / "backend" / executable,
        resources / "frontend" / "server.js",
        resources / "frontend" / ".next" / "static",
        resources / "LICENSE",
        resources / "NOTICE",
        resources / "PRIVACY.md",
        resources / "THIRD_PARTY_NOTICES.md",
    )
    missing = [str(path.relative_to(app_path)) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Packaged application resources are missing: " + ", ".join(missing))

    prohibited_suffixes = {".db", ".sqlite", ".sqlite3", ".p12", ".pfx"}
    prohibited_names = {".env", "key.env", "PUBLICATION_METADATA.json"}
    violations: list[str] = []
    for path in resources.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(resources).as_posix()
        if path.name in prohibited_names or path.suffix.lower() in prohibited_suffixes:
            violations.append(f"prohibited packaged file: {relative}")
        if path.suffix.lower() == ".pem" and path.name != "cacert.pem":
            violations.append(f"unexpected signing material: {relative}")
        data = path.read_bytes()
        if CHECKOUT_PATH_PATTERN.search(data):
            violations.append(f"private checkout path in packaged file: {relative}")
        scan_for_secret = (
            "node_modules" not in path.parts
            and not path.name.endswith(".nft.json")
            and path.suffix.lower() not in {".wasm", ".dylib"}
        )
        if scan_for_secret and any(pattern.search(data) for pattern in SECRET_PATTERNS):
            violations.append(f"possible secret in packaged file: {relative}")
    if violations:
        raise SystemExit("DESKTOP_ARTIFACT_GUARD_FAILED\n- " + "\n- ".join(violations))
    print(f"DESKTOP_ARTIFACT_OK app={app_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    resources = package.get("build", {}).get("extraResources", [])
    configured = {str(item.get("from")) for item in resources if isinstance(item, dict)}
    expected_config = {
        "../dist/prepmate-backend",
        "../Frontend/.next/standalone",
        "../Frontend/.next/standalone/node_modules",
        "../Frontend/.next/static",
        "../Frontend/public",
        "../LICENSE",
        "../NOTICE",
        "../PRIVACY.md",
        "../THIRD_PARTY_NOTICES.md",
    }
    if configured != expected_config:
        raise SystemExit("Desktop extraResources do not match the frozen local runtime")

    executable = "prepmate-backend.exe" if platform.system() == "Windows" else "prepmate-backend"
    required = (
        ROOT / "dist" / "prepmate-backend" / executable,
        ROOT / "Frontend" / ".next" / "standalone" / "server.js",
        ROOT / "Frontend" / ".next" / "static",
        ROOT / "Frontend" / "public",
        ROOT / "LICENSE",
        ROOT / "NOTICE",
        ROOT / "THIRD_PARTY_NOTICES.md",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Desktop package inputs are missing: " + ", ".join(missing))
    print("DESKTOP_BUNDLE_INPUTS_OK")
    if args.artifact:
        validate_packaged_application(args.artifact.resolve())


if __name__ == "__main__":
    main()
