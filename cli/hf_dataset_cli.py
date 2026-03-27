import argparse
import hashlib
import json
import math
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download


SCHEMA_VERSION = "1.0.0"
REQUIRED_PROJECT_PREFIXES = (
    "audio/",
    "index/",
    "index/shards/",
    "validations/",
    "audit/",
)
REQUIRED_PLACEHOLDER_FILES = (
    "audio/.gitkeep",
    "index/.gitkeep",
    "index/shards/.gitkeep",
    "validations/.gitkeep",
    "audit/.gitkeep",
)
REQUIRED_DETECTIONS_COLUMNS = (
    "detection_key",
    "audio_id",
    "scientific_name",
    "confidence",
    "start_time",
    "end_time",
)
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
REQUIRED_BIRDNET_COLUMNS = (
    "source_file",
    "scientific_name",
    "confidence",
    "start_time",
    "end_time",
)
SEGMENT_FILENAME_PATTERN = re.compile(
    r"^(?P<source_stem>.+)_(?P<start>\d+(?:\.\d+)?)-(?P<end>\d+(?:\.\d+)?)s_(?P<confidence_pct>\d+)%$"
)


@dataclass(slots=True)
class ShardMetadata:
    path: str
    rows: int
    sha256: str
    size_bytes: int


@dataclass(slots=True)
class SegmentFileRecord:
    scientific_name: str
    source_stem: str
    start_time: float
    end_time: float
    confidence_pct: int
    absolute_path: Path
    relative_path: str


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _upload_text(api: HfApi, dataset_repo: str, path_in_repo: str, content: str) -> None:
    api.upload_file(
        path_or_fileobj=BytesIO(content.encode("utf-8")),
        path_in_repo=path_in_repo,
        repo_id=dataset_repo,
        repo_type="dataset",
    )


def _upload_empty_file(api: HfApi, dataset_repo: str, path_in_repo: str) -> None:
    api.upload_file(
        path_or_fileobj=BytesIO(b""),
        path_in_repo=path_in_repo,
        repo_id=dataset_repo,
        repo_type="dataset",
    )


def ensure_project_dataset_structure(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    create_private_repo: bool,
) -> dict[str, Any]:
    api.create_repo(
        repo_id=dataset_repo,
        repo_type="dataset",
        private=create_private_repo,
        exist_ok=True,
    )

    files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))
    created_paths: list[str] = []

    for placeholder in REQUIRED_PLACEHOLDER_FILES:
        if placeholder not in files:
            _upload_empty_file(api=api, dataset_repo=dataset_repo, path_in_repo=placeholder)
            created_paths.append(placeholder)

    manifest_path = "manifest.json"
    if manifest_path not in files:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_slug": project_slug,
            "dataset_repo_id": dataset_repo,
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
            "index": {
                "total_detections": 0,
                "total_audio_files": 0,
                "shard_size": 0,
                "shards": [],
            },
        }
        _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo=manifest_path, content=json.dumps(manifest, indent=2))
        created_paths.append(manifest_path)

    return {
        "dataset_repo": dataset_repo,
        "project_slug": project_slug,
        "created_paths": created_paths,
    }


