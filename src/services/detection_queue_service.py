from dataclasses import dataclass

from src.domain.models import Detection
from src.repositories.contracts import DetectionRepository


@dataclass(slots=True)
class DetectionPage:
    project_slug: str
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool
    items: list[Detection]


class DetectionQueueService:
    def __init__(self, repository: DetectionRepository) -> None:
        self._repository = repository

    def get_page(
        self,
        project_slug: str,
        page: int,
        page_size: int,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> DetectionPage:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")

        total_items = self._repository.count_detections(
            project_slug=project_slug,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
        )
        total_pages = max(1, ((total_items - 1) // page_size) + 1) if total_items else 1
        page = min(page, total_pages)

        items = self._repository.list_detections(
            project_slug=project_slug,
            page=page,
            page_size=page_size,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
        )

        return DetectionPage(
            project_slug=project_slug,
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
            items=items,
        )
