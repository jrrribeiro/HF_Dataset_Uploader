from pathlib import Path

from src.uploader_cli.config import get_runtime_config, get_session_root


def test_get_session_root_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    custom_root = tmp_path / "custom-sessions"
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(custom_root))

    resolved = get_session_root()

    assert resolved == custom_root
    assert resolved.exists()
    assert resolved.is_dir()


def test_get_session_root_prefers_data_dir_when_session_dir_missing(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "container-data"
    monkeypatch.delenv("BIRDNET_UPLOADER_SESSION_DIR", raising=False)
    monkeypatch.setenv("BIRDNET_UPLOADER_DATA_DIR", str(data_root))

    resolved = get_session_root()

    assert resolved == data_root / "sessions"
    assert resolved.exists()
    assert resolved.is_dir()


def test_get_runtime_config_contains_expected_keys() -> None:
    config = get_runtime_config()

    assert "session_root" in config
    assert "cache_root" in config
    assert "log_root" in config
    assert config["max_batch_size"] == 10
    assert config["retry_max_attempts"] == 3
    assert config["index_shard_size"] == 10000
