from collections import defaultdict
from typing import DefaultDict

from src.domain.models import Validation
from src.repositories.append_only_validation_repository import OptimisticLockError


class InMemoryValidationRepository:
    def __init__(self) -> None:
        self._by_project: DefaultDict[str, list[Validation]] = defaultdict(list)
        self._versions: DefaultDict[str, dict[str, int]] = defaultdict(dict)

    def save_validation(self, project_slug: str, item: Validation, expected_version: int | None = None) -> int:
        current_version = int(self._versions[project_slug].get(item.detection_key, 0))
        expected = expected_version if expected_version is not None else current_version
        if expected != current_version:
            raise OptimisticLockError(item.detection_key, expected, current_version)

        self._by_project[project_slug].append(item)
        new_version = current_version + 1
        self._versions[project_slug][item.detection_key] = new_version
        return new_version

    def list_validations(self, project_slug: str) -> list[Validation]:
        return list(self._by_project.get(project_slug, []))
