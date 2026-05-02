import gradio as gr
import csv
import hashlib
import json
import os
import re
import tempfile
import wave
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

import numpy as np
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image

from src.config.runtime_config import RuntimeConfig
from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.domain.models import Detection, Project, Role
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository, OptimisticLockError
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.audio_fetch_service import AudioFetchService
from src.services.detection_queue_service import DetectionQueueService
from src.services.validation_service import ValidationService
from src.services.invite_email_notifier import EmailJSInviteEmailNotifier, InviteEmailNotifier
from src.auth.auth_service import AuthService
from src.ui.login_page import create_login_page
from src.ui.admin_panel import AdminPanelManager


class _AudioFetchResultProtocol(Protocol):
    cache_key: str
    local_path: str
    source: str


class _AudioServiceProtocol(Protocol):
    def fetch(
        self,
        dataset_repo: str,
        audio_id: str,
        allow_demo_fallback: bool = False,
        hf_token: str | None = None,
    ) -> _AudioFetchResultProtocol: ...

    def cleanup_after_validation(self, cache_key: str) -> None: ...


class _ValidationServiceProtocol(Protocol):
    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
        expected_version: int | None = None,
    ) -> object: ...


class _ValidationReadRepositoryProtocol(Protocol):
    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]: ...

    def list_events(self, project_slug: str) -> list[dict[str, object]]: ...


