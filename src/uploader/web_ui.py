from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import List

import gradio as gr

from huggingface_hub import HfApi

from .auth_service import AuthService
from .repo_service import RepositoryService
from .scanner import LocalScanner
from .deduplicator import Deduplicator
from .batch_uploader import BatchUploader
from .manifest import build_manifest_from_scan, manifest_to_bytes, write_shards_from_csv_rows
from .session_manager import SessionManager


def _store_uploaded_files(files: List, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if not files:
        return
    for f in files:
        # Gradio may pass either a path string, a file-like object, or a dict
        src_path = None
        if isinstance(f, str) and os.path.exists(f):
            src_path = f
        elif hasattr(f, "name") and isinstance(getattr(f, "name"), str) and os.path.exists(getattr(f, "name")):
            src_path = getattr(f, "name")
        elif isinstance(f, dict) and f.get("name") and os.path.exists(f.get("name")):
            src_path = f.get("name")

        if src_path:
            shutil.copy(src_path, dst / Path(src_path).name)
        else:
            # fallback: try reading bytes and write
            try:
                data = f.read()
                out_path = dst / (getattr(f, "name", "uploaded_file"))
                with open(out_path, "wb") as fh:
                    fh.write(data)
            except Exception:
                # ignore silently for best-effort behavior
                continue


def _handle_upload(token: str, repo_id: str, files, csv_file, remote_base: str, workers: int | None):
    # Basic validation
    if not token or not repo_id:
        return "Error: token and repo_id are required." , None

    # Store uploaded files to a temp directory
    tmpdir = Path(tempfile.mkdtemp(prefix="birdnet-upload-"))
    try:
        _store_uploaded_files(files or [], tmpdir)

        csv_path = None
        if csv_file:
            csv_tmp = tmpdir / Path(csv_file.name).name if hasattr(csv_file, "name") else tmpdir / "detections.csv"
            try:
                # csv_file may be a dict or file-like
                if isinstance(csv_file, str) and os.path.exists(csv_file):
                    shutil.copy(csv_file, csv_tmp)
                elif hasattr(csv_file, "name") and os.path.exists(getattr(csv_file, "name")):
                    shutil.copy(getattr(csv_file, "name"), csv_tmp)
                elif isinstance(csv_file, dict) and csv_file.get("name") and os.path.exists(csv_file.get("name")):
                    shutil.copy(csv_file.get("name"), csv_tmp)
                else:
                    # try read() then write
                    data = csv_file.read()
                    with open(csv_tmp, "wb") as fh:
                        fh.write(data)
                csv_path = str(csv_tmp)
            except Exception:
                csv_path = None

        # Validate repo / create if necessary
        api = HfApi(token=token)
        repo_service = RepositoryService(token)
        validation = repo_service.validate_repo(repo_id)
        if not validation.get("is_valid"):
            # attempt to create required structure
            try:
                repo_service.create_dataset(repo_id, private=True)
            except Exception:
                # fall back to warning
                pass

        # Build scan summary from files on disk
        scanner = LocalScanner()
        # LocalScanner expects a directory of segments; use tmpdir
        summary = scanner.scan_folder(str(tmpdir))

        # Upload CSV if present
        try:
            if csv_path:
                api.upload_file(path_or_file=str(csv_path), path_in_repo="index/detections.csv", repo_id=repo_id, repo_type="dataset")
        except Exception as exc:
            return f"CSV upload failed: {exc}", None

        # Build and upload manifest
        try:
            csv_rows = None
            if csv_path:
                import csv

                with open(csv_path, newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    csv_rows = list(reader)

            manifest = build_manifest_from_scan(repo_id, summary, csv_rows=csv_rows)
            api.upload_file(path_or_fileobj=manifest_to_bytes(manifest), path_in_repo="index/manifest.json", repo_id=repo_id, repo_type="dataset")
        except Exception as exc:
            return f"Manifest upload failed: {exc}", None

        # Generate and upload shards if CSV provided
        try:
            if csv_path and csv_rows:
                shards = write_shards_from_csv_rows(csv_rows)
                for shard_path in shards:
                    try:
                        api.upload_file(path_or_file=str(shard_path), path_in_repo=f"index/shards/{shard_path.name}", repo_id=repo_id, repo_type="dataset")
                    except Exception:
                        # continue with other shards
                        continue
        except Exception:
            pass

        # Dedup + batch upload
        dedup = Deduplicator(api=api, repo_id=repo_id)
        session = SessionManager()
        uploader = BatchUploader(api=api, repo_id=repo_id, deduplicator=dedup, session=session, max_workers=workers)

        # Build file_infos from scanned summary
        file_infos = []
        for species, items in summary.get("by_species", {}).items():
            for it in items:
                file_infos.append({"full_path": it["full_path"], "relative_path": it["relative_path"], "size": it.get("size", 0)})

        def on_progress(state: dict):
            # for now, we don't stream progress; could integrate via websocket
            pass

        result = uploader.upload_files(file_infos, remote_base=remote_base or "audio", on_progress=on_progress)
        return f"Upload finished: {result}", result
    finally:
        # cleanup tempdir
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass


def create_uploader_app():
    with gr.Blocks(title="BirdNET Uploader") as app:
        gr.Markdown("""
        # 🐦 BirdNET Uploader
        Upload audio segments (multiple files) and optional CSV of detections to a Hugging Face dataset.

        If you need to upload many files, download the Windows container and run the standalone uploader locally for best performance.
        """)

        with gr.Group("Authentication"):
            token = gr.Textbox(label="Hugging Face Token", type="password", placeholder="hf_xxx...", interactive=True)

        with gr.Group("Dataset"):
            repo_id = gr.Textbox(label="Dataset repo id (owner/name)", placeholder="username/dataset-name")
            remote_base = gr.Textbox(label="Remote base path (default: audio)", value="audio")

        with gr.Group("Files"):
            files = gr.File(label="Audio files (multiple)", file_count="multiple")
            csv_file = gr.File(label="Optional detections CSV", file_count="single", file_types=[".csv"])

        with gr.Row():
            workers = gr.Number(label="Parallel workers (for large uploads)", value=4)
            upload_btn = gr.Button("Start Upload")

        with gr.Group("Progress"):
            status = gr.Textbox(label="Status", interactive=False)

        with gr.Group("Download"):
            gr.Markdown("[Download Windows standalone uploader (zip)](https://github.com/jrrribeiro/BirdNET-Uploader-App/releases/latest/download/birdnet-uploader-windows.zip)")

        def _start(token_val, repo_val, files_val, csv_val, remote_base_val, workers_val):
            status_text, result = _handle_upload(token_val, repo_val, files_val, csv_val, remote_base_val, int(workers_val) if workers_val else None)
            return status_text

        upload_btn.click(_start, inputs=[token, repo_id, files, csv_file, remote_base, workers], outputs=[status])

    return app
