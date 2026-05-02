from pathlib import Path

from src.uploader_cli.session_manager import SessionManager


def test_session_checkpoint_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path))

    manager = SessionManager(session_id="upload-test-001")
    payload = {"repo_id": "alice/demo", "uploaded": 5, "status": "uploading"}
    manager.save_checkpoint(payload)

    reloaded = manager.load_checkpoint()
    assert reloaded == payload
    assert manager.checkpoint_path.exists()
