from __future__ import annotations

import json
import tempfile
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from .config import SCHEMA_VERSION, INDEX_SHARD_SIZE

try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    _HAVE_PANDAS = False


def _project_from_repo(repo_id: str) -> str:
    return repo_id.split("/", 1)[1]


def summarize_csv_rows(csv_rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    total_detections = 0
    unique_files: set[str] = set()

    for row in csv_rows:
        total_detections += 1
        file_name = str(row.get("audio_file") or row.get("file") or "")
        if file_name:
            unique_files.add(file_name)

    return {
        "total_detections": total_detections,
        "total_audio_files": len(unique_files),
    }


def build_manifest_from_scan(
    repo_id: str,
    scan_summary: dict[str, Any],
    *,
    csv_rows: Iterable[dict[str, Any]] | None = None,
    csv_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_slug = _project_from_repo(repo_id)
    total_files = int(scan_summary.get("total_files", 0))
    total_size = int(scan_summary.get("total_size", 0))

    total_detections = 0
    total_audio_files = total_files

    if csv_stats is not None:
        total_detections = int(csv_stats.get("total_detections", 0))
        total_audio_files = int(csv_stats.get("total_audio_files", total_files) or total_files)
    elif csv_rows is not None:
        csv_summary = summarize_csv_rows(csv_rows)
        total_detections = csv_summary["total_detections"]
        if csv_summary["total_audio_files"]:
            total_audio_files = csv_summary["total_audio_files"]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "project_slug": project_slug,
        "dataset_repo_id": repo_id,
        "index": {
            "total_detections": int(total_detections),
            "total_audio_files": int(total_audio_files),
            "shard_size": INDEX_SHARD_SIZE,
            "shards": [],
        },
    }

    return manifest


def manifest_to_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")


def write_shards_from_csv_rows(rows: Iterable[dict[str, Any]], *, shard_size: int = INDEX_SHARD_SIZE) -> list[Path]:
    rows_iter = iter(rows)
    first_row = next(rows_iter, None)
    if first_row is None:
        return []

    out_paths: list[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="hf-dataset-uploader-shards-"))

    try:
        buffered_rows = [first_row]
        shard_index = 0
        while buffered_rows:
            remaining = shard_size - len(buffered_rows)
            if remaining > 0:
                buffered_rows.extend(islice(rows_iter, remaining))
            chunk = buffered_rows
            if _HAVE_PANDAS:
                df = pd.DataFrame.from_records(chunk)
                shard_name = f"shard-{shard_index:06d}.parquet"
                shard_path = tmpdir / shard_name
                df.to_parquet(shard_path, index=False)
            else:
                shard_name = f"shard-{shard_index:06d}.jsonl"
                shard_path = tmpdir / shard_name
                with shard_path.open("w", encoding="utf-8") as fh:
                    for r in chunk:
                        fh.write(json.dumps(r, ensure_ascii=True) + "\n")

            out_paths.append(shard_path)
            shard_index += 1
            buffered_rows = list(islice(rows_iter, shard_size))

        return out_paths
    except Exception:
        try:
            for p in tmpdir.iterdir():
                p.unlink()
            tmpdir.rmdir()
        except Exception:
            pass
        raise
