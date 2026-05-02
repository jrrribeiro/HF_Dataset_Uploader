import json
from pathlib import Path

import pytest

from src.cli.project_cli import main


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_create_project_writes_projects_and_owner_acl(tmp_path: Path) -> None:
    projects_file = tmp_path / "projects.json"
    access_file = tmp_path / "user_access.json"
    projects_file.write_text("[]\n", encoding="utf-8")
    access_file.write_text("{}\n", encoding="utf-8")

    exit_code = main(
        [
            "create-project",
            "--projects-file",
            str(projects_file),
            "--user-access-file",
            str(access_file),
            "--slug",
            "amazonia-2026",
            "--name",
            "Amazonia 2026",
            "--dataset-repo-id",
            "birdnet/amazonia-2026",
            "--owner",
            "admin_user",
        ]
    )

    assert exit_code == 0
    projects = _read_json(projects_file)
    assert len(projects) == 1
    assert projects[0]["project_slug"] == "amazonia-2026"
    assert projects[0]["visibility"] == "collaborative"

    access = _read_json(access_file)
    assert access["admin_user"]["amazonia-2026"] == "admin"


def test_create_project_duplicate_slug_returns_error(tmp_path: Path) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            [
                {
                    "project_slug": "p1",
                    "name": "Project 1",
                    "dataset_repo_id": "org/p1",
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "create-project",
            "--projects-file",
            str(projects_file),
            "--slug",
            "p1",
            "--name",
            "Project 1",
            "--dataset-repo-id",
            "org/p1",
        ]
    )

    assert exit_code == 1


def test_init_build_and_verify_project_flow(tmp_path: Path) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            [
                {
                    "project_slug": "p2",
                    "name": "Project 2",
                    "dataset_repo_id": "org/p2",
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    dataset_root = tmp_path / "datasets"

    init_exit = main(
        [
            "init-dataset",
            "--dataset-root",
            str(dataset_root),
            "--slug",
            "p2",
            "--dataset-repo-id",
            "org/p2",
            "--name",
            "Project 2",
        ]
    )
    assert init_exit == 0

    detections_file = dataset_root / "p2" / "detections" / "detections.jsonl"
    detections_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "detection_key": "k1",
                        "audio_id": "a1",
                        "scientific_name": "Sp A",
                        "confidence": 0.6,
                    }
                ),
                json.dumps(
                    {
                        "detection_key": "k2",
                        "audio_id": "a2",
                        "scientific_name": "Sp B",
                        "confidence": 0.9,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    build_exit = main(
        [
            "build-index",
            "--dataset-root",
            str(dataset_root),
            "--slug",
            "p2",
        ]
    )
    assert build_exit == 0

    index_payload = _read_json(dataset_root / "p2" / "index" / "detections_index.json")
    assert index_payload["count"] == 2
    assert index_payload["detections"][0]["detection_key"] == "k2"

    verify_exit = main(
        [
            "verify-project",
            "--projects-file",
            str(projects_file),
            "--dataset-root",
            str(dataset_root),
            "--slug",
            "p2",
        ]
    )
    assert verify_exit == 0


def test_create_project_rejects_invalid_slug(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text("[]\n", encoding="utf-8")

    exit_code = main(
        [
            "create-project",
            "--projects-file",
            str(projects_file),
            "--slug",
            "Invalid Slug",
            "--name",
            "Project",
            "--dataset-repo-id",
            "org/p1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Invalid slug" in captured.out


def test_create_project_fails_on_invalid_projects_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text("{not-json", encoding="utf-8")

    exit_code = main(
        [
            "create-project",
            "--projects-file",
            str(projects_file),
            "--slug",
            "p3",
            "--name",
            "Project 3",
            "--dataset-repo-id",
            "org/p3",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Invalid JSON" in captured.out


def test_build_index_fails_on_invalid_jsonl_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset_root = tmp_path / "datasets"
    project_root = dataset_root / "p4"
    (project_root / "detections").mkdir(parents=True)
    (project_root / "index").mkdir(parents=True)
    (project_root / "detections" / "detections.jsonl").write_text("{bad json}\n", encoding="utf-8")

    exit_code = main(
        [
            "build-index",
            "--dataset-root",
            str(dataset_root),
            "--slug",
            "p4",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Invalid JSONL" in captured.out
    assert "line 1" in captured.out


def test_build_index_fails_on_non_numeric_confidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset_root = tmp_path / "datasets"
    project_root = dataset_root / "p5"
    (project_root / "detections").mkdir(parents=True)
    (project_root / "index").mkdir(parents=True)
    (project_root / "detections" / "detections.jsonl").write_text(
        json.dumps(
            {
                "detection_key": "k1",
                "audio_id": "a1",
                "scientific_name": "Sp",
                "confidence": "not-a-number",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "build-index",
            "--dataset-root",
            str(dataset_root),
            "--slug",
            "p5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "confidence" in captured.out


def test_verify_project_rejects_invalid_projects_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(json.dumps({"project_slug": "p2"}), encoding="utf-8")

    exit_code = main(
        [
            "verify-project",
            "--projects-file",
            str(projects_file),
            "--dataset-root",
            str(tmp_path / "datasets"),
            "--slug",
            "p2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Expected list" in captured.out


def test_verify_project_dry_run_returns_ok_with_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            [
                {
                    "project_slug": "p6",
                    "name": "Project 6",
                    "dataset_repo_id": "org/p6",
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "verify-project",
            "--projects-file",
            str(projects_file),
            "--dataset-root",
            str(tmp_path / "datasets"),
            "--slug",
            "p6",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DRY-RUN" in captured.out
    assert "missing path" in captured.out


def test_verify_project_dry_run_still_validates_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    projects_file = tmp_path / "projects.json"
    projects_file.write_text("{bad-json", encoding="utf-8")

    exit_code = main(
        [
            "verify-project",
            "--projects-file",
            str(projects_file),
            "--dataset-root",
            str(tmp_path / "datasets"),
            "--slug",
            "p6",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Invalid JSON" in captured.out