class _QueueServiceProtocol(Protocol):
    def get_page(
        self,
        project_slug: str,
        page: int,
        page_size: int,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> object: ...


def _seed_service() -> DetectionQueueService:
    return _seed_service_for_projects(["demo-project"])[0]


def _candidate_metadata_files(project_slug: str) -> list[str]:
    return [
        f"{project_slug}/detections.jsonl",
        f"{project_slug}/detections.json",
        f"{project_slug}/detections.csv",
        f"{project_slug}/segments.jsonl",
        f"{project_slug}/segments.json",
        f"{project_slug}/segments.csv",
        "detections.jsonl",
        "detections.json",
        "detections.csv",
        "segments.jsonl",
        "segments.json",
        "segments.csv",
        "metadata/detections.jsonl",
        "metadata/detections.json",
        "metadata/detections.csv",
        "metadata/segments.jsonl",
        "metadata/segments.json",
        "metadata/segments.csv",
        "validation/detections.jsonl",
        "validation/detections.json",
        "validation/detections.csv",
    ]


def _pick_row_value(raw: dict[str, object], keys: list[str]) -> str:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _to_float(value: object, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_audio_id(audio_value: str) -> str:
    normalized = audio_value.strip().replace("\\", "/")
    if normalized.startswith("audio/"):
        normalized = normalized[len("audio/") :]
    return normalized


def _build_detection_from_row(raw: dict[str, object], row_index: int, project_slug: str) -> Detection | None:
    row_project = _pick_row_value(raw, ["project_slug", "project", "project_id"])
    if row_project and row_project != project_slug:
        return None

    audio_id = _normalize_audio_id(
        _pick_row_value(
            raw,
            [
                "segment_path_in_repo",
                "segment_relpath",
                "audio_id",
                "audio_file",
                "audio_path",
                "segment_path",
                "file",
                "filepath",
                "path",
                "filename",
            ],
        )
    )
    if not audio_id:
        return None

    scientific_name = _pick_row_value(
        raw,
        [
            "scientific_name",
            "species",
            "species_name",
            "predicted_species",
            "label",
            "taxon",
        ],
    )
    if not scientific_name:
        scientific_name = "Unknown species"

    confidence = _to_float(
        raw.get("confidence", raw.get("score", raw.get("probability", raw.get("prediction_confidence", 1.0)))),
        1.0,
    )
    confidence = max(0.0, min(1.0, confidence))

    start_time = _to_float(
        raw.get("start_time", raw.get("start", raw.get("begin", raw.get("offset", raw.get("segment_start", 0.0))))),
        0.0,
    )
    end_time = _to_float(
        raw.get("end_time", raw.get("end", raw.get("stop", raw.get("segment_end", 0.0)))),
        0.0,
    )
    if end_time <= 0.0:
        duration = _to_float(raw.get("duration", 0.0), 0.0)
        if duration > 0.0:
            end_time = start_time + duration
    if end_time <= start_time:
        end_time = start_time + 1.0

    detection_key = _pick_row_value(raw, ["detection_key", "segment_id", "id", "uid", "key"])
    if not detection_key:
        stable = f"{project_slug}|{audio_id}|{scientific_name}|{start_time:.3f}|{end_time:.3f}|{row_index}"
        detection_key = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]

    try:
        return Detection(
            detection_key=detection_key,
            audio_id=audio_id,
            scientific_name=scientific_name,
            confidence=confidence,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception:
        return None


def _parse_detection_metadata_payload(payload: object, project_slug: str) -> list[Detection]:
    rows: list[dict[str, object]] = []
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        project_rows = payload.get(project_slug)
        if isinstance(project_rows, list):
            rows = [item for item in project_rows if isinstance(item, dict)]
        else:
            for key in ["detections", "segments", "items", "rows"]:
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    rows = [item for item in candidate if isinstance(item, dict)]
                    break

    parsed: list[Detection] = []
    seen_keys: set[str] = set()
    for index, row in enumerate(rows):
        detection = _build_detection_from_row(row, index, project_slug)
        if detection is None:
            continue
        if detection.detection_key in seen_keys:
            continue
        seen_keys.add(detection.detection_key)
        parsed.append(detection)
    return parsed


def _load_dataset_detections_for_project(project: Project) -> tuple[list[Detection], str]:
    dataset_repo = project.dataset_repo_id.strip()
    if not dataset_repo:
        return [], ""

    token = (project.dataset_token or "").strip() or None
    try:
        api = HfApi(token=token)
        repo_files = api.list_repo_files(repo_id=dataset_repo, repo_type="dataset")
    except Exception as exc:
        return [], f"⚠️ Could not list files for dataset {dataset_repo}: {exc}"

    if not repo_files:
        return [], f"⚠️ Dataset {dataset_repo} has no files."

    shard_detections, shard_warning = _load_detections_from_parquet_shards(
        project=project,
        dataset_repo=dataset_repo,
        token=token,
        repo_files=repo_files,
    )
    if shard_detections:
        return shard_detections, shard_warning

    preferred = _candidate_metadata_files(project.project_slug)
    selected_file = next((name for name in preferred if name in repo_files), "")
    if not selected_file:
        metadata_candidates = []
        for name in repo_files:
            lowered = name.lower()
            if lowered.startswith("audio/"):
                continue
            if not lowered.endswith((".json", ".jsonl", ".csv")):
                continue
            if "detection" in lowered or "segment" in lowered:
                metadata_candidates.append(name)
        if metadata_candidates:
            selected_file = sorted(metadata_candidates, key=lambda value: (len(value), value))[0]

    if not selected_file:
        parsed_from_paths = _build_detections_from_audio_paths(project, repo_files)
        if parsed_from_paths:
            return parsed_from_paths, ""
        return [], (
            f"⚠️ Dataset {dataset_repo} has no detection metadata file for project {project.project_slug}. "
            "Expected names like detections.jsonl / segments.csv (top-level, metadata/, or <project_slug>/), "
            "or audio files under audio/segments/<species>/..."
        )

    try:
        if token:
            downloaded_path = hf_hub_download(
                repo_id=dataset_repo,
                repo_type="dataset",
                filename=selected_file,
                token=token,
            )
        else:
            downloaded_path = hf_hub_download(
                repo_id=dataset_repo,
                repo_type="dataset",
                filename=selected_file,
            )
    except Exception as exc:
        return [], f"⚠️ Failed to download {selected_file} from {dataset_repo}: {exc}"

    metadata_path = Path(downloaded_path)
    try:
        if metadata_path.suffix.lower() == ".jsonl":
            rows = []
            for line in metadata_path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                value = json.loads(text)
                if isinstance(value, dict):
                    rows.append(value)
            parsed = _parse_detection_metadata_payload(rows, project.project_slug)
        elif metadata_path.suffix.lower() == ".csv":
            with metadata_path.open("r", encoding="utf-8", newline="") as file_handle:
                parsed = _parse_detection_metadata_payload(list(csv.DictReader(file_handle)), project.project_slug)
        else:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            parsed = _parse_detection_metadata_payload(payload, project.project_slug)
    except Exception as exc:
        return [], f"⚠️ Failed to parse detection metadata {selected_file} from {dataset_repo}: {exc}"

    if not parsed:
        parsed_from_paths = _build_detections_from_audio_paths(project, repo_files)
        if parsed_from_paths:
            return parsed_from_paths, ""
        return [], (
            f"⚠️ Metadata file {selected_file} from {dataset_repo} has no valid detections for project {project.project_slug}."
        )

    return parsed, ""


def _resolve_shard_paths_from_repo_files(repo_files: list[str]) -> list[str]:
    return sorted(
        {
            file_path
            for file_path in repo_files
            if str(file_path).lower().startswith("index/shards/") and str(file_path).lower().endswith(".parquet")
        }
    )


def _load_detections_from_parquet_shards(
    project: Project,
    dataset_repo: str,
    token: str | None,
    repo_files: list[str],
) -> tuple[list[Detection], str]:
    shard_paths = _resolve_shard_paths_from_repo_files(repo_files)

    if "manifest.json" in repo_files:
        try:
            if token:
                manifest_path = hf_hub_download(
                    repo_id=dataset_repo,
                    repo_type="dataset",
                    filename="manifest.json",
                    token=token,
                )
            else:
                manifest_path = hf_hub_download(
                    repo_id=dataset_repo,
                    repo_type="dataset",
                    filename="manifest.json",
                )
            manifest_payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifest_shards = manifest_payload.get("index", {}).get("shards", [])
            if isinstance(manifest_shards, list):
                manifest_paths = [
                    str(item.get("path", "")).strip()
                    for item in manifest_shards
                    if isinstance(item, dict)
                ]
                manifest_paths = [p for p in manifest_paths if p.lower().endswith(".parquet")]
                if manifest_paths:
                    shard_paths = manifest_paths
        except Exception:
            pass

    if not shard_paths:
        return [], ""

    try:
        import pandas as pd  # type: ignore[import-not-found]
    except Exception:
        return [], (
            f"⚠️ Dataset {dataset_repo} contains parquet index shards, but pandas/pyarrow are unavailable to read them."
        )

    rows: list[dict[str, object]] = []
    for shard_path in shard_paths:
        try:
            if token:
                downloaded = hf_hub_download(
                    repo_id=dataset_repo,
                    repo_type="dataset",
                    filename=shard_path,
                    token=token,
                )
            else:
                downloaded = hf_hub_download(
                    repo_id=dataset_repo,
                    repo_type="dataset",
                    filename=shard_path,
                )
            frame = pd.read_parquet(downloaded)
            rows.extend(frame.to_dict(orient="records"))
        except Exception:
            continue

    parsed = _parse_detection_metadata_payload(rows, project.project_slug)
    if not parsed:
        return [], f"⚠️ Dataset {dataset_repo} index shards were found but contain no rows for project {project.project_slug}."
    return parsed, ""


def _parse_segment_filename_hint(filename: str) -> tuple[float, float, float]:
    # Common uploader pattern: ..._12.0-15.0s_85%.wav
    segment_match = re.search(r"_(\d+(?:\.\d+)?)\-(\d+(?:\.\d+)?)s_(\d+(?:\.\d+)?)%", filename)
    if segment_match:
        start_time = float(segment_match.group(1))
        end_time = float(segment_match.group(2))
        confidence = float(segment_match.group(3)) / 100.0
        return start_time, end_time, max(0.0, min(1.0, confidence))

    # Fallback pattern without confidence: ..._12.0-15.0s
    basic_match = re.search(r"_(\d+(?:\.\d+)?)\-(\d+(?:\.\d+)?)s", filename)
    if basic_match:
        return float(basic_match.group(1)), float(basic_match.group(2)), 0.5

    return 0.0, 1.0, 0.5


def _build_detections_from_audio_paths(project: Project, repo_files: list[str]) -> list[Detection]:
    detections: list[Detection] = []
    seen_keys: set[str] = set()

    for file_path in repo_files:
        normalized = str(file_path).replace("\\", "/").strip()
        lower = normalized.lower()
        if not lower.startswith("audio/"):
            continue
        if not lower.endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a")):
            continue

        relative_audio_id = normalized[len("audio/") :]
        parts = relative_audio_id.split("/")
        if len(parts) < 2:
            continue

        if parts[0].lower() == "segments" and len(parts) >= 3:
            scientific_name = parts[1].replace("_", " ").strip() or "Unknown species"
        else:
            scientific_name = parts[-2].replace("_", " ").strip() or "Unknown species"

        filename = parts[-1]
        start_time, end_time, confidence = _parse_segment_filename_hint(filename)
        stable = f"{project.project_slug}|{relative_audio_id}|{scientific_name}|{start_time:.3f}|{end_time:.3f}"
        detection_key = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
        if detection_key in seen_keys:
            continue

        try:
            detections.append(
                Detection(
                    detection_key=detection_key,
                    audio_id=relative_audio_id,
                    scientific_name=scientific_name,
                    confidence=confidence,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
            seen_keys.add(detection_key)
        except Exception:
            continue

    return detections


def _seed_service_for_projects(
    project_slugs: list[str],
    seed_file_path: str | None = None,
    project_map: dict[str, Project] | None = None,
    allow_demo_defaults: bool = True,
) -> tuple[DetectionQueueService, list[str]]:
    repo = InMemoryDetectionRepository()
    detected_by_project = _load_seed_detections(seed_file_path)
    warnings: list[str] = []

    for project_slug in project_slugs:
        project = (project_map or {}).get(project_slug)
        dataset_items: list[Detection] = []
        if project is not None and project.active:
            dataset_items, dataset_warning = _load_dataset_detections_for_project(project)
            if dataset_warning:
                warnings.append(dataset_warning)

        seeded_items = detected_by_project.get(project_slug, [])
        if dataset_items:
            items = dataset_items
        elif seeded_items:
            items = seeded_items
        elif allow_demo_defaults:
            items = _default_demo_detections(project_slug)
        else:
            items = []
        items = sorted(items, key=lambda item: item.detection_key)
        repo.seed(project_slug, items)

    return DetectionQueueService(repo), warnings


def _build_detection_repository(
    project_slugs: list[str],
    seed_file_path: str | None,
    project_map: dict[str, Project] | None = None,
    allow_demo_defaults: bool = True,
) -> tuple[DetectionQueueService, str]:
    warning = _validate_seed_file(seed_file_path)
    service, dataset_warnings = _seed_service_for_projects(
        project_slugs,
        seed_file_path=seed_file_path,
        project_map=project_map,
        allow_demo_defaults=allow_demo_defaults,
    )

    warnings = [item for item in [warning, *dataset_warnings] if item.strip()]
    joined_warning = "\n\n".join(dict.fromkeys(warnings))
    return service, joined_warning


def _validate_seed_file(seed_file_path: str | None) -> str:
    if not seed_file_path:
        return ""

    normalized_path = Path(seed_file_path)
    if not normalized_path.exists():
        return (
            f"⚠️ BIRDNET_DETECTIONS_FILE not found: {normalized_path}. "
            "Set BIRDNET_DETECTIONS_FILE to a valid JSON file path or unset it to use default demo detections."
        )

    try:
        payload = json.loads(normalized_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (
            f"⚠️ BIRDNET_DETECTIONS_FILE invalid: {exc}. "
            "Fix JSON syntax and ensure UTF-8 encoding."
        )

    if isinstance(payload, dict):
        non_list_projects = [slug for slug, rows in payload.items() if not isinstance(rows, list)]
        if non_list_projects:
            sample = ", ".join(non_list_projects[:3])
            return (
                f"⚠️ Invalid seed JSON: projects without a detection list ({sample}). "
                "Each project key must map to a list of detection objects."
            )
        return ""

    if isinstance(payload, list):
        missing_project = 0
        for row in payload:
            if not isinstance(row, dict):
                continue
            if not str(row.get("project_slug", "")).strip():
                missing_project += 1
        if missing_project:
            return (
                "⚠️ Invalid seed JSON: entries without project_slug in list. "
                "Add project_slug to each detection object when using list format."
            )
        return ""

    return (
        "⚠️ Invalid seed JSON: format must be object-by-project or detection list. "
        "See README for supported examples."
    )


def _default_demo_detections(project_slug: str) -> list[Detection]:
    stable_prefix = hashlib.sha1(project_slug.encode("utf-8")).hexdigest()[:8]
    slug_prefix = project_slug.replace("-", "_")
    return [
        Detection(
            detection_key=f"{stable_prefix}00001001",
            audio_id=f"{slug_prefix}_audio_1001",
            scientific_name="Cyanocorax cyanopogon",
            confidence=0.93,
            start_time=1.2,
            end_time=2.5,
        ),
        Detection(
            detection_key=f"{stable_prefix}00001002",
            audio_id=f"{slug_prefix}_audio_1002",
            scientific_name="Ramphastos toco",
            confidence=0.88,
            start_time=0.8,
            end_time=2.1,
        ),
        Detection(
            detection_key=f"{stable_prefix}00001003",
            audio_id=f"{slug_prefix}_audio_1003",
            scientific_name="Cyanocorax cyanopogon",
            confidence=0.72,
            start_time=3.1,
            end_time=4.0,
        ),
        Detection(
            detection_key=f"{stable_prefix}00001004",
            audio_id=f"{slug_prefix}_audio_1004",
            scientific_name="Psarocolius decumanus",
            confidence=0.67,
            start_time=5.0,
            end_time=6.3,
        ),
    ]


def _load_seed_detections(seed_file_path: str | None) -> dict[str, list[Detection]]:
    if not seed_file_path:
        return {}

    normalized_path = Path(seed_file_path)
    if not normalized_path.exists():
        return {}

    try:
        payload = json.loads(normalized_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    result: dict[str, list[Detection]] = {}

    if isinstance(payload, dict):
        for project_slug, rows in payload.items():
            parsed_rows = _parse_detection_rows(rows)
            if parsed_rows:
                result[str(project_slug)] = parsed_rows
        return result

    if isinstance(payload, list):
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            project_slug = str(row.get("project_slug", "")).strip()
            if not project_slug:
                continue
            grouped.setdefault(project_slug, []).append(row)

        for project_slug, rows in grouped.items():
            parsed_rows = _parse_detection_rows(rows)
            if parsed_rows:
                result[project_slug] = parsed_rows

    return result


def _parse_detection_rows(rows: object) -> list[Detection]:
    parsed: list[Detection] = []
    if not isinstance(rows, list):
        return parsed

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            parsed.append(
                Detection(
                    detection_key=str(raw.get("detection_key", "")).strip(),
                    audio_id=str(raw.get("audio_id", "")).strip(),
                    scientific_name=str(raw.get("scientific_name", "")).strip(),
                    confidence=float(raw.get("confidence", 0.0)),
                    start_time=float(raw.get("start_time", 0.0)),
                    end_time=float(raw.get("end_time", 0.0)),
                )
            )
        except Exception:
            continue

    return parsed


def _default_projects() -> list[Project]:
    return [
        Project(
            project_slug="kenya-2024",
            name="Kenya Survey 2024",
            dataset_repo_id="birdnet/kenya-2024-dataset",
            active=True,
        ),
        Project(
            project_slug="nairobi-2023",
            name="Nairobi Survey 2023",
            dataset_repo_id="birdnet/nairobi-2023-dataset",
            active=True,
        ),
        Project(
            project_slug="demo-project",
            name="Demo Project",
            dataset_repo_id="birdnet/demo-dataset",
            active=True,
        ),
    ]


def _default_user_access() -> dict[str, dict[str, Role]]:
    return {
        "demo_user": {"demo-project": Role.validator, "birds-local": Role.validator},
        "admin_user": {"kenya-2024": Role.admin, "nairobi-2023": Role.admin},
        "validator_demo": {"demo-project": Role.validator, "kenya-2024": Role.validator},
        "validator_other": {"nairobi-2023": Role.validator},
    }


def _load_projects_from_file(projects_file_path: str | None) -> list[Project]:
    if not projects_file_path:
        return []

    path = Path(projects_file_path)
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    projects: list[Project] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            slug = str(row.get("project_slug", "")).strip()
            project_id = str(row.get("project_id", "")).strip()
            if not project_id and slug:
                # Deterministic legacy migration so IDs are stable before first re-persist.
                project_id = str(uuid5(NAMESPACE_URL, f"birdnet-validator:{slug}"))
            projects.append(
                Project(
                    project_id=project_id or str(uuid4()),
                    project_slug=slug,
                    name=str(row.get("name", "")).strip(),
                    dataset_repo_id=str(row.get("dataset_repo_id", "")).strip(),
                    visibility=str(row.get("visibility", "collaborative")).strip() or "collaborative",
                    owner_username=(str(row.get("owner_username", "")).strip() or None),
                    dataset_token=(str(row.get("dataset_token", "")).strip() or None),
                    active=bool(row.get("active", True)),
                )
            )
        except Exception:
            continue
    return projects


def _load_user_access_from_file(user_access_file_path: str | None) -> dict[str, dict[str, Role]]:
    if not user_access_file_path:
        return {}

    path = Path(user_access_file_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    result: dict[str, dict[str, Role]] = {}
    for username, roles_payload in payload.items():
        if not isinstance(roles_payload, dict):
            continue
        normalized_roles: dict[str, Role] = {}
        for project_slug, role_value in roles_payload.items():
            role_text = str(role_value).strip().lower()
            if role_text not in {"admin", "validator"}:
                continue
            normalized_roles[str(project_slug)] = Role(role_text)
        result[str(username)] = normalized_roles
    return result


def _load_pending_invites_from_file(invites_file_path: str | None) -> dict[str, dict[str, dict[str, str]]]:
    if not invites_file_path:
        return {}

    path = Path(invites_file_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def _resolve_bootstrap_file_paths(runtime_config: RuntimeConfig) -> tuple[Path, Path, Path]:
    bootstrap_dir = Path(runtime_config.bootstrap_base_dir)
    projects_path = Path(runtime_config.projects_file_path) if runtime_config.projects_file_path else (bootstrap_dir / "projects.json")
    user_access_path = Path(runtime_config.user_access_file_path) if runtime_config.user_access_file_path else (bootstrap_dir / "user_access.json")
    invites_path = Path(runtime_config.invites_file_path) if runtime_config.invites_file_path else (bootstrap_dir / "invites.json")
    return projects_path, user_access_path, invites_path


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp.{os.getpid()}"
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _persist_bootstrap_state(
    projects_path: Path,
    user_access_path: Path,
    invites_path: Path,
    admin_manager: AdminPanelManager,
    auth_service: AuthService,
) -> None:
    project_rows = admin_manager.list_projects()
    projects_payload = [
        {
            "project_id": str(project.get("project_id", "")).strip(),
            "project_slug": str(project.get("project_slug", "")).strip(),
            "name": str(project.get("name", "")).strip(),
            "dataset_repo_id": str(project.get("dataset_repo_id", "")).strip(),
            "visibility": str(project.get("visibility", "collaborative")).strip() or "collaborative",
            "owner_username": str(project.get("owner_username", "")).strip() or None,
            "dataset_token": str(project.get("dataset_token", "")).strip() or None,
            "active": bool(project.get("active", True)),
        }
        for project in project_rows
    ]
    _atomic_write_json(projects_path, projects_payload)

    access_payload = auth_service.export_user_access_map(include_inactive=True)
    _atomic_write_json(user_access_path, access_payload)

    invites_payload = auth_service.export_pending_invites_map()
    _atomic_write_json(invites_path, invites_payload)


def _bootstrap_auth_and_projects(
    auth_service: AuthService,
    admin_manager: AdminPanelManager,
    runtime_config: RuntimeConfig,
    projects_file_path: str | None = None,
    user_access_file_path: str | None = None,
    invites_file_path: str | None = None,
) -> str:
    projects = _load_projects_from_file(projects_file_path or runtime_config.projects_file_path)
    user_access = _load_user_access_from_file(user_access_file_path or runtime_config.user_access_file_path)
    pending_invites = _load_pending_invites_from_file(invites_file_path or runtime_config.invites_file_path)

    for project in projects:
        _ = admin_manager.register_project(project)

    for username, access in user_access.items():
        auth_service.register_user_project_access(username, access)

    # Enforce private-project owner-only ACL even if bootstrap files are malformed.
    for username in auth_service.list_usernames(include_inactive=True):
        for project_slug in list(auth_service.list_user_projects(username)):
            project = admin_manager.get_project(project_slug)
            if project is None:
                continue
            if project.visibility != "private":
                continue
            owner = (project.owner_username or "").strip()
            if not owner or username != owner:
                auth_service.remove_user_project_role(username, project_slug)

    auth_service.load_pending_invites_map(pending_invites)
    for invite in auth_service.list_all_pending_invites():
        project = admin_manager.get_project(invite.project_slug)
        if project is None:
            continue
        if project.visibility == "private":
            auth_service.revoke_project_invite(invite.username, invite.project_slug)

    emergency_admin_message = ""
    has_admin = any(
        role == "admin"
        for roles in auth_service.export_user_access_map(include_inactive=True).values()
        for role in roles.values()
    )
    if projects and not has_admin:
        emergency_admin_username = "admin_user"
        for project in projects:
            auth_service.upsert_user_project_role(emergency_admin_username, project.project_slug, Role.admin)
        auth_service.set_user_active(emergency_admin_username, True)
        emergency_admin_message = (
            "⚠️ No administrator was configured in bootstrap files. "
            "Emergency admin access was granted to username 'admin_user'."
        )

    if not projects:
        return ""

    return emergency_admin_message


def _page_to_table(
    service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    page_size: int = 25,
    validator_filter: str = "",
    status_filter: str = "all",
    updated_after: object = None,
    conflict_detection_key: str = "",
    show_conflicts_only: bool = False,
):
    filter_name = scientific_name.strip() if scientific_name.strip() else None
    page_obj = service.get_page(
        project_slug=project_slug,
        page=page,
        page_size=page_size,
        scientific_name=filter_name,
        min_confidence=min_confidence,
    )

    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)

    normalized_status_filter = status_filter.strip().lower() if status_filter else "all"
    normalized_validator_filter = validator_filter.strip().lower()
    updated_after_date: date | None = None
    if updated_after is not None:
        if isinstance(updated_after, datetime):
            updated_after_date = updated_after.date()
        elif isinstance(updated_after, date):
            updated_after_date = updated_after
        elif isinstance(updated_after, (int, float)):
            updated_after_date = datetime.fromtimestamp(float(updated_after)).date()
        else:
            updated_after_text = str(updated_after).strip()
            if updated_after_text:
                try:
                    updated_after_date = datetime.strptime(updated_after_text, "%Y-%m-%d").date()
                except ValueError:
                    try:
                        updated_after_date = datetime.fromisoformat(updated_after_text.replace("Z", "+00:00")).date()
                    except ValueError:
                        updated_after_date = None

    rows = [
        [
            item.detection_key,
            item.audio_id,
            item.scientific_name,
            round(item.confidence, 3),
            item.start_time,
            item.end_time,
            str(snapshot.get(item.detection_key, {}).get("status", "pending")),
            int(snapshot.get(item.detection_key, {}).get("version", 0)),
            "CONFLICT" if conflict_detection_key and item.detection_key == conflict_detection_key else "",
            "HIGH" if conflict_detection_key and item.detection_key == conflict_detection_key else "",
        ]
        for item in page_obj.items
    ]

    if normalized_validator_filter:
        rows = [
            row
            for row in rows
            if normalized_validator_filter in str(snapshot.get(str(row[0]), {}).get("validator", "")).strip().lower()
        ]

    if normalized_status_filter and normalized_status_filter != "all":
        rows = [row for row in rows if str(row[6]).strip().lower() == normalized_status_filter]

    if updated_after_date:
        filtered_rows: list[list[object]] = []
        for row in rows:
            snapshot_item = snapshot.get(str(row[0]), {})
            updated_at_value = str(snapshot_item.get("updated_at", "")).strip()
            if not updated_at_value:
                continue
            try:
                item_date = datetime.fromisoformat(updated_at_value.replace("Z", "+00:00")).date()
                if item_date >= updated_after_date:
                    filtered_rows.append(row)
            except ValueError:
                continue
        rows = filtered_rows

    if show_conflicts_only:
        rows = [row for row in rows if str(row[8]) == "CONFLICT"]

    status = f"Page {page_obj.page}/{page_obj.total_pages} | Base total: {page_obj.total_items} | Shown: {len(rows)}"
    if show_conflicts_only:
        status = f"{status} | Conflicts only: {len(rows)} item(ns)"
    return rows, status, page_obj.page


def _get_project_detection_count(service: _QueueServiceProtocol, project_slug: str) -> int:
    if not project_slug:
        return 0

    try:
        page_obj = service.get_page(
            project_slug=project_slug,
            page=1,
            page_size=1,
        )
        return int(getattr(page_obj, "total_items", 0))
    except Exception:
        return 0


def _build_queue_badge(service: _QueueServiceProtocol, project_slug: str | None) -> str:
    if not project_slug:
        return "<div style='display:inline-block;padding:6px 10px;border-radius:999px;background:#f3f4f6;color:#374151;font-weight:600;'>Queue: --</div>"

    total = _get_project_detection_count(service, project_slug)
    return (
        "<div style='display:inline-block;padding:6px 10px;border-radius:999px;"
        "background:#e0f2fe;color:#0c4a6e;font-weight:700;'>"
        f"Queue: {total}"
        "</div>"
    )


def _build_validation_report(snapshot_reader: _ValidationReadRepositoryProtocol, project_slug: str) -> str:
    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)
    events = snapshot_reader.list_events(project_slug=project_slug)

    counts: dict[str, int] = {}
    for payload in snapshot.values():
        status_value = str(payload.get("status", "unknown"))
        counts[status_value] = counts.get(status_value, 0) + 1

    parts = [
        f"Project: {project_slug}",
        f"Append-only events: {len(events)}",
        f"Detections with current state: {len(snapshot)}",
    ]
    if counts:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        parts.append(f"Current status: {summary}")
    else:
        parts.append("Current status: no validations")
    return " | ".join(parts)


def _extract_audio_id(rows: object, selected_index: int) -> str:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("No detections loaded in table")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Select a valid detection row in table")

    value = normalized_rows[selected_index][1]
    audio_id = str(value).strip()
    if not audio_id:
        raise ValueError("Invalid audio_id in selected detection")
    return audio_id


def _extract_detection_key(rows: object, selected_index: int) -> str:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("No detections loaded in table")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Select a valid detection row in table")

    value = normalized_rows[selected_index][0]
    detection_key = str(value).strip()
    if not detection_key:
        raise ValueError("Invalid detection_key in selected detection")
    return detection_key


def _find_detection_row_index(rows: object, detection_key: str) -> int:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    for index, row in enumerate(normalized_rows):
        if str(row[0]).strip() == detection_key:
            return index
    return 0


def _extract_expected_version(rows: object, selected_index: int) -> int:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("No detections loaded in table")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Select a valid detection row in table")

    value = normalized_rows[selected_index][7]
    return int(value)


def _fetch_selected_audio(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    selected_index: int,
    previous_cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[str | None, str, str]:
    repo = dataset_repo.strip()
    if not repo:
        return None, "", "Provide dataset repo in owner/repo format. Example: org/dataset-name"

    try:
        audio_id = _extract_audio_id(rows=rows, selected_index=selected_index)
        try:
            result = audio_service.fetch(
                dataset_repo=repo,
                audio_id=audio_id,
                allow_demo_fallback=allow_demo_fallback,
                hf_token=hf_token,
            )
        except TypeError:
            # Backward compatibility for fake/mocked services used in tests.
            result = audio_service.fetch(dataset_repo=repo, audio_id=audio_id)
        status = f"Audio loaded ({result.source}) for audio_id={audio_id}"
        return result.local_path, result.cache_key, status
    except Exception as exc:
        if previous_cache_key:
            return None, previous_cache_key, f"Failed to load audio: {exc}"
        return None, "", f"Failed to load audio: {exc}"


def _load_pcm_wave(audio_path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(audio_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)

    if sample_width == 1:
        audio = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        audio = (audio - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported PCM width: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    return sample_rate, audio


def _magma_like_colormap(normalized: np.ndarray) -> np.ndarray:
    # Lightweight gradient for spectrogram rendering (dark -> orange -> yellow).
    anchors = np.array(
        [
            [0, 0, 4],
            [28, 16, 68],
            [79, 18, 123],
            [129, 37, 129],
            [181, 54, 122],
            [229, 80, 100],
            [251, 135, 97],
            [254, 194, 135],
            [252, 253, 191],
        ],
        dtype=np.float32,
    )
    indices = np.clip((normalized * (len(anchors) - 1)).astype(np.float32), 0, len(anchors) - 1)
    lower = np.floor(indices).astype(np.int32)
    upper = np.clip(lower + 1, 0, len(anchors) - 1)
    blend = (indices - lower)[..., np.newaxis]
    rgb = anchors[lower] * (1.0 - blend) + anchors[upper] * blend
    return rgb.astype(np.uint8)


def _build_spectrogram_image(audio_path: str | None) -> str | None:
    if not audio_path:
        return None

    source_path = Path(audio_path)
    if not source_path.exists() or source_path.suffix.lower() != ".wav":
        return None

    try:
        _, samples = _load_pcm_wave(source_path)
    except Exception:
        return None

    if samples.size < 1024:
        return None

    window_size = 512
    hop_size = 128
    frame_count = 1 + max(0, (len(samples) - window_size) // hop_size)
    if frame_count <= 0:
        return None

    frames = np.lib.stride_tricks.sliding_window_view(samples, window_shape=window_size)[::hop_size]
    if frames.size == 0:
        return None

    window = np.hanning(window_size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    spectrum = np.maximum(spectrum, 1e-9)
    db = 20.0 * np.log10(spectrum)
    db = db.T
    low = float(np.percentile(db, 5))
    high = float(np.percentile(db, 99))
    if high <= low:
        return None

    normalized = np.clip((db - low) / (high - low), 0.0, 1.0)
    rgb = _magma_like_colormap(normalized)
    rgb = np.flipud(rgb)

    image = Image.fromarray(rgb, mode="RGB").resize((900, 320), resample=Image.Resampling.BICUBIC)
    cache_name = hashlib.sha1(f"{audio_path}:{source_path.stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    output_path = Path(tempfile.gettempdir()) / f"birdnet_validator_spec_{cache_name}.png"
    image.save(output_path)
    return str(output_path)


def _fetch_selected_audio_with_spectrogram(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    selected_index: int,
    previous_cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[str | None, str, str, str | None]:
    audio_path, cache_key, status = _fetch_selected_audio(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=rows,
        selected_index=selected_index,
        previous_cache_key=previous_cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    spectrogram_path = _build_spectrogram_image(audio_path)
    if audio_path and spectrogram_path is None:
        status = f"{status} | Spectrogram unavailable (requires WAV)."
    return audio_path, cache_key, status, spectrogram_path


def _build_validation_summary_cards(rows: object) -> str:
    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []
    total = len(normalized_rows)
    positive = 0
    negative = 0
    for row in normalized_rows:
        status_value = str(row[6]).strip().lower() if len(row) > 6 else ""
        if status_value == "positive":
            positive += 1
        elif status_value == "negative":
            negative += 1

    return (
        "<div style='display:grid;grid-template-columns:repeat(3,minmax(120px,1fr));gap:12px;margin:4px 0 12px 0;'>"
        f"<div style='padding:10px 14px;border-radius:10px;background:#ececec;'><div style='font-size:12px;color:#555;'>Total Items</div><div style='font-size:24px;font-weight:700;color:#222;'>{total}</div></div>"
        f"<div style='padding:10px 14px;border-radius:10px;background:#e7f4ea;'><div style='font-size:12px;color:#3f6c49;'>Positive</div><div style='font-size:24px;font-weight:700;color:#215d2f;'>{positive}</div></div>"
        f"<div style='padding:10px 14px;border-radius:10px;background:#fdeaea;'><div style='font-size:12px;color:#7b3a3a;'>Negative</div><div style='font-size:24px;font-weight:700;color:#6f1f1f;'>{negative}</div></div>"
        "</div>"
    )


def _autofetch_first_row(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[int, str | None, str, str, str | None]:
    normalized_rows = _normalize_rows(rows)
    if not normalized_rows:
        return 0, None, "", "No detections available to auto-load audio", None

    audio_path, updated_cache_key, status, spectrogram_path = _fetch_selected_audio_with_spectrogram(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=normalized_rows,
        selected_index=0,
        previous_cache_key=cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    return 0, audio_path, updated_cache_key, status, spectrogram_path


def _select_and_fetch_audio(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    cache_key: str,
    evt: gr.SelectData,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[int, str | None, str, str, str | None]:
    if isinstance(evt.index, tuple):
        selected_index = int(evt.index[0])
    elif isinstance(evt.index, int):
        selected_index = int(evt.index)
    else:
        selected_index = 0

    audio_path, updated_cache_key, status, spectrogram_path = _fetch_selected_audio_with_spectrogram(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=rows,
        selected_index=selected_index,
        previous_cache_key=cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    return selected_index, audio_path, updated_cache_key, status, spectrogram_path


def _normalize_rows(rows: object) -> list[list[object]]:
    if hasattr(rows, "values"):
        return [list(item) for item in rows.values.tolist()]
    return [list(item) for item in rows] if rows else []


def _spectrogram_title(species_name: str | None, confidence: float | None) -> str:
    if not species_name or confidence is None:
        return "### Spectrogram"
    return f"### {species_name} - {confidence:.3f}"


def _selected_row_species_and_confidence(rows: object, selected_index: int) -> tuple[str | None, float | None]:
    normalized_rows = _normalize_rows(rows)
    if normalized_rows:
        safe_index = max(0, min(int(selected_index), len(normalized_rows) - 1))
        row = normalized_rows[safe_index]

        species_name: str | None = None
        confidence_value: float | None = None

        if len(row) > 2:
            raw_species = str(row[2]).strip()
            if raw_species.startswith("▶ "):
                raw_species = raw_species[2:].strip()
            species_name = raw_species or None

        if len(row) > 3:
            try:
                confidence_value = float(row[3])
            except Exception:
                confidence_value = None

        return species_name, confidence_value

    return None, None


def _mark_selected_row(rows: object, selected_index: int) -> list[list[object]]:
    normalized_rows = _normalize_rows(rows)
    if not normalized_rows:
        return []

    safe_index = max(0, min(int(selected_index), len(normalized_rows) - 1))
    marked_rows: list[list[object]] = []
    for row_index, row in enumerate(normalized_rows):
        updated = list(row)
        if len(updated) > 2:
            species = str(updated[2])
            if species.startswith("▶ "):
                species = species[2:]
            if row_index == safe_index:
                species = f"▶ {species}"
            updated[2] = species
        marked_rows.append(updated)

    return marked_rows


def _paginate_rows(rows: list[list[object]], page: int, page_size: int) -> tuple[list[list[object]], int, int]:
    total_items = len(rows)
    total_pages = max(1, ((total_items - 1) // page_size) + 1) if total_items else 1
    safe_page = max(1, min(page, total_pages))
    start = (safe_page - 1) * page_size
    end = start + page_size
    return rows[start:end], safe_page, total_pages


def _extract_species_options_from_queue(
    queue_service: _QueueServiceProtocol,
    project_slug: str,
    page_size: int,
) -> list[str]:
    if not project_slug:
        return []

    species_set: set[str] = set()
    page = 1
    while True:
        page_result = queue_service.get_page(
            project_slug=project_slug,
            page=page,
            page_size=page_size,
            scientific_name=None,
            min_confidence=None,
            max_confidence=None,
        )
        for item in page_result.items:
            name = str(item.scientific_name).strip()
            if name:
                species_set.add(name)
        if not page_result.has_next:
            break
        page += 1

    return sorted(species_set)


def _sort_rows_by_confidence_desc(rows: list[list[object]]) -> list[list[object]]:
    return sorted(rows, key=lambda row: float(row[3]) if len(row) > 3 else 0.0, reverse=True)


def _fetch_selected_audio_with_title(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    selected_index: int,
    previous_cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[str | None, str, str, str | None, str]:
    audio_path, cache_key, status, spectrogram_path = _fetch_selected_audio_with_spectrogram(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=rows,
        selected_index=selected_index,
        previous_cache_key=previous_cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    species_name, confidence_value = _selected_row_species_and_confidence(rows, selected_index)
    return audio_path, cache_key, status, spectrogram_path, _spectrogram_title(species_name, confidence_value)


def _select_and_fetch_audio_with_title(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    cache_key: str,
    evt: gr.SelectData,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[int, str | None, str, str, str | None, str]:
    selected_index, audio_path, updated_cache_key, status, spectrogram_path = _select_and_fetch_audio(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=rows,
        cache_key=cache_key,
        evt=evt,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    species_name, confidence_value = _selected_row_species_and_confidence(rows, selected_index)
    return (
        selected_index,
        audio_path,
        updated_cache_key,
        status,
        spectrogram_path,
        _spectrogram_title(species_name, confidence_value),
    )


def _autofetch_first_row_with_title(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[int, str | None, str, str, str | None, str]:
    selected_index, audio_path, updated_cache_key, status, spectrogram_path = _autofetch_first_row(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=rows,
        cache_key=cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    species_name, confidence_value = _selected_row_species_and_confidence(rows, selected_index)
    return (
        selected_index,
        audio_path,
        updated_cache_key,
        status,
        spectrogram_path,
        _spectrogram_title(species_name, confidence_value),
    )


def _advance_to_next_row_with_title(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    selected_index: int,
    cache_key: str,
    allow_demo_fallback: bool = False,
    hf_token: str | None = None,
) -> tuple[int, str | None, str, str, str | None, str]:
    normalized_rows = _normalize_rows(rows)
    if not normalized_rows:
        return 0, None, cache_key, "No detections available", None, _spectrogram_title(None, None)

    safe_index = max(0, min(int(selected_index) + 1, len(normalized_rows) - 1))
    audio_path, updated_cache_key, status, spectrogram_path = _fetch_selected_audio_with_spectrogram(
        audio_service=audio_service,
        dataset_repo=dataset_repo,
        rows=normalized_rows,
        selected_index=safe_index,
        previous_cache_key=cache_key,
        allow_demo_fallback=allow_demo_fallback,
        hf_token=hf_token,
    )
    species_name, confidence_value = _selected_row_species_and_confidence(normalized_rows, safe_index)
    return safe_index, audio_path, updated_cache_key, status, spectrogram_path, _spectrogram_title(species_name, confidence_value)


def _cleanup_selected_audio(audio_service: _AudioServiceProtocol, cache_key: str) -> tuple[str, str | None]:
    if not cache_key:
        return "No cached audio to clean", None

    audio_service.cleanup_after_validation(cache_key=cache_key)
    return "Audio cache cleaned after validation", None


def _save_selected_validation(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
    corrected_species: str | None = None,
) -> tuple[str, str, str | None]:
    validator_name = validator.strip()
    if not validator_name:
        return "Provide validator name before saving", cache_key, None

    try:
        detection_key = _extract_detection_key(rows=rows, selected_index=selected_index)
        expected_version = _extract_expected_version(rows=rows, selected_index=selected_index)
        _ = validation_service.validate_detection(
            project_slug=project_slug,
            detection_key=detection_key,
            status=status_value,
            validator=validator_name,
            notes=notes.strip(),
            corrected_species=(corrected_species or "").strip() or None,
            expected_version=expected_version,
        )
        if cache_key:
            audio_service.cleanup_after_validation(cache_key=cache_key)
        return f"Validation saved: {detection_key} -> {status_value}", "", None
    except OptimisticLockError as exc:
        return (
            "Concurrency conflict: this detection was updated by another validator "
            f"(detection_key={exc.detection_key}, current version={exc.current_version}, expected={exc.expected_version}). "
            "Refresh the table.",
            cache_key,
            None,
        )
    except Exception as exc:
        return f"Failed to save validation: {exc}", cache_key, None


def _save_selected_validation_with_refresh(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
    show_conflicts_only: bool,
    corrected_species: str | None = None,
) -> tuple[str, str, str | None, list[list[object]], int, int, str, str]:
    selected_key = ""
    try:
        selected_key = _extract_detection_key(rows=rows, selected_index=selected_index)
    except Exception:
        selected_key = ""

    save_status, updated_cache_key, audio_path = _save_selected_validation(
        validation_service=validation_service,
        audio_service=audio_service,
        project_slug=project_slug,
        rows=rows,
        selected_index=selected_index,
        status_value=status_value,
        validator=validator,
        notes=notes,
        cache_key=cache_key,
        corrected_species=corrected_species,
    )

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=show_conflicts_only,
    )
    refreshed_rows = _sort_rows_by_confidence_desc(refreshed_rows)

    if selected_key:
        refreshed_index = _find_detection_row_index(refreshed_rows, selected_key)
    else:
        refreshed_index = 0

    if "Concurrency conflict" in save_status:
        conflict_key = selected_key
        refreshed_rows, page_status, refreshed_page = _page_to_table(
            service=queue_service,
            snapshot_reader=snapshot_reader,
            project_slug=project_slug,
            page=refreshed_page,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            validator_filter=validator_filter,
            status_filter=status_filter,
            updated_after=updated_after,
            conflict_detection_key=conflict_key,
            show_conflicts_only=show_conflicts_only,
        )
        refreshed_rows = _sort_rows_by_confidence_desc(refreshed_rows)
        refreshed_index = _find_detection_row_index(refreshed_rows, selected_key) if selected_key else 0
        pending_status_value = status_value
        status = f"{save_status} Table reloaded to resolve conflict."
    else:
        conflict_key = ""
        pending_status_value = ""
        status = f"{save_status} | {page_status}"

    return (
        status,
        updated_cache_key,
        audio_path,
        refreshed_rows,
        refreshed_page,
        refreshed_index,
        pending_status_value,
        conflict_key,
    )


def _reapply_last_conflict_validation_with_refresh(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    pending_status_value: str,
    conflict_detection_key: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
    show_conflicts_only: bool,
) -> tuple[str, str, str | None, list[list[object]], int, int, str, str]:
    if not pending_status_value:
        refreshed_rows, page_status, refreshed_page = _page_to_table(
            service=queue_service,
            snapshot_reader=snapshot_reader,
            project_slug=project_slug,
            page=page,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            validator_filter=validator_filter,
            status_filter=status_filter,
            updated_after=updated_after,
            show_conflicts_only=show_conflicts_only,
        )
        refreshed_rows = _sort_rows_by_confidence_desc(refreshed_rows)
        return (
            f"No pending validation to reapply | {page_status}",
            cache_key,
            None,
            refreshed_rows,
            refreshed_page,
            selected_index,
            "",
            "",
        )

    target_index = _find_detection_row_index(rows, conflict_detection_key) if conflict_detection_key else selected_index
    return _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        rows=rows,
        selected_index=target_index,
        status_value=pending_status_value,
        validator=validator,
        notes=notes,
        cache_key=cache_key,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=show_conflicts_only,
    )


def _batch_validate_conflicts(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
) -> tuple[str, str, str | None, list[list[object]], int]:
    """Apply the same validation status to all visible conflicts in the table."""
    validator_name = validator.strip()
    if not validator_name:
        return "Provide validator name", "", None, [], page

    normalized_rows: list[list[object]]
    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        return "No conflict detection to validate", "", None, [], page

    conflict_rows = [row for row in normalized_rows if str(row[8]) == "CONFLICT"]
    if not conflict_rows:
        return "No conflict detection identified in table", "", None, normalized_rows, page

    success_count = 0
    failure_count = 0
    conflict_count = 0

    for row in conflict_rows:
        try:
            detection_key = str(row[0]).strip()
            expected_version = int(row[7])

            _ = validation_service.validate_detection(
                project_slug=project_slug,
                detection_key=detection_key,
                status=status_value,
                validator=validator_name,
                notes=notes.strip(),
                expected_version=expected_version,
            )
            success_count += 1
            if cache_key:
                audio_service.cleanup_after_validation(cache_key=cache_key)
        except OptimisticLockError:
            conflict_count += 1
        except Exception:
            failure_count += 1

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=False,
    )
    refreshed_rows = _sort_rows_by_confidence_desc(refreshed_rows)

    summary = f"Processed {len(conflict_rows)} conflicts: {success_count} success, {conflict_count} new conflicts, {failure_count} failures"
    status = f"{summary} | {page_status}"

    return status, "", None, refreshed_rows, refreshed_page


def _batch_reapply_all_pending(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    pending_statuses: dict[str, str],
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
) -> tuple[str, str, str | None, list[list[object]], int]:
    """Reapply all pending validations (stored conflicts) with current version."""
    if not pending_statuses:
        return "No pending validation to reapply", "", None, [], page

    validator_name = validator.strip()
    if not validator_name:
        return "Provide validator name", "", None, [], page

    success_count = 0
    conflict_count = 0
    failure_count = 0

    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)

    for detection_key, status_value in pending_statuses.items():
        try:
            current_version = int(snapshot.get(detection_key, {}).get("version", 0))

            _ = validation_service.validate_detection(
                project_slug=project_slug,
                detection_key=detection_key,
                status=status_value,
                validator=validator_name,
                notes=notes.strip(),
                expected_version=current_version,
            )
            success_count += 1
            if cache_key:
                audio_service.cleanup_after_validation(cache_key=cache_key)
        except OptimisticLockError:
            conflict_count += 1
        except Exception:
            failure_count += 1

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=False,
    )
    refreshed_rows = _sort_rows_by_confidence_desc(refreshed_rows)

    summary = f"Reapplied {len(pending_statuses)} validations: {success_count} success, {conflict_count} new conflicts, {failure_count} failures"
    status = f"{summary} | {page_status}"

    return status, "", None, refreshed_rows, refreshed_page


def build_demo_app(project_slug: str = "demo-project") -> gr.Blocks:
    """Build the demo validation app for a given project.
    
    Args:
        project_slug: Project identifier (default: demo-project)
    
    Returns:
        Gradio Blocks with validation interface
    """
    runtime_config = RuntimeConfig.from_env()
    service = _seed_service_for_projects(
        [project_slug],
        seed_file_path=runtime_config.detection_seed_path,
    )
    audio_service = AudioFetchService(EphemeralCacheManager(ttl_seconds=300, max_files=128))
    validation_base_dir = runtime_config.validation_base_dir
    validation_repository = AppendOnlyValidationRepository(base_dir=validation_base_dir)
    validation_service = ValidationService(validation_repository)

    with gr.Blocks(title="BirdNET-Validator-App") as demo:
        gr.Markdown("# BirdNET-Validator-App")
        gr.Markdown("Sprint 2: paged queue + on-demand audio with ephemeral cache.")

        dataset_repo = gr.Textbox(label="Dataset repo", value="YOUR_USER/birdnet-project-dataset")

        with gr.Row():
            species_filter = gr.Textbox(label="Species filter", placeholder="Ex: Cyanocorax cyanopogon")
            min_confidence = gr.Slider(label="Minimum confidence", minimum=0.0, maximum=1.0, step=0.01, value=0.0)
            show_conflicts_only = gr.Checkbox(label="Show only conflicts", value=False)

        with gr.Row():
            validator_filter = gr.Textbox(label="Validator filter", placeholder="Ex: validator-demo")
            validation_status_filter = gr.Dropdown(
                label="Status filter",
                choices=["all", "pending", "positive", "negative", "uncertain", "skip"],
                value="all",
            )
            updated_after_filter = gr.DateTime(label="Updated since", include_time=False, type="string")

        with gr.Row():
            prev_btn = gr.Button("Previous page")
            next_btn = gr.Button("Next page")
            refresh_btn = gr.Button("Apply filters")

        page_state = gr.State(value=1)
        table = gr.Dataframe(
            headers=[
                "detection_key",
                "audio_id",
                "scientific_name",
                "confidence",
                "start_time",
                "end_time",
                "validation_status",
                "version",
                "conflict_flag",
                "conflict_severity",
            ],
            label="Detections",
            interactive=False,
        )
        selected_index = gr.Number(label="Selected row", value=0, precision=0)

        with gr.Row():
            load_audio_btn = gr.Button("Load selected audio")
            clear_audio_btn = gr.Button("Clear cache after validation")

        with gr.Row():
            validator_name = gr.Textbox(label="Validator", value="validator-demo")
            validation_notes = gr.Textbox(label="Notes", placeholder="Optional")

        with gr.Row():
            approve_btn = gr.Button("Mark positive")
            reject_btn = gr.Button("Mark negative")
            uncertain_btn = gr.Button("Uncertain")
            skip_btn = gr.Button("Skip")
            reapply_btn = gr.Button("Reapply validation after conflict")

        with gr.Row():
            batch_approve_conflicts_btn = gr.Button("Approve all conflicts")
            batch_reject_conflicts_btn = gr.Button("Reject all conflicts")

        audio_player = gr.Audio(label="On-demand audio", type="filepath")
        cache_key_state = gr.State(value="")
        pending_status_state = gr.State(value="")
        conflict_detection_key_state = gr.State(value="")
        status = gr.Textbox(label="Status", interactive=False)

        # Keyboard shortcuts: 1=positive, 2=negative, 3=uncertain, 4=skip, R=reapply
        keyboard_shortcuts_info = gr.HTML(
            value="<div style='font-size: 12px; color: #666; padding: 8px; background-color: #f5f5f5; border-radius: 4px; margin-bottom: 10px;'>"
            "<strong>Keyboard shortcuts:</strong> 1=Positive | 2=Negative | 3=Uncertain | 4=Skip | R=Reapply"
            "</div>"
            "<script>"
            "document.addEventListener('keydown', function(event) {"
            "  if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;"
            "  const key = event.key.toLowerCase();"
            "  let buttonText = null;"
            "  if (key === '1') buttonText = 'Mark positive';"
            "  else if (key === '2') buttonText = 'Mark negative';"
            "  else if (key === '3') buttonText = 'Uncertain';"
            "  else if (key === '4') buttonText = 'Skip';"
            "  else if (key === 'r') buttonText = 'Reapply validation after conflict';"
            "  if (buttonText) {"
            "    event.preventDefault();"
            "    const buttons = document.querySelectorAll('button');"
            "    for (const btn of buttons) {"
            "      if (btn.textContent.includes(buttonText)) {"
            "        btn.click();"
            "        break;"
            "      }"
            "    }"
            "  }"
            "});"
            "</script>"
        )

        def refresh(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return _page_to_table(
                service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                page=page,
                scientific_name=species,
                min_confidence=confidence,
                page_size=runtime_config.page_size,
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=only_conflicts,
            )

        def go_next(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return refresh(
                page + 1,
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            )

        def go_prev(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return refresh(
                max(1, page - 1),
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            )

        def on_select(evt: gr.SelectData):
            if isinstance(evt.index, tuple):
                return int(evt.index[0])
            if isinstance(evt.index, int):
                return int(evt.index)
            return 0

        demo.load(
            fn=refresh,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        refresh_btn.click(
            fn=lambda species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: refresh(
                1,
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            ),
            inputs=[
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        next_btn.click(
            fn=go_next,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        prev_btn.click(
            fn=go_prev,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        table.select(fn=on_select, inputs=None, outputs=[selected_index])
        load_audio_btn.click(
            fn=lambda repo, rows, idx, cache_key: _fetch_selected_audio(
                audio_service=audio_service,
                dataset_repo=repo,
                rows=rows,
                selected_index=int(idx),
                previous_cache_key=cache_key,
            ),
            inputs=[dataset_repo, table, selected_index, cache_key_state],
            outputs=[audio_player, cache_key_state, status],
        )
        clear_audio_btn.click(
            fn=lambda cache_key: _cleanup_selected_audio(audio_service=audio_service, cache_key=cache_key),
            inputs=[cache_key_state],
            outputs=[status, audio_player],
        )
        approve_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="positive",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reject_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="negative",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        uncertain_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="uncertain",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        skip_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="skip",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reapply_btn.click(
            fn=lambda rows, idx, pending_status, conflict_key, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _reapply_last_conflict_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                pending_status_value=pending_status,
                conflict_detection_key=conflict_key,
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                pending_status_state,
                conflict_detection_key_state,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        batch_approve_conflicts_btn.click(
            fn=lambda rows, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value: _batch_validate_conflicts(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                status_value="positive",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
            ),
            inputs=[
                table,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state],
        )
        batch_reject_conflicts_btn.click(
            fn=lambda rows, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value: _batch_validate_conflicts(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                status_value="negative",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
            ),
            inputs=[
                table,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state],
        )

    return demo


def create_app() -> gr.Blocks:
    """Build the BirdNET Validator app with multi-project auth integration.
    
    Returns multi-tab interface with:
    - Login tab for user authentication
    - Project selection for authorized projects
    - Admin panel for project/user management (admin only)
    - Validation interface for selected project
    
    Returns:
        Gradio Blocks with full auth-integrated app
    """
    runtime_config = RuntimeConfig.from_env()

    # Initialize auth service
    auth_service = AuthService(
        session_ttl_minutes=120,
        invite_ttl_hours=runtime_config.invite_ttl_hours,
    )

    # Initialize EmailJS invite notifier (only transport)
    invite_notifier: InviteEmailNotifier = EmailJSInviteEmailNotifier(
        sender_email=runtime_config.invite_email_sender,
        service_id=runtime_config.emailjs_service_id or "",
        template_id=runtime_config.emailjs_template_id or "",
        public_key=runtime_config.emailjs_public_key or "",
        template_id_username_only=runtime_config.emailjs_template_id_username_only,
        template_id_email_only=runtime_config.emailjs_template_id_email_only,
        template_id_dual=runtime_config.emailjs_template_id_dual,
        endpoint=runtime_config.emailjs_endpoint,
        timeout_seconds=runtime_config.emailjs_timeout_seconds,
    )

    # Initialize admin panel manager
    admin_manager = AdminPanelManager(
        auth_service,
        invite_notifier=invite_notifier,
        invite_login_url=runtime_config.invite_email_login_url,
    )

    projects_file_path, user_access_file_path, invites_file_path = _resolve_bootstrap_file_paths(runtime_config)
    bootstrap_warning = _bootstrap_auth_and_projects(
        auth_service,
        admin_manager,
        runtime_config,
        projects_file_path=str(projects_file_path),
        user_access_file_path=str(user_access_file_path),
        invites_file_path=str(invites_file_path),
    )

    def _current_project_map() -> dict[str, Project]:
        project_map: dict[str, Project] = {}
        for row in admin_manager.list_projects():
            slug = str(row.get("project_slug", "")).strip()
            if not slug:
                continue
            project = admin_manager.get_project(slug)
            if project is not None:
                project_map[slug] = project
        return project_map

    queue_service, seed_warning = _build_detection_repository(
        [project["project_slug"] for project in admin_manager.list_projects()],
        seed_file_path=runtime_config.detection_seed_path,
        project_map=_current_project_map(),
        allow_demo_defaults=False,
    )
    service_ref: dict[str, DetectionQueueService] = {"queue": queue_service}
    audio_service = AudioFetchService(EphemeralCacheManager(ttl_seconds=300, max_files=128))
    validation_repository = AppendOnlyValidationRepository(base_dir=runtime_config.validation_base_dir)
    validation_service = ValidationService(validation_repository)

    with gr.Blocks(title="BirdNET-Validator-App") as wrapper:
        gr.Markdown("# BirdNET-Validator-App")
        gr.Markdown("**Version with authentication, project-level authorization, and admin panel**")
        if bootstrap_warning:
            gr.Markdown(bootstrap_warning)

        # Session state
        session_state = gr.State(value=None)
        selected_project_state = gr.State(value=None)
        selected_dataset_repo_state = gr.State(value="")
        seed_warning_state = gr.State(value=seed_warning)

        def _project_rows() -> list[list[object]]:
            projects = admin_manager.list_projects()
            return [
                [
                    p["project_slug"],
                    p["name"],
                    p["dataset_repo_id"],
                    p.get("visibility", "collaborative"),
                    p.get("owner_username", ""),
                    "yes" if bool(p.get("dataset_token_set", False)) else "no",
                    "yes" if bool(p["active"]) else "no",
                ]
                for p in projects
            ]

        def _project_slugs() -> list[str]:
            return [p["project_slug"] for p in admin_manager.list_projects()]

        def _project_map() -> dict[str, Project]:
            result: dict[str, Project] = {}
            for slug in _project_slugs():
                project = admin_manager.get_project(slug)
                if project is not None:
                    result[slug] = project
            return result

        def _admin_projects_for_session(session) -> list[str]:
            if session is None:
                return []
            admin_projects: list[str] = []
            for project_slug in session.authorized_projects:
                role = auth_service.get_user_role_for_project(session.username, project_slug)
                if role == Role.admin:
                    admin_projects.append(project_slug)
            return sorted(admin_projects)

        def _is_admin_for_project(session, project_slug: str) -> bool:
            if session is None:
                return False
            slug = (project_slug or "").strip()
            if not slug:
                return False
            role = auth_service.get_user_role_for_project(session.username, slug)
            return role == Role.admin

        def _persist_admin_state() -> tuple[bool, str]:
            try:
                _persist_bootstrap_state(
                    projects_path=projects_file_path,
                    user_access_path=user_access_file_path,
                    invites_path=invites_file_path,
                    admin_manager=admin_manager,
                    auth_service=auth_service,
                )
                return True, ""
            except Exception as exc:
                return False, str(exc)

        with gr.Tabs():
            # ===== TAB 1: Login =====
            with gr.Tab("🔐 Login", id="login_tab"):
                username_input, session_output, login_button, error_message = create_login_page(auth_service)

                # Store session ID when login succeeds
                def handle_login_success(session_id: str):
                    """Process successful login and store session."""
                    if session_id:
                        return auth_service.get_session(session_id)
                    return None

                session_output.change(
                    fn=handle_login_success,
                    inputs=[session_output],
                    outputs=[session_state],
                )

            # ===== TAB 2: Admin Panel =====
            with gr.Tab("⚙️ Admin", id="admin_tab"):
                admin_info = gr.Markdown(value="⚠️ Login first")
                admin_scope_info = gr.Markdown(value="")

                def create_admin_display(session):
                    """Show admin panel or access denied message."""
                    if session is None:
                        return (
                            "❌ **Not authenticated** — Login first in the **Login** tab.",
                            gr.update(visible=False),
                        )
                    admin_projects = _admin_projects_for_session(session)
                    return (
                        (
                            f"✅ **Admin Panel** — Welcome, {session.username}. "
                            f"You are admin in {len(admin_projects)} project(s). "
                            "You can always create a new project and become its admin."
                        ),
                        gr.update(visible=True),
                    )

                with gr.Group(visible=False) as admin_controls:
                    gr.Markdown("#### Registered Projects")

                    with gr.Row():
                        create_project_slug = gr.Textbox(
                            label="New Project Slug",
                            placeholder="ex: amazonas-2026",
                        )
                        create_project_name = gr.Textbox(
                            label="Project Name",
                            placeholder="ex: Amazonas Survey 2026",
                        )
                        create_project_repo = gr.Textbox(
                            label="HF Dataset Repo ID",
                            placeholder="ex: birdnet/amazonas-2026-dataset",
                        )
                        create_project_visibility = gr.Dropdown(
                            label="Visibility",
                            choices=["private", "collaborative"],
                            value="collaborative",
                        )
                        create_project_token = gr.Textbox(
                            label="Project HF Token (optional)",
                            placeholder="hf_xxx...",
                            type="password",
                        )

                    create_project_message = gr.Markdown()

                    def create_project(session, slug: str, name: str, repo_id: str, visibility: str, project_token: str):
                        if session is None:
                            return "❌ Access denied. Login required.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), session

                        slug = (slug or "").strip()
                        name = (name or "").strip()
                        repo_id = (repo_id or "").strip()
                        visibility_value = (visibility or "collaborative").strip().lower()
                        project_token_value = (project_token or "").strip() or None
                        if not slug or not name or not repo_id:
                            return "⚠️ Fill slug, name, and repo id.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), session
                        if visibility_value not in {"private", "collaborative"}:
                            return "⚠️ Visibility must be private or collaborative.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), session

                        created = admin_manager.register_project(
                            Project(
                                project_id=str(uuid4()),
                                project_slug=slug,
                                name=name,
                                dataset_repo_id=repo_id,
                                visibility=visibility_value,
                                owner_username=session.username,
                                dataset_token=project_token_value,
                                active=True,
                            )
                        )
                        if not created:
                            admin_projects = _admin_projects_for_session(session)
                            return (
                                f"⚠️ Project '{slug}' already exists.",
                                _project_rows(),
                                gr.update(choices=admin_projects),
                                gr.update(),
                                gr.update(),
                                gr.update(),
                                gr.update(),
                                gr.update(),
                                gr.update(choices=admin_projects),
                                gr.update(choices=admin_projects),
                                gr.update(choices=["all", *admin_projects], value="all"),
                                gr.update(),
                                session,
                            )

                        # Project creator is always admin of the project.
                        auth_service.upsert_user_project_role(session.username, slug, Role.admin)
                        persisted, persist_error = _persist_admin_state()

                        refreshed_service, refreshed_warning = _build_detection_repository(
                            _project_slugs(),
                            seed_file_path=runtime_config.detection_seed_path,
                            project_map=_project_map(),
                            allow_demo_defaults=False,
                        )
                        service_ref["queue"] = refreshed_service
                        refreshed_session = auth_service.refresh_session_authorizations(session.session_id) or session
                        admin_projects = _admin_projects_for_session(refreshed_session)

                        return (
                            (
                                f"✅ Project '{slug}' created successfully."
                                if persisted
                                else f"✅ Project '{slug}' created, but could not persist bootstrap files: {persist_error}"
                            ),
                            _project_rows(),
                            gr.update(choices=admin_projects, value=slug),
                            gr.update(value=""),
                            gr.update(value=""),
                            gr.update(value=""),
                            gr.update(value="collaborative"),
                            gr.update(value=""),
                            gr.update(choices=admin_projects, value=slug),
                            gr.update(choices=admin_projects, value=slug),
                            gr.update(choices=["all", *admin_projects], value="all"),
                            refreshed_warning,
                            refreshed_session,
                        )

                    create_project_btn = gr.Button("➕ Create Project", variant="primary")
                    projects_table = gr.Dataframe(
                        value=_project_rows(),
                        headers=["project_slug", "name", "dataset_repo_id", "visibility", "owner_username", "dataset_token_set", "active"],
                        interactive=False,
                    )
                    refresh_projects_btn = gr.Button("🔄 Refresh List")

                    gr.Markdown("<div style='height:8px;'></div>")

                    def _render_admin_scope_info(session, selected_admin_project: str):
                        if session is None:
                            return ""

                        selected = (selected_admin_project or "").strip()
                        if not selected:
                            admin_projects = _admin_projects_for_session(session)
                            if not admin_projects:
                                return (
                                    "ℹ️ You are authenticated, but currently not admin of any existing project. "
                                    "Create a project to become admin of it."
                                )
                            return (
                                f"ℹ️ Select a project to manage. "
                                f"You are admin in {len(admin_projects)} project(s): {', '.join(admin_projects)}"
                            )

                        role = auth_service.get_user_role_for_project(session.username, selected)
                        role_label = role.value.upper() if role is not None else "NO ACCESS"
                        if role == Role.admin:
                            return f"✅ Effective role on project '{selected}': {role_label}"
                        if role == Role.validator:
                            return (
                                f"⚠️ Effective role on project '{selected}': {role_label}. "
                                "Management actions require ADMIN for this project."
                            )
                        return f"❌ You do not have access to project '{selected}'."

                    def refresh_projects(session):
                        if session is None:
                            return []
                        return _project_rows()

                    refresh_projects_btn.click(
                        fn=refresh_projects,
                        inputs=[session_state],
                        outputs=[projects_table],
                    )

                    gr.Markdown("#### Project Token Management")
                    with gr.Row():
                        token_project_select = gr.Dropdown(
                            choices=_project_slugs(),
                            label="Project",
                        )
                        token_new_value = gr.Textbox(
                            label="New token",
                            placeholder="hf_xxx...",
                            type="password",
                        )
                        token_clear_checkbox = gr.Checkbox(label="Clear token", value=False)
                    token_update_message = gr.Markdown()
                    token_update_btn = gr.Button("Update Project Token")

                    def update_project_token(session, project_slug: str, new_token: str, clear_token: bool):
                        if session is None:
                            return "❌ Access denied. Login required.", gr.update(), gr.update()
                        if not _is_admin_for_project(session, project_slug):
                            return "❌ Access denied. You must be admin of the selected project.", gr.update(), gr.update()
                        project = admin_manager.get_project(project_slug)
                        if project is None:
                            return "⚠️ Select a valid project.", gr.update(), gr.update()

                        if bool(clear_token):
                            project.dataset_token = None
                            message = f"✅ Project token cleared for {project_slug}"
                        else:
                            candidate = (new_token or "").strip()
                            if not candidate:
                                return "⚠️ Provide a token or select clear token.", gr.update(), gr.update()
                            project.dataset_token = candidate
                            message = f"✅ Project token updated for {project_slug}"

                        persisted, persist_error = _persist_admin_state()
                        if not persisted:
                            message = f"{message} | ⚠️ Persistence failed: {persist_error}"

                        refreshed_service, refreshed_warning = _build_detection_repository(
                            _project_slugs(),
                            seed_file_path=runtime_config.detection_seed_path,
                            project_map=_project_map(),
                            allow_demo_defaults=False,
                        )
                        service_ref["queue"] = refreshed_service
                        if refreshed_warning:
                            message = f"{message} | {refreshed_warning}"

                        return message, gr.update(value=""), _project_rows()

                    token_update_btn.click(
                        fn=update_project_token,
                        inputs=[session_state, token_project_select, token_new_value, token_clear_checkbox],
                        outputs=[token_update_message, token_new_value, projects_table],
                    )

                with gr.Group(visible=False) as admin_users_controls:
                    gr.Markdown("#### Assign User to Project")
                    with gr.Row():
                        admin_username = gr.Textbox(
                            label="Username", placeholder="validator_001"
                        )
                        admin_invite_email = gr.Textbox(
                            label="Invite email",
                            placeholder="validator@example.org",
                        )
                        admin_project = gr.Dropdown(
                            choices=_project_slugs(),
                            label="Project",
                        )
                        admin_role = gr.Dropdown(
                            choices=["admin", "validator"],
                            value="validator",
                            label="Role",
                        )

                    admin_message = gr.Markdown()
                    invite_btn = gr.Button("✉️ Invite")

                    # Invite scenario selection
                    gr.Markdown(
                        "**Choose how to invite:**\n"
                        "- **Internal app only**: Invite by HF username (no email notifications)\n"
                        "- **Email only**: Invite by email (for users without HF account yet)\n"
                        "- **Both**: Invite both internally and via email"
                    )

                    invite_mode = gr.Radio(
                        choices=["Internal app only", "Email only", "Both"],
                        value="Both",
                        label="Invite Method",
                    )

                    with gr.Column():
                        admin_username = gr.Textbox(
                            label="HF Username (for internal app invite)",
                            placeholder="validator_001",
                            visible=True,
                        )
                        admin_invite_email = gr.Textbox(
                            label="Email Address (for email notification)",
                            placeholder="validator@example.org",
                            visible=True,
                        )

                    # Update visibility based on invite mode
                    def update_invite_fields(mode: str):
                        if mode == "Internal app only":
                            return gr.update(visible=True), gr.update(visible=False)
                        elif mode == "Email only":
                            return gr.update(visible=False), gr.update(visible=True)
                        else:  # Both
                            return gr.update(visible=True), gr.update(visible=True)

                    invite_mode.change(
                        fn=update_invite_fields,
                        inputs=[invite_mode],
                        outputs=[admin_username, admin_invite_email],
                    )

                    with gr.Row():
                        admin_project = gr.Dropdown(
                            choices=_project_slugs(),
                            label="Project",
                        )
                        admin_role = gr.Dropdown(
                            choices=["admin", "validator"],
                            value="validator",
                            label="Role",
                        )

                    admin_message = gr.Markdown()
                    invite_btn = gr.Button("✉️ Send Invite")

                    def assign_user(session, username: str, project: str, role: str):
                        if session is None:
                            return "❌ Access denied. Login required.", gr.update(), gr.update(), gr.update(), gr.update()
                        if not _is_admin_for_project(session, project):
                            return "❌ Access denied. You must be admin of the selected project.", gr.update(), gr.update(), gr.update(), gr.update()
                        success, msg = admin_manager.assign_user_to_project(
                            session.username,
                            username,
                            project,
                            role,
                        )
                        if success:
                            persisted, persist_error = _persist_admin_state()
                            final_message = msg if persisted else f"{msg} | ⚠️ Persistence failed: {persist_error}"
                            return final_message, gr.update(value=""), gr.update(value=""), gr.update(value=None), gr.update(value="validator")
                        return msg, gr.update(), gr.update(), gr.update(), gr.update()

                    assign_btn = gr.Button("✅ Assign", variant="primary")
                    assign_btn.click(
                        fn=assign_user,
                        inputs=[session_state, admin_username, admin_project, admin_role],
                        outputs=[admin_message, admin_username, admin_invite_email, admin_project, admin_role],
                    )

                    def invite_user(session, mode: str, username: str, invite_email: str, project: str, role: str):
                        if session is None:
                            return "❌ Access denied. Login required.", gr.update(), gr.update(), gr.update(), gr.update()
                        if not _is_admin_for_project(session, project):
                            return "❌ Access denied. You must be admin of the selected project.", gr.update(), gr.update(), gr.update(), gr.update()

                        final_username = None if mode == "Email only" else (username or None)
                        final_email = None if mode == "Internal app only" else (invite_email or None)

                        success, msg = admin_manager.invite_user_to_project(
                            actor_username=session.username,
                            invited_by=session.username,
                            username=final_username,
                            invitee_email=final_email,
                            project_slug=project,
                            role=role,
                        )
                        if success:
                            persisted, persist_error = _persist_admin_state()
                            final_message = msg if persisted else f"{msg} | ⚠️ Persistence failed: {persist_error}"
                            return final_message, gr.update(value=""), gr.update(value=""), gr.update(value=None), gr.update(value="validator")
                        return msg, gr.update(), gr.update(), gr.update(), gr.update()

                    invite_btn.click(
                        fn=invite_user,
                        inputs=[session_state, invite_mode, admin_username, admin_invite_email, admin_project, admin_role],
                        outputs=[admin_message, admin_username, admin_invite_email, admin_project, admin_role],
                    )

                    gr.Markdown("<div style='height:8px;'></div>")

                    gr.Markdown("#### Delete Project")
                    with gr.Row():
                        delete_project_slug = gr.Dropdown(
                            choices=_project_slugs(),
                            label="Project to delete",
                        )
                        delete_project_btn = gr.Button("🗑️ Delete Project", variant="stop")

                    def delete_project(session, project_slug: str):
                        if session is None:
                            return "❌ Access denied. Login required.", gr.update(), gr.update(), gr.update(), session, gr.update(), gr.update()
                        if not _is_admin_for_project(session, project_slug):
                            return "❌ Access denied. You must be admin of the selected project.", gr.update(), gr.update(), gr.update(), session, gr.update(), gr.update()

                        success, msg = admin_manager.delete_project(session.username, project_slug)
                        if not success:
                            return msg, _project_rows(), gr.update(choices=_project_slugs()), gr.update(choices=_project_slugs()), session, gr.update(), gr.update()

                        persisted, persist_error = _persist_admin_state()
                        if not persisted:
                            msg = f"{msg} | ⚠️ Persistence failed: {persist_error}"

                        refreshed_service, refreshed_warning = _build_detection_repository(
                            _project_slugs(),
                            seed_file_path=runtime_config.detection_seed_path,
                            project_map=_project_map(),
                            allow_demo_defaults=False,
                        )
                        service_ref["queue"] = refreshed_service
                        refreshed_session = auth_service.refresh_session_authorizations(session.session_id) or session

                        admin_projects = _admin_projects_for_session(refreshed_session)
                        return (
                            msg,
                            _project_rows(),
                            gr.update(choices=admin_projects, value=None),
                            gr.update(choices=admin_projects, value=None),
                            refreshed_session,
                            refreshed_warning,
                            gr.update(choices=admin_projects, value=None),
                        )

                    delete_project_btn.click(
                        fn=delete_project,
                        inputs=[session_state, delete_project_slug],
                        outputs=[
                            admin_message,
                            projects_table,
                            admin_project,
                            token_project_select,
                            session_state,
                            seed_warning_state,
                            delete_project_slug,
                        ],
                    )

                    gr.Markdown("<div style='height:8px;'></div>")

                    gr.Markdown("#### Pending Invites")
                    with gr.Row():
                        pending_invites_filter_project = gr.Dropdown(
                            choices=["all", *_project_slugs()],
                            value="all",
                            label="Filter by project",
                        )
                        pending_invite_username = gr.Textbox(label="Invite username", placeholder="validator_001")
                        pending_invite_project = gr.Dropdown(choices=_project_slugs(), label="Invite project")
                    pending_invites_table = gr.Dataframe(
                        value=[],
                        headers=["username", "project_slug", "role", "invited_by", "expires_at", "expires_in"],
                        interactive=False,
                    )
                    pending_invites_message = gr.Markdown()
                    with gr.Row():
                        refresh_pending_invites_btn = gr.Button("Refresh Pending Invites")
                        revoke_invite_btn = gr.Button("Revoke Invite")

                    def _pending_invites_rows(project_filter: str, session):
                        def _remaining_from_iso(iso_value: str) -> str:
                            raw = str(iso_value or "").strip()
                            if not raw:
                                return "unknown"
                            try:
                                expires_at = datetime.fromisoformat(raw)
                            except Exception:
                                return "unknown"
                            if expires_at.tzinfo is None:
                                now = datetime.now()
                            else:
                                now = datetime.now(expires_at.tzinfo)
                            remaining_seconds = int((expires_at - now).total_seconds())
                            if remaining_seconds <= 0:
                                return "expired"
                            days = remaining_seconds // 86400
                            hours = (remaining_seconds % 86400) // 3600
                            minutes = (remaining_seconds % 3600) // 60
                            if days > 0:
                                return f"{days}d {hours}h"
                            if hours > 0:
                                return f"{hours}h {minutes}m"
                            return f"{minutes}m"

                        selected = (project_filter or "all").strip().lower()
                        project = None if selected == "all" else project_filter
                        if project is not None and not _is_admin_for_project(session, project):
                            return []

                        admin_scope = set(_admin_projects_for_session(session))
                        invites = admin_manager.list_pending_invites(project_slug=project)
                        return [
                            [
                                row.get("username", ""),
                                row.get("project_slug", ""),
                                row.get("role", ""),
                                row.get("invited_by", ""),
                                row.get("expires_at", ""),
                                _remaining_from_iso(str(row.get("expires_at", ""))),
                            ]
                            for row in invites
                            if str(row.get("project_slug", "")) in admin_scope
                        ]

                    refresh_pending_invites_btn.click(
                        fn=_pending_invites_rows,
                        inputs=[pending_invites_filter_project, session_state],
                        outputs=[pending_invites_table],
                    )

                    def revoke_invite(session, username: str, project_slug: str, project_filter: str):
                        if session is None:
                            return "❌ Access denied. Login required.", _pending_invites_rows(project_filter, session)
                        if not _is_admin_for_project(session, project_slug):
                            return "❌ Access denied. You must be admin of the selected project.", _pending_invites_rows(project_filter, session)
                        success, msg = admin_manager.revoke_invite(username=username, project_slug=project_slug)
                        if success:
                            persisted, persist_error = _persist_admin_state()
                            if not persisted:
                                msg = f"{msg} | ⚠️ Persistence failed: {persist_error}"
                        return msg, _pending_invites_rows(project_filter, session)

                    revoke_invite_btn.click(
                        fn=revoke_invite,
                        inputs=[session_state, pending_invite_username, pending_invite_project, pending_invites_filter_project],
                        outputs=[pending_invites_message, pending_invites_table],
                    )

                    pending_invites_filter_project.change(
                        fn=_pending_invites_rows,
                        inputs=[pending_invites_filter_project, session_state],
                        outputs=[pending_invites_table],
                    )

                create_project_btn.click(
                    fn=create_project,
                    inputs=[session_state, create_project_slug, create_project_name, create_project_repo, create_project_visibility, create_project_token],
                    outputs=[
                        create_project_message,
                        projects_table,
                        admin_project,
                        create_project_slug,
                        create_project_name,
                        create_project_repo,
                        create_project_visibility,
                        create_project_token,
                        token_project_select,
                        pending_invite_project,
                        pending_invites_filter_project,
                        seed_warning_state,
                        session_state,
                    ],
                )

                session_state.change(
                    fn=create_admin_display,
                    inputs=[session_state],
                    outputs=[admin_info, admin_controls],
                )

                session_state.change(
                    fn=_render_admin_scope_info,
                    inputs=[session_state, admin_project],
                    outputs=[admin_scope_info],
                )

                session_state.change(
                    fn=lambda s: gr.update(visible=bool(s is not None)),
                    inputs=[session_state],
                    outputs=[admin_users_controls],
                )

                session_state.change(
                    fn=lambda s: _project_rows() if s is not None else [],
                    inputs=[session_state],
                    outputs=[projects_table],
                )

                session_state.change(
                    fn=lambda s: (
                        gr.update(choices=_admin_projects_for_session(s), value=None),
                        gr.update(choices=_admin_projects_for_session(s), value=None),
                        gr.update(choices=_admin_projects_for_session(s), value=None),
                        gr.update(choices=["all", *_admin_projects_for_session(s)], value="all"),
                        [],
                    ),
                    inputs=[session_state],
                    outputs=[admin_project, token_project_select, pending_invite_project, pending_invites_filter_project, pending_invites_table],
                )

                admin_project.change(
                    fn=_render_admin_scope_info,
                    inputs=[session_state, admin_project],
                    outputs=[admin_scope_info],
                )

            # ===== TAB 3: Project Selection =====
            with gr.Tab("📁 Select Project", id="project_tab"):
                project_info_display = gr.Markdown(
                    value="⚠️ Login first in the **Login** tab"
                )
                project_selector = gr.Dropdown(
                    choices=[],
                    label="Authorized Project",
                    interactive=False,
                    allow_custom_value=True,
                )
                invitations_info = gr.Markdown(value="")
                invite_selector = gr.Dropdown(choices=[], label="Pending Invites", interactive=False)
                with gr.Row():
                    refresh_invites_btn = gr.Button("Refresh Invites")
                    accept_invite_btn = gr.Button("Accept Invite", variant="primary")
                    accept_all_invites_btn = gr.Button("Accept All")
                    reject_invite_btn = gr.Button("Reject Invite")

                def update_project_selector(session):
                    """Update project dropdown when user logs in."""
                    if session is None:
                        return (
                            gr.Dropdown(choices=[], value=None, interactive=False),
                            "❌ Not authenticated. Login first.",
                            None,
                            "",
                        )

                    projects = session.authorized_projects
                    if not projects:
                        return (
                            gr.Dropdown(choices=[], value=None, interactive=False),
                            (
                                "ℹ️ **No projects available yet**\n\n"
                                "To get started:\n"
                                "1. Go to the **Admin** tab.\n"
                                "2. Fill **New Project Slug**, **Project Name**, and **HF Dataset Repo ID**.\n"
                                "3. Click **Create Project**.\n"
                                "4. Go back to **Select Project** and choose the created project."
                            ),
                            None,
                            "",
                        )

                    selected = projects[0]
                    role = auth_service.get_user_role_for_project(session.username, selected)
                    role_label = role.value.upper() if role else "UNKNOWN"
                    selected_project = admin_manager.get_project(selected)
                    dataset_repo_id = selected_project.dataset_repo_id if selected_project else ""
                    return (
                        gr.Dropdown(choices=projects, value=selected, interactive=True),
                        f"📁 **Project:** {selected} | **Your Role:** {role_label}",
                        selected,
                        dataset_repo_id,
                    )

                def _format_invite_option(invite) -> str:
                    return f"{invite.project_slug}|{invite.role.value}|{invite.invited_by}|{invite.expires_at.isoformat()}"

                def _format_invite_remaining(expires_at: datetime) -> str:
                    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.utcnow()
                    delta = expires_at - now
                    remaining_seconds = int(delta.total_seconds())
                    if remaining_seconds <= 0:
                        return "expired"

                    days = remaining_seconds // 86400
                    hours = (remaining_seconds % 86400) // 3600
                    minutes = (remaining_seconds % 3600) // 60

                    if days > 0:
                        return f"{days}d {hours}h"
                    if hours > 0:
                        return f"{hours}h {minutes}m"
                    return f"{minutes}m"

                def _build_invite_label(invite) -> str:
                    remaining = _format_invite_remaining(invite.expires_at)
                    return (
                        f"{invite.project_slug} ({invite.role.value})"
                        f" - invited by {invite.invited_by}"
                        f" - expires in {remaining}"
                    )

                def _build_invites_ui(session):
                    if session is None:
                        return gr.update(value="", visible=False), gr.update(choices=[], value=None, interactive=False)
                    invites = auth_service.list_pending_invites(session.username)
                    if not invites:
                        return gr.update(value="No pending invites", visible=True), gr.update(choices=[], value=None, interactive=False)
                    encoded = [_format_invite_option(item) for item in invites]
                    labeled_choices = [(_build_invite_label(invite), encoded_value) for invite, encoded_value in zip(invites, encoded)]
                    return (
                        gr.update(value=f"Pending invites: {len(labeled_choices)}", visible=True),
                        gr.update(choices=labeled_choices, value=encoded[0], interactive=True),
                    )

                def _parse_invite_option(raw_option: str) -> tuple[str, str, str]:
                    """Compatibility parser: supports old and new encoded invite strings."""
                    value = str(raw_option or "").strip()
                    parts = value.split("|")
                    if len(parts) < 3:
                        return "", "", ""
                    return parts[0].strip(), parts[1].strip(), parts[2].strip()

                def _accept_invite(session, selected_option: str):
                    if session is None:
                        return "❌ Login first", session
                    project_slug, _, _ = _parse_invite_option(selected_option)
                    if not project_slug:
                        return "⚠️ Select an invite", session
                    success, message = auth_service.accept_project_invite(session.username, project_slug)
                    refreshed = auth_service.refresh_session_authorizations(session.session_id) or session
                    if success:
                        _persist_admin_state()
                    return message, refreshed

                def _reject_invite(session, selected_option: str):
                    if session is None:
                        return "❌ Login first", session
                    project_slug, _, _ = _parse_invite_option(selected_option)
                    if not project_slug:
                        return "⚠️ Select an invite", session
                    success, message = auth_service.reject_project_invite(session.username, project_slug)
                    refreshed = auth_service.refresh_session_authorizations(session.session_id) or session
                    if success:
                        _persist_admin_state()
                    return message, refreshed

                def _accept_all_invites(session):
                    if session is None:
                        return "❌ Login first", session
                    accepted, failed, message = auth_service.accept_all_project_invites(session.username)
                    refreshed = auth_service.refresh_session_authorizations(session.session_id) or session
                    if accepted > 0:
                        _persist_admin_state()
                    detail = f"{message}"
                    if failed:
                        detail = f"{detail} | failed={failed}"
                    return detail, refreshed

                session_state.change(
                    fn=update_project_selector,
                    inputs=[session_state],
                    outputs=[project_selector, project_info_display, selected_project_state, selected_dataset_repo_state],
                )

                session_state.change(
                    fn=_build_invites_ui,
                    inputs=[session_state],
                    outputs=[invitations_info, invite_selector],
                )

                refresh_invites_btn.click(
                    fn=_build_invites_ui,
                    inputs=[session_state],
                    outputs=[invitations_info, invite_selector],
                )

                accept_invite_btn.click(
                    fn=_accept_invite,
                    inputs=[session_state, invite_selector],
                    outputs=[project_info_display, session_state],
                ).then(
                    fn=update_project_selector,
                    inputs=[session_state],
                    outputs=[project_selector, project_info_display, selected_project_state, selected_dataset_repo_state],
                ).then(
                    fn=_build_invites_ui,
                    inputs=[session_state],
                    outputs=[invitations_info, invite_selector],
                )

                accept_all_invites_btn.click(
                    fn=_accept_all_invites,
                    inputs=[session_state],
                    outputs=[project_info_display, session_state],
                ).then(
                    fn=update_project_selector,
                    inputs=[session_state],
                    outputs=[project_selector, project_info_display, selected_project_state, selected_dataset_repo_state],
                ).then(
                    fn=_build_invites_ui,
                    inputs=[session_state],
                    outputs=[invitations_info, invite_selector],
                )

                reject_invite_btn.click(
                    fn=_reject_invite,
                    inputs=[session_state, invite_selector],
                    outputs=[project_info_display, session_state],
                ).then(
                    fn=_build_invites_ui,
                    inputs=[session_state],
                    outputs=[invitations_info, invite_selector],
                )

                def update_selected_project(selected: str, session):
                    """Update state when project is selected."""
                    if session and selected:
                        selected_project = admin_manager.get_project(selected)
                        dataset_repo_id = selected_project.dataset_repo_id if selected_project else ""
                        return selected, dataset_repo_id
                    return None, ""

                project_selector.change(
                    fn=update_selected_project,
                    inputs=[project_selector, session_state],
                    outputs=[selected_project_state, selected_dataset_repo_state],
                )

            # ===== TAB 4: Validation =====
            with gr.Tab("✓ Validation", id="validation_tab"):
                validation_status = gr.Markdown(
                    value="",
                    visible=False,
                )
                queue_badge = gr.HTML(value="", visible=False)
                seed_warning_banner = gr.Markdown(value="", visible=False)

                def render_seed_warning(warning_text: str):
                    text = (warning_text or "").strip()
                    if not text:
                        return gr.update(value="", visible=False)
                    return gr.update(value=text, visible=True)

                seed_warning_state.change(
                    fn=render_seed_warning,
                    inputs=[seed_warning_state],
                    outputs=[seed_warning_banner],
                )
                wrapper.load(
                    fn=render_seed_warning,
                    inputs=[seed_warning_state],
                    outputs=[seed_warning_banner],
                )

                def get_validation_status(session, selected_project, dataset_repo_id):
                    """Show status message based on login/project state."""
                    if session is None:
                        return "❌ **Not authenticated** — Login first in the **Login** tab"
                    if selected_project is None:
                        return f"⚠️ **Project not selected** — Select a project in the **Select Project** tab"
                    total_detections = _get_project_detection_count(service_ref["queue"], selected_project)
                    return (
                        f"✅ **Ready to validate** — Project: **{selected_project}** | "
                        f"User: **{session.username}** | Dataset: **{dataset_repo_id or 'not set'}** | "
                        f"Loaded detections: **{total_detections}**"
                    )

                session_state.change(
                    fn=lambda s, p, r: get_validation_status(s, p, r),
                    inputs=[session_state, selected_project_state, selected_dataset_repo_state],
                    outputs=[validation_status],
                )
                session_state.change(
                    fn=lambda p: _build_queue_badge(service_ref["queue"], p),
                    inputs=[selected_project_state],
                    outputs=[queue_badge],
                )

                selected_project_state.change(
                    fn=lambda s, p, r: get_validation_status(s, p, r),
                    inputs=[session_state, selected_project_state, selected_dataset_repo_state],
                    outputs=[validation_status],
                )
                selected_project_state.change(
                    fn=lambda p: _build_queue_badge(service_ref["queue"], p),
                    inputs=[selected_project_state],
                    outputs=[queue_badge],
                )

                selected_dataset_repo_state.change(
                    fn=lambda s, p, r: get_validation_status(s, p, r),
                    inputs=[session_state, selected_project_state, selected_dataset_repo_state],
                    outputs=[validation_status],
                )

                wrapper.load(
                    fn=lambda p: _build_queue_badge(service_ref["queue"], p),
                    inputs=[selected_project_state],
                    outputs=[queue_badge],
                )

                gr.Markdown("---")
                page_state = gr.State(value=1)
                project_species_state = gr.State(value=[])
                custom_corrected_species_state = gr.State(value={})
                favorite_detection_state = gr.State(value={})

                with gr.Row(equal_height=False):
                    with gr.Column(scale=8):
                        validation_summary_cards = gr.HTML(value=_build_validation_summary_cards([]))

                        spectrogram_title = gr.Markdown("### Spectrogram")
                        spectrogram_image = gr.Image(
                            label="",
                            type="filepath",
                            interactive=False,
                            height=330,
                        )
                        with gr.Row():
                            audio_player = gr.Audio(label="Selected Audio", type="filepath", autoplay=True)
                        auto_play_audio = gr.Checkbox(label="Auto-play selected audio", value=True)

                        with gr.Row():
                            approve_btn = gr.Button("Positive", variant="primary")
                            reject_btn = gr.Button("Negative")
                            uncertain_btn = gr.Button("Uncertain")
                            skip_btn = gr.Button("Skip")
                            favorite_btn = gr.Button("☆ Favorite", variant="secondary")

                        corrected_species_input = gr.Dropdown(
                            label="Corrected species",
                            choices=["Noise", "Undetermined"],
                            allow_custom_value=True,
                            filterable=True,
                            value=None,
                        )

                        status = gr.Textbox(label="Status", interactive=False)

                        table = gr.Dataframe(
                            headers=[
                                "detection_key",
                                "audio_id",
                                "scientific_name",
                                "confidence",
                                "start_time",
                                "end_time",
                                "validation_status",
                                "version",
                                "conflict_flag",
                                "conflict_severity",
                            ],
                            label="Detections",
                            interactive=False,
                        )
                        selected_index = gr.Number(label="Selected row", value=0, precision=0, visible=False)

                    with gr.Column(scale=4):
                        dataset_repo = gr.Textbox(label="Dataset repo", interactive=False)
                        species_filter = gr.Dropdown(
                            label="Species to validate",
                            choices=[],
                            value=None,
                            interactive=False,
                        )

                        gr.Markdown("#### Navigation")
                        with gr.Row():
                            prev_btn = gr.Button("←")
                            next_btn = gr.Button("→")

                        gr.Markdown("#### Filters")
                        min_confidence = gr.Slider(label="Minimum confidence", minimum=0.0, maximum=1.0, step=0.01, value=0.0)
                        validator_filter = gr.Textbox(label="Validator filter", placeholder="Ex: validator-demo")
                        validation_status_filter = gr.Dropdown(
                            label="Status filter",
                            choices=["all", "pending", "positive", "negative", "uncertain", "skip"],
                            value="all",
                        )
                        updated_after_filter = gr.DateTime(label="Updated since", include_time=False, type="string")
                        show_conflicts_only = gr.Checkbox(label="Show only conflicts", value=False)
                        refresh_btn = gr.Button("Apply Filters")

                        gr.Markdown("#### Actions")
                        validator_name = gr.Textbox(label="Validator", value="validator-demo")
                        validation_notes = gr.Textbox(label="Notes", placeholder="Optional", lines=4)
                        keyboard_shortcuts_info = gr.HTML(
                            value="<div style='font-size:12px;color:#333;padding:8px 10px;background:#f5f5f5;border-radius:6px;margin-bottom:8px;'>"
                            "<strong>Shortcuts:</strong> ArrowUp=Positive | ArrowDown=Negative | 1=Positive | 2=Negative | 3=Uncertain | 4=Skip"
                            "</div>"
                            "<script>"
                            "document.addEventListener('keydown', function(event) {"
                            "  if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;"
                            "  const key = event.key;"
                            "  let buttonText = null;"
                            "  if (key === 'ArrowUp' || key === '1') buttonText = 'Positive';"
                            "  else if (key === 'ArrowDown' || key === '2') buttonText = 'Negative';"
                            "  else if (key === '3') buttonText = 'Uncertain';"
                            "  else if (key === '4') buttonText = 'Skip';"
                            "  if (!buttonText) return;"
                            "  event.preventDefault();"
                            "  const buttons = document.querySelectorAll('button');"
                            "  for (const btn of buttons) {"
                            "    if ((btn.textContent || '').includes(buttonText)) { btn.click(); break; }"
                            "  }"
                            "});"
                            "</script>"
                        )

                cache_key_state = gr.State(value="")
                pending_status_state = gr.State(value="")
                conflict_detection_key_state = gr.State(value="")
                def _session_hf_token(session) -> str | None:
                    if session is None:
                        return None
                    return auth_service.get_hf_token_for_user(session.username)

                def _project_fetch_token(project_slug: str, session) -> str | None:
                    session_token = _session_hf_token(session)
                    if session_token:
                        return session_token

                    project = admin_manager.get_project(project_slug) if project_slug else None
                    if project is not None and project.visibility == "private":
                        if session is None or session.username != (project.owner_username or "").strip():
                            return None
                        project_token = (project.dataset_token or "").strip()
                        if project_token:
                            return project_token
                    return None

                def refresh(
                    project_slug: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                    only_conflicts: bool,
                ):
                    if not project_slug:
                        return [], "", 1
                    species_name = (species or "").strip()
                    if not species_name:
                        return [], "Select a species to start validation", 1

                    rows, status_text, updated_page = _page_to_table(
                        service=service_ref["queue"],
                        snapshot_reader=validation_repository,
                        project_slug=project_slug,
                        page=page,
                        scientific_name=species_name,
                        min_confidence=confidence,
                        page_size=runtime_config.page_size,
                        validator_filter=validator_filter_value,
                        status_filter=status_filter_value,
                        updated_after=updated_after_value,
                        show_conflicts_only=only_conflicts,
                    )
                    rows = _sort_rows_by_confidence_desc(rows)
                    return rows, status_text, updated_page

                def go_next(
                    project_slug: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                    only_conflicts: bool,
                ):
                    return refresh(
                        project_slug,
                        page + 1,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    )

                def go_prev(
                    project_slug: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                    only_conflicts: bool,
                ):
                    return refresh(
                        project_slug,
                        max(1, page - 1),
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    )

                def refresh_for_selected_project(project_slug: str):
                    if not project_slug:
                        return gr.update(choices=[], value=None, interactive=False), [], "", 1, None, None, _spectrogram_title(None, None), _build_validation_summary_cards([]), gr.update(choices=["Noise", "Undetermined"], value=None), []

                    species_options = _extract_species_options_from_queue(
                        queue_service=service_ref["queue"],
                        project_slug=project_slug,
                        page_size=max(32, runtime_config.page_size),
                    )
                    corrected_choices = species_options + ["Noise", "Undetermined"]
                    return (
                        gr.update(choices=species_options, value=None, interactive=True),
                        [],
                        "Select a species to start validation",
                        1,
                        None,
                        None,
                        _spectrogram_title(None, None),
                        _build_validation_summary_cards([]),
                        gr.update(choices=corrected_choices, value=None),
                        species_options,
                    )

                def save_for_project(
                    project_slug: str,
                    status_value: str,
                    rows: object,
                    idx: int,
                    name: str,
                    notes: str,
                    corrected_species_value: str | None,
                    cache_key: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                    only_conflicts: bool,
                ):
                    if not project_slug:
                        return "Select a project before validating", cache_key, None, rows, page, idx, "", ""
                    return _save_selected_validation_with_refresh(
                        validation_service=validation_service,
                        audio_service=audio_service,
                        queue_service=service_ref["queue"],
                        snapshot_reader=validation_repository,
                        project_slug=project_slug,
                        rows=rows,
                        selected_index=int(idx),
                        status_value=status_value,
                        validator=name,
                        notes=notes,
                        corrected_species=corrected_species_value,
                        cache_key=cache_key,
                        page=int(page),
                        scientific_name=species,
                        min_confidence=float(confidence),
                        validator_filter=validator_filter_value,
                        status_filter=status_filter_value,
                        updated_after=updated_after_value,
                        show_conflicts_only=bool(only_conflicts),
                    )

                def reapply_for_project(
                    project_slug: str,
                    rows: object,
                    idx: int,
                    pending_status: str,
                    conflict_key: str,
                    name: str,
                    notes: str,
                    cache_key: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                    only_conflicts: bool,
                ):
                    if not project_slug:
                        return "Select a project before reapplying", cache_key, None, rows, page, idx, pending_status, conflict_key
                    return _reapply_last_conflict_validation_with_refresh(
                        validation_service=validation_service,
                        audio_service=audio_service,
                        queue_service=service_ref["queue"],
                        snapshot_reader=validation_repository,
                        project_slug=project_slug,
                        rows=rows,
                        selected_index=int(idx),
                        pending_status_value=pending_status,
                        conflict_detection_key=conflict_key,
                        validator=name,
                        notes=notes,
                        cache_key=cache_key,
                        page=int(page),
                        scientific_name=species,
                        min_confidence=float(confidence),
                        validator_filter=validator_filter_value,
                        status_filter=status_filter_value,
                        updated_after=updated_after_value,
                        show_conflicts_only=bool(only_conflicts),
                    )

                def batch_for_project(
                    project_slug: str,
                    rows: object,
                    status_value: str,
                    name: str,
                    notes: str,
                    cache_key: str,
                    page: int,
                    species: str,
                    confidence: float,
                    validator_filter_value: str,
                    status_filter_value: str,
                    updated_after_value: object,
                ):
                    if not project_slug:
                        return "Select a project before validating", cache_key, None, rows, page
                    return _batch_validate_conflicts(
                        validation_service=validation_service,
                        audio_service=audio_service,
                        queue_service=service_ref["queue"],
                        snapshot_reader=validation_repository,
                        project_slug=project_slug,
                        rows=rows,
                        status_value=status_value,
                        validator=name,
                        notes=notes,
                        cache_key=cache_key,
                        page=int(page),
                        scientific_name=species,
                        min_confidence=float(confidence),
                        validator_filter=validator_filter_value,
                        status_filter=status_filter_value,
                        updated_after=updated_after_value,
                    )

                def build_report_for_project(project_slug: str) -> str:
                    if not project_slug:
                        return "Select a project to generate report"
                    return _build_validation_report(validation_repository, project_slug)

                def save_corrected_species_option(
                    project_slug: str,
                    corrected_value: str | None,
                    detected_species: list[str],
                    custom_by_project: dict[str, list[str]],
                ):
                    base_choices = list(dict.fromkeys([*detected_species, "Noise", "Undetermined"]))
                    value = (corrected_value or "").strip()

                    if not project_slug:
                        return gr.update(choices=base_choices, value=value or None), custom_by_project

                    updated = {k: list(v) for k, v in (custom_by_project or {}).items()}
                    custom_values = updated.get(project_slug, [])
                    if value and value not in base_choices and value not in custom_values:
                        custom_values.append(value)
                        updated[project_slug] = custom_values

                    final_choices = list(dict.fromkeys([*base_choices, *updated.get(project_slug, [])]))
                    return gr.update(choices=final_choices, value=value or None), updated

                def toggle_favorite_detection(
                    project_slug: str,
                    rows: object,
                    idx: int,
                    favorite_map: dict[str, list[str]],
                ):
                    normalized_rows = _normalize_rows(rows)
                    if not project_slug or not normalized_rows:
                        return "No detection selected to favorite", favorite_map, gr.update(value="☆ Favorite", variant="secondary")

                    safe_idx = max(0, min(int(idx), len(normalized_rows) - 1))
                    detection_key = str(normalized_rows[safe_idx][0]).strip()
                    updated_map = {k: list(v) for k, v in (favorite_map or {}).items()}
                    project_favs = set(updated_map.get(project_slug, []))
                    if detection_key in project_favs:
                        project_favs.remove(detection_key)
                        action = "removed from favorites"
                        button_update = gr.update(value="☆ Favorite", variant="secondary")
                    else:
                        project_favs.add(detection_key)
                        action = "added to favorites"
                        button_update = gr.update(value="★ Favorited", variant="primary")
                    updated_map[project_slug] = sorted(project_favs)
                    return f"Detection {detection_key} {action}", updated_map, button_update

                def update_favorite_button_state(
                    project_slug: str,
                    rows: object,
                    idx: int,
                    favorite_map: dict[str, list[str]],
                ):
                    normalized_rows = _normalize_rows(rows)
                    if not project_slug or not normalized_rows:
                        return gr.update(value="☆ Favorite", variant="secondary")

                    safe_idx = max(0, min(int(idx), len(normalized_rows) - 1))
                    detection_key = str(normalized_rows[safe_idx][0]).strip()
                    favs = set((favorite_map or {}).get(project_slug, []))
                    if detection_key in favs:
                        return gr.update(value="★ Favorited", variant="primary")
                    return gr.update(value="☆ Favorite", variant="secondary")

                def on_table_select(project_slug: str, repo: str, rows: object, cache_key: str, session, evt: gr.SelectData):
                    return _select_and_fetch_audio_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        cache_key=cache_key,
                        evt=evt,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    )

                refresh_event = refresh_btn.click(
                    fn=refresh,
                    inputs=[
                        selected_project_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[table, status, page_state],
                )
                next_event = next_btn.click(
                    fn=go_next,
                    inputs=[
                        selected_project_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[table, status, page_state],
                )
                prev_event = prev_btn.click(
                    fn=go_prev,
                    inputs=[
                        selected_project_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[table, status, page_state],
                )

                selected_dataset_repo_state.change(
                    fn=lambda repo_id: gr.update(value=repo_id),
                    inputs=[selected_dataset_repo_state],
                    outputs=[dataset_repo],
                )
                project_change_event = selected_project_state.change(
                    fn=refresh_for_selected_project,
                    inputs=[selected_project_state],
                    outputs=[species_filter, table, status, page_state, audio_player, spectrogram_image, spectrogram_title, validation_summary_cards, corrected_species_input, project_species_state],
                )

                species_filter.change(
                    fn=lambda project_slug, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: refresh(
                        project_slug,
                        1,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    ),
                    inputs=[
                        selected_project_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[table, status, page_state],
                ).then(
                    fn=lambda rows: _build_validation_summary_cards(rows),
                    inputs=[table],
                    outputs=[validation_summary_cards],
                ).then(
                    fn=lambda project_slug, repo, rows, cache_key, session: _autofetch_first_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                )

                table_select_event = table.select(
                    fn=on_table_select,
                    inputs=[selected_project_state, selected_dataset_repo_state, table, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                )
                table_select_event.then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                )

                auto_play_audio.change(
                    fn=lambda enabled: gr.update(autoplay=bool(enabled)),
                    inputs=[auto_play_audio],
                    outputs=[audio_player],
                )

                refresh_event.then(
                    fn=lambda rows: _build_validation_summary_cards(rows),
                    inputs=[table],
                    outputs=[validation_summary_cards],
                ).then(
                    fn=lambda project_slug, repo, rows, cache_key, session: _autofetch_first_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                )
                next_event.then(
                    fn=lambda rows: _build_validation_summary_cards(rows),
                    inputs=[table],
                    outputs=[validation_summary_cards],
                ).then(
                    fn=lambda project_slug, repo, rows, cache_key, session: _autofetch_first_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                )
                prev_event.then(
                    fn=lambda rows: _build_validation_summary_cards(rows),
                    inputs=[table],
                    outputs=[validation_summary_cards],
                ).then(
                    fn=lambda project_slug, repo, rows, cache_key, session: _autofetch_first_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                )

                favorite_btn.click(
                    fn=toggle_favorite_detection,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[status, favorite_detection_state, favorite_btn],
                )

                corrected_species_input.change(
                    fn=save_corrected_species_option,
                    inputs=[selected_project_state, corrected_species_input, project_species_state, custom_corrected_species_state],
                    outputs=[corrected_species_input, custom_corrected_species_state],
                )

                approve_event = approve_btn.click(
                    fn=lambda project_slug, rows, idx, name, notes, corrected_species_value, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: save_for_project(
                        project_slug,
                        "positive",
                        rows,
                        idx,
                        name,
                        notes,
                        corrected_species_value,
                        cache_key,
                        page,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    ),
                    inputs=[
                        selected_project_state,
                        table,
                        selected_index,
                        validator_name,
                        validation_notes,
                        corrected_species_input,
                        cache_key_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
                )
                reject_event = reject_btn.click(
                    fn=lambda project_slug, rows, idx, name, notes, corrected_species_value, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: save_for_project(
                        project_slug,
                        "negative",
                        rows,
                        idx,
                        name,
                        notes,
                        corrected_species_value,
                        cache_key,
                        page,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    ),
                    inputs=[
                        selected_project_state,
                        table,
                        selected_index,
                        validator_name,
                        validation_notes,
                        corrected_species_input,
                        cache_key_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
                )
                uncertain_event = uncertain_btn.click(
                    fn=lambda project_slug, rows, idx, name, notes, corrected_species_value, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: save_for_project(
                        project_slug,
                        "uncertain",
                        rows,
                        idx,
                        name,
                        notes,
                        corrected_species_value,
                        cache_key,
                        page,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    ),
                    inputs=[
                        selected_project_state,
                        table,
                        selected_index,
                        validator_name,
                        validation_notes,
                        corrected_species_input,
                        cache_key_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
                )
                skip_event = skip_btn.click(
                    fn=lambda project_slug, rows, idx, name, notes, corrected_species_value, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: save_for_project(
                        project_slug,
                        "skip",
                        rows,
                        idx,
                        name,
                        notes,
                        corrected_species_value,
                        cache_key,
                        page,
                        species,
                        confidence,
                        validator_filter_value,
                        status_filter_value,
                        updated_after_value,
                        only_conflicts,
                    ),
                    inputs=[
                        selected_project_state,
                        table,
                        selected_index,
                        validator_name,
                        validation_notes,
                        corrected_species_input,
                        cache_key_state,
                        page_state,
                        species_filter,
                        min_confidence,
                        validator_filter,
                        validation_status_filter,
                        updated_after_filter,
                        show_conflicts_only,
                    ],
                    outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
                )

                approve_event.then(
                    fn=lambda project_slug, repo, rows, idx, cache_key, session: _advance_to_next_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        selected_index=int(idx),
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, selected_index, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                ).then(fn=lambda rows: _build_validation_summary_cards(rows), inputs=[table], outputs=[validation_summary_cards])

                reject_event.then(
                    fn=lambda project_slug, repo, rows, idx, cache_key, session: _advance_to_next_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        selected_index=int(idx),
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, selected_index, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                ).then(fn=lambda rows: _build_validation_summary_cards(rows), inputs=[table], outputs=[validation_summary_cards])

                uncertain_event.then(
                    fn=lambda project_slug, repo, rows, idx, cache_key, session: _advance_to_next_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        selected_index=int(idx),
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, selected_index, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                ).then(fn=lambda rows: _build_validation_summary_cards(rows), inputs=[table], outputs=[validation_summary_cards])

                skip_event.then(
                    fn=lambda project_slug, repo, rows, idx, cache_key, session: _advance_to_next_row_with_title(
                        audio_service=audio_service,
                        dataset_repo=repo,
                        rows=rows,
                        selected_index=int(idx),
                        cache_key=cache_key,
                        allow_demo_fallback=False,
                        hf_token=_project_fetch_token(project_slug, session),
                    ),
                    inputs=[selected_project_state, selected_dataset_repo_state, table, selected_index, cache_key_state, session_state],
                    outputs=[selected_index, audio_player, cache_key_state, status, spectrogram_image, spectrogram_title],
                ).then(
                    fn=lambda rows, idx: _mark_selected_row(rows, int(idx)),
                    inputs=[table, selected_index],
                    outputs=[table],
                ).then(
                    fn=update_favorite_button_state,
                    inputs=[selected_project_state, table, selected_index, favorite_detection_state],
                    outputs=[favorite_btn],
                ).then(fn=lambda rows: _build_validation_summary_cards(rows), inputs=[table], outputs=[validation_summary_cards])

                session_state.change(
                    fn=lambda s: gr.update(value=(s.username if s is not None else "")),
                    inputs=[session_state],
                    outputs=[validator_name],
                )

            # ===== TAB 5: Report =====
            with gr.Tab("📊 Report", id="report_tab"):
                report_header = gr.Markdown("### Validation Dashboard")
                report_project_selector = gr.Dropdown(
                    choices=[],
                    value=None,
                    label="Project",
                    interactive=False,
                    allow_custom_value=True,
                )
                report_kpis = gr.HTML(value="")
                report_species_table = gr.Dataframe(
                    headers=["species", "total_recordings", "validated", "remaining"],
                    value=[],
                    interactive=False,
                    label="Species Overview",
                )
                report_status = gr.Markdown("")

                def _list_project_detections(project_slug: str) -> list[Detection]:
                    if not project_slug:
                        return []
                    page = 1
                    collected: list[Detection] = []
                    while True:
                        page_obj = service_ref["queue"].get_page(
                            project_slug=project_slug,
                            page=page,
                            page_size=500,
                            scientific_name=None,
                            min_confidence=None,
                            max_confidence=None,
                        )
                        collected.extend(page_obj.items)
                        if not page_obj.has_next:
                            break
                        page += 1
                    return collected

                def _render_report_dashboard(project_slug: str):
                    slug = (project_slug or "").strip()
                    if not slug:
                        return "", [], "Select a project to view the dashboard"

                    items = _list_project_detections(slug)
                    snapshot = validation_repository.load_current_snapshot(project_slug=slug)
                    total_recordings = len(items)

                    species_totals: dict[str, dict[str, int]] = {}
                    validated_recordings = 0

                    for item in items:
                        species_name = str(item.scientific_name).strip() or "Unknown species"
                        counters = species_totals.setdefault(species_name, {"total": 0, "validated": 0})
                        counters["total"] += 1

                        state = snapshot.get(item.detection_key, {})
                        status_value = str(state.get("status", "pending")).strip().lower()
                        if status_value and status_value != "pending":
                            counters["validated"] += 1
                            validated_recordings += 1

                    validated_species = sum(1 for counters in species_totals.values() if counters["validated"] > 0)
                    remaining_recordings = max(0, total_recordings - validated_recordings)

                    rows = []
                    for species_name, counters in species_totals.items():
                        remaining = max(0, counters["total"] - counters["validated"])
                        rows.append([species_name, counters["total"], counters["validated"], remaining])
                    rows.sort(key=lambda row: (-int(row[1]), str(row[0]).lower()))

                    kpis_html = (
                        "<div style='display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:12px;margin:6px 0 12px 0;'>"
                        f"<div style='padding:10px 14px;border-radius:10px;background:#eef2ff;'><div style='font-size:12px;color:#4f46e5;'>Validated species</div><div style='font-size:24px;font-weight:700;color:#312e81;'>{validated_species}</div></div>"
                        f"<div style='padding:10px 14px;border-radius:10px;background:#fff7ed;'><div style='font-size:12px;color:#c2410c;'>Recordings remaining</div><div style='font-size:24px;font-weight:700;color:#9a3412;'>{remaining_recordings}</div></div>"
                        f"<div style='padding:10px 14px;border-radius:10px;background:#ecfdf3;'><div style='font-size:12px;color:#166534;'>Recordings validated</div><div style='font-size:24px;font-weight:700;color:#14532d;'>{validated_recordings}</div></div>"
                        "</div>"
                    )
                    status_text = (
                        f"Project: **{slug}** | Total recordings: **{total_recordings}** | "
                        f"Validated: **{validated_recordings}** | Remaining: **{remaining_recordings}**"
                    )
                    return kpis_html, rows, status_text

                session_state.change(
                    fn=lambda s: (
                        gr.update(
                            choices=(s.authorized_projects if s is not None else []),
                            value=(s.authorized_projects[0] if (s is not None and s.authorized_projects) else None),
                            interactive=bool(s is not None and s.authorized_projects),
                        ),
                        "",
                        [],
                        "Login and choose a project to view metrics" if s is None else "",
                    ),
                    inputs=[session_state],
                    outputs=[report_project_selector, report_kpis, report_species_table, report_status],
                )

                selected_project_state.change(
                    fn=lambda p: gr.update(value=p if p else None),
                    inputs=[selected_project_state],
                    outputs=[report_project_selector],
                )

                report_project_selector.change(
                    fn=_render_report_dashboard,
                    inputs=[report_project_selector],
                    outputs=[report_kpis, report_species_table, report_status],
                )

    return wrapper
