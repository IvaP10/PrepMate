#!/usr/bin/env python3
"""Refresh or verify license metadata for a fully pinned Python lockfile."""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
DENIED = re.compile(
    r"\b(?:AGPL(?:-|\s)|Affero|SSPL(?:-|\s)|Server Side Public License|"
    r"Business Source License|BUSL(?:-|\s)|Commons Clause|Elastic License)\b",
    re.IGNORECASE,
)


def locked_requirements(path: Path) -> list[tuple[str, str, str]]:
    locked: dict[tuple[str, str], str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        versions = [item.version for item in requirement.specifier if item.operator == "=="]
        if len(versions) != 1:
            raise RuntimeError(f"Lockfile entry is not exactly pinned: {line}")
        version = versions[0]
        name = canonicalize_name(requirement.name)
        locked[(name, version)] = line
    return [(name, version, locked[(name, version)]) for name, version in sorted(locked)]


def pypi_record(item: tuple[str, str, str]) -> dict[str, str]:
    name, version, requirement = item
    url = f"https://pypi.org/pypi/{quote(name)}/{quote(version)}/json"
    request = Request(url, headers={"User-Agent": "open-source-license-inventory/1"})
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    info = payload.get("info") or {}
    classifiers = [
        value.split(" :: ")[-1]
        for value in (info.get("classifiers") or [])
        if str(value).startswith("License ::")
    ]
    license_value = (
        info.get("license_expression")
        or info.get("license")
        or ", ".join(classifiers)
        or "UNKNOWN"
    )
    return {
        "ecosystem": "python-optional",
        "name": str(info.get("name") or name),
        "normalized_name": name,
        "version": version,
        "requirement": requirement,
        "license": re.sub(r"\s+", " ", str(license_value)).strip()[:500],
        "metadata_url": url,
    }


def validate(lockfile: Path, inventory_path: Path) -> list[str]:
    expected = {(name, version) for name, version, _ in locked_requirements(lockfile)}
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = payload.get("packages") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return ["inventory does not contain a packages list"]
    actual = {
        (str(item.get("normalized_name") or ""), str(item.get("version") or ""))
        for item in records if isinstance(item, dict)
    }
    errors: list[str] = []
    for missing in sorted(expected - actual):
        errors.append(f"missing locked package: {missing[0]}=={missing[1]}")
    for extra in sorted(actual - expected):
        errors.append(f"inventory package is not locked: {extra[0]}=={extra[1]}")
    for item in records:
        if not isinstance(item, dict):
            errors.append("inventory contains a non-object record")
            continue
        license_value = str(item.get("license") or "UNKNOWN")
        label = f"{item.get('name')}=={item.get('version')}"
        if license_value == "UNKNOWN":
            errors.append(f"license metadata requires manual review: {label}")
        elif DENIED.search(license_value):
            errors.append(f"denied license for {label}: {license_value}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lockfile", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    lockfile = (ROOT / args.lockfile).resolve()
    inventory_path = (ROOT / args.inventory).resolve()

    if args.refresh:
        locked = locked_requirements(lockfile)
        with ThreadPoolExecutor(max_workers=8) as executor:
            records = list(executor.map(pypi_record, locked))
        inventory_path.write_text(
            json.dumps(
                {
                    "schema": "python-lock-license-inventory-v1",
                    "lockfile": lockfile.relative_to(ROOT).as_posix(),
                    "packages": records,
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

    try:
        errors = validate(lockfile, inventory_path)
    except (OSError, ValueError, RuntimeError) as exc:
        errors = [str(exc)]
    if errors:
        print("LOCK_LICENSE_INVENTORY_FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    count = len(locked_requirements(lockfile))
    print(f"LOCK_LICENSE_INVENTORY_OK packages={count} lockfile={lockfile.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
