from dataclasses import dataclass
from datetime import date
from pathlib import Path
import json

import pandas as pd
import pytest

from src.ui.app_factory import (
    _build_validation_report,
    _cleanup_selected_audio,
    _extract_audio_id,
    _extract_detection_key,
    _find_detection_row_index,
    _fetch_selected_audio,
    _page_to_table,
    _save_selected_validation,
    _save_selected_validation_with_refresh,
    _reapply_last_conflict_validation_with_refresh,
    _batch_validate_conflicts,
    create_app,
    _load_seed_detections,
    _validate_seed_file,
    _build_detection_repository,
    _get_project_detection_count,
    _build_queue_badge,
    _load_projects_from_file,
    _load_user_access_from_file,
    _bootstrap_auth_and_projects,
)
from src.auth.auth_service import AuthService
from src.config.runtime_config import RuntimeConfig
from src.domain.models import Detection, Project
from src.ui.admin_panel import AdminPanelManager


@dataclass
class FakeFetchResult:
    cache_key: str
    local_path: str
    source: str


class FakeAudioService:
    def __init__(self) -> None:
        self.cleaned: list[str] = []

    def fetch(self, dataset_repo: str, audio_id: str) -> FakeFetchResult:
        _ = dataset_repo
        return FakeFetchResult(cache_key=f"key:{audio_id}", local_path=f"/tmp/{audio_id}.wav", source="remote")

    def cleanup_after_validation(self, cache_key: str) -> None:
        self.cleaned.append(cache_key)


class FakeValidationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, str]:
        _ = corrected_species
        payload = {
            "project_slug": project_slug,
            "detection_key": detection_key,
            "status": status,
            "validator": validator,
            "notes": notes,
            "expected_version": str(expected_version),
        }
        self.calls.append(payload)
        return payload


class FakeConflictValidationService:
    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, str]:
        _ = project_slug
        _ = detection_key
        _ = status
        _ = validator
        _ = notes
        _ = corrected_species
        _ = expected_version
        from src.repositories.append_only_validation_repository import OptimisticLockError

        raise OptimisticLockError("dkey_01", expected_version or 0, 3)


class FakeSnapshotReader:
    def __init__(self) -> None:
        self.snapshot: dict[str, dict[str, object]] = {
            "dkey_01": {
                "status": "positive",
                "validator": "validator-demo",
                "updated_at": "2026-03-25T10:00:00+00:00",
                "version": 2,
            },
            "dkey_02": {
                "status": "negative",
                "validator": "validator-other",
                "updated_at": "2026-03-20T10:00:00+00:00",
                "version": 1,
            }
        }
        self.events: list[dict[str, object]] = [
            {"detection_key": "dkey_01", "status": "positive"},
            {"detection_key": "dkey_02", "status": "negative"},
        ]

    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]:
        _ = project_slug
        return self.snapshot

    def list_events(self, project_slug: str) -> list[dict[str, object]]:
        _ = project_slug
        return self.events


class FakeQueueService:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, object] = {}

    class _Page:
        def __init__(self) -> None:
            self.page = 1
            self.total_pages = 1
            self.total_items = 2
            self.items = [
                type(
                    "DetectionLike",
                    (),
                    {
                        "detection_key": "dkey_01",
                        "audio_id": "audio_01",
                        "scientific_name": "sp",
                        "confidence": 0.9,
                        "start_time": 0.0,
                        "end_time": 1.0,
                    },
                )(),
                type(
                    "DetectionLike",
                    (),
                    {
                        "detection_key": "dkey_02",
                        "audio_id": "audio_02",
                        "scientific_name": "sp2",
                        "confidence": 0.85,
                        "start_time": 1.0,
                        "end_time": 2.0,
                    },
                )(),
            ]

    def get_page(self, **kwargs: object) -> "FakeQueueService._Page":
        self.last_kwargs = kwargs
        return FakeQueueService._Page()


def test_extract_audio_id_from_list_rows() -> None:
    rows = [["k1", "audio_01", "sp", 0.9, 0.0, 1.0]]
    assert _extract_audio_id(rows, 0) == "audio_01"


def test_extract_audio_id_from_dataframe_rows() -> None:
    frame = pd.DataFrame([["k1", "audio_02", "sp", 0.9, 0.0, 1.0]])
    assert _extract_audio_id(frame, 0) == "audio_02"


