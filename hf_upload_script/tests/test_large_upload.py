from __future__ import annotations

from pathlib import Path

import pandas as pd

from uploader.large_upload import (
    build_upload_plan,
    load_remote_paths,
    materialize_staging_folder,
    scan_local_inventory,
    upload_large_staging_folder,
)


def _write_audio(path: Path, payload: bytes = b"audio") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_scan_local_inventory_reads_audio_once(tmp_path: Path) -> None:
    _write_audio(tmp_path / "Species one" / "a.wav")
    _write_audio(tmp_path / "Species one" / "b.mp3")
    (tmp_path / "Species one" / "notes.txt").write_text("ignore", encoding="utf-8")

    events: list[dict] = []
    records = scan_local_inventory(tmp_path, on_progress=events.append, progress_every=1)

    assert [record.original_relative_path for record in records] == [
        "Species one/a.wav",
        "Species one/b.mp3",
    ]
    assert {record.logical_group for record in records} == {"Species one"}
    assert events[-1]["done"] is True
    assert events[-1]["files"] == 2


def test_build_upload_plan_shards_large_logical_folder(tmp_path: Path) -> None:
    records = []
    for index in range(5):
        _write_audio(tmp_path / "Species one" / f"{index}.wav")
    records = scan_local_inventory(tmp_path)

    plan = build_upload_plan(records, set(), max_files_per_folder=2)

    stored_paths = [item.stored_path for item in plan]
    assert stored_paths[0].startswith("audio/Species_one/shard-000000/")
    assert stored_paths[2].startswith("audio/Species_one/shard-000001/")
    assert stored_paths[4].startswith("audio/Species_one/shard-000002/")
    assert all(item.status == "upload" for item in plan)


def test_build_upload_plan_skips_remote_paths(tmp_path: Path) -> None:
    _write_audio(tmp_path / "Species one" / "a.wav")
    records = scan_local_inventory(tmp_path)
    initial_plan = build_upload_plan(records, set())

    remote_paths = {initial_plan[0].stored_path}
    plan = build_upload_plan(records, remote_paths)

    assert plan[0].status == "skip"


def test_materialize_staging_folder_writes_index_and_only_upload_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_audio(source / "Species one" / "a.wav", b"a")
    _write_audio(source / "Species one" / "b.wav", b"b")
    records = scan_local_inventory(source)
    initial_plan = build_upload_plan(records, set())
    remote_paths = {initial_plan[0].stored_path}
    plan = build_upload_plan(records, remote_paths)

    csv_path = tmp_path / "detections.csv"
    csv_path.write_text("source_file,label\nx.wav,test\n", encoding="utf-8")
    staging = tmp_path / "staging"

    summary = materialize_staging_folder(plan, staging, csv_file=csv_path, repo_id="owner/repo")

    uploaded_files = [item for item in plan if item.status == "upload"]
    assert summary["upload_files"] == 1
    assert summary["skipped_files"] == 1
    assert (staging / uploaded_files[0].stored_path).exists()
    assert (staging / "index" / "detections.csv").exists()

    index = pd.read_parquet(staging / "index" / "files.parquet")
    assert set(index["status"]) == {"skip", "upload"}
    assert set(index["logical_group"]) == {"Species one"}


def test_materialize_staging_folder_removes_stale_payload_but_keeps_cache(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_audio(source / "Species one" / "a.wav", b"a")
    plan = build_upload_plan(scan_local_inventory(source), set())
    staging = tmp_path / "staging"
    stale_file = staging / "audio" / "old.wav"
    cache_file = staging / ".cache" / "huggingface" / "keep.json"
    stale_file.parent.mkdir(parents=True)
    cache_file.parent.mkdir(parents=True)
    stale_file.write_bytes(b"old")
    cache_file.write_text("cache", encoding="utf-8")

    materialize_staging_folder(plan, staging, repo_id="owner/repo")

    assert not stale_file.exists()
    assert cache_file.exists()
    assert (staging / plan[0].stored_path).exists()


class FakeApi:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.uploaded: list[dict] = []

    def create_repo(self, **kwargs):
        self.created.append(kwargs)

    def upload_large_folder(self, **kwargs):
        self.uploaded.append(kwargs)

    def list_repo_files(self, **kwargs):
        return ["audio/existing.wav", "index/files.parquet"]


def test_load_remote_paths_calls_hub_once() -> None:
    api = FakeApi()

    paths = load_remote_paths(api, "owner/repo")

    assert paths == {"audio/existing.wav", "index/files.parquet"}


def test_upload_large_staging_folder_uses_single_large_folder_call(tmp_path: Path) -> None:
    api = FakeApi()

    upload_large_staging_folder(api, repo_id="owner/repo", staging_dir=tmp_path, workers=3)

    assert len(api.created) == 1
    assert len(api.uploaded) == 1
    assert api.uploaded[0]["repo_id"] == "owner/repo"
    assert api.uploaded[0]["repo_type"] == "dataset"
    assert api.uploaded[0]["folder_path"] == str(tmp_path.resolve())
    assert api.uploaded[0]["num_workers"] == 3
