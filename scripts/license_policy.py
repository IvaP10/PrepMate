#!/usr/bin/env python3
"""Inventory installed Python and locked npm licenses and reject denied terms.

Run this inside the clean environment created from the release lockfile.  The
JSON output is suitable for attaching beside the release SBOMs; it deliberately
contains package metadata only, never source paths, settings, or credentials.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
DENIED = re.compile(
    r"\b(?:AGPL(?:-|\s)|Affero|SSPL(?:-|\s)|Server Side Public License|"
    r"Business Source License|BUSL(?:-|\s)|Commons Clause|Elastic License)\b",
    re.IGNORECASE,
)


def locked_python_versions(lock_path: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        versions = [item.version for item in requirement.specifier if item.operator == "=="]
        if len(versions) != 1:
            raise RuntimeError(f"Python lock entry is not exactly pinned: {line}")
        locked[canonicalize_name(requirement.name)] = versions[0]
    return locked


def python_inventory(lock_path: Path) -> list[dict[str, str]]:
    expected = locked_python_versions(lock_path)
    installed = {
        canonicalize_name(distribution.metadata.get("Name") or distribution.name): distribution
        for distribution in importlib.metadata.distributions()
    }
    missing = sorted(set(expected) - set(installed))
    if missing:
        raise RuntimeError("Locked Python packages are not installed: " + ", ".join(missing))
    records: list[dict[str, str]] = []
    for normalized_name, expected_version in sorted(expected.items()):
        distribution = installed[normalized_name]
        if distribution.version != expected_version:
            raise RuntimeError(
                f"Installed {normalized_name}=={distribution.version} does not match lock {expected_version}"
            )
        metadata = distribution.metadata
        classifiers = [
            value.split(" :: ")[-1]
            for value in metadata.get_all("Classifier", [])
            if value.startswith("License ::")
        ]
        license_value = (
            metadata.get("License-Expression")
            or metadata.get("License")
            or ", ".join(classifiers)
            or "UNKNOWN"
        )
        records.append({
            "ecosystem": "python",
            "name": metadata.get("Name") or distribution.name,
            "version": distribution.version,
            "license": re.sub(r"\s+", " ", license_value).strip()[:500],
        })
    return sorted(records, key=lambda item: item["name"].lower())


def npm_inventory(lock_path: Path) -> list[dict[str, str]]:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    records: list[dict[str, str]] = []
    for package_path, package in (payload.get("packages") or {}).items():
        if not package_path or not isinstance(package, dict):
            continue
        name = str(package.get("name") or package_path.rsplit("node_modules/", 1)[-1])
        records.append({
            "ecosystem": "npm",
            "name": name,
            "version": str(package.get("version") or "UNKNOWN"),
            "license": str(package.get("license") or "UNKNOWN"),
            "lockfile": lock_path.relative_to(ROOT).as_posix(),
        })
    return sorted(records, key=lambda item: (item["name"].lower(), item["version"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="optional JSON inventory path")
    args = parser.parse_args()

    try:
        inventory = python_inventory(ROOT / "requirements.lock.txt")
        for relative in ("package-lock.json", "Frontend/package-lock.json", "desktop/package-lock.json"):
            inventory.extend(npm_inventory(ROOT / relative))
        optional_inventory_path = ROOT / "requirements-ocr.licenses.json"
        optional_payload = json.loads(optional_inventory_path.read_text(encoding="utf-8"))
        optional_records = optional_payload.get("packages") if isinstance(optional_payload, dict) else None
        if not isinstance(optional_records, list):
            raise RuntimeError("requirements-ocr.licenses.json does not contain a packages list")
        inventory.extend(item for item in optional_records if isinstance(item, dict))
    except (OSError, ValueError, RuntimeError) as exc:
        print("OPEN_SOURCE_LICENSE_POLICY_FAILED")
        print(f"- {exc}")
        return 1

    denied = [item for item in inventory if DENIED.search(item.get("license", ""))]
    unknown = [
        item
        for item in inventory
        if str(item.get("license") or "").strip().upper() in {"", "UNKNOWN"}
    ]
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"schema": "prepmate-license-inventory-v1", "packages": inventory}, indent=2) + "\n",
            encoding="utf-8",
        )
    if denied or unknown:
        print("OPEN_SOURCE_LICENSE_POLICY_FAILED")
        for item in denied:
            print(f"- {item['ecosystem']}:{item['name']}@{item['version']} declares {item['license']}")
        for item in unknown:
            print(f"- {item['ecosystem']}:{item['name']}@{item['version']} has no reviewed license")
        return 1
    print(f"OPEN_SOURCE_LICENSE_POLICY_OK packages={len(inventory)} unknown=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
