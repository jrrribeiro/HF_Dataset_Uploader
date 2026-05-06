from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from huggingface_hub import HfApi

from .config import INDEX_SHARD_SIZE, SCHEMA_VERSION
from .exceptions import RepositoryError


class RepositoryService:
    """Create and initialize dataset repositories for uploader sessions."""

    def __init__(self, token: str):
        self._api = HfApi(token=token)

    def create_dataset(self, repo_id: str, *, private: bool = True) -> str:
        if not self._is_valid_repo_id(repo_id):
            raise RepositoryError("Repository id must be in the form 'owner/name'")

        try:
            self._api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
            self._init_structure(repo_id)
        except Exception as exc:  # pragma: no cover - external API behavior
            raise RepositoryError(f"Could not create dataset: {exc}") from exc

        return repo_id

    def _init_structure(self, repo_id: str) -> None:
        project_slug = self._project_slug_from_repo_id(repo_id)
        placeholder_dirs = [
            f"audio/{project_slug}/.gitkeep",
            "index/shards/.gitkeep",
            "validations/.gitkeep",
            "audit/ingestion-runs/.gitkeep",
        ]

        for path_in_repo in placeholder_dirs:
            self._api.upload_file(
                path_or_fileobj=BytesIO(b""),
                path_in_repo=path_in_repo,
                repo_id=repo_id,
                repo_type="dataset",
            )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_slug": project_slug,
            "dataset_repo_id": repo_id,
            "index": {
                "total_detections": 0,
                "total_audio_files": 0,
                "shard_size": INDEX_SHARD_SIZE,
                "shards": [],
            },
        }
        self._api.upload_file(
            path_or_fileobj=BytesIO(json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")),
            path_in_repo="index/manifest.json",
            repo_id=repo_id,
            repo_type="dataset",
        )

    def validate_repo(self, repo_id: str) -> dict[str, Any]:
        if not self._is_valid_repo_id(repo_id):
            raise RepositoryError("Repository id must be in the form 'owner/name'")

        try:
            repo_files = self._api.list_repo_files(repo_id=repo_id, repo_type="dataset")
        except Exception as exc:  # pragma: no cover - external API behavior
            raise RepositoryError(f"Could not list dataset files: {exc}") from exc

        project_slug = self._project_slug_from_repo_id(repo_id)
        required_prefixes = [
            f"audio/{project_slug}/",
            "index/shards/",
            "validations/",
            "audit/ingestion-runs/",
        ]
        missing_prefixes = [
            prefix for prefix in required_prefixes if not any(path.startswith(prefix) for path in repo_files)
        ]

        has_manifest = "index/manifest.json" in repo_files
        manifest_ok = has_manifest
        manifest_error = ""

        is_valid = not missing_prefixes and has_manifest
        return {
            "repo_id": repo_id,
            "is_valid": is_valid,
            "project_slug": project_slug,
            "missing_prefixes": missing_prefixes,
            "has_manifest": has_manifest,
            "manifest_ok": manifest_ok if has_manifest else False,
            "manifest_error": manifest_error,
        }

    @staticmethod
    def _is_valid_repo_id(repo_id: str) -> bool:
        if not repo_id or repo_id.count("/") != 1:
            return False
        owner, name = repo_id.split("/", maxsplit=1)
        return bool(owner.strip()) and bool(name.strip()) and " " not in repo_id

    @staticmethod
    def _project_slug_from_repo_id(repo_id: str) -> str:
        return repo_id.split("/", maxsplit=1)[1]
