from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_DATASET_DIRS = [
    "audio",
    "detections",
    "index",
    "exports",
]

EXIT_OK = 0
EXIT_VALIDATION_ERROR = 1
EXIT_IO_ERROR = 2

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
REPO_ID_PATTERN = re.compile(r"^[^\s/]+/[^\s/]+$")


class CliValidationError(ValueError):
    pass


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except UnicodeDecodeError as exc:
        raise CliValidationError(f"Invalid UTF-8 content in {path}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"Could not read {path}: {exc}") from exc


def _validate_slug(slug: str) -> None:
    if not SLUG_PATTERN.fullmatch(slug):
        raise CliValidationError(
            "Invalid slug. Use lowercase letters, numbers, and hyphens, length 2-63."
        )


def _validate_repo_id(repo_id: str) -> None:
    if not REPO_ID_PATTERN.fullmatch(repo_id):
        raise CliValidationError(
            "Invalid dataset_repo_id. Expected format 'owner/repo' without spaces."
        )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    raw = _safe_read_text(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliValidationError(f"Invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _project_exists(projects: list[dict[str, Any]], slug: str) -> bool:
    return any(p.get("project_slug") == slug for p in projects)


def _as_project_list(payload: Any, source: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise CliValidationError(f"Expected list in {source}, got {type(payload).__name__}")
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise CliValidationError(f"Project entry at index {idx} in {source} is not an object")
        for field in ("project_slug", "name", "dataset_repo_id"):
            if field not in item or not isinstance(item[field], str) or not item[field].strip():
                raise CliValidationError(
                    f"Project entry at index {idx} in {source} has invalid '{field}'"
                )
    return payload


def _as_access_map(payload: Any, source: Path) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise CliValidationError(f"Expected object in {source}, got {type(payload).__name__}")
    for username, roles in payload.items():
        if not isinstance(username, str) or not username.strip():
            raise CliValidationError(f"Invalid username key in {source}")
        if not isinstance(roles, dict):
            raise CliValidationError(f"Roles for '{username}' in {source} must be an object")
        for project_slug, role in roles.items():
            if not isinstance(project_slug, str) or not project_slug.strip():
                raise CliValidationError(f"Invalid project slug for user '{username}' in {source}")
            if role not in {"admin", "validator"}:
                raise CliValidationError(
                    f"Invalid role '{role}' for user '{username}' and project '{project_slug}' in {source}"
                )
    return payload


def cmd_create_project(args: argparse.Namespace) -> int:
    _validate_slug(args.slug)
    _validate_repo_id(args.dataset_repo_id)

    if args.owner and not args.owner.strip():
        raise CliValidationError("Owner cannot be blank")

    projects_file = Path(args.projects_file)
    projects = _as_project_list(_load_json(projects_file, []), projects_file)

    if _project_exists(projects, args.slug):
        print(f"ERROR: project '{args.slug}' already exists")
        return EXIT_VALIDATION_ERROR

    project_entry: dict[str, Any] = {
        "project_id": str(uuid4()),
        "project_slug": args.slug,
        "name": args.name,
        "dataset_repo_id": args.dataset_repo_id,
        "visibility": args.visibility,
        "active": not args.inactive,
    }
    if args.owner:
        project_entry["owner_username"] = args.owner
    if args.dataset_token:
        project_entry["dataset_token"] = args.dataset_token

    projects.append(project_entry)
    projects.sort(key=lambda p: str(p.get("project_slug", "")))
    _write_json(projects_file, projects)

    if args.user_access_file and args.owner:
        access_file = Path(args.user_access_file)
        access_payload = _as_access_map(_load_json(access_file, {}), access_file)
        owner_roles = access_payload.setdefault(args.owner, {})
        owner_roles[args.slug] = "admin"
        _write_json(access_file, access_payload)

    print(f"OK: project '{args.slug}' created")
    return EXIT_OK


def cmd_init_dataset(args: argparse.Namespace) -> int:
    _validate_slug(args.slug)
    _validate_repo_id(args.dataset_repo_id)

    root = Path(args.dataset_root) / args.slug
    for dirname in DEFAULT_DATASET_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)

    detections_file = root / "detections" / "detections.jsonl"
    if not detections_file.exists():
        detections_file.write_text("", encoding="utf-8")

    metadata = {
        "project_slug": args.slug,
        "dataset_repo_id": args.dataset_repo_id,
    }
    if args.name:
        metadata["name"] = args.name

    _write_json(root / "index" / "project_metadata.json", metadata)
    print(f"OK: dataset scaffold initialized at {root}")
    return EXIT_OK


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows

    raw_content = _safe_read_text(path)
    for line_no, raw in enumerate(raw_content.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CliValidationError(
                f"Invalid JSONL in {path} at line {line_no}: {exc.msg} (column {exc.colno})"
            ) from exc

        if not isinstance(parsed, dict):
            raise CliValidationError(
                f"Invalid JSONL in {path} at line {line_no}: expected object per line"
            )

        required = ("detection_key", "audio_id", "scientific_name", "confidence")
        for field in required:
            if field not in parsed:
                raise CliValidationError(
                    f"Invalid JSONL in {path} at line {line_no}: missing '{field}'"
                )

        try:
            parsed["confidence"] = float(parsed["confidence"])
        except (TypeError, ValueError) as exc:
            raise CliValidationError(
                f"Invalid JSONL in {path} at line {line_no}: 'confidence' must be numeric"
            ) from exc

        rows.append(parsed)
    return rows


def cmd_build_index(args: argparse.Namespace) -> int:
    _validate_slug(args.slug)

    project_root = Path(args.dataset_root) / args.slug
    detections_file = project_root / "detections" / "detections.jsonl"
    rows = _read_jsonl(detections_file)

    sorted_rows = sorted(rows, key=lambda d: d["confidence"], reverse=True)
    index_payload = {
        "project_slug": args.slug,
        "count": len(sorted_rows),
        "detections": [
            {
                "detection_key": r.get("detection_key"),
                "audio_id": r.get("audio_id"),
                "scientific_name": r.get("scientific_name"),
                "confidence": r["confidence"],
            }
            for r in sorted_rows
        ],
    }

    _write_json(project_root / "index" / "detections_index.json", index_payload)
    print(f"OK: index generated with {len(sorted_rows)} detections")
    return EXIT_OK


def cmd_verify_project(args: argparse.Namespace) -> int:
    _validate_slug(args.slug)

    projects_file = Path(args.projects_file)
    projects = _as_project_list(_load_json(projects_file, []), projects_file)

    findings: list[str] = []

    if not _project_exists(projects, args.slug):
        findings.append(f"project '{args.slug}' not found in {projects_file}")

    project_root = Path(args.dataset_root) / args.slug
    for dirname in DEFAULT_DATASET_DIRS:
        expected = project_root / dirname
        if not expected.exists():
            findings.append(f"missing path: {expected}")

    required_files = [
        project_root / "detections" / "detections.jsonl",
        project_root / "index" / "project_metadata.json",
        project_root / "index" / "detections_index.json",
    ]
    for required in required_files:
        if not required.exists():
            findings.append(f"missing path: {required}")

    if findings:
        if args.dry_run:
            print("DRY-RUN: project verification found issues:")
        else:
            print("ERROR: project verification failed:")
        for item in findings:
            print(f" - {item}")
        if args.dry_run:
            print("DRY-RUN: completed without failing exit code")
            return EXIT_OK
        return EXIT_VALIDATION_ERROR

    print(f"OK: project '{args.slug}' verified")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="birdnet-project")
    sub = parser.add_subparsers(dest="command", required=True)

    create_project = sub.add_parser("create-project", help="Create project in bootstrap JSON")
    create_project.add_argument("--projects-file", required=True)
    create_project.add_argument("--user-access-file")
    create_project.add_argument("--slug", required=True)
    create_project.add_argument("--name", required=True)
    create_project.add_argument("--dataset-repo-id", required=True)
    create_project.add_argument("--visibility", choices=["private", "collaborative"], default="collaborative")
    create_project.add_argument("--owner")
    create_project.add_argument("--dataset-token")
    create_project.add_argument("--inactive", action="store_true")
    create_project.set_defaults(func=cmd_create_project)

    init_dataset = sub.add_parser("init-dataset", help="Create initial dataset folder scaffold")
    init_dataset.add_argument("--dataset-root", required=True)
    init_dataset.add_argument("--slug", required=True)
    init_dataset.add_argument("--dataset-repo-id", required=True)
    init_dataset.add_argument("--name")
    init_dataset.set_defaults(func=cmd_init_dataset)

    build_index = sub.add_parser("build-index", help="Build simple index from detections JSONL")
    build_index.add_argument("--dataset-root", required=True)
    build_index.add_argument("--slug", required=True)
    build_index.set_defaults(func=cmd_build_index)

    verify_project = sub.add_parser("verify-project", help="Verify project config and local scaffold")
    verify_project.add_argument("--projects-file", required=True)
    verify_project.add_argument("--dataset-root", required=True)
    verify_project.add_argument("--slug", required=True)
    verify_project.add_argument(
        "--dry-run",
        action="store_true",
        help="Print verification findings without returning a failure exit code",
    )
    verify_project.set_defaults(func=cmd_verify_project)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.func(args))
    except CliValidationError as exc:
        print(f"ERROR: {exc}")
        return EXIT_VALIDATION_ERROR
    except OSError as exc:
        print(f"ERROR: I/O failure: {exc}")
        return EXIT_IO_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
