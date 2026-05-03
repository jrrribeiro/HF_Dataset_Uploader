from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import threading

from huggingface_hub import HfApi

from .config import get_cache_root
from .hash_utils import compute_file_hash
from .exceptions import ValidationError


class Deduplicator:
    """Check remote file presence and cache the remote path index locally."""

    def __init__(self, api: HfApi, repo_id: str, *, repo_type: str = "dataset") -> None:
        self._api = api
        self.repo_id = repo_id
        self.repo_type = repo_type
        self._remote_paths: set[str] | None = None
        self._decision_cache: dict[str, dict[str, Any]] = {}
        self.cache_path = self._build_cache_path()
        self._lock = threading.Lock()

    def _build_cache_path(self) -> Path:
        cache_root = get_cache_root() / "dedup"
        cache_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{self.repo_type}:{self.repo_id}".encode("utf-8")).hexdigest()[:16]
        return cache_root / f"{digest}.json"

    def load_cached_index(self) -> set[str]:
        if self._remote_paths is not None:
            return self._remote_paths
        with self._lock:
            if self.cache_path.exists():
                raw = self.cache_path.read_text(encoding="utf-8")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValidationError(f"Invalid dedup cache JSON at {self.cache_path}") from exc

                remote_paths = payload.get("remote_paths", [])
                if not isinstance(remote_paths, list):
                    raise ValidationError(f"Invalid dedup cache format at {self.cache_path}")
                self._remote_paths = {str(path) for path in remote_paths}
                return self._remote_paths

            self._remote_paths = self.refresh_remote_index()
            return self._remote_paths

    def refresh_remote_index(self) -> set[str]:
        try:
            repo_files = self._api.list_repo_files(repo_id=self.repo_id, repo_type=self.repo_type)
        except Exception as exc:  # pragma: no cover - external API behavior
            raise ValidationError(f"Could not read remote file listing for {self.repo_id}: {exc}") from exc

        remote_paths = {str(path) for path in repo_files}
        with self._lock:
            self._remote_paths = remote_paths
            self._write_cache(remote_paths)
        return remote_paths

    def check_remote(self, remote_path: str, *, file_path: str | Path | None = None) -> dict[str, Any]:
        cache_key = self._build_decision_key(remote_path, file_path=file_path)
        cached = self._decision_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        remote_paths = self.load_cached_index()
        exists = remote_path in remote_paths

        payload = {
            "remote_path": remote_path,
            "status": "skip" if exists else "upload",
            "cached_remote_index": True,
        }
        if file_path is not None:
            file_path_obj = Path(file_path)
            payload["local_size"] = file_path_obj.stat().st_size
            payload["local_sha256"] = compute_file_hash(file_path_obj)

        self._decision_cache[cache_key] = dict(payload)
        return payload

    def mark_uploaded(self, remote_path: str) -> None:
        with self._lock:
            remote_paths = self.load_cached_index()
            if remote_path not in remote_paths:
                remote_paths.add(remote_path)
                self._write_cache(remote_paths)

            keys_to_update = [key for key, value in self._decision_cache.items() if value.get("remote_path") == remote_path]
            for key in keys_to_update:
                self._decision_cache[key]["status"] = "skip"

    def _write_cache(self, remote_paths: set[str]) -> None:
        payload = {
            "repo_id": self.repo_id,
            "repo_type": self.repo_type,
            "updated_at": datetime.now(UTC).isoformat(),
            "remote_paths": sorted(remote_paths),
        }
        temp_path = self.cache_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.cache_path)

    def _build_decision_key(self, remote_path: str, *, file_path: str | Path | None) -> str:
        if file_path is None:
            return remote_path
        file_path_obj = Path(file_path)
        try:
            stat = file_path_obj.stat()
        except FileNotFoundError as exc:
            raise ValidationError(f"Local file not found: {file_path_obj}") from exc
        return f"{remote_path}:{file_path_obj.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
