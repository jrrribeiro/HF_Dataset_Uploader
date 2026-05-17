from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .config import SCHEMA_VERSION, INDEX_SHARD_SIZE
import tempfile
import os
import json
from pathlib import Path
from typing import List

try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    _HAVE_PANDAS = False


def _project_from_repo(repo_id: str) -> str:
    return repo_id.split("/", 1)[1]


def build_manifest_from_scan(repo_id: str, scan_summary: dict[str, Any], *, csv_rows: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    project_slug = _project_from_repo(repo_id)
    total_files = int(scan_summary.get("total_files", 0))
    total_size = int(scan_summary.get("total_size", 0))

    total_detections = 0
    total_audio_files = total_files
    shards: list[str] = []

    if csv_rows is not None:
        rows = list(csv_rows)
        total_detections = len(rows)
        unique_files = {str(r.get("audio_file") or r.get("file") or "") for r in rows}
        unique_files = {p for p in unique_files if p}
        if unique_files:
            total_audio_files = len(unique_files)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "project_slug": project_slug,
        "dataset_repo_id": repo_id,
        "index": {
            "total_detections": int(total_detections),
            "total_audio_files": int(total_audio_files),
            "shard_size": INDEX_SHARD_SIZE,
            "shards": shards,
        },
    }

    return manifest


def manifest_to_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")


def write_shards_from_csv_rows(rows: Iterable[dict[str, Any]], *, shard_size: int = INDEX_SHARD_SIZE) -> List[Path]:
    rows_list = list(rows)
    if not rows_list:
        return []

    out_paths: List[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="hf-dataset-uploader-shards-"))

    try:
        for i in range(0, len(rows_list), shard_size):
            chunk = rows_list[i : i + shard_size]
            shard_index = i // shard_size
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

        return out_paths
    except Exception:
        try:
            for p in tmpdir.iterdir():
                p.unlink()
            tmpdir.rmdir()
        except Exception:
            pass
        raise
