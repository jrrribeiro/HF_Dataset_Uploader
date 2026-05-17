from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List

import gradio as gr

os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "5")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

from .auth_service import AuthService
from .hf_tuning import configure_hf_http_backoff

# Apply HF http_backoff tuning before importing modules that may import huggingface_hub
configure_hf_http_backoff()

from .repo_service import RepositoryService
from .scanner import LocalScanner
from .deduplicator import Deduplicator
from .batch_uploader import BatchUploader
from .manifest import build_manifest_from_scan, manifest_to_bytes, write_shards_from_csv_rows
from .session_manager import SessionManager
from .config import WEB_UI_MAX_SIZE_BYTES


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


def _extract_archive(archive_path: Path, extract_to: Path) -> bool:
    """Extract tar, tar.gz, or zip archives. Returns True if extraction succeeded."""
    try:
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_to)
            return True
        elif archive_path.suffix.lower() == ".gz":
            # Handle .tar.gz
            if archive_path.stem.endswith(".tar"):
                with tarfile.open(archive_path, "r:gz") as tf:
                    tf.extractall(extract_to)
                return True
            else:
                return False
        elif archive_path.suffix.lower() == ".tar":
            with tarfile.open(archive_path, "r") as tf:
                tf.extractall(extract_to)
            return True
        else:
            return False
    except Exception as exc:
        print(f"Archive extraction error: {exc}")
        return False