def test_fetch_selected_audio_success() -> None:
    service = FakeAudioService()
    rows = [["k1", "audio_03", "sp", 0.9, 0.0, 1.0]]

    path, cache_key, status = _fetch_selected_audio(
        audio_service=service,
        dataset_repo="org/dataset",
        rows=rows,
        selected_index=0,
        previous_cache_key="",
    )

    assert path == "/tmp/audio_03.wav"
    assert cache_key == "key:audio_03"
    assert "Audio loaded" in status


def test_extract_detection_key_from_rows() -> None:
    rows = [["dkey_01", "audio_01", "sp", 0.9, 0.0, 1.0]]
    assert _extract_detection_key(rows, 0) == "dkey_01"


def test_fetch_selected_audio_validates_repo() -> None:
    service = FakeAudioService()
    rows = [["k1", "audio_03", "sp", 0.9, 0.0, 1.0]]

    path, cache_key, status = _fetch_selected_audio(
        audio_service=service,
        dataset_repo="   ",
        rows=rows,
        selected_index=0,
        previous_cache_key="old-key",
    )

    assert path is None
    assert cache_key == ""
    assert "Provide dataset repo" in status


def test_cleanup_selected_audio() -> None:
    service = FakeAudioService()

    status, player_value = _cleanup_selected_audio(service, "key:audio_03")

    assert "Audio cache cleaned" in status
    assert player_value is None
    assert service.cleaned == ["key:audio_03"]


def test_save_selected_validation_saves_and_cleans_audio_cache() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["0000000000001111", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path = _save_selected_validation(
        validation_service=validation_service,
        audio_service=audio_service,
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
    )

    assert "Validation saved" in status
    assert cache_key == ""
    assert audio_path is None
    assert len(validation_service.calls) == 1
    assert validation_service.calls[0]["detection_key"] == "0000000000001111"
    assert validation_service.calls[0]["expected_version"] == "0"
    assert audio_service.cleaned == ["cache:audio_11"]


def test_save_selected_validation_returns_conflict_message() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeConflictValidationService()
    rows = [["0000000000001111", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path = _save_selected_validation(
        validation_service=validation_service,
        audio_service=audio_service,
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
    )

    assert "Concurrency conflict" in status
    assert cache_key == "cache:audio_11"
    assert audio_path is None


def test_build_validation_report() -> None:
    report = _build_validation_report(FakeSnapshotReader(), "demo-project")

    assert "Project: demo-project" in report
    assert "Append-only events: 2" in report
    assert "Detections with current state: 2" in report
    assert "positive=1" in report
    assert "negative=1" in report


def test_page_to_table_includes_validation_status() -> None:
    queue = FakeQueueService()
    rows, status, page = _page_to_table(
        service=queue,
        snapshot_reader=FakeSnapshotReader(),
        project_slug="kenya-2024",
        page=1,
        scientific_name="",
        min_confidence=0.0,
    )

    assert page == 1
    assert "Page 1/1" in status
    assert rows[0][0] == "dkey_01"
    assert rows[0][6] == "positive"
    assert rows[0][7] == 2
    assert rows[0][8] == ""
    assert rows[0][9] == ""
    assert queue.last_kwargs["project_slug"] == "kenya-2024"


def test_page_to_table_marks_conflict_row() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        conflict_detection_key="dkey_01",
    )

    assert rows[0][8] == "CONFLICT"
    assert rows[0][9] == "HIGH"


def test_page_to_table_conflicts_only_filter_hides_non_conflicts() -> None:
    rows, status, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=True,
    )

    assert rows == []
    assert "Conflicts only: 0 item(ns)" in status


def test_page_to_table_conflicts_only_filter_keeps_conflict_rows() -> None:
    rows, status, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        conflict_detection_key="dkey_01",
        show_conflicts_only=True,
    )

    assert len(rows) == 1
    assert rows[0][8] == "CONFLICT"
    assert "Conflicts only: 1 item(ns)" in status


def test_page_to_table_filters_by_validator() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="other",
    )

    assert len(rows) == 1
    assert rows[0][0] == "dkey_02"


def test_page_to_table_filters_by_status() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        status_filter="negative",
    )

    assert len(rows) == 1
    assert rows[0][0] == "dkey_02"


