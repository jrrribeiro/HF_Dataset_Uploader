import os

from pathlib import Path

from src.uploader_cli.batch_uploader import BatchUploader
from src.uploader_cli.session_manager import SessionManager


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.raise_on = 0

    def upload_file(self, path_or_file, path_in_repo, repo_id):
        self.calls.append((path_or_file, path_in_repo, repo_id))
        if self.raise_on:
            self.raise_on -= 1
            raise RuntimeError("transient error")
        return {"file": path_in_repo}


class FakeDedup:
    def __init__(self, to_skip=None):
        self.to_skip = set(to_skip or [])
        self.marked = []

    def check_remote(self, remote_path, file_path=None):
        return {"remote_path": remote_path, "status": "skip" if remote_path in self.to_skip else "upload"}

    def mark_uploaded(self, remote_path):
        self.marked.append(remote_path)


def test_batch_uploader_retry_and_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRDNET_UPLOADER_SESSION_DIR", str(tmp_path / "sessions"))

    f1 = tmp_path / "a.wav"
    f1.write_bytes(b"one")
    f2 = tmp_path / "b.wav"
    f2.write_bytes(b"two")

    infos = [
        {"full_path": str(f1), "relative_path": "proj/a.wav", "size": f1.stat().st_size},
        {"full_path": str(f2), "relative_path": "proj/b.wav", "size": f2.stat().st_size},
    ]

    api = FakeAPI()
    api.raise_on = 1
    dedup = FakeDedup(to_skip={"audio/proj/b.wav"})
    session = SessionManager(session_id="test-batch")

    uploader = BatchUploader(api=api, repo_id="me/repo", deduplicator=dedup, session=session, max_retries=2, initial_backoff=0)
    result = uploader.upload_files(infos, remote_base="audio")

    assert result["uploaded"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert dedup.marked == ["audio/proj/a.wav"]
