from __future__ import annotations

import os
import json
import time
import logging
from io import BytesIO
from typing import Any
import requests

os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "5")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

from .config import INDEX_SHARD_SIZE, SCHEMA_VERSION, RETRY_MAX_ATTEMPTS, RETRY_INITIAL_BACKOFF_SECONDS

logger = logging.getLogger("hf_dataset_uploader.repo_service")
from .exceptions import RepositoryError


class RepositoryService:
    """Create and initialize dataset repositories for uploader sessions."""

    def __init__(self, token: str):
        # Import HfApi lazily to allow callers to set HF tuning/env before import
        from huggingface_hub import HfApi

        self._api = HfApi(token=token)

    def create_dataset(self, repo_id: str, *, private: bool = True, initialize_structure: bool = True) -> str:
        if not self._is_valid_repo_id(repo_id):
            raise RepositoryError("Repository id must be in the form 'owner/name'")

        try:
            self._api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
            if initialize_structure:
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

        max_attempts = RETRY_MAX_ATTEMPTS or 3
        backoff_base = RETRY_INITIAL_BACKOFF_SECONDS or 1.0
        connect_timeout = float(os.getenv("BNU_REPO_VALIDATE_CONNECT_TIMEOUT", "8"))
        read_timeout = float(os.getenv("BNU_REPO_VALIDATE_READ_TIMEOUT", "20"))

        def _request(method: str, url: str) -> requests.Response:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info("%s %s (attempt %d)", method, url, attempt)
                    start = time.time()
                    headers = {}
                    token = getattr(self._api, "token", None)
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    response = requests.request(method, url, timeout=(connect_timeout, read_timeout), headers=headers)
                    duration = time.time() - start
                    logger.info("%s %s -> %s in %.2fs", method, url, response.status_code, duration)
                    return response
                except Exception as exc:  # pragma: no cover - external network behavior
                    last_exc = exc
                    logger.warning("%s %s failed on attempt %d: %s", method, url, attempt, exc)
                    if attempt >= max_attempts:
                        raise
                    time.sleep(backoff_base * (2 ** (attempt - 1)))
            raise last_exc or RepositoryError(f"Request failed: {method} {url}")

        repo_api_url = f"https://huggingface.co/api/datasets/{repo_id}"
        repo_response = _request("GET", repo_api_url)
        if repo_response.status_code == 404:
            raise RepositoryError(f"Could not list dataset files: repository not found ({repo_id})")
        if repo_response.status_code >= 400:
            raise RepositoryError(f"Could not validate dataset repository: HTTP {repo_response.status_code}")

        manifest_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/index/manifest.json"
        try:
            manifest_response = _request("HEAD", manifest_url)
            has_manifest = manifest_response.status_code == 200
            manifest_error = "" if has_manifest else "index/manifest.json not found"
        except Exception as exc:  # pragma: no cover - network behavior
            logger.warning("Manifest check failed for %s, but repo exists so upload can continue: %s", repo_id, exc)
            has_manifest = False
            manifest_error = str(exc)

        project_slug = self._project_slug_from_repo_id(repo_id)
        is_valid = True
        missing_prefixes = []

        return {
            "repo_id": repo_id,
            "is_valid": is_valid,
            "project_slug": project_slug,
            "missing_prefixes": missing_prefixes,
            "has_manifest": has_manifest,
            "manifest_ok": bool(has_manifest),
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
