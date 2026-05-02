from pathlib import Path

from src.uploader_cli.scanner import LocalScanner


def test_scan_folder_counts_audio_files(tmp_path: Path) -> None:
    species_dir = tmp_path / "Toucan"
    species_dir.mkdir(parents=True)
    (species_dir / "sample_001.wav").write_bytes(b"abc")
    (species_dir / "sample_002.mp3").write_bytes(b"abcdef")
    (species_dir / "ignore.txt").write_text("x", encoding="utf-8")

    result = LocalScanner().scan_folder(str(tmp_path))

    assert result["total_files"] == 2
    assert result["total_size"] == 9
    assert "Toucan" in result["by_species"]
    assert result["by_species"]["Toucan"][0]["relative_path"].endswith("sample_001.wav")
    assert len(result["by_species"]["Toucan"][0]["sha256"]) == 64


def test_scan_folder_uses_first_directory_as_species_for_nested_layout(tmp_path: Path) -> None:
    nested_dir = tmp_path / "Falcon" / "session_a" / "day_01"
    nested_dir.mkdir(parents=True)
    (nested_dir / "capture_001.wav").write_bytes(b"abc123")

    result = LocalScanner().scan_folder(str(tmp_path))

    assert result["total_files"] == 1
    assert result["total_size"] == 6
    assert "Falcon" in result["by_species"]
    item = result["by_species"]["Falcon"][0]
    assert item["relative_path"].startswith("Falcon/")
    assert item["species"] == "Falcon"
