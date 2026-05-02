from pathlib import Path

from src.domain.models import Detection
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.detection_queue_service import DetectionQueueService
from src.services.validation_service import ValidationService
from src.ui.app_factory import _page_to_table, _save_selected_validation_with_refresh


class FakeAudioService:
    def __init__(self) -> None:
        self.cleaned: list[str] = []

    def cleanup_after_validation(self, cache_key: str) -> None:
        self.cleaned.append(cache_key)


def _seed_detections(repo: InMemoryDetectionRepository, project_slug: str) -> None:
    repo.seed(
        project_slug,
        [
            Detection(
                detection_key="0000000000000001",
                audio_id="audio_001",
                scientific_name="Species A",
                confidence=0.92,
                start_time=0.0,
                end_time=1.0,
            ),
            Detection(
                detection_key="0000000000000002",
                audio_id="audio_002",
                scientific_name="Species B",
                confidence=0.81,
                start_time=0.5,
                end_time=1.5,
            ),
        ],
    )


def _build_stack(tmp_path: Path, project_slug: str = "demo-project"):
    detection_repo = InMemoryDetectionRepository()
    _seed_detections(detection_repo, project_slug)

    queue_service = DetectionQueueService(detection_repo)
    validation_repo = AppendOnlyValidationRepository(base_dir=str(tmp_path))
    validation_service = ValidationService(validation_repo)
    return queue_service, validation_repo, validation_service


def test_validation_write_refreshes_table_and_snapshot(tmp_path: Path) -> None:
    project_slug = "demo-project"
    queue_service, validation_repo, validation_service = _build_stack(tmp_path, project_slug)
    audio_service = FakeAudioService()

    rows, _, page = _page_to_table(
        service=queue_service,
        snapshot_reader=validation_repo,
        project_slug=project_slug,
        page=1,
        scientific_name="",
        min_confidence=0.0,
        page_size=25,
    )

    assert rows[0][6] == "pending"
    assert rows[0][7] == 0

    status, cache_key, _, refreshed_rows, refreshed_page, _, pending_status, conflict_key = (
        _save_selected_validation_with_refresh(
            validation_service=validation_service,
            audio_service=audio_service,
            queue_service=queue_service,
            snapshot_reader=validation_repo,
            project_slug=project_slug,
            rows=rows,
            selected_index=0,
            status_value="positive",
            validator="validator-a",
            notes="confirmed",
            cache_key="cache:audio_001",
            page=page,
            scientific_name="",
            min_confidence=0.0,
            validator_filter="",
            status_filter="all",
            updated_after=None,
            show_conflicts_only=False,
        )
    )

    assert "Validation saved" in status
    assert cache_key == ""
    assert refreshed_page == 1
    assert pending_status == ""
    assert conflict_key == ""
    assert refreshed_rows[0][6] == "positive"
    assert refreshed_rows[0][7] == 1
    assert audio_service.cleaned == ["cache:audio_001"]

    events = validation_repo.list_events(project_slug)
    snapshot = validation_repo.load_current_snapshot(project_slug)
    assert len(events) == 1
    assert snapshot["0000000000000001"]["status"] == "positive"
    assert snapshot["0000000000000001"]["version"] == 1


def test_stale_version_returns_conflict_and_marks_conflict_row(tmp_path: Path) -> None:
    project_slug = "demo-project"
    queue_service, validation_repo, validation_service = _build_stack(tmp_path, project_slug)
    audio_service = FakeAudioService()

    stale_rows, _, page = _page_to_table(
        service=queue_service,
        snapshot_reader=validation_repo,
        project_slug=project_slug,
        page=1,
        scientific_name="",
        min_confidence=0.0,
        page_size=25,
    )

    _ = validation_service.validate_detection(
        project_slug=project_slug,
        detection_key="0000000000000001",
        status="positive",
        validator="validator-a",
        expected_version=0,
    )

    status, _, _, refreshed_rows, _, _, pending_status, conflict_key = _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=queue_service,
        snapshot_reader=validation_repo,
        project_slug=project_slug,
        rows=stale_rows,
        selected_index=0,
        status_value="negative",
        validator="validator-b",
        notes="should conflict",
        cache_key="",
        page=page,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after=None,
        show_conflicts_only=False,
    )

    assert "Concurrency conflict" in status
    assert pending_status == "negative"
    assert conflict_key == "0000000000000001"

    conflict_row = next(row for row in refreshed_rows if row[0] == "0000000000000001")
    assert conflict_row[8] == "CONFLICT"
    assert conflict_row[9] == "HIGH"

    snapshot = validation_repo.load_current_snapshot(project_slug)
    assert snapshot["0000000000000001"]["status"] == "positive"
    assert snapshot["0000000000000001"]["version"] == 1


def test_snapshot_filters_work_with_real_validation_data(tmp_path: Path) -> None:
    project_slug = "demo-project"
    queue_service, validation_repo, validation_service = _build_stack(tmp_path, project_slug)

    _ = validation_service.validate_detection(
        project_slug=project_slug,
        detection_key="0000000000000002",
        status="uncertain",
        validator="validator-z",
        notes="needs review",
        expected_version=0,
    )

    filtered_rows, status, _ = _page_to_table(
        service=queue_service,
        snapshot_reader=validation_repo,
        project_slug=project_slug,
        page=1,
        scientific_name="",
        min_confidence=0.0,
        page_size=25,
        validator_filter="validator-z",
        status_filter="uncertain",
    )

    assert len(filtered_rows) == 1
    assert filtered_rows[0][0] == "0000000000000002"
    assert filtered_rows[0][6] == "uncertain"
    assert "Shown: 1" in status
