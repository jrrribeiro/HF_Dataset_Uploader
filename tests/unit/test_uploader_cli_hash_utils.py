from pathlib import Path

from src.uploader_cli.hash_utils import compute_file_hash, verify_file_integrity


def test_compute_file_hash_matches_known_sha256(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"hello world")

    assert compute_file_hash(file_path) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_verify_file_integrity_returns_true_for_matching_hash(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"birdnet")
    expected = compute_file_hash(file_path)

    assert verify_file_integrity(file_path, expected) is True


def test_verify_file_integrity_returns_false_for_mismatch(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"birdnet")

    assert verify_file_integrity(file_path, "0" * 64) is False
