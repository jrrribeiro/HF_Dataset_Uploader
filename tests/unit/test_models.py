from src.domain.models import Detection, Role, User


def test_user_model() -> None:
    user = User(username="admin", role=Role.admin, active=True)
    assert user.username == "admin"


def test_detection_confidence_range() -> None:
    item = Detection(
        detection_key="abcd1234abcd1234",
        audio_id="audio_001",
        scientific_name="Cyanocorax cyanopogon",
        confidence=0.75,
        start_time=1.0,
        end_time=3.0,
    )
    assert item.confidence == 0.75
