"""Local-only runtime services used by the desktop build."""

from __future__ import annotations

import json
import os
import platform
import base64
import hashlib
import hmac
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PRODUCT_NAME = "PrepMate"
LEGACY_PRODUCT_NAME = "InterAI"
LOCAL_USER_ID = "local-prepmate-user"
KEYCHAIN_SERVICE = PRODUCT_NAME
LEGACY_KEYCHAIN_SERVICE = LEGACY_PRODUCT_NAME
SETTINGS_FILE_NAME = "settings.json"
PROVIDER_KEY_MARKERS_FIELD = "provider_key_saved"
DATA_KEY_ACCOUNT = "data-encryption-key:v1"
SUPPORTED_PROVIDERS = {"openai", "anthropic", "google", "openai_compatible"}
_TEST_DATA_KEY = hashlib.sha256(b"prepmate-test-only-data-key").digest()
_TEST_PROVIDER_KEYS: dict[str, str] = {}


def _configured_data_dir() -> str:
    return os.getenv("PREPMATE_DATA_DIR", "").strip() or os.getenv("INTERAI_DATA_DIR", "").strip()


def _legacy_data_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / LEGACY_PRODUCT_NAME
    if platform.system() == "Windows":
        return Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / LEGACY_PRODUCT_NAME
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / LEGACY_PRODUCT_NAME


def local_data_dir() -> Path:
    configured = _configured_data_dir()
    if configured:
        path = Path(configured).expanduser()
    elif platform.system() == "Darwin":
        path = Path.home() / "Library" / "Application Support" / PRODUCT_NAME
    elif platform.system() == "Windows":
        path = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / PRODUCT_NAME
    else:
        path = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / PRODUCT_NAME
    legacy = _legacy_data_dir()
    if not configured and not path.exists() and legacy.exists():
        # Preserve an existing private checkout during the product rename. A
        # later explicit wipe can remove both namespaces; this migration only
        # copies data into the new location and never deletes the old one.
        shutil.copytree(legacy, path, dirs_exist_ok=True)
        legacy_database = path / "interai.sqlite3"
        renamed_database = path / "prepmate.sqlite3"
        if legacy_database.exists() and not renamed_database.exists():
            shutil.copy2(legacy_database, renamed_database)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def local_database_path() -> Path:
    return local_data_dir() / "prepmate.sqlite3"


def _settings_path() -> Path:
    return local_data_dir() / SETTINGS_FILE_NAME


def _read_settings() -> dict[str, Any]:
    try:
        payload = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_settings(payload: dict[str, Any]) -> None:
    path = _settings_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _provider_key_is_marked_saved(provider: str) -> bool:
    """Read only the non-secret credential marker; never touch the keychain."""
    markers = _read_settings().get(PROVIDER_KEY_MARKERS_FIELD)
    return bool(markers.get(str(provider or "").strip().lower())) if isinstance(markers, dict) else False


def _record_provider_key_state(provider: str, saved: bool) -> None:
    """Persist credential presence without persisting any credential material."""
    selected = str(provider or "").strip().lower()
    if selected not in SUPPORTED_PROVIDERS:
        return
    path = _settings_path()
    if not saved and not path.is_file():
        # Complete wipe removes settings before deleting Keychain entries. Do
        # not recreate an otherwise empty settings file during that cleanup.
        return
    payload = _read_settings()
    markers = payload.get(PROVIDER_KEY_MARKERS_FIELD)
    normalized = dict(markers) if isinstance(markers, dict) else {}
    if saved:
        normalized[selected] = True
    else:
        normalized.pop(selected, None)
    if normalized:
        payload[PROVIDER_KEY_MARKERS_FIELD] = normalized
    else:
        payload.pop(PROVIDER_KEY_MARKERS_FIELD, None)
    _write_settings(payload)


def get_local_preferences() -> dict[str, Any]:
    payload = _read_settings()
    provider = str(payload.get("provider") or os.getenv("PREPMATE_PROVIDER") or os.getenv("INTERAI_PROVIDER") or "openai").strip().lower()
    model = str(payload.get("model") or os.getenv("PREPMATE_MODEL") or os.getenv("INTERAI_MODEL") or "gpt-5-mini").strip()
    endpoint = str(payload.get("endpoint") or "").strip()
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "theme": payload.get("theme") if payload.get("theme") in {"light", "dark"} else "light",
        # This is deliberately a non-secret settings marker. Reading Settings
        # or readiness at app startup must never query the OS Keychain.
        "has_api_key": _provider_key_is_marked_saved(provider),
        "requires_api_key": provider_requires_api_key(provider, endpoint),
    }


