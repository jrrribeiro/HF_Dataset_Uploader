import json
from datetime import UTC, datetime
from pathlib import Path
import threading
from uuid import uuid4

from src.domain.models import Validation


class OptimisticLockError(Exception):
    def __init__(self, detection_key: str, expected_version: int, current_version: int) -> None:
        self.detection_key = detection_key
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Optimistic lock conflict for detection_key={detection_key}: "
            f"expected_version={expected_version}, current_version={current_version}"
        )


class AppendOnlyValidationRepository:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for_project(self, project_slug: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(project_slug)
            if lock is None:
                lock = threading.Lock()
                self._locks[project_slug] = lock
            return lock

    @staticmethod
    def _atomic_write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.parent / f".{path.name}.tmp.{uuid4().hex}"
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def save_validation(self, project_slug: str, item: Validation, expected_version: int | None = None) -> int:
        project_dir = self._base_dir / project_slug / "validations"
        project_dir.mkdir(parents=True, exist_ok=True)

        with self._lock_for_project(project_slug):
            current_file = project_dir / "current.json"
            if current_file.exists():
                current_payload = json.loads(current_file.read_text(encoding="utf-8"))
            else:
                current_payload = {}

            current_item = current_payload.get(item.detection_key, {})
            current_version = int(current_item.get("version", 0))
            expected = expected_version if expected_version is not None else current_version
            if expected != current_version:
                raise OptimisticLockError(
                    detection_key=item.detection_key,
                    expected_version=expected,
                    current_version=current_version,
                )

            new_version = current_version + 1

            event_date = datetime.now(UTC).strftime("%Y%m%d")
            events_file = project_dir / f"events-{event_date}.jsonl"
            event = {
                "event_id": str(uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
                "project_slug": project_slug,
                "expected_version": expected,
                "previous_version": current_version,
                "new_version": new_version,
                **item.model_dump(),
            }
            with events_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")

            current_payload[item.detection_key] = {
                "status": item.status,
                "corrected_species": item.corrected_species,
                "notes": item.notes,
                "validator": item.validator,
                "updated_at": event["timestamp"],
                "version": new_version,
            }
            self._atomic_write_json(current_file, current_payload)
            return new_version

    def list_events(self, project_slug: str) -> list[dict[str, object]]:
        project_dir = self._base_dir / project_slug / "validations"
        if not project_dir.exists():
            return []

        events: list[dict[str, object]] = []
        for path in sorted(project_dir.glob("events-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    payload = line.strip()
                    if payload:
                        events.append(json.loads(payload))
        return events

    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]:
        current_file = self._base_dir / project_slug / "validations" / "current.json"
        if not current_file.exists():
            return {}
        return json.loads(current_file.read_text(encoding="utf-8"))
