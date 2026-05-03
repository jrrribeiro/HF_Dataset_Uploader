import csv
import os
from pathlib import Path
from click.testing import CliRunner

import pytest

from src.uploader_cli.main import cli


class FakeHfApi:
    def __init__(self, token=None, storage_dir=None):
        self.token = token
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def upload_file(self, path_or_file=None, path_or_fileobj=None, path_in_repo=None, repo_id=None, repo_type=None):
        target = self.storage_dir / path_in_repo
        target.parent.mkdir(parents=True, exist_ok=True)
        if path_or_fileobj is not None:
            # bytes or file-like
            if hasattr(path_or_fileobj, "read"):
                data = path_or_fileobj.read()
            else:
                data = path_or_fileobj
            if isinstance(data, str):
                data = data.encode("utf-8")
            target.write_bytes(data)
            return {"file": path_in_repo}
        if path_or_file is not None:
            src = Path(path_or_file)
            if not src.exists():
                raise FileNotFoundError(path_or_file)
            target.write_bytes(src.read_bytes())
            return {"file": path_in_repo}
        raise ValueError("No file provided to upload_file")

    def list_repo_files(self, repo_id=None, repo_type=None):
        files = []
        for p in self.storage_dir.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(self.storage_dir)).replace("\\", "/"))
        return files


@pytest.fixture()
def tmp_remote(tmp_path):
    d = tmp_path / "remote"
    d.mkdir()
    return d


def test_upload_flow_csv_and_segments(tmp_path, monkeypatch, tmp_remote):
    # prepare local segments
    segments = tmp_path / "segments"
    (segments / "proj").mkdir(parents=True)
    a = segments / "proj" / "a.wav"
    a.write_bytes(b"one")
    b = segments / "proj" / "b.wav"
    b.write_bytes(b"two")

    # prepare CSV
    csv_file = tmp_path / "detections.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["audio_file", "score"])
        writer.writeheader()
        writer.writerow({"audio_file": "proj/a.wav", "score": "0.9"})
        writer.writerow({"audio_file": "proj/b.wav", "score": "0.8"})

    # monkeypatch HfApi to our fake implementation
    def _fake_hfapi_factory(token=None):
        return FakeHfApi(token=token, storage_dir=tmp_remote)

    monkeypatch.setattr("huggingface_hub.HfApi", _fake_hfapi_factory)
    # avoid network call in RepositoryService.validate_repo by stubbing it
    # avoid network call in RepositoryService.validate_repo by stubbing it
    def _fake_validate(self, repo_id: str):
        return {
            "repo_id": repo_id,
            "is_valid": True,
            "project_slug": repo_id.split("/", 1)[1],
            "missing_prefixes": [],
            "has_manifest": True,
            "manifest_ok": True,
            "manifest_error": "",
        }

    monkeypatch.setattr("src.uploader_cli.main.RepositoryService.validate_repo", _fake_validate)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "upload",
            "--repo-id",
            "me/repo",
            "--segments",
            str(segments),
            "--csv",
            str(csv_file),
            "--token",
            "fake-token",
            "--workers",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output

    # verify remote structure
    remote_files = {p.relative_to(tmp_remote).as_posix() for p in tmp_remote.rglob("*") if p.is_file()}
    assert "index/manifest.json" in remote_files
    assert "index/detections.csv" in remote_files
    # shards may be parquet or jsonl
    shards = [p for p in remote_files if p.startswith("index/shards/")]
    assert len(shards) >= 1
    # audio files uploaded under audio/
    assert "audio/proj/a.wav" in remote_files
    assert "audio/proj/b.wav" in remote_files
