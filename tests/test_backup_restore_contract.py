from pathlib import Path

import pytest

from scripts.backup_database import backup_metrics_payload, decrypt_file, encrypt_file, load_key


def test_backup_encryption_round_trip_and_plaintext_absence(tmp_path: Path):
    key = bytes(range(32))
    source = tmp_path / "source.dump"
    encrypted = tmp_path / "backup.dump.enc"
    restored = tmp_path / "restored.dump"
    private_data = b"candidate transcript and encrypted report evidence" * 1000
    source.write_bytes(private_data)

    encrypt_file(source, encrypted, key)
    decrypt_file(encrypted, restored, key)

    assert private_data not in encrypted.read_bytes()
    assert restored.read_bytes() == private_data


def test_backup_authentication_rejects_ciphertext_tampering(tmp_path: Path):
    key = bytes(range(32))
    source = tmp_path / "source.dump"
    encrypted = tmp_path / "backup.dump.enc"
    source.write_bytes(b"sealed evidence")
    encrypt_file(source, encrypted, key)
    damaged = bytearray(encrypted.read_bytes())
    damaged[-17] ^= 1
    encrypted.write_bytes(damaged)

    with pytest.raises(Exception):
        decrypt_file(encrypted, tmp_path / "restored.dump", key)


def test_backup_key_must_be_exactly_32_bytes():
    assert load_key(bytes(range(32)).hex()) == bytes(range(32))
    with pytest.raises(ValueError):
        load_key("too-short")


def test_backup_metrics_report_retention_and_freshness_without_private_metadata(tmp_path: Path):
    backup = tmp_path / "interai-test.dump.enc"
    backup.write_bytes(b"encrypted")

    payload = backup_metrics_payload(tmp_path).decode("utf-8")

    assert "interai_backup_files 1" in payload
    assert "interai_backup_latest_age_seconds" in payload
    assert str(tmp_path) not in payload
