from typing import Protocol

from src.domain.models import Detection, Project, User, Validation


class ProjectRepository(Protocol):
    def get_project(self, project_slug: str) -> Project: ...


class DetectionRepository(Protocol):
    def list_detections(
        self,
        project_slug: str,
        page: int,
        page_size: int,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> list[Detection]: ...

    def count_detections(
        self,
        project_slug: str,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> int: ...


class ValidationRepository(Protocol):
    def save_validation(self, project_slug: str, item: Validation, expected_version: int | None = None) -> int: ...


class AuthRepository(Protocol):
    def authenticate(self, username: str) -> User: ...
