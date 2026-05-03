from __future__ import annotations

import os
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import threading

from .config import get_session_root
from .exceptions import SessionError


class SessionManager:
    """Persist and recover upload checkpoints."""

    def __init__(self, session_id: str | None = None):
        if session_id is None:
            now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            session_id = f"upload-{now}"
        self.session_id = session_id
        self.session_dir = get_session_root() / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @classmethod
    def create_session(cls, metadata: dict[str, Any] | None = None) -> "SessionManager":
        session = cls()
        if metadata:
            session.save_metadata(metadata)
        return session

    @property
    def checkpoint_path(self) -> Path:
        return self.session_dir / "checkpoint.json"

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / "metadata.json"

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        serialized = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
        temp_path.write_text(serialized, encoding="utf-8")
        with temp_path.open("a", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)

    def save_metadata(self, payload: dict[str, Any]) -> None:
        self._atomic_write_json(self.metadata_path, payload)

    def load_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        raw = self.metadata_path.read_text(encoding="utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionError(f"Invalid metadata JSON for session '{self.session_id}'") from exc

    def save_checkpoint(self, payload: dict[str, Any]) -> None:
        self._atomic_write_json(self.checkpoint_path, payload)

    def load_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {}
        raw = self.checkpoint_path.read_text(encoding="utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionError(f"Invalid checkpoint JSON for session '{self.session_id}'") from exc

    def mark_file_done(self, *, remote_path: str, bytes_uploaded: int, status: str = "uploaded") -> dict[str, Any]:
        with self._lock:
            checkpoint = self.load_checkpoint()
            checkpoint.setdefault("uploaded_files", [])
            checkpoint.setdefault("uploaded", 0)
            checkpoint.setdefault("failed", 0)
            checkpoint["uploaded"] = int(checkpoint["uploaded"]) + 1
            checkpoint["status"] = status
            checkpoint["last_completed_file"] = remote_path
            checkpoint["last_update_at"] = datetime.now(UTC).isoformat()
            checkpoint["bytes_uploaded"] = int(checkpoint.get("bytes_uploaded", 0)) + int(bytes_uploaded)
            checkpoint["uploaded_files"].append(remote_path)
            self.save_checkpoint(checkpoint)
            return checkpoint

    def mark_file_failed(self, *, remote_path: str, error: str) -> dict[str, Any]:
        with self._lock:
            checkpoint = self.load_checkpoint()
            checkpoint.setdefault("failed_files", [])
            checkpoint.setdefault("uploaded", 0)
            checkpoint.setdefault("failed", 0)
            checkpoint["failed"] = int(checkpoint["failed"]) + 1
            checkpoint["status"] = "failed"
            checkpoint["last_failed_file"] = remote_path
            checkpoint["last_error"] = error
            checkpoint["last_update_at"] = datetime.now(UTC).isoformat()
            checkpoint["failed_files"].append({"remote_path": remote_path, "error": error})
            self.save_checkpoint(checkpoint)
            return checkpoint
