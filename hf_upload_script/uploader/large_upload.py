from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import AUDIO_EXTENSIONS, SCHEMA_VERSION


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class LocalFileRecord:
    full_path: str
    original_relative_path: str
    logical_group: str
    filename: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class PlannedFile:
    full_path: str
    original_relative_path: str
    logical_group: str
    stored_path: str
    size: int
    mtime_ns: int
    status: str


def scan_local_inventory(
    folder_path: str | Path,
    *,
    audio_extensions: set[str] | None = None,
    on_progress: ProgressCallback | None = None,
    progress_every: int = 500,
) -> list[LocalFileRecord]:
    """Scan local audio files once and return a compact inventory."""
    root_path = Path(folder_path).resolve()
    extensions = audio_extensions or AUDIO_EXTENSIONS
    records: list[LocalFileRecord] = []
    scanned_entries = 0
    total_size = 0
    started_at = time.time()

    for current_root, _, files in os.walk(root_path):
        current_path = Path(current_root)
        for filename in files:
            scanned_entries += 1
            ext = Path(filename).suffix.lower()
            if ext not in extensions:
                if on_progress and scanned_entries % progress_every == 0:
                    on_progress({"phase": "scan", "files": len(records), "entries": scanned_entries, "bytes": total_size})
                continue

            full_path = current_path / filename
            stat = full_path.stat()
            relative_path = full_path.relative_to(root_path).as_posix()
            logical_group = _infer_logical_group(relative_path)
            records.append(
                LocalFileRecord(
                    full_path=str(full_path),
                    original_relative_path=relative_path,
                    logical_group=logical_group,
                    filename=filename,
                    size=int(stat.st_size),
                    mtime_ns=int(stat.st_mtime_ns),
                )
            )
            total_size += int(stat.st_size)

            if on_progress and len(records) % progress_every == 0:
                on_progress({"phase": "scan", "files": len(records), "entries": scanned_entries, "bytes": total_size})

    if on_progress:
        on_progress(
            {
                "phase": "scan",
                "files": len(records),
                "entries": scanned_entries,
                "bytes": total_size,
                "elapsed": time.time() - started_at,
                "done": True,
            }
        )
    return records


def load_remote_paths(
    api: Any,
    repo_id: str,
    *,
    repo_type: str = "dataset",
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
    on_progress: ProgressCallback | None = None,
) -> set[str]:
    """Load remote repository paths with a single Hub listing call."""
    started_at = time.time()
    last_exc: Exception | None = None
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        if on_progress:
            on_progress({"phase": "remote", "status": "listing", "attempt": attempt, "max_attempts": attempts})
        try:
            paths = set(str(path) for path in api.list_repo_files(repo_id=repo_id, repo_type=repo_type))
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            if on_progress:
                on_progress({"phase": "remote", "status": "retrying", "attempt": attempt, "error": str(exc)})
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    else:
        raise last_exc or RuntimeError("Could not list remote repository files")
    if on_progress:
        on_progress({"phase": "remote", "files": len(paths), "elapsed": time.time() - started_at, "done": True})
    return paths


def ensure_dataset_repo(
    api: Any,
    repo_id: str,
    *,
    private: bool = True,
    create_repo: bool = True,
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> dict[str, Any]:
    """Ensure a dataset repository exists and report whether this run created it."""
    attempts = max(1, int(max_attempts))
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            api.repo_info(repo_id=repo_id, repo_type="dataset", timeout=20)
            return {"repo_id": repo_id, "exists": True, "created": False}
        except Exception as exc:
            last_exc = exc
            if not _looks_like_missing_repo(exc):
                if attempt < attempts:
                    time.sleep(backoff_seconds * (2 ** (attempt - 1)))
                    continue
                if not create_repo:
                    raise
                break

            if not create_repo:
                raise RuntimeError(
                    f"Dataset repository does not exist: {repo_id}. "
                    "Rerun with repository creation enabled."
                ) from exc

            api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=False)
            return {"repo_id": repo_id, "exists": True, "created": True}

    if not create_repo:
        raise last_exc or RuntimeError(f"Could not access dataset repository: {repo_id}")

    api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
    return {"repo_id": repo_id, "exists": True, "created": False, "repo_info_error": str(last_exc or "")}


def build_upload_plan(
    records: Iterable[LocalFileRecord],
    remote_paths: set[str],
    *,
    remote_base: str = "audio",
    max_files_per_folder: int = 9000,
) -> list[PlannedFile]:
    """Create deterministic stored paths and skip records already present remotely."""
    if max_files_per_folder <= 0:
        raise ValueError("max_files_per_folder must be positive")

    remote_base = remote_base.strip("/")
    group_counts: dict[str, int] = {}
    planned: list[PlannedFile] = []

    for record in records:
        group_key = record.logical_group
        index = group_counts.get(group_key, 0)
        group_counts[group_key] = index + 1
        shard_index = index // max_files_per_folder
        stored_filename = _stored_filename(record.original_relative_path, record.filename)
        stored_parts = [
            part
            for part in (
                remote_base,
                _safe_path_part(record.logical_group),
                f"shard-{shard_index:06d}",
                stored_filename,
            )
            if part
        ]
        stored_path = "/".join(stored_parts)
        status = "skip" if stored_path in remote_paths else "upload"
        planned.append(
            PlannedFile(
                full_path=record.full_path,
                original_relative_path=record.original_relative_path,
                logical_group=record.logical_group,
                stored_path=stored_path,
                size=record.size,
                mtime_ns=record.mtime_ns,
                status=status,
            )
        )

    return planned


