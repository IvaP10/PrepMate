import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_release_notes.py"


def test_release_notes_extracts_requested_version(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 1.2.3\n\n- Shipped the release.\n\n## 1.2.2\n\n- Older release.\n",
        encoding="utf-8",
    )
    output = tmp_path / "RELEASE_NOTES.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "1.2.3",
            "--changelog",
            str(changelog),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == (
        "# PrepMate 1.2.3 release notes\n\n- Shipped the release.\n"
    )


def test_release_notes_rejects_unknown_version(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 1.2.3\n\n- Shipped.\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "9.9.9",
            "--changelog",
            str(changelog),
            "--output",
            str(tmp_path / "RELEASE_NOTES.md"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "does not contain release notes" in result.stderr
