import pytest

from src.domain.models import Detection
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.detection_queue_service import DetectionQueueService


def _sample(project: str = "ppbio-rabeca") -> list[Detection]:
    return [
        Detection(
            detection_key="0000000000000001",
            audio_id="audio_001",
            scientific_name="Species A",
            confidence=0.91,
            start_time=0.0,
            end_time=1.0,
        ),
        Detection(
            detection_key="0000000000000002",
            audio_id="audio_002",
            scientific_name="Species B",
            confidence=0.61,
            start_time=0.0,
            end_time=1.0,
        ),
        Detection(
            detection_key="0000000000000003",
            audio_id="audio_003",
            scientific_name="Species A",
            confidence=0.75,
            start_time=0.0,
            end_time=1.0,
        ),
        Detection(
            detection_key="0000000000000004",
            audio_id="audio_004",
            scientific_name="Species C",
            confidence=0.40,
            start_time=0.0,
            end_time=1.0,
        ),
    ]


def test_get_page_basic_pagination() -> None:
    repo = InMemoryDetectionRepository()
    repo.seed("ppbio-rabeca", _sample())
    service = DetectionQueueService(repo)

    page = service.get_page(project_slug="ppbio-rabeca", page=1, page_size=2)

    assert page.total_items == 4
    assert page.total_pages == 2
    assert page.has_next is True
    assert page.has_previous is False
    assert len(page.items) == 2


def test_get_page_caps_requested_page_to_last_page() -> None:
    repo = InMemoryDetectionRepository()
    repo.seed("ppbio-rabeca", _sample())
    service = DetectionQueueService(repo)

    page = service.get_page(project_slug="ppbio-rabeca", page=99, page_size=3)

    assert page.page == 2
    assert page.total_pages == 2
    assert len(page.items) == 1


def test_get_page_with_filters() -> None:
    repo = InMemoryDetectionRepository()
    repo.seed("ppbio-rabeca", _sample())
    service = DetectionQueueService(repo)

    page = service.get_page(
        project_slug="ppbio-rabeca",
        page=1,
        page_size=10,
        scientific_name="Species A",
        min_confidence=0.8,
    )

    assert page.total_items == 1
    assert len(page.items) == 1
    assert page.items[0].detection_key == "0000000000000001"


def test_get_page_requires_positive_page_and_page_size() -> None:
    repo = InMemoryDetectionRepository()
    repo.seed("ppbio-rabeca", _sample())
    service = DetectionQueueService(repo)

    with pytest.raises(ValueError):
        _ = service.get_page(project_slug="ppbio-rabeca", page=0, page_size=10)

    with pytest.raises(ValueError):
        _ = service.get_page(project_slug="ppbio-rabeca", page=1, page_size=0)
