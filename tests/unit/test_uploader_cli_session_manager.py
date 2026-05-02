from pathlib import Path

import pytest

from src.uploader_cli.exceptions import SessionError
from src.uploader_cli.session_manager import SessionManager


def test_create_session_persists_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    session = SessionManager.create_session({"repo_id": "alice/parrots-2026", "segments_dir": "C:/data"})

    assert session.metadata_path.exists()
    metadata = session.load_metadata()
    assert metadata["repo_id"] == "alice/parrots-2026"
    assert metadata["segments_dir"] == "C:/data"


def test_save_checkpoint_is_atomic_and_loads_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    session = SessionManager(session_id="upload-test-001")
    checkpoint = {"repo_id": "alice/parrots-2026", "uploaded": 1, "failed": 0, "status": "ready"}
    session.save_checkpoint(checkpoint)

    assert session.checkpoint_path.exists()
    assert session.load_checkpoint() == checkpoint


def test_mark_file_done_updates_checkpoint_counters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    session = SessionManager(session_id="upload-test-002")
    session.save_checkpoint({"repo_id": "alice/parrots-2026", "uploaded": 0, "failed": 0, "status": "ready"})

    updated = session.mark_file_done(remote_path="audio/parrots-2026/song.wav", bytes_uploaded=512)

    assert updated["uploaded"] == 1
    assert updated["bytes_uploaded"] == 512
    assert updated["last_completed_file"] == "audio/parrots-2026/song.wav"
    assert updated["status"] == "uploaded"


def test_mark_file_failed_updates_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    session = SessionManager(session_id="upload-test-003")
    session.save_checkpoint({"repo_id": "alice/parrots-2026", "uploaded": 0, "failed": 0, "status": "ready"})

    updated = session.mark_file_failed(remote_path="audio/parrots-2026/broken.wav", error="network error")

    assert updated["failed"] == 1
    assert updated["last_failed_file"] == "audio/parrots-2026/broken.wav"
    assert updated["last_error"] == "network error"
    assert updated["status"] == "failed"


def test_load_checkpoint_rejects_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    session = SessionManager(session_id="upload-test-004")
    session.checkpoint_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(SessionError, match="Invalid checkpoint JSON"):
        session.load_checkpoint()
