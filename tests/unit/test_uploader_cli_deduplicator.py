from pathlib import Path

import pytest

from src.uploader_cli.deduplicator import Deduplicator


class FakeApi:
    def __init__(self, files: list[str]) -> None:
        self.files = files
        self.calls = 0

    def list_repo_files(self, repo_id: str, repo_type: str = "dataset") -> list[str]:
        _ = repo_id
        _ = repo_type
        self.calls += 1
        return list(self.files)


def test_check_remote_uses_cached_remote_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_CACHE_DIR", str(tmp_path / "cache"))
    api = FakeApi(["audio/parrots-2026/existing.wav"])
    local_file = tmp_path / "local.wav"
    local_file.write_bytes(b"birdnet")

    dedup = Deduplicator(api, "alice/parrots-2026")
    first = dedup.check_remote("audio/parrots-2026/existing.wav", file_path=local_file)
    second = dedup.check_remote("audio/parrots-2026/missing.wav", file_path=local_file)

    assert first["status"] == "skip"
    assert second["status"] == "upload"
    assert api.calls == 1


def test_check_remote_persists_remote_index_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_CACHE_DIR", str(tmp_path / "cache"))
    api = FakeApi(["audio/parrots-2026/existing.wav"])

    dedup = Deduplicator(api, "alice/parrots-2026")
    dedup.load_cached_index()

    assert dedup.cache_path.exists()
    assert "existing.wav" in dedup.cache_path.read_text(encoding="utf-8")


def test_mark_uploaded_updates_local_remote_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_CACHE_DIR", str(tmp_path / "cache"))
    api = FakeApi([])

    dedup = Deduplicator(api, "alice/parrots-2026")
    assert dedup.check_remote("audio/parrots-2026/new.wav")["status"] == "upload"

    dedup.mark_uploaded("audio/parrots-2026/new.wav")

    assert dedup.check_remote("audio/parrots-2026/new.wav")["status"] == "skip"
