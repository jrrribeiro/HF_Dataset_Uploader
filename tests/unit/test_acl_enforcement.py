"""Tests for ACL (Access Control List) enforcement at repository level.

Validates that project isolation works correctly:
- Data from project A is not visible in project B
- Validation operations are isolated per project
- DetectionRepository filters by project_slug
"""

import pytest
import tempfile
from pathlib import Path

from src.domain.models import Detection, Role, Validation
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository
from src.auth.auth_service import AuthService


class TestDetectionRepositoryProjectIsolation:
    """Test that DetectionRepository respects project boundaries."""

    @pytest.fixture
    def detection_repo(self):
        """Create a new detection repository."""
        return InMemoryDetectionRepository()

    @pytest.fixture
    def setup_multi_project_detections(self, detection_repo):
        """Seed multiple projects with different detections."""
        # Project 1: Kenya Survey
        kenya_detections = [
            Detection(
                detection_key="00000000000KE001",
                audio_id="audio_ke_001",
                scientific_name="Cyanocorax cyanopogon",
                confidence=0.95,
                start_time=0.0,
                end_time=1.5,
            ),
            Detection(
                detection_key="00000000000KE002",
                audio_id="audio_ke_002",
                scientific_name="Ramphastos toco",
                confidence=0.87,
                start_time=0.0,
                end_time=2.0,
            ),
        ]
        detection_repo.seed("kenya-2024", kenya_detections)

        # Project 2: Nairobi Survey
        nairobi_detections = [
            Detection(
                detection_key="00000000000NB001",
                audio_id="audio_nb_001",
                scientific_name="Tockus erythrorhynchus",
                confidence=0.92,
                start_time=0.0,
                end_time=1.2,
            ),
        ]
        detection_repo.seed("nairobi-2023", nairobi_detections)

        # Project 3: Demo
        demo_detections = [
            Detection(
                detection_key="00000000000DE001",
                audio_id="audio_demo_001",
                scientific_name="Psarocolius decumanus",
                confidence=0.78,
                start_time=0.0,
                end_time=1.8,
            ),
            Detection(
                detection_key="00000000000DE002",
                audio_id="audio_demo_002",
                scientific_name="Cyanocorax cyanopogon",
                confidence=0.85,
                start_time=0.0,
                end_time=1.1,
            ),
            Detection(
                detection_key="00000000000DE003",
                audio_id="audio_demo_003",
                scientific_name="Tockus erythrorhynchus",
                confidence=0.73,
                start_time=0.0,
                end_time=1.5,
            ),
        ]
        detection_repo.seed("demo-project", demo_detections)

    def test_list_detections_isolates_projects(self, detection_repo, setup_multi_project_detections):
        """Test that listing detections from one project doesn't return data from others."""
        kenya_items = detection_repo.list_detections(
            project_slug="kenya-2024", page=1, page_size=10
        )
        nairobi_items = detection_repo.list_detections(
            project_slug="nairobi-2023", page=1, page_size=10
        )
        demo_items = detection_repo.list_detections(
            project_slug="demo-project", page=1, page_size=10
        )

        # Kenya project has exactly 2 items
        assert len(kenya_items) == 2
        assert all(item.detection_key.startswith("00000000000KE") for item in kenya_items)

        # Nairobi project has exactly 1 item
        assert len(nairobi_items) == 1
        assert nairobi_items[0].detection_key.startswith("00000000000NB")

        # Demo project has exactly 3 items
        assert len(demo_items) == 3
        assert all(item.detection_key.startswith("00000000000DE") for item in demo_items)

    def test_count_detections_respects_boundaries(self, detection_repo, setup_multi_project_detections):
        """Test that detection count is accurate per project."""
        kenya_count = detection_repo.count_detections(project_slug="kenya-2024")
        nairobi_count = detection_repo.count_detections(project_slug="nairobi-2023")
        demo_count = detection_repo.count_detections(project_slug="demo-project")

        assert kenya_count == 2
        assert nairobi_count == 1
        assert demo_count == 3

    def test_filters_applied_within_project_isolation(self, detection_repo, setup_multi_project_detections):
        """Test that filters work correctly within project boundaries."""
        # Filter by species in Kenya
        kenya_cyanocorax = detection_repo.list_detections(
            project_slug="kenya-2024",
            page=1,
            page_size=10,
            scientific_name="Cyanocorax cyanopogon",
        )

        assert len(kenya_cyanocorax) == 1
        assert kenya_cyanocorax[0].detection_key == "00000000000KE001"

        # Same species in demo project should be independent
        demo_cyanocorax = detection_repo.list_detections(
            project_slug="demo-project",
            page=1,
            page_size=10,
            scientific_name="Cyanocorax cyanopogon",
        )

        assert len(demo_cyanocorax) == 1
        assert demo_cyanocorax[0].detection_key == "00000000000DE002"

    def test_confidence_filter_respects_project_boundaries(self, detection_repo, setup_multi_project_detections):
        """Test that confidence filtering doesn't leak across projects."""
        # Find high confidence items in each project
        high_confidence = 0.90

        kenya_high = detection_repo.list_detections(
            project_slug="kenya-2024",
            page=1,
            page_size=10,
            min_confidence=high_confidence,
        )
        nairobi_high = detection_repo.list_detections(
            project_slug="nairobi-2023",
            page=1,
            page_size=10,
            min_confidence=high_confidence,
        )

        assert len(kenya_high) == 1  # Only KE2024000001 (0.95)
        assert len(nairobi_high) == 1  # Only NB2023000001 (0.92)

    def test_nonexistent_project_returns_empty(self, detection_repo):
        """Test that querying a non-existent project returns empty results."""
        results = detection_repo.list_detections(
            project_slug="nonexistent-project", page=1, page_size=10
        )
        assert len(results) == 0

        count = detection_repo.count_detections(project_slug="nonexistent-project")
        assert count == 0