def _handle_upload(token: str, repo_id: str, files, csv_file, remote_base: str, workers: int | None, progress=gr.Progress()):
    # Basic validation
    if not token or not repo_id:
        return "Error: token and repo_id are required." , None

    # Store uploaded files to a temp directory
    tmpdir = Path(tempfile.mkdtemp(prefix="hf-dataset-uploader-upload-"))
    try:
        progress(0, desc="Initializing upload...")
        _store_uploaded_files(files or [], tmpdir)

        # Handle archive extraction: look for .tar, .tar.gz, .zip files
        audio_dir = tmpdir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        for uploaded_file in tmpdir.iterdir():
            if uploaded_file.is_file():
                suffix = uploaded_file.suffix.lower()
                # Check for .tar.gz before .gz
                if uploaded_file.name.endswith(".tar.gz"):
                    progress(0.1, desc=f"Extracting {uploaded_file.name}...")
                    if _extract_archive(uploaded_file, audio_dir):
                        uploaded_file.unlink()  # Delete archive after extraction
                    else:
                        return f"Failed to extract {uploaded_file.name}", None
                elif suffix in {".tar", ".gz", ".zip"}:
                    progress(0.1, desc=f"Extracting {uploaded_file.name}...")
                    if _extract_archive(uploaded_file, audio_dir):
                        uploaded_file.unlink()  # Delete archive after extraction
                    else:
                        return f"Failed to extract {uploaded_file.name}", None
                elif suffix == ".csv":
                    # Keep CSV files as-is; handle them separately
                    pass
                else:
                    # Assume non-archive, non-CSV files are audio files
                    shutil.move(str(uploaded_file), str(audio_dir / uploaded_file.name))

        # Validate total size for web UI (1GB limit)
        total_size = sum(f.stat().st_size for f in audio_dir.rglob("*") if f.is_file())
        if total_size > WEB_UI_MAX_SIZE_BYTES:
            size_gb = total_size / (1024**3)
            return (
                f"Upload exceeds 1 GB limit ({size_gb:.2f} GB). "
                "Please download the Windows standalone uploader for large archives: "
                "https://github.com/jrrribeiro/HF_Dataset_Uploader/releases/latest",
                None
            )

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
        progress(0.2, desc="Validating/creating repository...")
        
        try:
            validation = repo_service.validate_repo(repo_id)
            if not validation.get("is_valid"):
                # Attempt to create required structure
                progress(0.25, desc="Creating repository structure...")
                try:
                    repo_service.create_dataset(repo_id, private=True)
                    progress(0.27, desc="Repository created successfully!")
                except Exception as e:
                    error_msg = str(e)
                    return (
                        f"❌ Could not create/initialize dataset '{repo_id}'.\n"
                        f"Error: {error_msg[:150]}\n\n"
                        f"Possible causes:\n"
                        f"• Invalid repo_id format (should be 'username/dataset-name')\n"
                        f"• No write permission to the dataset\n"
                        f"• HuggingFace API error", 
                        None
                    )
        except Exception as e:
            error_msg = str(e)
            # Dataset doesn't exist - try to create it
            if "404" in error_msg or "Repository Not Found" in error_msg:
                progress(0.22, desc="Dataset not found. Creating...")
                try:
                    repo_service.create_dataset(repo_id, private=True)
                    progress(0.27, desc="Dataset created successfully!")
                except Exception as create_error:
                    create_msg = str(create_error)
                    return (
                        f"❌ Dataset '{repo_id}' not found and could not be created.\n"
                        f"Error: {create_msg[:150]}\n\n"
                        f"Please:\n"
                        f"1. Verify the repo_id format: 'your-username/dataset-name'\n"
                        f"2. Check your HuggingFace token has dataset creation permissions\n"
                        f"3. Try again",
                        None
                    )
            else:
                return f"❌ Repository validation failed: {error_msg[:150]}", None

        # Build scan summary from extracted/uploaded files
        progress(0.3, desc="Scanning files...")
        scanner = LocalScanner()
        # Scan the audio_dir where all files are now consolidated
        summary = scanner.scan_folder(str(audio_dir))
        
        total_files = summary.get("total_files", 0)
        progress(0.4, desc=f"Found {total_files} audio files. Processing metadata...")

        # Upload CSV if present
        try:
            if csv_path:
                progress(0.45, desc="Uploading detections CSV...")
                api.upload_file(path_or_fileobj=str(csv_path), path_in_repo="index/detections.csv", repo_id=repo_id, repo_type="dataset")
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

            progress(0.5, desc="Building manifest...")
            manifest = build_manifest_from_scan(repo_id, summary, csv_rows=csv_rows)
            progress(0.55, desc="Uploading manifest...")
            api.upload_file(path_or_fileobj=manifest_to_bytes(manifest), path_in_repo="index/manifest.json", repo_id=repo_id, repo_type="dataset")
        except Exception as exc:
            return f"Manifest upload failed: {exc}", None

        # Generate and upload shards if CSV provided
        try:
            if csv_path and csv_rows:
                progress(0.6, desc="Generating shards...")
                shards = write_shards_from_csv_rows(csv_rows)
                for i, shard_path in enumerate(shards):
                    try:
                        progress(0.6 + (0.1 * i / len(shards)), desc=f"Uploading shard {i+1}/{len(shards)}...")
                        api.upload_file(path_or_fileobj=str(shard_path), path_in_repo=f"index/shards/{shard_path.name}", repo_id=repo_id, repo_type="dataset")
                    except Exception:
                        # continue with other shards
                        continue
        except Exception:
            pass

        # Dedup + batch upload
        progress(0.7, desc="Preparing uploads...")
        dedup = Deduplicator(api=api, repo_id=repo_id)
        session = SessionManager()
        uploader = BatchUploader(api=api, repo_id=repo_id, deduplicator=dedup, session=session, max_workers=workers)

        # Build file_infos from scanned summary
        file_infos = []
        for species, items in summary.get("by_species", {}).items():
            for it in items:
                file_infos.append({"full_path": it["full_path"], "relative_path": it["relative_path"], "size": it.get("size", 0)})

        uploaded_count = [0]  # Use list to allow mutation in nested function
        
        def on_progress_update(state: dict):
            uploaded = state.get("uploaded", 0)
            skipped = state.get("skipped", 0)
            failed = state.get("failed", 0)
            total = len(file_infos)
            progress(0.7 + (0.25 * uploaded / max(total, 1)), desc=f"Uploading: {uploaded}/{total} files")

        progress(0.7, desc="Starting file uploads...")
        result = uploader.upload_files(file_infos, remote_base=remote_base or "audio", on_progress=on_progress_update)
        progress(0.95, desc="Finalizing...")
        
        uploaded = result.get("uploaded", 0)
        skipped = result.get("skipped", 0)
        failed = result.get("failed", 0)
        status_msg = f"Upload finished! Uploaded: {uploaded}, Skipped: {skipped}, Failed: {failed}"
        progress(1.0, desc="Complete")
        return status_msg, result
    finally:
        # cleanup tempdir
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass


