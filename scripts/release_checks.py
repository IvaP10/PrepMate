#!/usr/bin/env python3
"""Validate release metadata and required signing credentials without logging secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def package_version(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def require_environment(names: tuple[str, ...]) -> None:
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise SystemExit("Missing required release secret names: " + ", ".join(missing))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="")
    parser.add_argument("--signing", choices=("none", "macos", "windows"), default="none")
    parser.add_argument(
        "--distribution",
        "--publication",
        dest="distribution",
        action="store_true",
        help="validate the public binary-distribution gate (publication is kept as a compatibility alias)",
    )
    args = parser.parse_args()

    versions = {
        package_version(ROOT / "package.json"),
        package_version(ROOT / "Frontend" / "package.json"),
        package_version(ROOT / "desktop" / "package.json"),
    }
    if len(versions) != 1:
        raise SystemExit("Root, renderer, and desktop package versions must match")
    version = versions.pop()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"Invalid semantic version: {version}")
    if args.tag and args.tag.startswith("v") and args.tag != f"v{version}":
        raise SystemExit(f"Tag {args.tag} does not match package version v{version}")

    if args.signing == "macos":
        require_environment((
            "CSC_LINK",
            "CSC_KEY_PASSWORD",
            "APPLE_ID",
            "APPLE_APP_SPECIFIC_PASSWORD",
            "APPLE_TEAM_ID",
        ))
    elif args.signing == "windows":
        require_environment(("WIN_CSC_LINK", "WIN_CSC_KEY_PASSWORD"))

    if args.distribution:
        metadata_path = ROOT / "PUBLICATION_METADATA.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        errors = []
        required_text = (
            "product_name", "product_slug", "copyright_owner",
            "website_url", "download_url", "release_manifest_url",
            "release_storage_url", "support_url", "security_report_url",
            "bundle_identifier", "environment_prefix", "keychain_service",
            "data_directory_name", "backend_executable", "minimum_macos_version",
        )
        for field in required_text:
            value = str(metadata.get(field) or "").strip()
            if not value or "REQUIRED:" in value or "[" in value:
                errors.append(f"publication metadata field is incomplete: {field}")
        if str(metadata.get("status") or "") != "approved_for_binary_distribution":
            errors.append("publication metadata status is not approved_for_binary_distribution")
        if str(metadata.get("source_visibility") or "") != "private":
            errors.append("source_visibility must be private")
        if metadata.get("publish_source") is not False:
            errors.append("publish_source must remain false for a binary-only release")
        if metadata.get("automatic_updates") is not False:
            errors.append("automatic_updates must remain false for this release")
        if metadata.get("accounts_required") is not False:
            errors.append("accounts_required must remain false for this release")
        if metadata.get("analytics_enabled") is not False:
            errors.append("analytics_enabled must remain false for this release")
        product_name = str(metadata.get("product_name") or "").strip()
        product_slug = str(metadata.get("product_slug") or "").strip().lower()
        environment_prefix = str(metadata.get("environment_prefix") or "").strip()
        backend_executable = str(metadata.get("backend_executable") or "").strip()
        keychain_service = str(metadata.get("keychain_service") or "").strip()
        data_directory_name = str(metadata.get("data_directory_name") or "").strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", product_slug):
            errors.append("product_slug must be lowercase and package-safe")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", environment_prefix):
            errors.append("environment_prefix must be uppercase and environment-safe")
        if backend_executable != f"{product_slug}-backend":
            errors.append("backend_executable must match product_slug")
        if keychain_service != product_name:
            errors.append("keychain_service must match product_name")
        if data_directory_name != product_name:
            errors.append("data_directory_name must match product_name")
        supported_platforms = metadata.get("supported_platforms")
        if supported_platforms != ["macos-arm64", "macos-x64"]:
            errors.append("supported_platforms must contain only macos-arm64 and macos-x64 in this release")
        supported_macos_versions = metadata.get("supported_macos_versions")
        if not isinstance(supported_macos_versions, list) or not supported_macos_versions:
            errors.append("supported_macos_versions must list the public macOS support range")
        elif any("REQUIRED:" in str(value) for value in supported_macos_versions):
            errors.append("supported_macos_versions is incomplete")
        minimum_macos_version = str(metadata.get("minimum_macos_version") or "").strip()
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", minimum_macos_version):
            errors.append("minimum_macos_version must be a macOS version number")
        for field in (
            "website_url", "download_url", "release_manifest_url",
            "release_storage_url", "support_url", "security_report_url",
        ):
            value = str(metadata.get(field) or "").strip()
            if value.startswith("REQUIRED:") or ".invalid" in value or "example" in value.lower():
                continue
            if not re.fullmatch(r"https://[^\s]+", value):
                errors.append(f"{field} must be an https URL")

        for field in (
            "name_clearance_confirmed",
            "content_rights_review_confirmed",
            "domain_configured",
            "distribution_storage_configured",
            "public_support_route_confirmed",
            "public_security_route_confirmed",
            "macos_signing_configured",
            "macos_notarization_configured",
            "clean_machine_validation_confirmed",
            "branch_protection_confirmed",
            "copyright_owner_confirmed",
        ):
            if metadata.get(field) is not True:
                errors.append(f"owner confirmation is missing: {field}")

        package_paths = (
            ROOT / "package.json",
            ROOT / "Frontend" / "package.json",
            ROOT / "desktop" / "package.json",
        )
        packages = [json.loads(path.read_text(encoding="utf-8")) for path in package_paths]
        expected_package_names = (
            product_slug,
            f"{product_slug}-renderer",
            f"{product_slug}-desktop",
        )
        for path, package, expected_name in zip(package_paths, packages, expected_package_names):
            if package.get("name") != expected_name:
                errors.append(f"{path.relative_to(ROOT)} does not match product_slug")
        desktop_build = packages[2].get("build") or {}
        if desktop_build.get("productName") != product_name:
            errors.append("desktop productName does not match publication metadata")
        if desktop_build.get("appId") != metadata.get("bundle_identifier"):
            errors.append("desktop appId does not match bundle_identifier")
        configured_resources = {
            str(item.get("from") or "")
            for item in (desktop_build.get("extraResources") or [])
            if isinstance(item, dict)
        }
        if f"../dist/{backend_executable}" not in configured_resources:
            errors.append("desktop backend resource does not match backend_executable")
        if not str(desktop_build.get("artifactName") or "").startswith(f"{product_name}-${{version}}-"):
            errors.append("desktop artifactName does not match product_name")
        backend_spec = ROOT / "desktop" / f"{product_slug}.spec"
        if not backend_spec.is_file():
            errors.append(f"desktop/{product_slug}.spec is missing")
        else:
            spec_text = backend_spec.read_text(encoding="utf-8")
            if f'name="{backend_executable}"' not in spec_text:
                errors.append("backend spec executable does not match publication metadata")
        root_build_script = str((packages[0].get("scripts") or {}).get("build:backend") or "")
        if f"desktop/{product_slug}.spec" not in root_build_script:
            errors.append("root backend build script does not match product_slug")
        runtime_text = (ROOT / "local_runtime.py").read_text(encoding="utf-8")
        if f'PRODUCT_NAME = "{product_name}"' not in runtime_text:
            errors.append("local runtime product name does not match publication metadata")
        for snippet, label in (
            (f'LOCAL_USER_ID = "local-{product_slug}-user"', "local user namespace"),
            (f'"{product_slug}.sqlite3"', "database filename"),
            (f'os.getenv("{environment_prefix}_DATA_DIR"', "data-directory environment prefix"),
            (f'os.getenv("{environment_prefix}_API_TOKEN"', "API-token environment prefix"),
            (f'os.getenv("{environment_prefix}_PROVIDER"', "provider environment prefix"),
            (f'os.getenv("{environment_prefix}_MODEL"', "model environment prefix"),
        ):
            if snippet not in runtime_text:
                errors.append(f"local runtime {label} does not match publication metadata")

        config_text = (ROOT / "config.py").read_text(encoding="utf-8")
        for suffix in ("DATA_DIR", "PROVIDER", "MODEL", "PROVIDER_TIMEOUT"):
            if f'os.getenv("{environment_prefix}_{suffix}"' not in config_text:
                errors.append(f"config environment prefix is missing {environment_prefix}_{suffix}")

        desktop_main = (ROOT / "desktop" / "src" / "main.cjs").read_text(encoding="utf-8")
        for snippet, label in (
            (f'{environment_prefix}_DATA_DIR:', "data-directory environment"),
            (f'{environment_prefix}_API_TOKEN:', "API-token environment"),
            (f'"{backend_executable}"', "backend executable"),
            (f'title: "{product_name}"', "window title"),
        ):
            if snippet not in desktop_main:
                errors.append(f"desktop {label} does not match publication metadata")

        about_text = (ROOT / "Frontend" / "app" / "about" / "page.tsx").read_text(encoding="utf-8")
        if product_name not in about_text:
            errors.append("About page does not contain the approved product name")
        for label in ("download", "privacy", "support", "security"):
            if label not in about_text.lower():
                errors.append(f"About page is missing the public {label} link")
        security_text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        if "public security route" not in security_text.lower() and "security@" not in security_text.lower():
            errors.append("SECURITY.md must describe the configured public security route")
        notice_path = ROOT / "NOTICE"
        if not notice_path.is_file():
            errors.append("NOTICE is missing")
        else:
            notice = notice_path.read_text(encoding="utf-8")
            for value in (
                str(metadata.get("product_name") or ""),
                str(metadata.get("copyright_year") or ""),
                str(metadata.get("copyright_owner") or ""),
            ):
                if value and value not in notice:
                    errors.append(f"NOTICE does not contain approved value: {value}")
        if errors:
            raise SystemExit("PUBLICATION_GATE_BLOCKED\n- " + "\n- ".join(errors))

    print(
        f"RELEASE_METADATA_OK version={version} signing={args.signing} "
        f"distribution={'approved' if args.distribution else 'not-requested'}"
    )


if __name__ == "__main__":
    main()