def materialize_staging_folder(
    plan: Iterable[PlannedFile],
    staging_dir: str | Path,
    *,
    csv_file: str | Path | None = None,
    repo_id: str,
    mode: str = "hardlink",
    on_progress: ProgressCallback | None = None,
    progress_every: int = 500,
) -> dict[str, Any]:
    """Build a local folder whose layout is ready for upload_large_folder."""
    staging_path = Path(staging_dir).resolve()
    staging_path.mkdir(parents=True, exist_ok=True)
    _clean_staging_payload(staging_path)
    index_dir = staging_path / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    upload_rows: list[dict[str, Any]] = []
    copied = 0
    linked = 0
    skipped = 0
    total_bytes = 0
    started_at = time.time()

    for item in plan:
        row = asdict(item)
        all_rows.append(row)
        if item.status != "upload":
            skipped += 1
            continue

        destination = staging_path / Path(item.stored_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _place_file(Path(item.full_path), destination, mode=mode)
        if mode == "copy":
            copied += 1
        else:
            linked += 1
        total_bytes += item.size
        upload_rows.append(row)

        if on_progress and len(upload_rows) % progress_every == 0:
            on_progress(
                {
                    "phase": "staging",
                    "files": len(upload_rows),
                    "bytes": total_bytes,
                    "total": len(all_rows),
                }
            )

    _write_index(index_dir / "files.parquet", all_rows)
    _write_jsonl(index_dir / "files.jsonl", all_rows)
    _write_json(index_dir / "upload_plan.json", upload_rows)
    _write_manifest(index_dir / "manifest.json", repo_id=repo_id, rows=all_rows)

    if csv_file:
        shutil.copy2(str(csv_file), index_dir / "detections.csv")

    summary = {
        "total_files": len(all_rows),
        "upload_files": len(upload_rows),
        "skipped_files": skipped,
        "upload_bytes": total_bytes,
        "linked_files": linked,
        "copied_files": copied,
        "staging_dir": str(staging_path),
        "elapsed": time.time() - started_at,
    }
    _write_json(index_dir / "staging_summary.json", summary)
    if on_progress:
        on_progress({"phase": "staging", **summary, "done": True})
    return summary


def upload_large_staging_folder(
    api: Any,
    *,
    repo_id: str,
    staging_dir: str | Path,
    workers: int | None = None,
    private: bool = True,
    print_report_every: int = 30,
    disable_file_progress: bool = True,
    quiet_hf_logs: bool = True,
) -> None:
    if not hasattr(api, "upload_large_folder"):
        raise RuntimeError(
            "This huggingface_hub version does not expose HfApi.upload_large_folder. "
            "Upgrade with: python -m pip install -U huggingface_hub hf_xet"
        )

    api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
    if disable_file_progress:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            from huggingface_hub.utils import disable_progress_bars

            disable_progress_bars()
        except Exception:
            pass
    if quiet_hf_logs:
        import logging

        logging.getLogger("huggingface_hub").setLevel(logging.CRITICAL)
    api.upload_large_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(Path(staging_dir).resolve()),
        num_workers=workers,
        print_report=True,
        print_report_every=print_report_every,
    )


def _infer_logical_group(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 2:
        return parts[0]
    if len(parts) == 1:
        return Path(parts[0]).stem.split("_")[0] or "unknown"
    return "unknown"


def _stored_filename(original_relative_path: str, filename: str) -> str:
    digest = hashlib.sha1(original_relative_path.encode("utf-8")).hexdigest()[:12]
    path = Path(filename)
    return f"{_safe_path_part(path.stem)}__{digest}{path.suffix.lower()}"


def _safe_path_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "unknown"


def _place_file(source: Path, destination: Path, *, mode: str) -> None:
    if destination.exists():
        return
    if mode == "copy":
        shutil.copy2(source, destination)
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _clean_staging_payload(staging_path: Path) -> None:
    protected = {".cache"}
    anchor_parts = {part.lower() for part in staging_path.parts}
    allowed_anchor = bool(anchor_parts.intersection({"hf-dataset-uploader", "hf_staging", "hf-staging"}))
    if not allowed_anchor and staging_path.name.lower() != "staging":
        raise RuntimeError(f"Refusing to clean unexpected staging path: {staging_path}")

    for child in staging_path.iterdir():
        if child.name in protected:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _looks_like_missing_repo(exc: Exception) -> bool:
    message = str(exc).lower()
    return "404" in message or "not found" in message or "repository not found" in message


def _write_index(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import pandas as pd  # type: ignore

        pd.DataFrame.from_records(rows).to_parquet(path, index=False)
    except Exception:
        _write_jsonl(path.with_suffix(".jsonl"), rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_manifest(path: Path, *, repo_id: str, rows: list[dict[str, Any]]) -> None:
    by_group: dict[str, int] = {}
    total_size = 0
    for row in rows:
        by_group[str(row["logical_group"])] = by_group.get(str(row["logical_group"]), 0) + 1
        total_size += int(row.get("size", 0))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_repo_id": repo_id,
        "index": {
            "total_audio_files": len(rows),
            "total_audio_bytes": total_size,
            "logical_groups": by_group,
            "files_index": "index/files.parquet",
            "files_index_fallback": "index/files.jsonl",
        },
    }
    _write_json(path, manifest)
