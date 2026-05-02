from collections import defaultdict
from typing import DefaultDict

from src.domain.models import Detection


class InMemoryDetectionRepository:
    def __init__(self) -> None:
        self._project_items: DefaultDict[str, list[Detection]] = defaultdict(list)

    def seed(self, project_slug: str, detections: list[Detection]) -> None:
        self._project_items[project_slug] = list(detections)

    def list_detections(
        self,
        project_slug: str,
        page: int,
        page_size: int,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> list[Detection]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")

        filtered = self._apply_filters(
            project_slug=project_slug,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
        )

        start = (page - 1) * page_size
        end = start + page_size
        return filtered[start:end]

    def count_detections(
        self,
        project_slug: str,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> int:
        return len(
            self._apply_filters(
                project_slug=project_slug,
                scientific_name=scientific_name,
                min_confidence=min_confidence,
                max_confidence=max_confidence,
            )
        )

    def _apply_filters(
        self,
        project_slug: str,
        scientific_name: str | None,
        min_confidence: float | None,
        max_confidence: float | None,
    ) -> list[Detection]:
        items = self._project_items.get(project_slug, [])

        def match(item: Detection) -> bool:
            if scientific_name and item.scientific_name != scientific_name:
                return False
            if min_confidence is not None and item.confidence < min_confidence:
                return False
            if max_confidence is not None and item.confidence > max_confidence:
                return False
            return True

        return [item for item in items if match(item)]
