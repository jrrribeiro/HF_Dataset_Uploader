from pathlib import Path

import pytest

from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.services.audio_fetch_service import AudioFetchService


def test_fetch_downloads_and_then_hits_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.wav"
    remote_file.write_bytes(b"audio-bytes")
    calls: list[str] = []

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        calls.append(filename)
        return str(remote_file)

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    first = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")
    second = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")

    assert first.source == "remote"
    assert second.source == "cache"
    assert len(calls) == 1


def test_fetch_without_extension_tries_supported_extensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.mp3"
    remote_file.write_bytes(b"audio-bytes")
    attempts: list[str] = []

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        attempts.append(filename)
        if filename.endswith(".mp3"):
            return str(remote_file)
        raise RuntimeError("not found")

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch(dataset_repo="org/project-dataset", audio_id="recording_001")

    assert result.source == "remote"
    assert any(path.endswith(".wav") for path in attempts)
    assert any(path.endswith(".mp3") for path in attempts)


def test_fetch_uses_demo_fallback_when_remote_audio_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        _ = filename
        raise RuntimeError("not found")

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch(
        dataset_repo="org/project-dataset",
        audio_id="missing_demo_audio_001",
        allow_demo_fallback=True,
    )

    assert result.source == "demo-fallback"
    assert Path(result.local_path).exists()
    assert Path(result.local_path).suffix.lower() == ".wav"


def test_cleanup_after_validation_removes_cached_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.wav"
    remote_file.write_bytes(b"audio-bytes")

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        _ = filename
        return str(remote_file)

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")
    path_before = Path(result.local_path)
    assert path_before.exists()

    service.cleanup_after_validation(result.cache_key)

    assert not path_before.exists()
    assert cache.get(result.cache_key) is None


def test_fetch_local_loads_local_audio_file(tmp_path: Path) -> None:
    """Test loading audio from local filesystem (useful for testing with local segments)."""
    # Create a local audio file
    local_audio = tmp_path / "local_segment.wav"
    local_audio.write_bytes(b"local-audio-bytes")

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch_local(str(local_audio))

    assert result.source == "local"
    assert Path(result.local_path).exists()
    assert Path(result.local_path).read_bytes() == b"local-audio-bytes"
    assert "local:" in result.cache_key


def test_fetch_local_caches_on_second_call(tmp_path: Path) -> None:
    """Test that local audio is cached after first fetch."""
    local_audio = tmp_path / "segment.wav"
    local_audio.write_bytes(b"segment-bytes")

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    first = service.fetch_local(str(local_audio))
    second = service.fetch_local(str(local_audio))

    assert first.source == "local"
    assert second.source == "cache"
    assert first.cache_key == second.cache_key


def test_fetch_local_raises_on_nonexistent_file(tmp_path: Path) -> None:
    """Test that fetch_local raises error for missing files."""
    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    with pytest.raises(FileNotFoundError, match="Local audio file not found"):
        service.fetch_local(str(tmp_path / "nonexistent.wav"))


def test_fetch_local_raises_on_unsupported_format(tmp_path: Path) -> None:
    """Test that fetch_local rejects unsupported audio formats."""
    unsupported_file = tmp_path / "audio.xyz"
    unsupported_file.write_bytes(b"not-audio")

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    with pytest.raises(ValueError, match="Unsupported audio format"):
        service.fetch_local(str(unsupported_file))