def test_page_to_table_filters_by_updated_after() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        updated_after="2026-03-24",
    )

    assert len(rows) == 1
    assert rows[0][0] == "dkey_01"


def test_page_to_table_filters_by_updated_after_date_object() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        updated_after=date(2026, 3, 24),
    )

    assert len(rows) == 1
    assert rows[0][0] == "dkey_01"


def test_find_detection_row_index() -> None:
    rows = [["dkey_00", "audio_00"], ["dkey_01", "audio_01"]]

    assert _find_detection_row_index(rows, "dkey_01") == 1
    assert _find_detection_row_index(rows, "missing") == 0


def test_save_selected_validation_with_refresh_success() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
        show_conflicts_only=False,
    )

    assert "Validation saved" in status
    assert cache_key == ""
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert pending_status == ""
    assert conflict_key == ""


def test_save_selected_validation_with_refresh_conflict() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeConflictValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
        show_conflicts_only=False,
    )

    assert "Concurrency conflict" in status
    assert "Table reloaded" in status
    assert cache_key == "cache:audio_11"
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert refreshed_rows[0][8] == "CONFLICT"
    assert refreshed_rows[0][9] == "HIGH"
    assert pending_status == "positive"
    assert conflict_key == "dkey_01"


def test_reapply_last_conflict_validation_with_refresh() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 2, "conflict"]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _reapply_last_conflict_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        pending_status_value="positive",
        conflict_detection_key="dkey_01",
        validator="validator-demo",
        notes="retry",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
        show_conflicts_only=False,
    )

    assert "Validation saved" in status
    assert cache_key == ""
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert pending_status == ""
    assert conflict_key == ""


def test_reapply_last_conflict_without_pending_status() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 2, ""]]

    status, _, _, _, _, _, pending_status, conflict_key = _reapply_last_conflict_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        pending_status_value="",
        conflict_detection_key="",
        validator="validator-demo",
        notes="retry",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
        show_conflicts_only=False,
    )

    assert "No pending validation" in status
    assert pending_status == ""
    assert conflict_key == ""


def test_create_app_with_keyboard_shortcuts() -> None:
    """Test that create_app successfully creates the UI with keyboard shortcuts enabled."""
    app = create_app()
    assert app is not None
    # Verify the app is a Gradio Blocks instance
    assert hasattr(app, "queue")
    assert hasattr(app, "launch")


