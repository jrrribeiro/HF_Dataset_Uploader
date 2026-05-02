"""Integration tests for validating local audio segments.

These tests demonstrate how to load audio from the local filesystem
and run it through the validation workflow, useful for testing with
local audio segments instead of remote datasets.
"""

from pathlib import Path

import pytest

from src.auth.auth_service import AuthService
from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.domain.models import Detection
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.repositories.in_memory_validation_repository import InMemoryValidationRepository
from src.services.audio_fetch_service import AudioFetchService
from src.services.detection_queue_service import DetectionQueueService
from src.services.validation_service import ValidationService


@pytest.fixture
def local_audio_files(tmp_path: Path) -> dict[str, Path]:
    """Create test audio files locally."""
    audio_dir = tmp_path / "audio_segments"
    audio_dir.mkdir()

    # Create minimal WAV files for testing
    files = {
        "segment_001.wav": audio_dir / "segment_001.wav",
        "segment_002.wav": audio_dir / "segment_002.wav",
        "segment_003.wav": audio_dir / "segment_003.wav",
    }

    for filename, filepath in files.items():
        # Write minimal WAV header + dummy audio data (16 bytes header + 100 bytes data)
        wav_header = b"RIFF" + (108).to_bytes(4, "little") + b"WAVEfmt " + \
                     (16).to_bytes(4, "little") + \
                     (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + \
                     (16000).to_bytes(4, "little") + (32000).to_bytes(4, "little") + \
                     (2).to_bytes(2, "little") + (16).to_bytes(2, "little") + \
                     b"data" + (64).to_bytes(4, "little") + (b"\x00" * 64)
        filepath.write_bytes(wav_header)

    return files


@pytest.fixture
def auth_service() -> AuthService:
    """Create auth service with test users."""
    service = AuthService()
    service.register_user_project_access(
        username="alice",
        project_access={"birds-local": "validator"}
    )
    return service


@pytest.fixture
def repositories() -> tuple[InMemoryDetectionRepository, InMemoryValidationRepository]:
    """Create in-memory repositories."""
    detection_repo = InMemoryDetectionRepository()
    validation_repo = InMemoryValidationRepository()
    return detection_repo, validation_repo


@pytest.fixture
def services(tmp_path: Path, repositories: tuple) -> tuple[AudioFetchService, ValidationService, DetectionQueueService]:
    """Create service instances for local audio testing."""
    detection_repo, validation_repo = repositories

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=120, max_files=20)
    audio_service = AudioFetchService(cache)
    validation_service = ValidationService(validation_repo)
    detection_queue = DetectionQueueService(detection_repo)

    return audio_service, validation_service, detection_queue


def test_load_local_audio_segment_and_create_detection(
    local_audio_files: dict[str, Path],
    repositories: tuple,
) -> None:
    """Test loading a local audio file and creating a detection from it."""
    detection_repo, _ = repositories
    segment_path = local_audio_files["segment_001.wav"]

    # Create a detection object for the local audio segment
    detection = Detection(
        detection_key="LOCAL-SEG-001-ABCD",
        audio_id=segment_path.name,
        scientific_name="Parus major",  # Great Tit
        confidence=0.85,
        start_time=0.5,
        end_time=2.5,
    )

    # Seed the detection into the repository
    detection_repo.seed(project_slug="birds-local", detections=[detection])

    # Verify detection was stored by listing all detections
    detections = detection_repo.list_detections(
        project_slug="birds-local",
        page=1,
        page_size=10,
    )
    assert len(detections) == 1
    assert detections[0].scientific_name == "Parus major"
    assert detections[0].confidence == 0.85


def test_fetch_local_audio_and_validate(
    local_audio_files: dict[str, Path],
    services: tuple,
    repositories: tuple,
) -> None:
    """Test fetching local audio and validating a detection."""
    audio_service, validation_service, _ = services
    detection_repo, _ = repositories
    segment_path = local_audio_files["segment_001.wav"]

    # Fetch the local audio file
    audio_result = audio_service.fetch_local(str(segment_path))

    assert audio_result.source == "local"
    assert Path(audio_result.local_path).exists()

    # Create and seed a detection for this audio
    detection = Detection(
        detection_key="LOCAL-SEG-002-EFGH",
        audio_id=segment_path.name,
        scientific_name="Turdus merula",  # European Blackbird
        confidence=0.92,
        start_time=1.0,
        end_time=3.0,
    )
    detection_repo.seed(project_slug="birds-local", detections=[detection])

    # Validate the detection
    result = validation_service.validate_detection(
        project_slug="birds-local",
        detection_key="LOCAL-SEG-002-EFGH",
        status="confirmed",
        validator="alice",
        notes="Clear call, high confidence",
        corrected_species="Turdus merula",
    )

    assert result.item.status == "confirmed"
    assert result.item.validator == "alice"
    assert result.item.notes == "Clear call, high confidence"


