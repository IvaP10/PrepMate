import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_download_manifest.py"


def _write_asset(directory: Path, name: str, content: bytes = b"asset") -> None:
    (directory / name).write_bytes(content)


def _complete_assets(directory: Path) -> None:
    for suffix in (
        "-mac-arm64.dmg",
        "-mac-arm64.zip",
        "-mac-x64.dmg",
        "-mac-x64.zip",
    ):
        _write_asset(directory, f"PrepMate-1.2.3{suffix}")
    _write_asset(directory, "sbom-python.json", b"{}")
    _write_asset(directory, "license-inventory.json", b"{}")
    for name in ("LICENSE", "NOTICE", "PRIVACY.md", "THIRD_PARTY_NOTICES.md", "RELEASE_NOTES.md"):
        _write_asset(directory, name, name.encode("utf-8"))
    entries = []
    for path in sorted(directory.iterdir()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.name}\n")
    _write_asset(directory, "SHA256SUMS.txt", "".join(entries).encode("utf-8"))


def test_download_manifest_contains_both_macos_architectures(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _complete_assets(assets)
    output = tmp_path / "latest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--assets",
            str(assets),
            "--output",
            str(output),
            "--version",
            "1.2.3",
            "--base-url",
            "https://downloads.example.test/releases/1.2.3",
            "--website-url",
            "https://prepmate.example.test",
            "--release-notes-url",
            "https://prepmate.example.test/changelog",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["schema"] == "prepmate-download-manifest-v1"
    assert manifest["version"] == "1.2.3"
    assert manifest["supported_macos_versions"] == ["macOS 13 Ventura and later"]
    assert set(manifest["downloads"]["macos"]) == {"arm64", "x64"}
    arm_dmg = manifest["downloads"]["macos"]["arm64"]["dmg"]
    assert arm_dmg["url"].endswith("PrepMate-1.2.3-mac-arm64.dmg")
    expected_hash = hashlib.sha256(b"asset").hexdigest()
    assert arm_dmg["sha256"] == expected_hash
    assert manifest["verification"]["sbom"] == [
        "https://downloads.example.test/releases/1.2.3/sbom-python.json"
    ]
    assert manifest["legal"]["privacy"].endswith("/PRIVACY.md")


def test_download_manifest_rejects_missing_architecture(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _complete_assets(assets)
    (assets / "PrepMate-1.2.3-mac-x64.zip").unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--assets",
            str(assets),
            "--output",
            str(tmp_path / "latest.json"),
            "--version",
            "1.2.3",
            "--base-url",
            "https://downloads.example.test/releases/1.2.3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "mac-x64.zip" in result.stderr
