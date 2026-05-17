from __future__ import annotations

import time
import concurrent.futures
import os
import logging
import threading
from typing import List, Tuple, Any, TYPE_CHECKING
from pathlib import Path
from typing import Any, Callable, Iterable

if TYPE_CHECKING:
    from huggingface_hub import HfApi

from .config import MAX_BATCH_SIZE, RETRY_MAX_ATTEMPTS, RETRY_INITIAL_BACKOFF_SECONDS
from .deduplicator import Deduplicator
from .session_manager import SessionManager


logger = logging.getLogger("birdnet_uploader.batch_uploader")


class BatchUploader:
    """Orchestrate uploads with deduplication, retries and session checkpoints."""

    def __init__(
        self,
        api: Any,
        repo_id: str,
        deduplicator: Deduplicator,
        session: SessionManager | None = None,
        *,
        max_retries: int | None = None,
        initial_backoff: float | None = None,
        max_workers: int | None = None,
    ) -> None:
        self._api = api
        self.repo_id = repo_id
        self.deduplicator = deduplicator
        self.session = session or SessionManager.create_session()
        self.max_retries = max_retries or RETRY_MAX_ATTEMPTS
        self.initial_backoff = initial_backoff or RETRY_INITIAL_BACKOFF_SECONDS
        # If not provided, choose a reasonable parallelism level for IO-bound uploads
        if max_workers is None:
            cpu = os.cpu_count() or 1
            # Use more threads than CPUs since uploads are IO-bound; cap to 32
            self.max_workers = min(32, max(4, cpu * 4))
        else:
            self.max_workers = max_workers

        # Max seconds to wait for an upload_folder call before falling back
        self.folder_upload_timeout = float(os.getenv("BNU_FOLDER_UPLOAD_TIMEOUT", "20"))
        # Max seconds to wait for an individual upload_file call
        self.upload_file_timeout = float(os.getenv("BNU_UPLOAD_FILE_TIMEOUT", "90"))

    @staticmethod
    def _run_with_timeout(func: Callable[..., Any], timeout_s: float, *args: Any, **kwargs: Any) -> Any:
        result: dict[str, Any] = {"value": None, "exc": None}

        def _target() -> None:
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - network behavior
                result["exc"] = exc

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout_s)
        if t.is_alive():
            raise TimeoutError(f"Operation timed out after {timeout_s}s")
        if result["exc"] is not None:
            raise result["exc"]
        return result["value"]

    def _upload_file_with_retry(self, local_path: str | Path, remote_path: str) -> None:
        attempts = 0
        last_exc: Exception | None = None
        while attempts <= self.max_retries:
            try:
                logger.info("Starting upload_file: %s -> %s (attempt %d)", local_path, remote_path, attempts + 1)
                start = time.time()
                # Execute in daemon thread with real timeout (no blocking shutdown wait).
                self._run_with_timeout(
                    self._api.upload_file,
                    self.upload_file_timeout,
                    path_or_fileobj=str(local_path),
                    path_in_repo=remote_path,
                    repo_id=self.repo_id,
                    repo_type="dataset",
                )
                duration = time.time() - start
                logger.info("Finished upload_file: %s -> %s in %.2fs", local_path, remote_path, duration)
                return
            except Exception as exc:  # pragma: no cover - network behavior
                last_exc = exc
                attempts += 1
                logger.warning("upload_file failed for %s -> %s (attempt %d): %s", local_path, remote_path, attempts, exc)
                logger.debug("Exception repr: %r", exc)
                if attempts > self.max_retries:
                    logger.error("Giving up upload_file for %s after %d attempts", remote_path, attempts)
                    raise
                backoff = self.initial_backoff * (2 ** (attempts - 1))
                logger.info("Backing off %.1fs before retry", backoff)
                time.sleep(backoff)

    def upload_files(
        self,
        file_infos: Iterable[dict[str, Any]],
        *,
        remote_base: str = "",
        batch_size: int | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        batch_size = batch_size or MAX_BATCH_SIZE
        uploaded = 0
        skipped = 0
        failed = 0

        to_upload: List[Tuple[str, str, int]] = []
        for info in file_infos:
            full_path = str(info["full_path"])
            relative = info["relative_path"].lstrip("/")
            remote_path = f"{remote_base.rstrip('/')}/{relative}" if remote_base else relative
            remote_path = remote_path.lstrip("/")

            decision = self.deduplicator.check_remote(remote_path, file_path=full_path)
            if decision.get("status") == "skip":
                skipped += 1
                self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=0, status="skipped")
                if on_progress:
                    on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})
                continue

            to_upload.append((full_path, remote_path, int(info.get("size", 0))))

        if not self.max_workers or self.max_workers <= 1:
            for full_path, remote_path, size in to_upload:
                try:
                    self._upload_file_with_retry(full_path, remote_path)
                    try:
                        self.deduplicator.mark_uploaded(remote_path)
                    except Exception:
                        pass
                    uploaded += 1
                    self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=size)
                    if on_progress:
                        on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})
                except Exception as exc:
                    failed += 1
                    self.session.mark_file_failed(remote_path=remote_path, error=str(exc))
                    if on_progress:
                        on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})
            return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

        # Optimization: group files by their local directory and use upload_folder
        # for directories with many files to reduce API calls.
        dir_groups: dict[str, list[Tuple[str, str, int]]] = {}
        for full_path, remote_path, size in to_upload:
            local_dir = str(Path(full_path).parent)
            dir_groups.setdefault(local_dir, []).append((full_path, remote_path, size))

        remaining_tasks: list[Tuple[str, str, int]] = []
        # Threshold to prefer folder upload over per-file uploads
        FOLDER_UPLOAD_THRESHOLD = 8

        for local_dir, items in dir_groups.items():
            if len(items) >= FOLDER_UPLOAD_THRESHOLD:
                # Determine remote target directory (use the remote path of first item)
                _, sample_remote, _ = items[0]
                remote_parent = str(Path(sample_remote).parent).replace('\\', '/')
                # Attempt folder upload with retries
                attempts = 0
                max_attempts = self.max_retries or 3
                last_exc = None
                while attempts <= max_attempts:
                    try:
                        logger.info(
                            "Starting upload_folder: %s -> %s (attempt %d, %d files)",
                            local_dir,
                            remote_parent,
                            attempts + 1,
                            len(items),
                        )
                        start = time.time()
                        # Execute in daemon thread with real timeout (no blocking shutdown wait).
                        self._run_with_timeout(
                            self._api.upload_folder,
                            self.folder_upload_timeout,
                            local_dir,
                            remote_parent,
                            repo_id=self.repo_id,
                            repo_type="dataset",
                        )
                        duration = time.time() - start
                        logger.info("Finished upload_folder: %s -> %s in %.2fs", local_dir, remote_parent, duration)
                        # Mark each file as uploaded
                        for full_path, remote_path, size in items:
                            try:
                                self.deduplicator.mark_uploaded(remote_path)
                            except Exception:
                                pass
                            self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=size)
                            uploaded += 1
                            if on_progress:
                                on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})
                        break
                    except Exception as exc:
                        last_exc = exc
                        attempts += 1
                        logger.warning("upload_folder failed for %s -> %s (attempt %d): %s", local_dir, remote_parent, attempts, exc)
                        if attempts > max_attempts:
                            logger.error("upload_folder giving up after %d attempts, falling back to per-file uploads", attempts)
                            # Fall back to per-file upload for these items
                            remaining_tasks.extend(items)
                            break
                        backoff = self.initial_backoff * (2 ** (attempts - 1))
                        logger.info("Backing off %.1fs before retrying upload_folder", backoff)
                        time.sleep(backoff)
            else:
                remaining_tasks.extend(items)


        # Proceed with threaded per-file uploads for remaining tasks

        def _worker(task: Tuple[str, str, int]) -> Tuple[str, str]:
            full_path, remote_path, size = task
            try:
                logger.debug("Worker starting upload for %s", remote_path)
                start = time.time()
                self._upload_file_with_retry(full_path, remote_path)
                dur = time.time() - start
                logger.debug("Worker finished upload for %s in %.2fs", remote_path, dur)
                try:
                    self.deduplicator.mark_uploaded(remote_path)
                except Exception:
                    pass
                self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=size)
                return ("ok", remote_path)
            except Exception as exc:
                self.session.mark_file_failed(remote_path=remote_path, error=str(exc))
                return ("fail", remote_path)

        failed_tasks: list[Tuple[str, str, int]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(_worker, t): t for t in remaining_tasks}
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                task = futures.get(fut)
                if res[0] == "ok":
                    uploaded += 1
                else:
                    failed += 1
                    if task:
                        failed_tasks.append(task)
                if on_progress:
                    on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})

        # If we had failures with parallel uploads, attempt a sequential retry pass with reduced concurrency
        if failed_tasks:
            logger.warning("%d files failed in parallel upload. Retrying sequentially with reduced concurrency...", len(failed_tasks))
            seq_retry_backoff = max(self.initial_backoff, 1.0)
            # Attempt sequential retries for failed tasks
            for full_path, remote_path, size in failed_tasks:
                try:
                    time.sleep(seq_retry_backoff)
                    self._upload_file_with_retry(full_path, remote_path)
                    try:
                        self.deduplicator.mark_uploaded(remote_path)
                    except Exception:
                        pass
                    self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=size)
                    uploaded += 1
                    failed -= 1
                    if on_progress:
                        on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})
                except Exception as exc:
                    logger.warning("Sequential retry failed for %s: %s", remote_path, exc)
                    # leave failed count as-is

        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}
