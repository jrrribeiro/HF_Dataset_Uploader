from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Callable

from huggingface_hub import HfApi

from .repo_service import RepositoryService
from .scanner import LocalScanner
from .deduplicator import Deduplicator
from .batch_uploader import BatchUploader
from .manifest import build_manifest_from_scan, manifest_to_bytes, write_shards_from_csv_rows
from .session_manager import SessionManager
from .config import WEB_UI_MAX_SIZE_BYTES


def perform_upload(token: str, repo_id: str, file_paths: List[str] | None, csv_path: str | None, remote_base: str, workers: int | None, progress_callback: Callable[[float, str], None] | None = None) -> dict:
    """Perform upload using the existing backend modules.

    progress_callback(percent: float (0.0-1.0), message: str)
    Returns a result dict with uploaded/skipped/failed counts.
    """
    def prog(p: float, desc: str = ""):
        if progress_callback:
            try:
                progress_callback(p, desc)
            except Exception:
                pass

    if not token or not repo_id:
        raise ValueError("token and repo_id are required")

    tmpdir = Path(tempfile.mkdtemp(prefix="hf-dataset-uploader-native-"))
    try:
        prog(0.0, "Initializing upload")
        # copy files into tmpdir
        audio_dir = tmpdir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        if file_paths:
            for p in file_paths:
                pth = Path(p)
                if pth.is_file():
                    suffix = pth.suffix.lower()
                    if suffix in {".zip", ".tar", ".gz", ".tar.gz"}:
                        try:
                            if suffix == ".zip":
                                with zipfile.ZipFile(pth, "r") as zf:
                                    zf.extractall(audio_dir)
                            else:
                                with tarfile.open(pth, "r:*") as tf:
                                    tf.extractall(audio_dir)
                        except Exception:
                            # fallback: copy
                            shutil.copy(pth, audio_dir / pth.name)
                    else:
                        shutil.copy(pth, audio_dir / pth.name)

        # Validate size
        total_size = sum(f.stat().st_size for f in audio_dir.rglob("*") if f.is_file())
        if total_size > WEB_UI_MAX_SIZE_BYTES:
            raise RuntimeError(f"Upload exceeds max size {WEB_UI_MAX_SIZE_BYTES} bytes")

        api = HfApi(token=token)
        repo_service = RepositoryService(token)
        prog(0.2, "Validating repository")
        try:
            validation = repo_service.validate_repo(repo_id)
            if not validation.get("is_valid"):
                repo_service.create_dataset(repo_id, private=True)
        except Exception:
            # try create
            repo_service.create_dataset(repo_id, private=True)

        prog(0.3, "Scanning files")
        scanner = LocalScanner()
        summary = scanner.scan_folder(str(audio_dir))
        # Upload CSV if provided
        if csv_path:
            try:
                api.upload_file(path_or_fileobj=str(csv_path), path_in_repo="index/detections.csv", repo_id=repo_id, repo_type="dataset")
            except Exception:
                # continue without CSV
                pass

        prog(0.5, "Building manifest and uploading")
        csv_rows = None
        if csv_path:
            try:
                import csv
                with open(csv_path, newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    csv_rows = list(reader)
            except Exception:
                csv_rows = None

        manifest = build_manifest_from_scan(repo_id, summary, csv_rows=csv_rows)
        api.upload_file(path_or_fileobj=manifest_to_bytes(manifest), path_in_repo="index/manifest.json", repo_id=repo_id, repo_type="dataset")

        # shards
        if csv_rows:
            try:
                shards = write_shards_from_csv_rows(csv_rows)
                for shard_path in shards:
                    try:
                        api.upload_file(path_or_fileobj=str(shard_path), path_in_repo=f"index/shards/{shard_path.name}", repo_id=repo_id, repo_type="dataset")
                    except Exception:
                        continue
            except Exception:
                pass

        prog(0.7, "Preparing uploads")
        dedup = Deduplicator(api=api, repo_id=repo_id)
        session = SessionManager()
        uploader = BatchUploader(api=api, repo_id=repo_id, deduplicator=dedup, session=session, max_workers=workers)

        file_infos = []
        for species, items in summary.get("by_species", {}).items():
            for it in items:
                file_infos.append({"full_path": it["full_path"], "relative_path": it["relative_path"], "size": it.get("size", 0)})

        def on_progress(state: dict):
            uploaded = state.get("uploaded", 0)
            total = len(file_infos)
            prog(0.7 + (0.25 * uploaded / max(total, 1)), f"Uploading: {uploaded}/{total}")

        prog(0.7, "Starting uploads")
        result = uploader.upload_files(file_infos, remote_base=remote_base or "audio", on_progress=on_progress)

        prog(0.95, "Finalizing")
        return result
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass
