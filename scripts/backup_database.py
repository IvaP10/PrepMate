#!/usr/bin/env python3
"""Create authenticated encrypted PostgreSQL backups and verify their freshness."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"INTERAI-BACKUP-V1\0"
CHUNK_SIZE = 1024 * 1024
_metrics_directory = Path("/backups")


def backup_metrics_payload(directory: Path) -> bytes:
    backups = sorted(directory.glob("interai-*.dump.enc"), key=lambda item: item.stat().st_mtime, reverse=True)
    lines = [
        "# HELP interai_backup_files Number of retained encrypted database backups.",
        "# TYPE interai_backup_files gauge",
        f"interai_backup_files {len(backups)}",
    ]
    if backups:
        latest = backups[0]
        age_seconds = max(0.0, time.time() - latest.stat().st_mtime)
        lines.extend([
            "# HELP interai_backup_latest_age_seconds Age of the newest encrypted database backup.",
            "# TYPE interai_backup_latest_age_seconds gauge",
            f"interai_backup_latest_age_seconds {age_seconds:.3f}",
        ])
    return ("\n".join(lines) + "\n").encode("utf-8")


class _BackupMetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = backup_metrics_payload(_metrics_directory)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def start_metrics_server(directory: Path) -> ThreadingHTTPServer:
    global _metrics_directory
    _metrics_directory = directory
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("BACKUP_METRICS_PORT", "9101"))), _BackupMetricsHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="backup-metrics").start()
    return server


def load_key(value: str | None = None) -> bytes:
    encoded = (value if value is not None else os.getenv("BACKUP_ENCRYPTION_KEY", "")).strip()
    candidates: list[bytes] = []
    try:
        candidates.append(bytes.fromhex(encoded))
    except ValueError:
        pass
    try:
        candidates.append(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except Exception:
        pass
    for candidate in candidates:
        if len(candidate) == 32:
            return candidate
    raise ValueError("BACKUP_ENCRYPTION_KEY must encode exactly 32 random bytes")


def encrypt_file(source: Path, destination: Path, key: bytes) -> None:
    nonce = secrets.token_bytes(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with source.open("rb") as reader, temporary.open("wb") as writer:
            writer.write(MAGIC)
            writer.write(nonce)
            while chunk := reader.read(CHUNK_SIZE):
                writer.write(encryptor.update(chunk))
            writer.write(encryptor.finalize())
            writer.write(encryptor.tag)
            writer.flush()
            os.fsync(writer.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def encrypt_postgres_dump(destination: Path, key: bytes) -> None:
    nonce = secrets.token_bytes(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    temporary = destination.with_suffix(destination.suffix + ".partial")
    process = subprocess.Popen(
        ["pg_dump", "--format=custom", "--no-owner", "--no-privileges"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("pg_dump stdout is unavailable")
        with process.stdout as reader, temporary.open("wb") as writer:
            writer.write(MAGIC)
            writer.write(nonce)
            while chunk := reader.read(CHUNK_SIZE):
                writer.write(encryptor.update(chunk))
            writer.write(encryptor.finalize())
            writer.write(encryptor.tag)
            writer.flush()
            os.fsync(writer.fileno())
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code:
            raise RuntimeError(f"pg_dump failed with exit code {return_code}: {stderr[:300]}")
        temporary.replace(destination)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        temporary.unlink(missing_ok=True)


def decrypt_file(source: Path, destination: Path, key: bytes) -> None:
    size = source.stat().st_size
    header_size = len(MAGIC) + 12
    if size <= header_size + 16:
        raise ValueError("Encrypted backup is truncated")
    with source.open("rb") as reader:
        if reader.read(len(MAGIC)) != MAGIC:
            raise ValueError("Encrypted backup has an unsupported format")
        nonce = reader.read(12)
        reader.seek(-16, os.SEEK_END)
        tag = reader.read(16)
        remaining = size - header_size - 16
        reader.seek(header_size)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        temporary = destination.with_suffix(destination.suffix + ".partial")
        try:
            with temporary.open("wb") as writer:
                while remaining:
                    chunk = reader.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("Encrypted backup ended unexpectedly")
                    remaining -= len(chunk)
                    writer.write(decryptor.update(chunk))
                writer.write(decryptor.finalize())
                writer.flush()
                os.fsync(writer.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(directory: Path) -> Path:
    key = load_key()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"interai-{timestamp}.dump.enc"
    encrypt_postgres_dump(destination, key)
    manifest = {
        "schema": "interai-encrypted-backup-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": os.getenv("PGDATABASE", ""),
        "encrypted_file": destination.name,
        "encrypted_bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }
    manifest_path = destination.with_suffix(destination.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True), flush=True)
    return destination


def remove_expired(directory: Path, retention_days: int) -> None:
    cutoff = time.time() - max(1, retention_days) * 86400
    for backup in directory.glob("interai-*.dump.enc"):
        if backup.stat().st_mtime < cutoff:
            backup.unlink(missing_ok=True)
            backup.with_suffix(backup.suffix + ".json").unlink(missing_ok=True)


def verify_latest(directory: Path, maximum_age_hours: float) -> dict:
    backups = sorted(directory.glob("interai-*.dump.enc"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not backups:
        raise RuntimeError("No encrypted backup exists")
    latest = backups[0]
    age_hours = (time.time() - latest.stat().st_mtime) / 3600
    if age_hours > maximum_age_hours:
        raise RuntimeError(f"Latest backup is stale ({age_hours:.2f} hours)")
    manifest_path = latest.with_suffix(latest.suffix + ".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not secrets.compare_digest(str(manifest.get("sha256") or ""), sha256_file(latest)):
        raise RuntimeError("Encrypted backup checksum does not match its manifest")
    return {"backup": latest.name, "age_hours": round(age_hours, 3), "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("once", "loop"):
        item = subparsers.add_parser(command)
        item.add_argument("--directory", type=Path, default=Path("/backups"))
    verify = subparsers.add_parser("verify-latest")
    verify.add_argument("--directory", type=Path, default=Path("/backups"))
    verify.add_argument("--maximum-age-hours", type=float, default=26)
    args = parser.parse_args()

    if args.command == "verify-latest":
        print(json.dumps(verify_latest(args.directory, args.maximum_age_hours), sort_keys=True))
        return 0
    retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))
    args.directory.mkdir(parents=True, exist_ok=True)
    metrics_server = start_metrics_server(args.directory) if args.command == "loop" else None
    while True:
        try:
            create_backup(args.directory)
            remove_expired(args.directory, retention_days)
            if args.command == "once":
                return 0
            time.sleep(int(os.getenv("BACKUP_INTERVAL_SECONDS", "86400")))
        finally:
            if args.command == "once" and metrics_server is not None:
                metrics_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