def save_local_preferences(*, provider: str, model: str, endpoint: str = "") -> dict[str, Any]:
    provider, model, endpoint = normalize_provider_preferences(provider, model, endpoint)
    payload = _read_settings()
    payload.update({"provider": provider, "model": model, "endpoint": endpoint})
    _write_settings(payload)
    return get_local_preferences()


def normalize_provider_preferences(provider: str, model: str, endpoint: str = "") -> tuple[str, str, str]:
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    endpoint = str(endpoint or "").strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported AI provider")
    if not model:
        raise ValueError("A model is required")
    if provider == "openai_compatible":
        endpoint = validate_provider_endpoint(endpoint)
    else:
        endpoint = ""
    return provider, model, endpoint


def save_local_theme(theme: str) -> None:
    normalized = str(theme or "").strip().lower()
    if normalized not in {"light", "dark"}:
        raise ValueError("Theme must be light or dark")
    payload = _read_settings()
    payload["theme"] = normalized
    _write_settings(payload)


def _keyring():
    # PyInstaller's embedded macOS keyring backend can block the event loop
    # inside SecItemCopyMatching when the frozen executable is unsigned. Use
    # the native `security` CLI for packaged builds instead; it still stores
    # credentials in the user's OS Keychain and returns a bounded subprocess
    # result without changing the storage contract.
    if getattr(sys, "frozen", False):
        return None
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _keychain_account(provider: str) -> str:
    return f"provider-api-key:{str(provider).strip().lower()}"


def _test_runtime() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() == "test" or "pytest" in sys.modules


def configured_api_token() -> str:
    """Return the per-launch token injected by the desktop shell, if present."""
    return (os.getenv("PREPMATE_API_TOKEN", "").strip() or os.getenv("INTERAI_API_TOKEN", "").strip())


def api_token_matches(candidate: str | None) -> bool:
    expected = configured_api_token()
    return not expected or hmac.compare_digest(expected, str(candidate or "").strip())


def is_loopback_host(value: str | None) -> bool:
    raw = str(value or "").strip().lower()
    if raw in {"::1", "[::1]"}:
        return True
    host = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
    return host in {"127.0.0.1", "localhost"}


def is_allowed_local_origin(value: str | None) -> bool:
    origin = str(value or "").strip()
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and is_loopback_host(parsed.hostname)