def test_batch_validate_conflicts_all_success() -> None:
    """Test batch approval of all conflicts in table."""
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [
        ["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 1, "CONFLICT", "HIGH"],
        ["dkey_02", "audio_12", "sp", 0.85, 1.0, 2.0, "pending", 1, "CONFLICT", "HIGH"],
    ]

    status, cache_key, audio_path, refreshed_rows, refreshed_page = _batch_validate_conflicts(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        status_value="positive",
        validator="validator-demo",
        notes="batch approval",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
    )

    assert "Processed 2 conflicts" in status
    assert "2 success" in status
    assert cache_key == ""
    assert refreshed_page == 1
    assert len(validation_service.calls) == 2


def test_batch_validate_conflicts_no_conflicts() -> None:
    """Test batch validation when no conflicts are present."""
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [
        ["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "positive", 2, "", ""],
    ]

    status, cache_key, audio_path, refreshed_rows, refreshed_page = _batch_validate_conflicts(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        status_value="positive",
        validator="validator-demo",
        notes="batch approval",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        validator_filter="",
        status_filter="all",
        updated_after="",
    )

    assert "No conflict detection" in status
    assert len(validation_service.calls) == 0


def test_load_seed_detections_from_json_dict(tmp_path: Path) -> None:
    payload = {
        "kenya-2024": [
            {
                "detection_key": "0000000000001001",
                "audio_id": "audio_1001",
                "scientific_name": "Cyanocorax cyanopogon",
                "confidence": 0.91,
                "start_time": 0.0,
                "end_time": 1.0,
            }
        ]
    }
    seed_file = tmp_path / "detections.json"
    seed_file.write_text(json.dumps(payload), encoding="utf-8")

    result = _load_seed_detections(str(seed_file))

    assert "kenya-2024" in result
    assert len(result["kenya-2024"]) == 1
    assert result["kenya-2024"][0].audio_id == "audio_1001"


def test_validate_seed_file_warns_for_invalid_shape(tmp_path: Path) -> None:
    seed_file = tmp_path / "detections-invalid.json"
    seed_file.write_text(json.dumps({"kenya-2024": {"wrong": True}}), encoding="utf-8")

    warning = _validate_seed_file(str(seed_file))

    assert "Invalid" in warning


def test_validate_seed_file_warns_when_file_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-seed.json"

    warning = _validate_seed_file(str(missing_path))

    assert "not found" in warning
    assert "BIRDNET_DETECTIONS_FILE" in warning


def test_build_detection_repository_includes_new_project_defaults() -> None:
    queue, warning = _build_detection_repository(["brand-new-project"], seed_file_path=None)
    page = queue.get_page(project_slug="brand-new-project", page=1, page_size=10)

    assert warning == ""
    assert page.project_slug == "brand-new-project"
    assert len(page.items) == 4


def test_get_project_detection_count_reads_total_items() -> None:
    queue = FakeQueueService()

    total = _get_project_detection_count(queue, "kenya-2024")

    assert total == 2


def test_get_project_detection_count_handles_service_error() -> None:
    class BrokenQueueService:
        def get_page(self, **kwargs: object):
            _ = kwargs
            raise RuntimeError("boom")

    total = _get_project_detection_count(BrokenQueueService(), "kenya-2024")

    assert total == 0


def test_build_queue_badge_without_project() -> None:
    badge = _build_queue_badge(FakeQueueService(), None)

    assert "Queue: --" in badge


def test_build_queue_badge_with_project() -> None:
    badge = _build_queue_badge(FakeQueueService(), "kenya-2024")

    assert "Queue: 2" in badge


def test_fetch_selected_audio_repo_hint() -> None:
    service = FakeAudioService()
    rows = [["k1", "audio_03", "sp", 0.9, 0.0, 1.0]]

    _, _, status = _fetch_selected_audio(
        audio_service=service,
        dataset_repo="",
        rows=rows,
        selected_index=0,
        previous_cache_key="",
    )

    assert "owner/repo" in status
    assert "Example" in status


def test_load_projects_from_file_reads_valid_payload(tmp_path: Path) -> None:
    payload = [
        {
            "project_slug": "project-a",
            "name": "Project A",
            "dataset_repo_id": "org/project-a",
            "active": True,
        }
    ]
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    projects = _load_projects_from_file(str(path))

    assert len(projects) == 1
    assert projects[0].project_slug == "project-a"


def test_load_user_access_from_file_reads_valid_payload(tmp_path: Path) -> None:
    payload = {
        "validator_a": {"project-a": "validator"},
        "admin_a": {"project-a": "admin", "project-b": "admin"},
    }
    path = tmp_path / "access.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    access = _load_user_access_from_file(str(path))

    assert access["validator_a"]["project-a"].value == "validator"
    assert access["admin_a"]["project-b"].value == "admin"


def test_bootstrap_auth_and_projects_uses_config_files_without_demo_fallback(tmp_path: Path) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            [
                {
                    "project_slug": "project-a",
                    "name": "Project A",
                    "dataset_repo_id": "org/project-a",
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({"validator_a": {"project-a": "validator"}}),
        encoding="utf-8",
    )

    runtime_config = RuntimeConfig(
        detection_seed_path=None,
        validation_base_dir=str(tmp_path / "validations"),
        bootstrap_base_dir=str(tmp_path / "bootstrap"),
        page_size=25,
        projects_file_path=str(projects_file),
        user_access_file_path=str(users_file),
        invites_file_path=None,
        invite_ttl_hours=72,
        enable_demo_bootstrap=False,
        invite_email_enabled=False,
        invite_email_sender="",
        invite_email_login_url="",
    )
    auth_service = AuthService()
    from src.services.invite_email_notifier import EmailJSInviteEmailNotifier
    notifier = EmailJSInviteEmailNotifier("", "", "", "", timeout_seconds=20)
    admin_manager = AdminPanelManager(auth_service, invite_notifier=notifier)

    warning = _bootstrap_auth_and_projects(auth_service, admin_manager, runtime_config)
    emergency_admin_session = auth_service.login("admin_user")

    assert "Emergency admin access" in warning
    assert auth_service.login("validator_a") is not None
    assert emergency_admin_session is not None
    assert any(p["project_slug"] == "project-a" for p in admin_manager.list_projects())


def test_bootstrap_auth_and_projects_warns_when_not_configured(tmp_path: Path) -> None:
    runtime_config = RuntimeConfig(
        detection_seed_path=None,
        validation_base_dir=str(tmp_path / "validations"),
        bootstrap_base_dir=str(tmp_path / "bootstrap"),
        page_size=25,
        projects_file_path=None,
        user_access_file_path=None,
        invites_file_path=None,
        invite_ttl_hours=72,
        enable_demo_bootstrap=False,
        invite_email_enabled=False,
        invite_email_sender="",
        invite_email_login_url="",
    )
    auth_service = AuthService()
    from src.services.invite_email_notifier import EmailJSInviteEmailNotifier
    notifier = EmailJSInviteEmailNotifier("", "", "", "", timeout_seconds=20)
    admin_manager = AdminPanelManager(auth_service, invite_notifier=notifier)

    warning = _bootstrap_auth_and_projects(auth_service, admin_manager, runtime_config)
    assert warning == ""


def test_bootstrap_auth_and_projects_recovers_emergency_admin_when_missing(tmp_path: Path) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            [
                {
                    "project_slug": "project-a",
                    "name": "Project A",
                    "dataset_repo_id": "org/project-a",
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({"validator_only": {"project-a": "validator"}}),
        encoding="utf-8",
    )

    runtime_config = RuntimeConfig(
        detection_seed_path=None,
        validation_base_dir=str(tmp_path / "validations"),
        bootstrap_base_dir=str(tmp_path / "bootstrap"),
        page_size=25,
        projects_file_path=str(projects_file),
        user_access_file_path=str(users_file),
        invites_file_path=None,
        invite_ttl_hours=72,
        enable_demo_bootstrap=False,
        invite_email_enabled=False,
        invite_email_sender="",
        invite_email_login_url="",
    )
    auth_service = AuthService()
    from src.services.invite_email_notifier import EmailJSInviteEmailNotifier
    notifier = EmailJSInviteEmailNotifier("", "", "", "", timeout_seconds=20)
    admin_manager = AdminPanelManager(auth_service, invite_notifier=notifier)

    warning = _bootstrap_auth_and_projects(auth_service, admin_manager, runtime_config)
    emergency_session = auth_service.login("admin_user")

    assert "Emergency admin access" in warning
    assert emergency_session is not None
    assert emergency_session.role.value == "admin"


def test_load_dataset_detections_for_project_reads_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.ui import app_factory as module

    class FakeHfApi:
        def __init__(self, token: str | None = None) -> None:
            _ = token

        def list_repo_files(self, repo_id: str, repo_type: str = "dataset") -> list[str]:
            _ = repo_id
            _ = repo_type
            return ["detections.jsonl"]

    metadata_file = tmp_path / "detections.jsonl"
    metadata_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "project_slug": "project-a",
                        "audio_id": "audio_0001",
                        "scientific_name": "Species A",
                        "confidence": 0.92,
                        "start_time": 1.0,
                        "end_time": 2.0,
                    }
                ),
                json.dumps(
                    {
                        "project_slug": "project-a",
                        "audio_id": "audio_0002",
                        "scientific_name": "Species B",
                        "confidence": 0.81,
                        "start_time": 2.0,
                        "end_time": 3.0,
                    }
                ),
                json.dumps(
                    {
                        "project_slug": "project-other",
                        "audio_id": "audio_9999",
                        "scientific_name": "Other",
                        "confidence": 0.5,
                        "start_time": 0.0,
                        "end_time": 1.0,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "HfApi", FakeHfApi)
    monkeypatch.setattr(module, "hf_hub_download", lambda **kwargs: str(metadata_file))

    project = Project(
        project_slug="project-a",
        name="Project A",
        dataset_repo_id="org/project-a",
        active=True,
    )
    detections, warning = module._load_dataset_detections_for_project(project)

    assert warning == ""
    assert len(detections) == 2
    assert {item.scientific_name for item in detections} == {"Species A", "Species B"}


def test_build_detection_repository_prefers_dataset_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ui import app_factory as module

    project = Project(
        project_slug="project-a",
        name="Project A",
        dataset_repo_id="org/project-a",
        active=True,
    )

    monkeypatch.setattr(
        module,
        "_load_dataset_detections_for_project",
        lambda project_obj: (
            [
                Detection(
                    detection_key="0000000000002222",
                    audio_id="audio_dataset_1",
                    scientific_name="Dataset Species",
                    confidence=0.95,
                    start_time=0.0,
                    end_time=1.0,
                )
            ],
            "",
        ),
    )

    queue, warning = _build_detection_repository(
        ["project-a"],
        seed_file_path=None,
        project_map={"project-a": project},
        allow_demo_defaults=False,
    )
    page = queue.get_page(project_slug="project-a", page=1, page_size=10)

    assert warning == ""
    assert len(page.items) == 1
    assert page.items[0].scientific_name == "Dataset Species"


def test_load_dataset_detections_for_project_falls_back_to_audiofolder_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ui import app_factory as module

    class FakeHfApi:
        def __init__(self, token: str | None = None) -> None:
            _ = token

        def list_repo_files(self, repo_id: str, repo_type: str = "dataset") -> list[str]:
            _ = repo_id
            _ = repo_type
            return [
                "audio/segments/Accipiter_striatus/Catim_20250221_060600_0.0-3.0s_85%.wav",
                "audio/segments/Aegolius_harrisii/Aiuab_20260123_182900_9.0-12.0s_68%.wav",
            ]

    monkeypatch.setattr(module, "HfApi", FakeHfApi)

    project = Project(
        project_slug="teste7",
        name="Teste 7",
        dataset_repo_id="jrrribeiro/teste7",
        active=True,
    )

    detections, warning = module._load_dataset_detections_for_project(project)

    assert warning == ""
    assert len(detections) == 2
    assert {item.scientific_name for item in detections} == {"Accipiter striatus", "Aegolius harrisii"}
    assert {item.audio_id for item in detections} == {
        "segments/Accipiter_striatus/Catim_20250221_060600_0.0-3.0s_85%.wav",
        "segments/Aegolius_harrisii/Aiuab_20260123_182900_9.0-12.0s_68%.wav",
    }


def test_parse_segment_filename_hint_reads_time_and_confidence() -> None:
    from src.ui import app_factory as module

    start, end, conf = module._parse_segment_filename_hint("any_12.0-15.0s_85%.wav")

    assert start == 12.0
    assert end == 15.0
    assert conf == 0.85


def test_build_detection_from_row_prefers_segment_path_for_audio_id() -> None:
    from src.ui import app_factory as module

    row = {
        "project_slug": "project-a",
        "segment_path_in_repo": "audio/segments/species_a/example.wav",
        "audio_id": "source_stem_only",
        "scientific_name": "Species A",
        "confidence": 0.77,
        "start_time": 0.0,
        "end_time": 3.0,
    }

    detection = module._build_detection_from_row(row, 0, "project-a")

    assert detection is not None
    assert detection.audio_id == "segments/species_a/example.wav"


def test_load_dataset_detections_for_project_uses_parquet_shards_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ui import app_factory as module

    class FakeHfApi:
        def __init__(self, token: str | None = None) -> None:
            _ = token

        def list_repo_files(self, repo_id: str, repo_type: str = "dataset") -> list[str]:
            _ = repo_id
            _ = repo_type
            return ["manifest.json", "index/shards/shard-00000.parquet"]

    expected = [
        Detection(
            detection_key="0000000000003333",
            audio_id="segments/species_a/example.wav",
            scientific_name="Species A",
            confidence=0.9,
            start_time=0.0,
            end_time=3.0,
        )
    ]

    monkeypatch.setattr(module, "HfApi", FakeHfApi)
    monkeypatch.setattr(
        module,
        "_load_detections_from_parquet_shards",
        lambda project, dataset_repo, token, repo_files: (expected, ""),
    )

    project = Project(
        project_slug="project-a",
        name="Project A",
        dataset_repo_id="org/project-a",
        active=True,
    )

    detections, warning = module._load_dataset_detections_for_project(project)

    assert warning == ""
    assert len(detections) == 1
    assert detections[0].scientific_name == "Species A"
