from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, List

from .config import SCHEMA_VERSION, INDEX_SHARD_SIZE


def build_manifest_from_scan(scan: dict[str, Any], repo_id: str | None = None) -> dict[str, Any]:
    project_slug = None
    if repo_id and "/" in repo_id:
        project_slug = repo_id.split("/", 1)[1]

    return {
        "schema_version": SCHEMA_VERSION,
        "project_slug": project_slug or "unknown",
        "dataset_repo_id": repo_id,
        "index": {
            "total_detections": 0,
            "total_audio_files": scan.get("total_files", 0),
            "shard_size": INDEX_SHARD_SIZE,
            "shards": [],
        },
    }


def manifest_to_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")


def write_shards_from_csv_rows(rows: Iterable[dict[str, Any]], out_dir: Path) -> List[Path]:
    """Write simple JSONL shards from CSV rows. Returns list of shard paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shard_paths: List[Path] = []
    shard_index = 0
    batch: List[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= INDEX_SHARD_SIZE:
            path = out_dir / f"shard-{shard_index:04d}.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                for item in batch:
                    fh.write(json.dumps(item, ensure_ascii=True) + "\n")
            shard_paths.append(path)
            shard_index += 1
            batch = []

    if batch:
        path = out_dir / f"shard-{shard_index:04d}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for item in batch:
                fh.write(json.dumps(item, ensure_ascii=True) + "\n")
        shard_paths.append(path)

    return shard_paths
from src.uploader_cli.manifest import *