def test_validate_multiple_local_audio_segments(
    local_audio_files: dict[str, Path],
    services: tuple,
    repositories: tuple,
) -> None:
    """Test validating multiple local audio segments in one session."""
    audio_service, validation_service, _ = services
    detection_repo, _ = repositories
    segment_files = [
        (local_audio_files["segment_001.wav"], "species_1"),
        (local_audio_files["segment_002.wav"], "species_2"),
        (local_audio_files["segment_003.wav"], "species_3"),
    ]

    # Create and seed all detections first
    detections = []
    for idx, (segment_path, species) in enumerate(segment_files):
        detection = Detection(
            detection_key=f"LOCAL-BATCH-{idx:03d}-IJKL",
            audio_id=segment_path.name,
            scientific_name=species,
            confidence=0.80 + (idx * 0.05),
            start_time=0.5,
            end_time=2.5,
        )
        detections.append(detection)

    detection_repo.seed(project_slug="birds-local", detections=detections)

    validations = []

    for idx, (segment_path, species) in enumerate(segment_files):
        # Fetch local audio
        audio_result = audio_service.fetch_local(str(segment_path))
        assert audio_result.source in ("local", "cache")

        # Validate the detection
        validation_result = validation_service.validate_detection(
            project_slug="birds-local",
            detection_key=f"LOCAL-BATCH-{idx:03d}-IJKL",
            status="confirmed",
            validator=f"validator_{idx}",
            notes=f"Validated segment {idx + 1}",
        )
        validations.append(validation_result)

    # Verify all validations were created
    assert len(validations) == 3
    for idx, validation in enumerate(validations):
        assert validation.item.status == "confirmed"
        assert validation.item.validator == f"validator_{idx}"


def test_validation_table_with_local_segments(
    local_audio_files: dict[str, Path],
    services: tuple,
    repositories: tuple,
) -> None:
    """Test that validation table can display validations for local audio segments."""
    audio_service, validation_service, _ = services
    detection_repo, validation_repo = repositories

    segment_path = local_audio_files["segment_001.wav"]

    # 1. Create and seed detection for local audio
    detection = Detection(
        detection_key="LOCAL-UI-TEST-001",
        audio_id=segment_path.name,
        scientific_name="Accipiter nisus",  # Eurasian Sparrowhawk
        confidence=0.88,
        start_time=0.0,
        end_time=3.5,
    )
    detection_repo.seed(project_slug="birds-local", detections=[detection])

    # 2. Fetch the local audio
    audio_result = audio_service.fetch_local(str(segment_path))
    assert audio_result.source in ("local", "cache")

    # 3. Validate the detection
    validation_result = validation_service.validate_detection(
        project_slug="birds-local",
        detection_key="LOCAL-UI-TEST-001",
        status="confirmed",
        validator="ui_tester",
        notes="UI test validation",
        corrected_species="Accipiter nisus",
    )

    # 4. Retrieve validation to simulate table display
    project_validations = validation_repo.list_validations(project_slug="birds-local")

    # Verify the validation appears in the table
    assert len(project_validations) == 1
    assert project_validations[0].detection_key == "LOCAL-UI-TEST-001"
    assert project_validations[0].status == "confirmed"
    assert project_validations[0].corrected_species == "Accipiter nisus"


def test_local_audio_cache_reuse(
    local_audio_files: dict[str, Path],
    services: tuple,
) -> None:
    """Test that local audio files are cached efficiently on repeated access."""
    audio_service, _, _ = services
    segment_path = local_audio_files["segment_002.wav"]

    # First fetch
    result1 = audio_service.fetch_local(str(segment_path))
    assert result1.source == "local"
    path1 = result1.local_path

    # Second fetch should come from cache
    result2 = audio_service.fetch_local(str(segment_path))
    assert result2.source == "cache"
    assert result2.local_path == path1
    assert result2.cache_key == result1.cache_key

    # Cleanup
    audio_service.cleanup_after_validation(result1.cache_key)
    # After cleanup, next fetch should load from local again
    result3 = audio_service.fetch_local(str(segment_path))
    assert result3.source == "local"
