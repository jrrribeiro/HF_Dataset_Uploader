from src.repositories.in_memory_validation_repository import InMemoryValidationRepository
from src.services.validation_service import ValidationService


def test_validate_detection_saves_item() -> None:
    repo = InMemoryValidationRepository()
    service = ValidationService(repo)

    result = service.validate_detection(
        project_slug="demo-project",
        detection_key="0000000000009999",
        status="positive",
        validator="validator-demo",
        notes="ok",
        expected_version=0,
    )

    assert result.item.status == "positive"
    assert result.item.validator == "validator-demo"
    assert result.new_version == 1
    saved = repo.list_validations("demo-project")
    assert len(saved) == 1
    assert saved[0].detection_key == "0000000000009999"