def create_uploader_app():
    with gr.Blocks(title="HF Dataset Uploader") as app:
        gr.Markdown("""
        # HF Dataset Uploader
        Upload audio segments (multiple files) and optional CSV of detections to a Hugging Face dataset.

        If you need to upload many files, download the Windows portable build and run the standalone uploader locally for best performance.
        """)

        with gr.Group("Authentication"):
            token = gr.Textbox(label="Hugging Face Token", type="password", placeholder="hf_xxx...", interactive=True)

        with gr.Group("Dataset"):
            repo_id = gr.Textbox(label="Dataset repo id (owner/name)", placeholder="username/dataset-name")
            remote_base = gr.Textbox(label="Remote base path (default: audio)", value="audio")

        with gr.Group("Files"):
            files = gr.File(
                label="Audio files or archive (.tar/.tar.gz/.zip) with optional CSV",
                file_count="multiple",
                file_types=[".wav", ".mp3", ".flac", ".ogg", ".m4a", ".tar", ".tar.gz", ".zip"]
            )
            csv_file = gr.File(label="Optional detections CSV (or include in archive)", file_count="single", file_types=[".csv"])

        with gr.Row():
            workers = gr.Number(label="Parallel workers (for large uploads)", value=4)
            upload_btn = gr.Button("Start Upload")

        with gr.Group("Progress"):
            status = gr.Textbox(label="Status", interactive=False)

        with gr.Group("Download"):
            gr.Markdown("""
## [DOWNLOAD] Windows Portable Download

Para uploads maiores (>1 GB) ou melhor performance, baixe o executavel portatil:

**[Download hf-dataset-uploader-windows.zip](https://github.com/jrrribeiro/HF_Dataset_Uploader/releases/latest)**

- **Tamanho**: ~109 MB (sem Python necessario)
- **Performance**: Upload ilimitado via CLI
- **Seguranca**: Checksum disponivel na pagina do release acima
- **Instrucoes**: [README principal](https://github.com/jrrribeiro/HF_Dataset_Uploader/blob/main/README.md)
- **Troubleshooting**: [README principal](https://github.com/jrrribeiro/HF_Dataset_Uploader/blob/main/README.md)

### [INFO] Checksum SHA256
```
71d126edf726298ed25d4b72b5364e85fa6b1e76157c4f1ee0ab76b4a653f359
```

### ⚡ Novidades na v1.0.4
- [OK] **CRITICO**: Gradio agora incluido no exe (antes faltava!)
- [OK] **Melhorado**: Timeout aumentado para uploads longos
- [OK] **Corrigido**: Parametro API de batch_uploader (path_or_file -> path_or_fileobj)
- [OK] Melhorado: Tratamento de erros durante uploads
- [OK] Adicionado: test_imports.py para diagnostico
""")

        def _start(token_val, repo_val, files_val, csv_val, remote_base_val, workers_val, progress=gr.Progress()):
            status_text, result = _handle_upload(token_val, repo_val, files_val, csv_val, remote_base_val, int(workers_val) if workers_val else None, progress=progress)
            return status_text

        upload_btn.click(_start, inputs=[token, repo_id, files, csv_file, remote_base, workers], outputs=[status])

    return app