class TestValidationRepositoryProjectIsolation:
    """Test that ValidationRepository respects project boundaries."""

    @pytest.fixture
    def validation_repo(self):
        """Create a temporary validation repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield AppendOnlyValidationRepository(base_dir=temp_dir)

    def test_save_validation_isolates_by_project(self, validation_repo):
        """Test that validations are isolated per project."""
        # Save validation to project 1
        validation1 = Validation(
            detection_key="00000000PRJA0001",
            status="positive",
            validator="validator_demo",
            notes="Clear detection",
        )
        version1 = validation_repo.save_validation("kenya-2024", validation1)

        # Save validation with same key to project 2
        validation2 = Validation(
            detection_key="00000000PRJA0001",  # Same key but different project
            status="negative",
            validator="validator_other",
            notes="False alarm",
        )
        version2 = validation_repo.save_validation("nairobi-2023", validation2)

        # Both should be version 1 in their respective projects
        assert version1 == 1
        assert version2 == 1

        # Load snapshots - they should be different
        snapshot1 = validation_repo.load_current_snapshot("kenya-2024")
        snapshot2 = validation_repo.load_current_snapshot("nairobi-2023")

        assert snapshot1["00000000PRJA0001"]["status"] == "positive"
        assert snapshot2["00000000PRJA0001"]["status"] == "negative"

    def test_list_events_respects_project_boundaries(self, validation_repo):
        """Test that events are isolated per project."""
        # Add events to project 1
        val1 = Validation(
            detection_key="0000000000KEY001",
            status="positive",
            validator="user1",
        )
        validation_repo.save_validation("project-a", val1)

        val2 = Validation(
            detection_key="0000000000KEY002",
            status="negative",
            validator="user2",
        )
        validation_repo.save_validation("project-a", val2)

        # Add event to project 2
        val3 = Validation(
            detection_key="0000000000KEY001",  # Same key, different project
            status="uncertain",
            validator="user3",
        )
        validation_repo.save_validation("project-b", val3)

        # List events from each project
        events_a = validation_repo.list_events("project-a")
        events_b = validation_repo.list_events("project-b")

        # Project A has 2 events
        assert len(events_a) == 2
        assert all(e["project_slug"] == "project-a" for e in events_a)

        # Project B has 1 event
        assert len(events_b) == 1
        assert events_b[0]["project_slug"] == "project-b"

    def test_optimistic_lock_respects_project_scope(self, validation_repo):
        """Test that optimistic locking is per project."""
        # Save initial validation to project 1
        val = Validation(
            detection_key="0000000000TEST001",
            status="positive",
            validator="user1",
        )
        v1 = validation_repo.save_validation("proj1", val)
        assert v1 == 1

        # Update in project 1 with correct version
        val_update = Validation(
            detection_key="0000000000TEST001",
            status="negative",
            validator="user1",
        )
        v2 = validation_repo.save_validation("proj1", val_update, expected_version=1)
        assert v2 == 2

        # In project 2, same key should be at version 0
        val_other = Validation(
            detection_key="0000000000TEST001",
            status="uncertain",
            validator="user2",
        )
        # Should succeed because version 0 is correct for project 2
        v1_other = validation_repo.save_validation("proj2", val_other)
        assert v1_other == 1

    def test_nonexistent_project_returns_empty_snapshot(self, validation_repo):
        """Test that querying non-existent project returns empty snapshot."""
        snapshot = validation_repo.load_current_snapshot("nonexistent")
        assert snapshot == {}

        events = validation_repo.list_events("nonexistent")
        assert events == []


class TestAuthServiceWithRepositoryIntegration:
    """Test that AuthService correctly controls access to repositories."""

    @pytest.fixture
    def auth_service(self):
        """Create an auth service with test users."""
        service = AuthService()

        # Setup users with different project access
        service.register_user_project_access(
            "admin_user",
            {"project-a": Role.admin, "project-b": Role.admin},
        )
        service.register_user_project_access(
            "validator_a",
            {"project-a": Role.validator},
        )
        service.register_user_project_access(
            "validator_b",
            {"project-b": Role.validator},
        )

        return service

    def test_user_can_only_see_authorized_projects(self, auth_service):
        """Test that users can only access their authorized projects."""
        # Validator A should see project-a
        assert auth_service.is_user_authorized_for_project("validator_a", "project-a")
        assert not auth_service.is_user_authorized_for_project("validator_a", "project-b")

        # Validator B should see project-b
        assert auth_service.is_user_authorized_for_project("validator_b", "project-b")
        assert not auth_service.is_user_authorized_for_project("validator_b", "project-a")

        # Admin should see both
        assert auth_service.is_user_authorized_for_project("admin_user", "project-a")
        assert auth_service.is_user_authorized_for_project("admin_user", "project-b")

    def test_session_contains_only_authorized_projects(self, auth_service):
        """Test that session lists only authorized projects."""
        session_a = auth_service.login("validator_a")
        assert session_a.authorized_projects == ["project-a"]

        session_b = auth_service.login("validator_b")
        assert session_b.authorized_projects == ["project-b"]

        session_admin = auth_service.login("admin_user")
        assert sorted(session_admin.authorized_projects) == ["project-a", "project-b"]

    def test_user_role_isolation_per_project(self, auth_service):
        """Test that user roles are correctly isolated per project."""
        # Create a user with mixed roles
        auth_service.register_user_project_access(
            "mixed_user",
            {"proj1": Role.admin, "proj2": Role.validator},
        )

        # Check roles per project
        assert auth_service.get_user_role_for_project("mixed_user", "proj1") == Role.admin
        assert auth_service.get_user_role_for_project("mixed_user", "proj2") == Role.validator
        assert auth_service.get_user_role_for_project("mixed_user", "proj3") is None
