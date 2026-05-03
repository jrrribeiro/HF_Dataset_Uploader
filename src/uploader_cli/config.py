from __future__ import annotations

import os
from pathlib import Path
from typing import Any


APP_NAME = "BirdNET Uploader"
SCHEMA_VERSION = "1.0.0"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
INDEX_SHARD_SIZE = 10_000

MAX_BATCH_SIZE = 10
RETRY_MAX_ATTEMPTS = 3
RETRY_INITIAL_BACKOFF_SECONDS = 1.0
RETRY_MAX_BACKOFF_SECONDS = 30.0

KEYRING_SERVICE = "birdnet-uploader"
KEYRING_ACCOUNT = "hf_token"


def _resolve_path_from_env(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name)
    value = Path(raw).expanduser() if raw else default
    value.mkdir(parents=True, exist_ok=True)
    return value


def get_session_root() -> Path:
    """Resolve and create the session storage root directory."""
    data_root = os.getenv("BIRDNET_UPLOADER_DATA_DIR")
    if data_root:
        return _resolve_path_from_env("BIRDNET_UPLOADER_SESSION_DIR", Path(data_root).expanduser() / "sessions")
    return _resolve_path_from_env(
        "BIRDNET_UPLOADER_SESSION_DIR",
        Path.home() / ".birdnet-uploader" / "sessions",
    )


def get_cache_root() -> Path:
    return _resolve_path_from_env(
        "BIRDNET_UPLOADER_CACHE_DIR",
        Path.home() / ".birdnet-uploader" / "cache",
    )


def get_log_root() -> Path:
    return _resolve_path_from_env(
        "BIRDNET_UPLOADER_LOG_DIR",
        Path.home() / ".birdnet-uploader" / "logs",
    )


def get_runtime_config() -> dict[str, Any]:
    return {
        "session_root": str(get_session_root()),
        "cache_root": str(get_cache_root()),
        "log_root": str(get_log_root()),
        "max_batch_size": MAX_BATCH_SIZE,
        "retry_max_attempts": RETRY_MAX_ATTEMPTS,
        "retry_initial_backoff_seconds": RETRY_INITIAL_BACKOFF_SECONDS,
        "retry_max_backoff_seconds": RETRY_MAX_BACKOFF_SECONDS,
        "index_shard_size": INDEX_SHARD_SIZE,
    }
