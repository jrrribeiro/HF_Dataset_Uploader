from __future__ import annotations

import csv
import os
import logging
import shutil
import tarfile
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from huggingface_hub import HfApi

from .batch_uploader import BatchUploader
from .deduplicator import Deduplicator
from .manifest import build_manifest_from_scan, manifest_to_bytes, summarize_csv_rows, write_shards_from_csv_rows
from .repo_service import RepositoryService
from .scanner import LocalScanner
from .session_manager import SessionManager
from .config import WEB_UI_MAX_SIZE_BYTES


class _CallbackLogHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]):
        super().__init__(level=logging.INFO)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self._callback(message)
        except Exception:
            pass


@contextmanager
def _capture_logs(log_callback: Callable[[str], None] | None):
    if log_callback is None:
        yield
        return

    handler = _CallbackLogHandler(log_callback)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    try:
        yield
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(previous_level)


def _is_archive(path: Path) -> bool:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    return suffixes[-1:] in ([".zip"], [".tar"], [".gz"]) or suffixes[-2:] == [".tar", ".gz"]


def _archive_extract_name(path: Path) -> str:
    if path.suffixes[-2:] == [".tar", ".gz"]:
        return path.name[:-7]
    if path.suffixes[-1:] == [".gz"] and path.name.endswith(".tgz"):
        return path.name[:-4]
    return path.stem


def _copy_file_to_staging(path: Path, staging_root: Path) -> Path:
    staged_dir = staging_root / path.stem
    staged_dir.mkdir(parents=True, exist_ok=True)
    target = staged_dir / path.name
    shutil.copy2(path, target)
    return staged_dir


def _scan_single_file(path: Path) -> dict[str, Any]:
    species = path.stem.split("_")[0] or "unknown"
    size = path.stat().st_size
    return {
        "total_files": 1,
        "total_size": size,
        "by_species": {
            species: [
                {
                    "name": path.name,
                    "full_path": str(path),
                    "relative_path": path.name,
                    "species": species,
                    "size": size,
                }
            ]
        },
    }


