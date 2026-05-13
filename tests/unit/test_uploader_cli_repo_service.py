import json

import pytest
import requests

from src.uploader_cli.exceptions import RepositoryError
from src.uploader_cli.repo_service import RepositoryService


class _FakeApi:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.created_repo_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.repo_files: list[str] = []

    def create_repo(self, repo_id: str, repo_type: str, private: bool, exist_ok: bool) -> None:
        self.created_repo_calls.append(
            {
                "repo_id": repo_id,
                "repo_type": repo_type,
                "private": private,
                "exist_ok": exist_ok,
            }
        )

    def upload_file(self, path_or_fileobj, path_in_repo: str, repo_id: str, repo_type: str) -> None:
        payload_bytes = b""
        if hasattr(path_or_fileobj, "read"):
            payload_bytes = path_or_fileobj.read()
        elif isinstance(path_or_fileobj, (bytes, bytearray)):
            payload_bytes = bytes(path_or_fileobj)

        self.upload_calls.append(
            {
                "path_in_repo": path_in_repo,
                "repo_id": repo_id,
                "repo_type": repo_type,
                "payload": payload_bytes,
            }
        )

    def list_repo_files(self, repo_id: str, repo_type: str = "dataset") -> list[str]:
        _ = repo_id
        _ = repo_type
        return list(self.repo_files)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _install_request_fakes(monkeypatch: pytest.MonkeyPatch, *, repo_exists: bool, manifest_exists: bool) -> None:
    def _fake_request(method: str, url: str, timeout=None, headers=None):
        _ = timeout
        _ = headers
        if method == "GET" and "/api/datasets/" in url:
            return _FakeResponse(200 if repo_exists else 404)
        if method == "HEAD" and "/resolve/main/index/manifest.json" in url:
            return _FakeResponse(200 if manifest_exists else 404)
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("src.uploader_cli.repo_service.requests.request", _fake_request)


def test_create_dataset_initializes_expected_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api = _FakeApi(token="hf_test")
    monkeypatch.setattr("src.uploader_cli.repo_service.HfApi", lambda token: fake_api)

    service = RepositoryService(token="hf_test")
    repo_id = service.create_dataset("alice/parrots-2026", private=True)

    assert repo_id == "alice/parrots-2026"
    assert len(fake_api.created_repo_calls) == 1
    assert fake_api.created_repo_calls[0]["repo_type"] == "dataset"
    assert fake_api.created_repo_calls[0]["private"] is True

    uploaded_paths = [call["path_in_repo"] for call in fake_api.upload_calls]
    assert "audio/parrots-2026/.gitkeep" in uploaded_paths
    assert "index/shards/.gitkeep" in uploaded_paths
    assert "validations/.gitkeep" in uploaded_paths
    assert "audit/ingestion-runs/.gitkeep" in uploaded_paths
    assert "index/manifest.json" in uploaded_paths

    manifest_payload = next(call for call in fake_api.upload_calls if call["path_in_repo"] == "index/manifest.json")
    manifest = json.loads(manifest_payload["payload"].decode("utf-8"))
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["project_slug"] == "parrots-2026"
    assert manifest["dataset_repo_id"] == "alice/parrots-2026"


def test_create_dataset_rejects_invalid_repo_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.uploader_cli.repo_service.HfApi", lambda token: _FakeApi(token=token))

    service = RepositoryService(token="hf_test")
    with pytest.raises(RepositoryError, match="owner/name"):
        service.create_dataset("invalid_repo")


def test_validate_repo_returns_valid_for_expected_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api = _FakeApi(token="hf_test")
    monkeypatch.setattr("src.uploader_cli.repo_service.HfApi", lambda token: fake_api)
    _install_request_fakes(monkeypatch, repo_exists=True, manifest_exists=True)

    service = RepositoryService(token="hf_test")
    result = service.validate_repo("alice/parrots-2026")

    assert result["is_valid"] is True
    assert result["missing_prefixes"] == []
    assert result["has_manifest"] is True
    assert result["project_slug"] == "parrots-2026"


def test_validate_repo_reports_missing_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api = _FakeApi(token="hf_test")
    monkeypatch.setattr("src.uploader_cli.repo_service.HfApi", lambda token: fake_api)
    _install_request_fakes(monkeypatch, repo_exists=True, manifest_exists=False)

    service = RepositoryService(token="hf_test")
    result = service.validate_repo("alice/parrots-2026")

    assert result["is_valid"] is True
    assert result["has_manifest"] is False
    assert result["manifest_error"]


def test_validate_repo_rejects_invalid_repo_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.uploader_cli.repo_service.HfApi", lambda token: _FakeApi(token=token))
    service = RepositoryService(token="hf_test")

    with pytest.raises(RepositoryError, match="owner/name"):
        service.validate_repo("bad-format")
