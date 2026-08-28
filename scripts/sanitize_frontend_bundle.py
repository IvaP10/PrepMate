#!/usr/bin/env python3
"""Remove private checkout paths from the standalone renderer bundle."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "Frontend"
STANDALONE = FRONTEND / ".next" / "standalone"
STATIC = FRONTEND / ".next" / "static"
PLACEHOLDER = "__PREPMATE_BUNDLE_ROOT__"


def rewrite_paths(path: Path, replacements: tuple[tuple[bytes, bytes], ...]) -> bool:
    try:
        original = path.read_bytes()
    except OSError:
        return False
    rewritten = original
    for old, new in replacements:
        rewritten = rewritten.replace(old, new)
    if rewritten == original:
        return False
    path.write_bytes(rewritten)
    return True


def main() -> None:
    server = STANDALONE / "server.js"
    if not server.is_file():
        raise SystemExit(f"Standalone renderer entrypoint is missing: {server}")

    absolute_paths = tuple(
        sorted(
            {
                str(FRONTEND).encode("utf-8"),
                str(ROOT).encode("utf-8"),
            },
            key=len,
            reverse=True,
        )
    )
    replacements = tuple((value, PLACEHOLDER.encode("utf-8")) for value in absolute_paths)
    changed = 0
    for directory in (STANDALONE, STATIC):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and rewrite_paths(path, replacements):
                changed += 1

    text = server.read_text(encoding="utf-8")
    marker = "process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)"
    if "const bundleRoot = dir" not in text:
        injection = """const bundleRoot = dir
if (nextConfig.outputFileTracingRoot === \"__PREPMATE_BUNDLE_ROOT__\") {
  nextConfig.outputFileTracingRoot = bundleRoot
}
if (nextConfig.turbopack?.root === \"__PREPMATE_BUNDLE_ROOT__\") {
  nextConfig.turbopack.root = bundleRoot
}
if (nextConfig.repoRoot === \"__PREPMATE_BUNDLE_ROOT__\") {
  nextConfig.repoRoot = bundleRoot
}

"""
        if marker not in text:
            raise SystemExit("Standalone renderer entrypoint format changed; sanitization stopped")
        text = text.replace(marker, injection + marker, 1)
        server.write_text(text, encoding="utf-8")
        changed += 1

    forbidden = [
        str(ROOT).encode("utf-8"),
        str(FRONTEND).encode("utf-8"),
    ]
    leaked = []
    for directory in (STANDALONE, STATIC):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if any(value in data for value in forbidden):
                leaked.append(path.relative_to(FRONTEND).as_posix())
    if leaked:
        raise SystemExit("Renderer bundle still contains checkout paths: " + ", ".join(leaked))
    print(f"FRONTEND_BUNDLE_SANITIZED files_changed={changed}")


if __name__ == "__main__":
    main()
