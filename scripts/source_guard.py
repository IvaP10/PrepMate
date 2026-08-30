#!/usr/bin/env python3
"""Fail CI when release source contains hosted-era code or likely secrets."""

from __future__ import annotations

import re
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = {
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "PRIVACY.md",
    "RELEASING.md",
    "CHANGELOG.md",
    "MAINTAINERS.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "PUBLICATION_METADATA.json",
    "PUBLIC_RELEASE_BLOCKERS.md",
    "NOTICE",
    "NOTICE.template",
    "CODE_OF_CONDUCT.md",
    "local_schema.sql",
    "local_migrations/001-local-schema-base.sql",
    "local_migrations/002-encrypted-evidence-columns.sql",
    "local_migrations/003-prepmate-alpha-local-runtime.sql",
    "local_migrations/004-sensitive-analysis-encryption.sql",
    "local_migrations/005-sensitive-session-state-encryption.sql",
    "local_migrations/006-desktop-runtime-compatibility.sql",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/dependabot.yml",
    "package-lock.json",
    "Frontend/package-lock.json",
    "desktop/package-lock.json",
    "desktop/package.json",
    "scripts/secret_scan.py",
    "scripts/personal_data_scan.py",
    "scripts/build_download_manifest.py",
    "scripts/build_release_notes.py",
    "scripts/sanitize_frontend_bundle.py",
    "scripts/sqlite_query_audit.py",
    "scripts/license_policy.py",
    "scripts/lock_license_inventory.py",
    "scripts/dco_check.py",
    "requirements.lock.txt",
    "requirements-ocr.txt",
    "requirements-ocr.lock.txt",
    "requirements-ocr.licenses.json",
}
REMOVED_PATHS = {
    "auth.py",
    "payment.py",
    "pricing.py",
    "entitlements.py",
    "redis_client.py",
    "alembic.ini",
    "schema.sql",
    "docker-compose.yml",
    "key.env",
    "key.env.example",
    "Frontend/components/auth-screen.tsx",
    "Frontend/lib/auth.ts",
    "Frontend/lib/auth-bootstrap.ts",
    "Frontend/app/checkout/page.tsx",
    "Frontend/components/settings/account-tab.tsx",
    "Frontend/components/settings/billing-tab.tsx",
}
REMOVED_PREFIXES = ("migrations/", "infra/", "Frontend/app/admin/")
FORBIDDEN_DEPENDENCIES = {
    "alembic",
    "asyncpg",
    "passlib",
    "psycopg",
    "psycopg2",
    "pyjwt",
    "razorpay",
    "redis",
    "sqlalchemy",
    "pymupdf",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
}


def repository_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    paths = []
    for raw in output.decode("utf-8").split("\0"):
        if not raw:
            continue
        path = ROOT / raw
        if path.is_file():
            paths.append(path)
    return paths


def main() -> int:
    errors: list[str] = []
    relative_files = {path.relative_to(ROOT).as_posix(): path for path in repository_files()}
    try:
        publication_metadata = json.loads(
            (ROOT / "PUBLICATION_METADATA.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        publication_metadata = {}
        errors.append(f"could not read publication metadata: {exc}")
    product_slug = str(publication_metadata.get("product_slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", product_slug):
        errors.append("PUBLICATION_METADATA.json must define a lowercase package-safe product_slug")
    elif f"desktop/{product_slug}.spec" not in relative_files:
        errors.append(f"missing product backend spec: desktop/{product_slug}.spec")

    for required in sorted(REQUIRED_FILES):
        if required not in relative_files:
            errors.append(f"missing required release file: {required}")

    for name in sorted(relative_files):
        lower = name.lower()
        basename = Path(name).name.lower()
        if name in REMOVED_PATHS or any(name.startswith(prefix) for prefix in REMOVED_PREFIXES):
            errors.append(f"hosted-era path must remain removed: {name}")
        if basename in {".env", "key.env"} or (basename.startswith(".env.") and basename != ".env.example"):
            errors.append(f"environment file must not be committed: {name}")
        if Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".pfx"}:
            errors.append(f"runtime data or signing material must not be committed: {name}")

        try:
            text = relative_files[name].read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"possible {label} in {name}")

    requirements = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in ROOT.glob("requirements*.txt")
    )
    requirement_names = {
        re.split(r"[<>=!~\[; ]", line.strip(), maxsplit=1)[0]
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "--"))
    }
    for dependency in sorted(FORBIDDEN_DEPENDENCIES & requirement_names):
        errors.append(f"hosted/account dependency must remain removed: {dependency}")

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8", errors="ignore")
    if "apache license" not in license_text.lower() or "version 2.0" not in license_text.lower():
        errors.append("LICENSE must be the Apache License, Version 2.0")

    package_metadata = []
    for package_name in ("package.json", "Frontend/package.json", "desktop/package.json"):
        try:
            package_metadata.append(json.loads((ROOT / package_name).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            errors.append(f"could not read package metadata: {package_name}: {exc}")
    for package_name, metadata in zip(("package.json", "Frontend/package.json", "desktop/package.json"), package_metadata):
        if metadata.get("license") != "Apache-2.0":
            errors.append(f"{package_name} must declare Apache-2.0")
    expected_names = {
        "package.json": product_slug,
        "Frontend/package.json": f"{product_slug}-renderer",
        "desktop/package.json": f"{product_slug}-desktop",
    }
    for package_name, metadata in zip(expected_names, package_metadata):
        if metadata.get("name") != expected_names[package_name]:
            errors.append(f"{package_name} must match the publication product slug")

    schema = (ROOT / "local_schema.sql").read_text(encoding="utf-8").lower()
    for table in ("subscriptions", "planentitlements", "paymentintentoutbox", "authsessions"):
        if table in schema:
            errors.append(f"local schema contains removed account/billing table: {table}")

    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for name, path in relative_files.items()
        if Path(name).suffix.lower() in {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx"}
    )
    if re.search(r"(?:localStorage|sessionStorage)\.setItem\([^\n]*(?:api.?key|provider.?key)", source_text, re.I):
        errors.append("provider API keys must not be written to browser storage")
    for forbidden_text, explanation in (
        (r"\bSpeechRecognition\b|\bwebkitSpeechRecognition\b", "browser-managed speech recognition must remain removed"),
        (r"\bKOKORO_[A-Z0-9_]+\b", "removed interviewer-speech runtime configuration must remain removed"),
        (r"INTERAI" + r"_ENABLE_UNSAFE_LOCAL_EXECUTION", "legacy unsafe execution escape hatch must remain removed"),
        (r"PREPMATE" + r"_ENABLE_UNSAFE_LOCAL_EXECUTION", "unsafe execution escape hatch must remain removed"),
        (
            r"\b(?:" + "Anti" + "CheatEvents|Mal" + "practiceEvents|Proctoring" + r"Flags)\b",
            "punitive coaching tables must remain removed",
        ),
        (r"(?:cdn\.jsdelivr\.net|storage\.googleapis\.com)[^\s\"']*(?:mediapipe|tasks-vision)", "remote mutable vision assets must remain removed"),
        (r"https?://[^\s\"']+", "network destinations must be reviewed explicitly"),
    ):
        if forbidden_text.startswith("http"):
            # URLs are expected in documentation and provider integrations; the
            # CSP and asset checks are more precise than a blanket URL ban.
            continue
        if re.search(forbidden_text, source_text, re.I):
            errors.append(explanation)

    if errors:
        print("SOURCE_BOUNDARY_GUARD_FAILED", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print("SOURCE_BOUNDARY_GUARD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