def validate_provider_endpoint(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("An API endpoint is required for an OpenAI-compatible provider")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise ValueError("The provider endpoint is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The provider endpoint must use http or https")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("The provider endpoint cannot contain credentials or a fragment")
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        raise ValueError("Non-local provider endpoints must use https")
    return endpoint


def provider_requires_api_key(provider: str, endpoint: str = "") -> bool:
    if str(provider).strip().lower() != "openai_compatible":
        return True
    try:
        return not is_loopback_host(urlsplit(str(endpoint or "")).hostname)
    except ValueError:
        return True


def _native_keychain_get(account: str, service: str = KEYCHAIN_SERVICE) -> str:
    if platform.system() == "Darwin" and shutil.which("security"):
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    if platform.system() == "Linux" and shutil.which("secret-tool"):
        result = subprocess.run(
            ["secret-tool", "lookup", "service", service, "account", account],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    raise RuntimeError("The operating-system keychain integration is unavailable")


def _native_keychain_set(account: str, value: str, service: str = KEYCHAIN_SERVICE) -> None:
    if platform.system() == "Darwin" and shutil.which("security"):
        result = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", value],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
    elif platform.system() == "Linux" and shutil.which("secret-tool"):
        result = subprocess.run(
            ["secret-tool", "store", "--label", service, "service", service, "account", account],
            input=value + "\n",
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
    raise RuntimeError("The operating-system keychain integration is unavailable")


def _native_keychain_delete(account: str, service: str = KEYCHAIN_SERVICE) -> None:
    if platform.system() == "Darwin" and shutil.which("security"):
        result = subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", account],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 or "could not be found" in result.stderr.lower():
            return
    elif platform.system() == "Linux" and shutil.which("secret-tool"):
        result = subprocess.run(
            ["secret-tool", "clear", "service", service, "account", account],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
    raise RuntimeError("The operating-system keychain integration is unavailable")


def get_provider_api_key(provider: str | None = None) -> str:
    selected = str(provider or get_local_preferences().get("provider") or "openai").strip().lower()
    if _test_runtime():
        return _TEST_PROVIDER_KEYS.get(selected, "")
    account = _keychain_account(selected)
    try:
        backend = _keyring()
        value = backend.get_password(KEYCHAIN_SERVICE, account) if backend else _native_keychain_get(account)
        if not value:
            value = backend.get_password(LEGACY_KEYCHAIN_SERVICE, account) if backend else _native_keychain_get(account, LEGACY_KEYCHAIN_SERVICE)
            if value:
                # Migrate the old namespace lazily without ever placing the
                # credential in settings, SQLite, logs, or browser storage.
                try:
                    if backend:
                        backend.set_password(KEYCHAIN_SERVICE, account, value)
                    else:
                        _native_keychain_set(account, value)
                except Exception:
                    pass
    except Exception as exc:  # pragma: no cover - OS keychain dependent
        raise RuntimeError("The operating-system keychain could not be read") from exc
    return str(value or "").strip()


def set_provider_api_key(provider: str, api_key: str) -> None:
    provider = str(provider or "").strip().lower()
    api_key = str(api_key or "").strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported AI provider")
    if len(api_key) < 8:
        raise ValueError("The API key looks too short")
    if _test_runtime():
        _TEST_PROVIDER_KEYS[provider] = api_key
        _record_provider_key_state(provider, True)
        return
    account = _keychain_account(provider)
    try:
        backend = _keyring()
        if backend:
            backend.set_password(KEYCHAIN_SERVICE, account, api_key)
        else:
            _native_keychain_set(account, api_key)
    except Exception as exc:  # pragma: no cover - OS keychain dependent
        raise RuntimeError("The operating-system keychain could not be updated") from exc
    _record_provider_key_state(provider, True)


def delete_provider_api_key(provider: str | None = None) -> None:
    selected = str(provider or get_local_preferences().get("provider") or "openai").strip().lower()
    if _test_runtime():
        _TEST_PROVIDER_KEYS.pop(selected, None)
        _record_provider_key_state(selected, False)
        return
    account = _keychain_account(selected)
    try:
        backend = _keyring()
        if backend:
            for service in (KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_SERVICE):
                try:
                    backend.delete_password(service, account)
                except Exception:
                    pass
        else:
            for service in (KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_SERVICE):
                try:
                    _native_keychain_delete(account, service)
                except Exception:
                    pass
    except Exception as exc:  # pragma: no cover - OS keychain dependent
        # OS keychains commonly report a missing item as an exception.  A
        # delete operation is idempotent for the UI.
        if "not found" not in str(exc).lower() and "no password" not in str(exc).lower():
            raise RuntimeError("The operating-system keychain could not be updated") from exc
    _record_provider_key_state(selected, False)


def delete_data_encryption_key() -> None:
    """Remove the database key from both the current and legacy keychain names."""
    if _test_runtime():
        return
    try:
        backend = _keyring()
        services = (KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_SERVICE)
        if backend:
            for service in services:
                try:
                    backend.delete_password(service, DATA_KEY_ACCOUNT)
                except Exception:
                    pass
        else:
            for service in services:
                try:
                    _native_keychain_delete(DATA_KEY_ACCOUNT, service)
                except Exception:
                    pass
    except Exception as exc:  # pragma: no cover - OS keychain dependent
        if "not found" not in str(exc).lower() and "no password" not in str(exc).lower():
            raise RuntimeError("The operating-system keychain could not be updated") from exc


def clear_local_caches() -> dict[str, Any]:
    """Remove downloaded model/media/cache folders without touching history."""
    data_dir = local_data_dir()
    legacy_dir = _legacy_data_dir()
    directories = (data_dir,) if _configured_data_dir() else (data_dir, legacy_dir)
    removed: list[str] = []
    for directory in directories:
        for name in ("cache", "caches", "models", "model-cache", "uploads", "media"):
            path = directory / name
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                    removed.append(str(path))
            except OSError as exc:
                raise RuntimeError(f"Could not remove local directory {path}: {exc}") from exc
    try:
        from knowledge_map import clear_cache
        clear_cache()
    except Exception:
        pass
    try:
        from local_cache import get_local_cache
        get_local_cache().clear()
    except Exception:
        pass
    return {"removed": removed, "data_directory": str(data_dir)}


def wipe_local_data() -> dict[str, Any]:
    """Delete the local database, preferences, caches, and provider secrets.

    The schema is recreated immediately so the running desktop process remains
    usable after a wipe. The migrated legacy directory is included only when it
    is the platform's known application-data location; arbitrary configured
    directories are never traversed.
    """
    from database import close_connection_pool, ensure_local_schema, init_connection_pool

    data_dir = local_data_dir()
    legacy_dir = _legacy_data_dir()
    known_files = {
        "prepmate.sqlite3",
        "prepmate.sqlite3-shm",
        "prepmate.sqlite3-wal",
        "interai.sqlite3",
        "interai.sqlite3-shm",
        "interai.sqlite3-wal",
        SETTINGS_FILE_NAME,
    }
    removed: list[str] = []

    close_connection_pool()
    # A caller-provided directory is an isolated test/workspace boundary. Do
    # not reach outside it and remove a similarly named legacy directory.
    directories = (data_dir,) if _configured_data_dir() else (data_dir, legacy_dir)
    for filename in sorted(known_files):
        for directory in directories:
            path = directory / filename
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed.append(str(path))
            except OSError as exc:
                raise RuntimeError(f"Could not remove local file {path}: {exc}") from exc

    for directory in directories:
        for path in directory.glob("*.sqlite3.backup-*"):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed.append(str(path))
            except OSError as exc:
                raise RuntimeError(f"Could not remove local backup {path}: {exc}") from exc

    # Remove only explicitly named user-cache directories. Model packs are
    # intentionally included because they may contain downloaded user data.
    removed.extend(clear_local_caches()["removed"])

    for provider in sorted(SUPPORTED_PROVIDERS):
        delete_provider_api_key(provider)
    delete_data_encryption_key()

    ensure_local_schema()
    init_connection_pool()
    return {
        "removed": removed,
        "data_directory": str(data_dir),
        "database_recreated": True,
    }


def has_provider_api_key(provider: str | None = None) -> bool:
    selected = str(provider or get_local_preferences().get("provider") or "openai").strip().lower()
    return _provider_key_is_marked_saved(selected)


def get_or_create_data_encryption_key() -> bytes:
    """Load the local field-encryption key from the OS credential store.

    The database and settings file never contain this key. Tests use an
    isolated deterministic key so CI does not need a desktop keychain.
    """
    if _test_runtime():
        return _TEST_DATA_KEY

    encoded = ""
    try:
        backend = _keyring()
        encoded = str(backend.get_password(KEYCHAIN_SERVICE, DATA_KEY_ACCOUNT) or "") if backend else _native_keychain_get(DATA_KEY_ACCOUNT)
        if not encoded:
            encoded = str(backend.get_password(LEGACY_KEYCHAIN_SERVICE, DATA_KEY_ACCOUNT) or "") if backend else _native_keychain_get(DATA_KEY_ACCOUNT, LEGACY_KEYCHAIN_SERVICE)
    except Exception:
        encoded = ""

    if not encoded:
        encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        try:
            backend = _keyring()
            if backend:
                backend.set_password(KEYCHAIN_SERVICE, DATA_KEY_ACCOUNT, encoded)
            else:
                _native_keychain_set(DATA_KEY_ACCOUNT, encoded)
        except Exception as exc:  # pragma: no cover - OS keychain dependent
            raise RuntimeError("The operating-system keychain could not store the local data key") from exc
    elif backend := _keyring():
        # A key found under the old product name remains valid; copy it to the
        # new namespace before future reads so a rename never strands data.
        try:
            if not backend.get_password(KEYCHAIN_SERVICE, DATA_KEY_ACCOUNT):
                backend.set_password(KEYCHAIN_SERVICE, DATA_KEY_ACCOUNT, encoded)
        except Exception:
            pass
    elif encoded:
        try:
            _native_keychain_set(DATA_KEY_ACCOUNT, encoded)
        except Exception:
            pass

    try:
        key = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("The local data key in the operating-system keychain is invalid") from exc
    if len(key) != 32:
        raise RuntimeError("The local data key in the operating-system keychain is invalid")
    return key


def local_user() -> dict[str, Any]:
    return {
        "user_id": LOCAL_USER_ID,
        "name": "Local user",
        "full_name": "Local user",
        "email": None,
        "local_only": True,
    }
