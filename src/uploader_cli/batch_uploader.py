from __future__ import annotations

import time
import concurrent.futures
from typing import List, Tuple
from pathlib import Path
from typing import Any, Callable, Iterable

from huggingface_hub import HfApi

from .config import MAX_BATCH_SIZE, RETRY_MAX_ATTEMPTS, RETRY_INITIAL_BACKOFF_SECONDS
from .deduplicator import Deduplicator
from .session_manager import SessionManager


class BatchUploader:
    """Orchestrate uploads with deduplication, retries and session checkpoints."""

    def __init__(
        self,
        api: HfApi,
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
        self.max_workers = max_workers

    def _upload_file_with_retry(self, local_path: str | Path, remote_path: str) -> None:
        attempts = 0
        last_exc: Exception | None = None
        while attempts <= self.max_retries:
            try:
                # The HfApi.upload_file signature varies across versions; callers/tests
                # should accept the positional usage shown here and monkeypatch in tests.
                self._api.upload_file(path_or_file=local_path, path_in_repo=remote_path, repo_id=self.repo_id)
                return
            except Exception as exc:  # pragma: no cover - network behavior
                last_exc = exc
                attempts += 1
                if attempts > self.max_retries:
                    raise
                backoff = self.initial_backoff * (2 ** (attempts - 1))
                time.sleep(backoff)

    def upload_files(
        self,
        file_infos: Iterable[dict[str, Any]],
        *,
        remote_base: str = "",
        batch_size: int | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Upload an iterable of file info dictionaries.

        Each file_info must include `full_path` and `relative_path`. `size` is optional.
        """
        batch_size = batch_size or MAX_BATCH_SIZE
        uploaded = 0
        skipped = 0
        failed = 0

        # First pass: decide which files to skip and which to upload
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

        # If no parallelism requested, perform sequential upload to preserve behavior
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

        # Parallel upload path
        def _worker(task: Tuple[str, str, int]) -> Tuple[str, str]:
            full_path, remote_path, size = task
            try:
                self._upload_file_with_retry(full_path, remote_path)
                try:
                    self.deduplicator.mark_uploaded(remote_path)
                except Exception:
                    pass
                self.session.mark_file_done(remote_path=remote_path, bytes_uploaded=size)
                return ("ok", remote_path)
            except Exception as exc:
                self.session.mark_file_failed(remote_path=remote_path, error=str(exc))
                return ("fail", remote_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(_worker, t): t for t in to_upload}
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if res[0] == "ok":
                    uploaded += 1
                else:
                    failed += 1
                if on_progress:
                    on_progress({"uploaded": uploaded, "skipped": skipped, "failed": failed})

        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}