def _merge_scan_summaries(summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged_by_species: dict[str, list[dict[str, Any]]] = {}
    total_files = 0
    total_size = 0
    for summary in summaries:
        total_files += int(summary.get("total_files", 0))
        total_size += int(summary.get("total_size", 0))
        for species, items in summary.get("by_species", {}).items():
            merged_by_species.setdefault(species, []).extend(items)
    return {
        "total_files": total_files,
        "total_size": total_size,
        "by_species": merged_by_species,
    }


def perform_upload(
    token: str,
    repo_id: str,
    selected_paths: list[str] | None,
    csv_path: str | None,
    workers: int | None,
    *,
    progress_callback: Callable[[float, str], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Upload selected folders, files, or archives with live progress and log callbacks."""

    def _check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Upload cancelled")

    def _progress(value: float, message: str) -> None:
        if progress_callback:
            progress_callback(max(0.0, min(1.0, value)), message)

    if not token or not repo_id:
        raise ValueError("token and repo_id are required")

    paths = [Path(path).expanduser().resolve() for path in (selected_paths or [])]
    if not paths:
        raise ValueError("No files or folders selected")

    staging_root = Path(tempfile.mkdtemp(prefix="hf-dataset-uploader-native-"))
    try:
        with _capture_logs(log_callback):
            _progress(0.0, "Starting upload")
            logging.getLogger(__name__).info("Selected %d input item(s)", len(paths))

            expanded_roots: list[Path] = []
            single_file_summaries: list[dict[str, Any]] = []

            for index, source in enumerate(paths, start=1):
                _check_cancel()
                if source.is_dir():
                    expanded_roots.append(source)
                    logging.getLogger(__name__).info("Added folder: %s", source)
                    _progress(0.05 + (0.1 * index / len(paths)), f"Added folder {source.name}")
                    continue

                if not source.is_file():
                    raise ValueError(f"Path does not exist: {source}")

                if _is_archive(source):
                    archive_root = staging_root / _archive_extract_name(source)
                    archive_root.mkdir(parents=True, exist_ok=True)
                    logging.getLogger(__name__).info("Extracting archive: %s", source)
                    if source.suffix.lower() == ".zip":
                        with zipfile.ZipFile(source, "r") as zf:
                            zf.extractall(archive_root)
                    else:
                        with tarfile.open(source, "r:*") as tf:
                            tf.extractall(archive_root)
                    expanded_roots.append(archive_root)
                    _progress(0.05 + (0.1 * index / len(paths)), f"Extracted {source.name}")
                    continue

                staged_root = _copy_file_to_staging(source, staging_root)
                single_file_summaries.append(_scan_single_file(staged_root / source.name))
                logging.getLogger(__name__).info("Queued file: %s", source)
                _progress(0.05 + (0.1 * index / len(paths)), f"Queued file {source.name}")

            api = HfApi(token=token)
            repo_service = RepositoryService(token)
            _progress(0.15, "Validating repository")
            try:
                validation = repo_service.validate_repo(repo_id)
                if not validation.get("is_valid"):
                    repo_service.create_dataset(repo_id, private=True)
            except Exception:
                repo_service.create_dataset(repo_id, private=True)

            scanner = LocalScanner()
            scan_summaries: list[dict[str, Any]] = list(single_file_summaries)
            total_scan_roots = len(expanded_roots)

            for index, root in enumerate(expanded_roots, start=1):
                _check_cancel()

                def root_progress(local_fraction: float, message: str, *, root_name: str = root.name) -> None:
                    base = 0.20 + (0.20 * (index - 1) / max(total_scan_roots, 1))
                    span = 0.20 / max(total_scan_roots, 1)
                    _progress(base + (span * local_fraction), f"{root_name}: {message}")

                logging.getLogger(__name__).info("Scanning root %d/%d: %s", index, total_scan_roots, root)
                scan_summaries.append(
                    scanner.scan_folder(
                        str(root),
                        progress_callback=root_progress,
                        cancel_event=cancel_event,
                    )
                )

            _check_cancel()
            summary = _merge_scan_summaries(scan_summaries)
            _progress(0.45, f"Found {summary['total_files']} audio files")

            csv_stats = None
            if csv_path:
                _check_cancel()
                _progress(0.48, "Summarizing CSV")
                with open(csv_path, newline="", encoding="utf-8") as fh:
                    csv_stats = summarize_csv_rows(csv.DictReader(fh))

            _check_cancel()
            _progress(0.52, "Building manifest")
            manifest = build_manifest_from_scan(repo_id, summary, csv_stats=csv_stats)

            def _upload_with_retry(path_or_fileobj: Any, path_in_repo: str) -> None:
                max_attempts = int(os.getenv("BNU_HUB_UPLOAD_ATTEMPTS", "3"))
                timeout_s = float(os.getenv("BNU_HUB_UPLOAD_TIMEOUT", "90"))
                base_backoff = float(os.getenv("BNU_HUB_UPLOAD_BACKOFF", "1.0"))
                last_exc: Exception | None = None

                for attempt in range(1, max_attempts + 1):
                    try:
                        result: dict[str, Any] = {"exc": None}

                        def _target() -> None:
                            try:
                                connect_timeout = float(os.getenv("BNU_HUB_CONNECT_TIMEOUT", "8"))
                                read_timeout = float(os.getenv("BNU_HUB_READ_TIMEOUT", "30"))
                                try:
                                    api.upload_file(
                                        path_or_fileobj=path_or_fileobj,
                                        path_in_repo=path_in_repo,
                                        repo_id=repo_id,
                                        repo_type="dataset",
                                        timeout=(connect_timeout, read_timeout),
                                    )
                                except TypeError:
                                    api.upload_file(
                                        path_or_fileobj=path_or_fileobj,
                                        path_in_repo=path_in_repo,
                                        repo_id=repo_id,
                                        repo_type="dataset",
                                    )
                            except Exception as exc:  # pragma: no cover - network behavior
                                result["exc"] = exc

                        t = threading.Thread(target=_target, daemon=True)
                        t.start()
                        t.join(timeout_s)
                        if t.is_alive():
                            raise TimeoutError(f"upload_file timed out after {timeout_s}s")
                        if result["exc"] is not None:
                            raise result["exc"]
                        return
                    except Exception as exc:  # pragma: no cover - network behavior
                        last_exc = exc
                        if attempt >= max_attempts:
                            break
                        wait_s = base_backoff * (2 ** (attempt - 1))
                        logging.getLogger(__name__).info("upload_file failed for %s: %s. Retrying in %.1fs", path_in_repo, exc, wait_s)
                        time.sleep(wait_s)

                raise RuntimeError(f"Upload failed for {path_in_repo}: {last_exc}")

            _upload_with_retry(manifest_to_bytes(manifest), "index/manifest.json")

            if csv_path:
                _check_cancel()
                _progress(0.58, "Creating CSV shards")
                def _on_shard_generated(count: int) -> None:
                    _progress(0.58, f"Creating CSV shards ({count} ready)")

                with open(csv_path, newline="", encoding="utf-8") as fh:
                    shards = write_shards_from_csv_rows(
                        csv.DictReader(fh),
                        on_progress=_on_shard_generated,
                        cancel_event=cancel_event,
                    )
                total_shards = max(len(shards), 1)
                for idx, shard_path in enumerate(shards, start=1):
                    _check_cancel()
                    _progress(0.58 + (0.07 * (idx / total_shards)), f"Uploading shard {idx}/{total_shards}: {shard_path.name}")
                    _upload_with_retry(str(shard_path), f"index/shards/{shard_path.name}")

            _check_cancel()
            _progress(0.65, "Preparing uploads")
            dedup = Deduplicator(api=api, repo_id=repo_id)
            session = SessionManager()
            uploader = BatchUploader(api=api, repo_id=repo_id, deduplicator=dedup, session=session, max_workers=workers)

            file_infos: list[dict[str, Any]] = []
            for species_items in summary.get("by_species", {}).values():
                file_infos.extend(species_items)

            uploaded_total = 0
            skipped_total = 0
            failed_total = 0

            def on_progress(state: dict[str, Any]) -> None:
                nonlocal uploaded_total, skipped_total, failed_total
                uploaded_total = int(state.get("uploaded", uploaded_total))
                skipped_total = int(state.get("skipped", skipped_total))
                failed_total = int(state.get("failed", failed_total))
                completed = uploaded_total + skipped_total + failed_total
                total = max(len(file_infos), 1)
                _progress(
                    0.65 + (0.34 * completed / total),
                    f"Upload progress: uploaded {uploaded_total}, skipped {skipped_total}, failed {failed_total}",
                )

            _check_cancel()
            _progress(0.66, f"Uploading {len(file_infos)} audio file(s)")
            result = uploader.upload_files(
                file_infos,
                remote_base="audio",
                on_progress=on_progress,
                cancel_event=cancel_event,
                log_callback=log_callback,
            )

            _check_cancel()
            _progress(1.0, "Upload finished")
            result.setdefault("uploaded", uploaded_total)
            result.setdefault("skipped", skipped_total)
            result.setdefault("failed", failed_total)
            return result
    finally:
        try:
            shutil.rmtree(staging_root)
        except Exception:
            pass
