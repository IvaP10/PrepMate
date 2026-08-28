#!/usr/bin/env python3
"""Build the public binary-download manifest from verified release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_asset(directory: Path, suffix: str) -> Path:
    matches = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.name.endswith(suffix)
    )
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one release asset ending in {suffix!r}; found "
            f"{', '.join(path.name for path in matches) or 'none'}"
        )
    return matches[0]


def artifact_record(path: Path, base_url: str) -> dict[str, object]:
    return {
        "filename": path.name,
        "url": f"{base_url.rstrip('/')}/{path.name}",
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def verify_release_inventory(assets: Path, output: Path) -> list[Path]:
    required_files = (
        "LICENSE",
        "NOTICE",
        "PRIVACY.md",
        "THIRD_PARTY_NOTICES.md",
        "RELEASE_NOTES.md",
        "license-inventory.json",
    )
    missing = [name for name in required_files if not (assets / name).is_file()]
    if missing:
        raise SystemExit(
            "Release legal or verification files are missing: " + ", ".join(missing)
        )
    sboms = sorted(assets.glob("sbom-*.json"))
    if not sboms:
        raise SystemExit("At least one sbom-*.json file is required")

    checksums_path = assets / "SHA256SUMS.txt"
    checksum_entries: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, filename = line.split(None, 1)
        except ValueError as exc:
            raise SystemExit(f"Invalid checksum line: {line!r}") from exc
        checksum_entries[filename.strip()] = digest.strip()

    inventory_files = [
        path
        for path in sorted(assets.iterdir())
        if path.is_file()
        and path.name != checksums_path.name
        and path.resolve() != output.resolve()
    ]
    missing_entries = [
        path.name for path in inventory_files if path.name not in checksum_entries
    ]
    if missing_entries:
        raise SystemExit(
            "SHA256SUMS.txt is missing entries for: " + ", ".join(missing_entries)
        )
    mismatched = [
        path.name
        for path in inventory_files
        if checksum_entries[path.name] != sha256(path)
    ]
    if mismatched:
        raise SystemExit(
            "SHA256SUMS.txt contains mismatched entries for: " + ", ".join(mismatched)
        )
    return sboms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--release-notes-url", default="")
    parser.add_argument("--website-url", default="")
    args = parser.parse_args()

    version = str(args.version).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"Invalid release version: {version}")
    base_url = str(args.base_url).strip().rstrip("/")
    if not re.fullmatch(r"https://[^\s]+", base_url):
        raise SystemExit("--base-url must be an https URL")

    assets = args.assets.resolve()
    if not assets.is_dir():
        raise SystemExit(f"Release asset directory does not exist: {assets}")

    arm_dmg = find_asset(assets, "-mac-arm64.dmg")
    arm_zip = find_asset(assets, "-mac-arm64.zip")
    x64_dmg = find_asset(assets, "-mac-x64.dmg")
    x64_zip = find_asset(assets, "-mac-x64.zip")
    checksums = assets / "SHA256SUMS.txt"
    if not checksums.is_file():
        raise SystemExit("SHA256SUMS.txt is missing from the release assets")

    metadata_path = ROOT / "PUBLICATION_METADATA.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    product_name = str(metadata.get("product_name") or "PrepMate").strip()
    website_url = str(args.website_url or metadata.get("website_url") or "").strip()
    release_notes_url = str(args.release_notes_url).strip() or f"{base_url}/RELEASE_NOTES.md"
    if not re.fullmatch(r"https://[^\s]+", release_notes_url):
        raise SystemExit("--release-notes-url must be an https URL")
    sboms = verify_release_inventory(assets, args.output.resolve())
    supported_macos_versions = metadata.get("supported_macos_versions") or []
    known_limitations = metadata.get("known_limitations") or []

    manifest = {
        "schema": "prepmate-download-manifest-v1",
        "status": "published",
        "product_name": product_name,
        "version": version,
        "channel": "alpha" if "-alpha" in version else "stable",
        "released_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "supported_macos_versions": supported_macos_versions,
        "known_limitations": known_limitations,
        "download_page": f"{website_url.rstrip('/')}/download" if website_url else "",
        "downloads": {
            "macos": {
                "arm64": {
                    "dmg": artifact_record(arm_dmg, base_url),
                    "zip": artifact_record(arm_zip, base_url),
                },
                "x64": {
                    "dmg": artifact_record(x64_dmg, base_url),
                    "zip": artifact_record(x64_zip, base_url),
                },
            }
        },
        "verification": {
            "checksums": f"{base_url}/{checksums.name}",
            "sbom": [
                f"{base_url}/{path.name}"
                for path in sboms
            ],
            "license_inventory": (
                f"{base_url}/license-inventory.json"
                if (assets / "license-inventory.json").is_file()
                else ""
            ),
        },
        "release_notes_url": release_notes_url,
        "legal": {
            "license": f"{base_url}/LICENSE",
            "notice": f"{base_url}/NOTICE",
            "privacy": f"{base_url}/PRIVACY.md",
            "third_party_notices": f"{base_url}/THIRD_PARTY_NOTICES.md",
        },
    }

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"DOWNLOAD_MANIFEST_OK version={version} "
        f"platforms=macos-arm64,macos-x64 output={output}"
    )


if __name__ == "__main__":
    main()