def load_detections_table(detections_file: str) -> pd.DataFrame:
    input_path = Path(detections_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Detections file not found: {detections_file}")

    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(input_path)
    elif suffix in {".jsonl", ".ndjson"}:
        frame = pd.read_json(input_path, lines=True)
    elif suffix == ".parquet":
        frame = pd.read_parquet(input_path)
    else:
        raise ValueError("Unsupported detections format. Use .csv, .jsonl/.ndjson, or .parquet")

    missing_columns = [col for col in REQUIRED_DETECTIONS_COLUMNS if col not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    if frame.empty:
        return frame

    deduped = frame.drop_duplicates(subset=["detection_key"], keep="last")
    return deduped.sort_values(by=["detection_key"]).reset_index(drop=True)


def load_birdnet_detections_csv(detections_csv: str) -> pd.DataFrame:
    input_path = Path(detections_csv)
    if not input_path.exists():
        raise FileNotFoundError(f"Detections CSV not found: {detections_csv}")

    frame = pd.read_csv(input_path)
    missing_columns = [col for col in REQUIRED_BIRDNET_COLUMNS if col not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required BirdNET columns: {', '.join(missing_columns)}")

    if frame.empty:
        return frame

    normalized = frame.copy()
    normalized["source_file"] = normalized["source_file"].astype(str).str.strip()
    normalized["source_stem"] = normalized["source_file"].apply(lambda value: Path(value).stem)
    normalized["scientific_name"] = normalized["scientific_name"].astype(str).str.strip()
    normalized["species_key"] = normalized["scientific_name"].str.casefold()
    normalized["start_time"] = pd.to_numeric(normalized["start_time"], errors="coerce")
    normalized["end_time"] = pd.to_numeric(normalized["end_time"], errors="coerce")
    normalized["confidence"] = pd.to_numeric(normalized["confidence"], errors="coerce")

    normalized = normalized.dropna(subset=["start_time", "end_time"]).reset_index(drop=True)
    return normalized


def _build_detection_key(project_slug: str, source_file: str, scientific_name: str, start_time: float, end_time: float) -> str:
    payload = f"{project_slug}|{source_file}|{scientific_name}|{start_time:.3f}|{end_time:.3f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def parse_segment_filename(file_name: str) -> tuple[str, float, float, int] | None:
    stem = Path(file_name).stem
    match = SEGMENT_FILENAME_PATTERN.match(stem)
    if not match:
        return None

    source_stem = match.group("source_stem")
    start_time = float(match.group("start"))
    end_time = float(match.group("end"))
    confidence_pct = int(match.group("confidence_pct"))
    return source_stem, start_time, end_time, confidence_pct


def discover_segment_records(segments_root: str) -> list[SegmentFileRecord]:
    root = Path(segments_root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Segments root not found: {segments_root}")

    records: list[SegmentFileRecord] = []
    for absolute_path in root.rglob("*"):
        if not absolute_path.is_file():
            continue
        if absolute_path.suffix.lower() != ".wav":
            continue

        rel = absolute_path.relative_to(root)
        scientific_name = rel.parts[0] if rel.parts else ""
        parsed = parse_segment_filename(absolute_path.name)
        if not parsed:
            continue
        source_stem, start_time, end_time, confidence_pct = parsed
        records.append(
            SegmentFileRecord(
                scientific_name=scientific_name,
                source_stem=source_stem,
                start_time=start_time,
                end_time=end_time,
                confidence_pct=confidence_pct,
                absolute_path=absolute_path,
                relative_path=rel.as_posix(),
            )
        )

    return records


def _match_birdnet_rows(project_slug: str, detections_csv: str, segments_root: str) -> dict[str, Any]:
    frame = load_birdnet_detections_csv(detections_csv=detections_csv)
    segment_records = discover_segment_records(segments_root=segments_root)

    by_species: dict[str, list[SegmentFileRecord]] = {}
    for record in segment_records:
        by_species.setdefault(record.scientific_name.casefold(), []).append(record)

    matched_rows: list[dict[str, Any]] = []
    unmatched_rows: list[dict[str, Any]] = []
    ambiguous_rows: list[dict[str, Any]] = []

    for row in frame.to_dict(orient="records"):
        species_key = str(row.get("species_key", "")).casefold()
        source_stem = str(row.get("source_stem", "")).strip()
        start_time = float(row["start_time"])
        end_time = float(row["end_time"])
        confidence = float(row["confidence"]) if pd.notna(row.get("confidence")) else 0.0

        species_candidates = by_species.get(species_key, [])
        exact_matches = [
            record
            for record in species_candidates
            if record.source_stem == source_stem
            and abs(record.start_time - start_time) < 1e-6
            and abs(record.end_time - end_time) < 1e-6
        ]

        if not exact_matches:
            unmatched_rows.append(
                {
                    "source_file": row.get("source_file", ""),
                    "scientific_name": row.get("scientific_name", ""),
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
            continue

        selected = exact_matches[0]
        if len(exact_matches) > 1:
            expected_pct = int(round(confidence * 100))
            exact_matches = sorted(exact_matches, key=lambda item: abs(item.confidence_pct - expected_pct))
            selected = exact_matches[0]
            ambiguous_rows.append(
                {
                    "source_file": row.get("source_file", ""),
                    "scientific_name": row.get("scientific_name", ""),
                    "start_time": start_time,
                    "end_time": end_time,
                    "candidates": len(exact_matches),
                }
            )

        matched_rows.append(
            {
                "project_slug": project_slug,
                "detection_key": _build_detection_key(
                    project_slug=project_slug,
                    source_file=str(row.get("source_file", "")),
                    scientific_name=str(row.get("scientific_name", "")),
                    start_time=start_time,
                    end_time=end_time,
                ),
                "audio_id": source_stem,
                "segment_filename": selected.absolute_path.name,
                "segment_relpath": selected.relative_path,
                "scientific_name": row.get("scientific_name", ""),
                "common_name": row.get("common_name", ""),
                "confidence": confidence,
                "start_time": start_time,
                "end_time": end_time,
                "exact_start": row.get("exact_start", start_time),
                "exact_end": row.get("exact_end", end_time),
                "locality": row.get("locality", ""),
                "point": row.get("point", ""),
                "date_folder": row.get("date_folder", ""),
                "min_freq": row.get("min_freq", None),
                "max_freq": row.get("max_freq", None),
                "box_source": row.get("box_source", ""),
                "label": row.get("label", ""),
                "source_file": row.get("source_file", ""),
                "schema_version": SCHEMA_VERSION,
                "ingested_at": _utcnow_iso(),
            }
        )

    return {
        "frame": frame,
        "segment_records_total": len(segment_records),
        "matched_rows": matched_rows,
        "unmatched_rows": unmatched_rows,
        "ambiguous_rows": ambiguous_rows,
    }


def run_ingest_segments_dry_run(project_slug: str, detections_csv: str, segments_root: str) -> dict[str, Any]:
    match_result = _match_birdnet_rows(
        project_slug=project_slug,
        detections_csv=detections_csv,
        segments_root=segments_root,
    )
    frame = match_result["frame"]
    matched_rows = match_result["matched_rows"]
    unmatched_rows = match_result["unmatched_rows"]
    ambiguous_rows = match_result["ambiguous_rows"]

    unique_audio = {row["audio_id"] for row in matched_rows}
    result = {
        "mode": "dry-run",
        "project_slug": project_slug,
        "detections_csv": detections_csv,
        "segments_root": segments_root,
        "csv_rows_total": int(len(frame)),
        "segments_found_total": int(match_result["segment_records_total"]),
        "matched_rows": len(matched_rows),
        "unmatched_rows": len(unmatched_rows),
        "ambiguous_rows": len(ambiguous_rows),
        "unique_audio_ids": len(unique_audio),
        "sample_unmatched": unmatched_rows[:20],
        "sample_ambiguous": ambiguous_rows[:20],
    }
    return result


def _file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_shards_in_directory(frame: pd.DataFrame, output_dir: Path, shard_size: int) -> list[ShardMetadata]:
    if shard_size <= 0:
        raise ValueError("shard_size must be greater than zero")

    output_dir.mkdir(parents=True, exist_ok=True)
    shards: list[ShardMetadata] = []

    if frame.empty:
        return shards

    total_rows = len(frame)
    total_shards = math.ceil(total_rows / shard_size)

    for index in range(total_shards):
        start = index * shard_size
        end = min(start + shard_size, total_rows)
        shard_frame = frame.iloc[start:end]
        shard_filename = f"shard-{index:05d}.parquet"
        local_path = output_dir / shard_filename
        shard_frame.to_parquet(local_path, index=False)

        shards.append(
            ShardMetadata(
                path=f"index/shards/{shard_filename}",
                rows=len(shard_frame),
                sha256=_file_sha256(local_path),
                size_bytes=local_path.stat().st_size,
            )
        )

    return shards


def build_manifest_payload(
    project_slug: str,
    dataset_repo: str,
    frame: pd.DataFrame,
    shard_size: int,
    shard_metadata: list[ShardMetadata],
) -> dict[str, Any]:
    now = _utcnow_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_slug": project_slug,
        "dataset_repo_id": dataset_repo,
        "updated_at": now,
        "index": {
            "total_detections": len(frame),
            "total_audio_files": int(frame["audio_id"].nunique()) if not frame.empty else 0,
            "shard_size": shard_size,
            "shards": [asdict(item) for item in shard_metadata],
        },
    }


def discover_audio_files(local_audio_dir: str) -> list[Path]:
    audio_root = Path(local_audio_dir)
    if not audio_root.exists() or not audio_root.is_dir():
        raise FileNotFoundError(f"Audio directory not found: {local_audio_dir}")

    files = [
        path
        for path in audio_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]
    return sorted(files)


def _chunk_items(items: list[Any], chunk_size: int) -> list[list[Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _load_resume_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {"uploaded": [], "failed": []}

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    uploaded = payload.get("uploaded", [])
    failed = payload.get("failed", [])
    return {
        "uploaded": uploaded if isinstance(uploaded, list) else [],
        "failed": failed if isinstance(failed, list) else [],
    }


def _save_resume_state(state_file: Path, uploaded: set[str], failed: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utcnow_iso(),
        "uploaded": sorted(uploaded),
        "failed": sorted(failed),
    }
    state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _upload_audio_with_retry(
    api: HfApi,
    dataset_repo: str,
    local_path: Path,
    path_in_repo: str,
    max_retries: int,
    retry_backoff_seconds: float,
) -> None:
    attempts = 0
    while True:
        attempts += 1
        try:
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=path_in_repo,
                repo_id=dataset_repo,
                repo_type="dataset",
            )
            return
        except Exception:
            if attempts > max_retries:
                raise
            time.sleep(retry_backoff_seconds * attempts)


def ingest_segments_to_hf(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    detections_csv: str,
    segments_root: str,
    batch_size: int,
    shard_size: int,
    max_retries: int,
    retry_backoff_seconds: float,
    resume_state_file: str,
) -> dict[str, Any]:
    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    match_result = _match_birdnet_rows(
        project_slug=project_slug,
        detections_csv=detections_csv,
        segments_root=segments_root,
    )
    frame = match_result["frame"]
    matched_rows = match_result["matched_rows"]
    unmatched_rows = match_result["unmatched_rows"]
    ambiguous_rows = match_result["ambiguous_rows"]

    # Deduplicate by remote path so retries/resume work on a stable key.
    path_to_local: dict[str, Path] = {}
    for row in matched_rows:
        repo_path = f"audio/segments/{row['segment_relpath']}"
        if repo_path in path_to_local:
            continue
        path_to_local[repo_path] = Path(segments_root) / row["segment_relpath"]

    state_path = Path(resume_state_file)
    state_payload = _load_resume_state(state_file=state_path)
    uploaded_state = set(str(item) for item in state_payload["uploaded"])
    failed_state = set(str(item) for item in state_payload["failed"])

    remote_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))

    pending: list[tuple[Path, str]] = []
    skipped_existing = 0
    for repo_path, local_path in path_to_local.items():
        if repo_path in remote_files:
            uploaded_state.add(repo_path)
            skipped_existing += 1
            continue
        if repo_path in uploaded_state:
            continue
        pending.append((local_path, repo_path))

    uploaded_now: set[str] = set()
    failed_now: set[str] = set()

    for batch_index, batch in enumerate(_chunk_items(pending, batch_size), start=1):
        batch_uploaded = 0
        batch_failed = 0
        for local_path, repo_path in batch:
            try:
                _upload_audio_with_retry(
                    api=api,
                    dataset_repo=dataset_repo,
                    local_path=local_path,
                    path_in_repo=repo_path,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                uploaded_state.add(repo_path)
                failed_state.discard(repo_path)
                uploaded_now.add(repo_path)
                batch_uploaded += 1
            except Exception:
                failed_state.add(repo_path)
                failed_now.add(repo_path)
                batch_failed += 1

        print(
            json.dumps(
                {
                    "event": "ingest-segments-audio-batch",
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "uploaded": batch_uploaded,
                    "failed": batch_failed,
                }
            )
        )
        _save_resume_state(state_file=state_path, uploaded=uploaded_state, failed=failed_state)

    index_frame = pd.DataFrame(matched_rows)
    if not index_frame.empty:
        index_frame["segment_path_in_repo"] = index_frame["segment_relpath"].apply(lambda value: f"audio/segments/{value}")

    with tempfile.TemporaryDirectory(prefix="birdnet-ingest-index-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        shard_dir = temp_dir / "index" / "shards"
        shard_metadata = build_shards_in_directory(frame=index_frame, output_dir=shard_dir, shard_size=shard_size)

        for item in shard_metadata:
            local_path = temp_dir / item.path
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=item.path,
                repo_id=dataset_repo,
                repo_type="dataset",
            )

    manifest = build_manifest_payload(
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        frame=index_frame,
        shard_size=shard_size,
        shard_metadata=shard_metadata,
    )
    _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo="manifest.json", content=json.dumps(manifest, indent=2))

    run_report = {
        "mode": "execute",
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "detections_csv": detections_csv,
        "segments_root": segments_root,
        "csv_rows_total": int(len(frame)),
        "segments_found_total": int(match_result["segment_records_total"]),
        "matched_rows": len(matched_rows),
        "unmatched_rows": len(unmatched_rows),
        "ambiguous_rows": len(ambiguous_rows),
        "unique_audio_ids": int(index_frame["audio_id"].nunique()) if not index_frame.empty else 0,
        "pending_audio_uploads": len(pending),
        "uploaded_audio_now": len(uploaded_now),
        "uploaded_audio_skipped_existing": skipped_existing,
        "failed_uploads": len(failed_now),
        "resume_state_file": str(state_path),
        "index_rows_written": len(index_frame),
        "shards_written": len(shard_metadata),
        "sample_unmatched": unmatched_rows[:20],
        "sample_ambiguous": ambiguous_rows[:20],
    }

    audit_path = f"audit/ingestion-runs/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo=audit_path, content=json.dumps(run_report, indent=2))
    return run_report


def sync_audio_batches(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    local_audio_dir: str,
    batch_size: int,
    max_retries: int,
    retry_backoff_seconds: float,
    resume_state_file: str,
) -> dict[str, Any]:
    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    all_files = discover_audio_files(local_audio_dir=local_audio_dir)
    state_path = Path(resume_state_file)
    state_payload = _load_resume_state(state_file=state_path)
    uploaded_state = set(str(item) for item in state_payload["uploaded"])

    remote_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))

    pending: list[tuple[Path, str]] = []
    for path in all_files:
        rel = path.relative_to(Path(local_audio_dir)).as_posix()
        repo_path = f"audio/{rel}"

        if repo_path in remote_files:
            uploaded_state.add(repo_path)
            continue

        if repo_path in uploaded_state:
            continue

        pending.append((path, repo_path))

    pending_paths = [item[0] for item in pending]
    by_local_to_repo = {local: repo for local, repo in pending}
    batches = _chunk_items(pending_paths, batch_size) if pending_paths else []

    uploaded_now: set[str] = set()
    failed: set[str] = set()

    for batch_index, batch in enumerate(batches, start=1):
        batch_uploaded = 0
        batch_failed = 0

        for local_path in batch:
            repo_path = by_local_to_repo[local_path]
            try:
                _upload_audio_with_retry(
                    api=api,
                    dataset_repo=dataset_repo,
                    local_path=local_path,
                    path_in_repo=repo_path,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                uploaded_now.add(repo_path)
                uploaded_state.add(repo_path)
                batch_uploaded += 1
            except Exception:
                failed.add(repo_path)
                batch_failed += 1

        print(
            json.dumps(
                {
                    "event": "sync-audio-batch",
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "uploaded": batch_uploaded,
                    "failed": batch_failed,
                }
            )
        )
        _save_resume_state(state_file=state_path, uploaded=uploaded_state, failed=failed)

    return {
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "total_local_audio_files": len(all_files),
        "pending_uploads": len(pending),
        "uploaded_now": len(uploaded_now),
        "failed": len(failed),
        "resume_state_file": str(state_path),
    }


def build_and_upload_index(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    detections_file: str,
    shard_size: int,
) -> dict[str, Any]:
    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    frame = load_detections_table(detections_file=detections_file)

    with tempfile.TemporaryDirectory(prefix="birdnet-index-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        shard_dir = temp_dir / "index" / "shards"
        metadata = build_shards_in_directory(frame=frame, output_dir=shard_dir, shard_size=shard_size)

        for item in metadata:
            local_path = temp_dir / item.path
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=item.path,
                repo_id=dataset_repo,
                repo_type="dataset",
            )

    manifest = build_manifest_payload(
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        frame=frame,
        shard_size=shard_size,
        shard_metadata=metadata,
    )
    _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo="manifest.json", content=json.dumps(manifest, indent=2))

    return {
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "total_detections": manifest["index"]["total_detections"],
        "total_audio_files": manifest["index"]["total_audio_files"],
        "total_shards": len(metadata),
    }


def collect_verify_errors(repo_files: set[str], manifest_payload: dict[str, Any], project_slug: str) -> list[str]:
    errors: list[str] = []

    for prefix in REQUIRED_PROJECT_PREFIXES:
        if not any(path.startswith(prefix) for path in repo_files):
            errors.append(f"Missing prefix in dataset repo: {prefix}")

    if manifest_payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Unexpected schema_version in manifest: {manifest_payload.get('schema_version')} (expected {SCHEMA_VERSION})"
        )

    if manifest_payload.get("project_slug") != project_slug:
        errors.append(
            f"Manifest project_slug mismatch: {manifest_payload.get('project_slug')} (expected {project_slug})"
        )

    index_section = manifest_payload.get("index", {})
    shards = index_section.get("shards", [])
    if not isinstance(shards, list):
        errors.append("Manifest index.shards must be a list")
        return errors

    for shard in shards:
        shard_path = shard.get("path")
        if not shard_path or not isinstance(shard_path, str):
            errors.append("Shard entry missing path")
            continue
        if shard_path not in repo_files:
            errors.append(f"Shard referenced in manifest not found in repo: {shard_path}")

    return errors


def upload_segments_to_hf(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    segments_root: str,
    batch_size: int = 50,
    max_retries: int = 3,
    retry_backoff_seconds: float = 1.0,
    should_pause: Callable[[], bool] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Upload local segments folder to dataset repo maintaining directory structure."""
    segments_path = Path(segments_root)
    if not segments_path.exists() or not segments_path.is_dir():
        raise FileNotFoundError(f"Segments root not found: {segments_root}")

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    all_audio_files: list[Path] = []
    for ext in SUPPORTED_AUDIO_EXTENSIONS:
        all_audio_files.extend(segments_path.rglob(f"*{ext}"))
    all_audio_files = sorted(all_audio_files)

    remote_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))
    pending: list[tuple[Path, str]] = []
    skipped_existing = 0
    for local_file in all_audio_files:
        relative_path = local_file.relative_to(segments_path)
        repo_path = f"audio/{project_slug}/{relative_path.as_posix()}"
        if repo_path in remote_files:
            skipped_existing += 1
            continue
        pending.append((local_file, repo_path))

    if not all_audio_files:
        return {
            "project_slug": project_slug,
            "dataset_repo": dataset_repo,
            "mode": "upload-segments-only",
            "total_files": 0,
            "uploaded": 0,
            "skipped_existing": 0,
            "failed": 0,
            "cancelled": False,
        }

    uploaded_count = 0
    failed_count = 0
    cancelled = False
    failed_files: list[str] = []

    batches = _chunk_items(pending, batch_size) if pending else []
    total_pending = len(pending)
    if progress_callback:
        progress_callback(
            {
                "event": "upload-start",
                "total_files": len(all_audio_files),
                "pending": total_pending,
                "skipped_existing": skipped_existing,
            }
        )

    for batch_idx, batch in enumerate(batches, start=1):
        for local_file, repo_path in batch:
            if should_cancel and should_cancel():
                cancelled = True
                break

            while should_pause and should_pause():
                time.sleep(0.5)
                if should_cancel and should_cancel():
                    cancelled = True
                    break

            if cancelled:
                break

            relative_path = local_file.relative_to(segments_path)

            try:
                _upload_audio_with_retry(
                    api=api,
                    dataset_repo=dataset_repo,
                    local_path=local_file,
                    path_in_repo=repo_path,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                uploaded_count += 1
            except Exception as exc:
                failed_count += 1
                failed_files.append(f"{relative_path.as_posix()}: {exc}")

            if progress_callback:
                progress_callback(
                    {
                        "event": "upload-progress",
                        "uploaded": uploaded_count,
                        "failed": failed_count,
                        "skipped_existing": skipped_existing,
                        "processed_pending": uploaded_count + failed_count,
                        "pending_total": total_pending,
                    }
                )

        if cancelled:
            break

        print(
            json.dumps(
                {
                    "event": "upload-batch",
                    "batch": batch_idx,
                    "total_batches": len(batches),
                    "uploaded_so_far": uploaded_count,
                    "failed_so_far": failed_count,
                    "skipped_existing": skipped_existing,
                }
            )
        )

    if progress_callback:
        progress_callback(
            {
                "event": "upload-complete",
                "uploaded": uploaded_count,
                "failed": failed_count,
                "skipped_existing": skipped_existing,
                "cancelled": cancelled,
            }
        )

    return {
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "mode": "upload-segments-only",
        "total_files": len(all_audio_files),
        "pending_files": total_pending,
        "uploaded": uploaded_count,
        "skipped_existing": skipped_existing,
        "failed": failed_count,
        "cancelled": cancelled,
        "failed_samples": failed_files[:10],
    }


def verify_project(api: HfApi, project_slug: str, dataset_repo: str) -> dict[str, Any]:
    repo_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))
    if "manifest.json" not in repo_files:
        return {
            "ok": False,
            "errors": ["manifest.json not found in dataset repository"],
        }

    manifest_local = hf_hub_download(
        repo_id=dataset_repo,
        repo_type="dataset",
        filename="manifest.json",
    )
    manifest_payload = json.loads(Path(manifest_local).read_text(encoding="utf-8"))
    errors = collect_verify_errors(repo_files=repo_files, manifest_payload=manifest_payload, project_slug=project_slug)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "total_files": len(repo_files),
        "total_shards": len(manifest_payload.get("index", {}).get("shards", [])),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HF dataset project CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create_project = sub.add_parser("create-project", help="Create project scaffold in HF dataset")
    create_project.add_argument("--project-slug", required=True)
    create_project.add_argument("--dataset-repo", required=True)
    create_project.add_argument("--private", action="store_true", help="Create private dataset repository when absent")

    build_index = sub.add_parser("build-index", help="Build and upload initial detection index")
    build_index.add_argument("--project-slug", required=True)
    build_index.add_argument("--dataset-repo", required=True)
    build_index.add_argument("--detections-file", required=True)
    build_index.add_argument("--shard-size", type=int, default=10000)

    sync_audio = sub.add_parser("sync-audio", help="Upload local audio files in resumable batches")
    sync_audio.add_argument("--project-slug", required=True)
    sync_audio.add_argument("--dataset-repo", required=True)
    sync_audio.add_argument("--local-audio-dir", required=True)
    sync_audio.add_argument("--batch-size", type=int, default=100)
    sync_audio.add_argument("--max-retries", type=int, default=3)
    sync_audio.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    sync_audio.add_argument("--resume-state-file", default=".sync-audio-state.json")

    verify_project = sub.add_parser("verify-project", help="Verify project integrity")
    verify_project.add_argument("--project-slug", required=True)
    verify_project.add_argument("--dataset-repo", required=True)

    ingest_segments = sub.add_parser("ingest-segments", help="Match BirdNET CSV rows with segment files")
    ingest_segments.add_argument("--project-slug", required=True)
    ingest_segments.add_argument("--dataset-repo", required=True)
    ingest_segments.add_argument("--detections-csv", required=True)
    ingest_segments.add_argument("--segments-root", required=True)
    ingest_segments.add_argument("--batch-size", type=int, default=200)
    ingest_segments.add_argument("--shard-size", type=int, default=10000)
    ingest_segments.add_argument("--max-retries", type=int, default=3)
    ingest_segments.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    ingest_segments.add_argument("--resume-state-file", default=".ingest-segments-state.json")
    ingest_segments.add_argument("--dry-run", action="store_true")
    ingest_segments.add_argument("--report-file", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    api = HfApi()

    if args.command == "create-project":
        result = ensure_project_dataset_structure(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            create_private_repo=bool(args.private),
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "build-index":
        result = build_and_upload_index(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            detections_file=args.detections_file,
            shard_size=args.shard_size,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "sync-audio":
        result = sync_audio_batches(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            local_audio_dir=args.local_audio_dir,
            batch_size=args.batch_size,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            resume_state_file=args.resume_state_file,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["failed"] == 0 else 1

    if args.command == "verify-project":
        result = verify_project(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "ingest-segments":
        if args.dry_run:
            result = run_ingest_segments_dry_run(
                project_slug=args.project_slug,
                detections_csv=args.detections_csv,
                segments_root=args.segments_root,
            )
        else:
            result = ingest_segments_to_hf(
                api=api,
                project_slug=args.project_slug,
                dataset_repo=args.dataset_repo,
                detections_csv=args.detections_csv,
                segments_root=args.segments_root,
                batch_size=args.batch_size,
                shard_size=args.shard_size,
                max_retries=args.max_retries,
                retry_backoff_seconds=args.retry_backoff_seconds,
                resume_state_file=args.resume_state_file,
            )

        if args.report_file:
            Path(args.report_file).write_text(json.dumps(result, indent=2), encoding="utf-8")

        print(json.dumps(result, indent=2))
        return 0 if result.get("failed_uploads", 0) == 0 else 1

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
