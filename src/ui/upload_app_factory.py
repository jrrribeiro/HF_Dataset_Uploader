import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import gradio as gr
from huggingface_hub import HfApi

from cli.hf_dataset_cli import ingest_segments_to_hf


def _build_api(token: str) -> HfApi:
    clean_token = (token or "").strip()
    if clean_token:
        return HfApi(token=clean_token)
    return HfApi()


def _extract_compressed_segments(
    archive_path: str,
) -> tuple[Path | None, tempfile.TemporaryDirectory[str] | None]:
    """Extract tar.gz, tar, or zip maintaining directory structure."""
    if not archive_path or not Path(archive_path).exists():
        return None, None

    temp_dir = tempfile.TemporaryDirectory()
    try:
        if archive_path.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path, "r:gz") as archive:
                archive.extractall(temp_dir.name)
        elif archive_path.endswith(".tar"):
            with tarfile.open(archive_path, "r") as archive:
                archive.extractall(temp_dir.name)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(temp_dir.name)
        else:
            temp_dir.cleanup()
            return None, None
        return Path(temp_dir.name), temp_dir
    except Exception:
        temp_dir.cleanup()
        return None, None


def _resolve_segments_root(
    segments_zip_path: str | None,
) -> tuple[Path | None, tempfile.TemporaryDirectory[str] | None]:
    if segments_zip_path and Path(segments_zip_path).exists():
        return _extract_compressed_segments(segments_zip_path)
    return None, None


def _format_segments_upload_progress(snapshot: dict[str, Any]) -> str:
    progress = snapshot.get("progress", {}) if isinstance(snapshot, dict) else {}
    result = snapshot.get("result", {}) if isinstance(snapshot, dict) else {}

    pending_total = int(progress.get("pending_total") or result.get("pending_files") or 0)
    processed_pending = int(progress.get("processed_pending") or 0)
    uploaded = int(progress.get("uploaded") or result.get("uploaded") or 0)
    failed = int(progress.get("failed") or result.get("failed") or 0)
    skipped = int(progress.get("skipped_existing") or result.get("skipped_existing") or 0)

    if pending_total > 0:
        percent = min(100.0, (processed_pending / pending_total) * 100.0)
        filled = int(percent // 5)
        bar = "█" * filled + "░" * (20 - filled)
        return (
            f"**[{bar}] {percent:.1f}%**\n"
            f"Processed: {processed_pending}/{pending_total}  |  "
            f"Uploaded: {uploaded}  |  Failed: {failed}  |  Already existed: {skipped}"
        )

    total_files = int(progress.get("total_files") or result.get("total_files") or 0)
    if total_files > 0:
        return f"**[░░░░░░░░░░░░░░░░░░░░] 0.0%**\nPreparing upload ({total_files} files detected)"

    return "**Progress:** waiting to start"


def _format_segments_upload_status(snapshot: dict[str, Any]) -> str:
    state = snapshot.get("status", "idle")
    message = snapshot.get("message", "Ready")
    result = snapshot.get("result", {}) if isinstance(snapshot.get("result"), dict) else {}
    if state == "completed":
        uploaded = int(result.get("uploaded") or 0)
        failed = int(result.get("failed") or 0)
        skipped = int(result.get("skipped_existing") or 0)
        return f"✅ Segments upload completed | Uploaded: {uploaded} | Failed: {failed} | Already existed: {skipped}"
    if state == "failed":
        return f"❌ Segments upload failed | {message}"
    if state == "cancelled":
        return "🛑 Segments upload cancelled"
    if state == "cancelling":
        return "🛑 Cancelling segments upload..."
    if state == "paused":
        return "⏸️ Segments upload paused"
    if state == "running":
        return "⏳ Segments upload in progress"
    return "ℹ️ Ready"


class SegmentsUploadSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pause = False
        self._cancel = False
        self._status = "idle"
        self._message = "Ready"
        self._progress: dict[str, Any] = {}
        self._result: dict[str, Any] = {}
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_progress(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._progress = payload

    def _should_pause(self) -> bool:
        with self._lock:
            return self._pause

    def _should_cancel(self) -> bool:
        with self._lock:
            return self._cancel

    def start(self, dataset_repo: str, archive_path: str | None, token: str, batch_size: int) -> tuple[str, str]:
        repo = (dataset_repo or "").strip()
        if not repo or "/" not in repo:
            return "❌ Provide dataset repo in owner/repo format", "**Progress:** waiting to start"
        if not archive_path:
            return "❌ Upload a segments archive (.tar, .tar.gz, or .zip)", "**Progress:** waiting to start"

        with self._lock:
            if self._is_running():
                snap = self.snapshot()
                return "⏳ There is already an upload running", _format_segments_upload_progress(snap)

            segments_root, temp_dir = _extract_compressed_segments(archive_path)
            if segments_root is None or temp_dir is None:
                return "❌ Invalid archive file", "**Progress:** waiting to start"

            self._pause = False
            self._cancel = False
            self._status = "running"
            self._message = "Upload started"
            self._progress = {"event": "upload-start"}
            self._result = {}
            self._temp_dir = temp_dir

            def worker() -> None:
                try:
                    from cli.hf_dataset_cli import upload_segments_to_hf

                    project_slug = repo.split("/")[1].replace("-dataset", "")
                    api = _build_api(token)
                    result = upload_segments_to_hf(
                        api=api,
                        project_slug=project_slug,
                        dataset_repo=repo,
                        segments_root=str(segments_root),
                        batch_size=int(batch_size),
                        should_pause=self._should_pause,
                        should_cancel=self._should_cancel,
                        progress_callback=self._on_progress,
                    )
                    with self._lock:
                        if result.get("cancelled"):
                            self._status = "cancelled"
                            self._message = "Upload cancelled"
                        else:
                            self._status = "completed"
                            self._message = "Upload completed"
                        self._result = result
                except Exception as exc:
                    with self._lock:
                        self._status = "failed"
                        self._message = f"Upload failed: {exc}"
                        self._result = {"error": str(exc)}
                finally:
                    with self._lock:
                        temp = self._temp_dir
                        self._temp_dir = None
                    if temp is not None:
                        temp.cleanup()

            self._thread = threading.Thread(target=worker, daemon=True)
            self._thread.start()

        snap = self.snapshot()
        return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)

    def pause(self) -> tuple[str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)
            self._pause = True
            self._status = "paused"
            self._message = "Upload paused"
        snap = self.snapshot()
        return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)

    def resume(self) -> tuple[str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)
            self._pause = False
            self._status = "running"
            self._message = "Upload resumed"
        snap = self.snapshot()
        return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)

    def cancel(self) -> tuple[str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)
            self._cancel = True
            self._pause = False
            self._status = "cancelling"
            self._message = "Cancellation requested"
        snap = self.snapshot()
        return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "message": self._message,
            "progress": self._progress,
            "result": self._result,
            "is_running": self._is_running(),
            "timestamp": int(time.time()),
        }

    def status(self) -> tuple[str, str]:
        snap = self.snapshot()
        return _format_segments_upload_status(snap), _format_segments_upload_progress(snap)


_SEGMENTS_UPLOAD_SESSION = SegmentsUploadSession()


def _start_segments_upload(
    dataset_repo: str,
    archive_path: str | None,
    token: str,
    batch_size: float,
) -> tuple[str, str]:
    return _SEGMENTS_UPLOAD_SESSION.start(dataset_repo, archive_path, token, int(batch_size))


def _pause_segments_upload() -> tuple[str, str]:
    return _SEGMENTS_UPLOAD_SESSION.pause()


def _resume_segments_upload() -> tuple[str, str]:
    return _SEGMENTS_UPLOAD_SESSION.resume()


def _cancel_segments_upload() -> tuple[str, str]:
    return _SEGMENTS_UPLOAD_SESSION.cancel()


def _refresh_segments_upload_status() -> tuple[str, str]:
    return _SEGMENTS_UPLOAD_SESSION.status()


def _run_ingestion(
    project_slug: str,
    dataset_repo: str,
    detections_csv: str | None,
    segments_zip_path: str | None,
    token: str,
) -> str:
    project = (project_slug or "").strip()
    repo = (dataset_repo or "").strip()

    if not project:
        return "❌ Provide the project slug"
    if not repo or "/" not in repo:
        return "❌ Provide dataset repo in owner/repo format"
    if not detections_csv:
        return "❌ Upload the detections CSV"

    segments_root, temp_dir = _resolve_segments_root(segments_zip_path)
    if segments_root is None:
        return "❌ Invalid segments archive. Upload a .tar, .tar.gz, or .zip file"

    try:
        api = _build_api(token)
        result = ingest_segments_to_hf(
            api=api,
            project_slug=project,
            dataset_repo=repo,
            detections_csv=detections_csv,
            segments_root=str(segments_root),
        )
        return (
            "✅ Ingestion completed | "
            f"Rows matched: {result['matched_rows']} | "
            f"Uploaded now: {result['uploaded_audio_now']} | "
            f"Skipped existing: {result['uploaded_audio_skipped_existing']} | "
            f"Failed uploads: {result['failed_uploads']}"
        )
    except Exception as exc:
        return f"❌ Ingestion failed: {exc}"
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def build_upload_app() -> gr.Blocks:
    with gr.Blocks(title="BirdNET Dataset Uploader") as demo:
        gr.Markdown("# BirdNET Dataset Uploader")
        gr.Markdown(
            "Choose one option below. Option A uploads only audio segments first. "
            "Option B ingests detections CSV + segments into your dataset in one run."
        )

        with gr.Tabs():
            with gr.Tab("Option A - Upload Segments Only"):
                gr.Markdown(
                    "Upload a compressed segments archive to your Hugging Face dataset. "
                    "Recommended as the first step for large projects."
                )
                with gr.Row():
                    segments_upload_repo = gr.Textbox(label="Dataset Repo (HF)", placeholder="owner/repo-dataset")
                    segments_upload_file = gr.File(
                        label="Segments Archive (.tar.gz, .tar, .zip)",
                        file_types=[".tar", ".tar.gz", ".tgz", ".zip"],
                        type="filepath",
                    )
                segments_upload_token = gr.Textbox(
                    label="HF Token (optional)",
                    type="password",
                    placeholder="Leave blank to use authenticated environment session",
                )
                segments_upload_batch_size = gr.Number(label="Upload Batch Size", value=50, precision=0)
                with gr.Row():
                    segments_upload_start = gr.Button("Start Upload", variant="primary")
                    segments_upload_pause = gr.Button("Pause", variant="secondary")
                    segments_upload_resume = gr.Button("Resume", variant="secondary")
                    segments_upload_cancel = gr.Button("Cancel", variant="stop")
                    segments_upload_refresh = gr.Button("Refresh Status", variant="secondary")
                segments_upload_status = gr.Markdown(value="ℹ️ Ready")
                segments_upload_progress = gr.Markdown(value="**Progress:** waiting to start")

            with gr.Tab("Option B - Ingest CSV + Segments"):
                gr.Markdown(
                    "Run full ingestion in one step: detections CSV + segments archive to build/update dataset index."
                )
                with gr.Row():
                    project_slug = gr.Textbox(label="Project Slug", placeholder="e.g. ppbio-aiuaba")
                    dataset_repo = gr.Textbox(label="Dataset Repo (HF)", placeholder="owner/repo-dataset")
                detections_csv = gr.File(label="Detections CSV", file_types=[".csv"], type="filepath")
                segments_zip = gr.File(
                    label="Segments Archive (.tar.gz, .tar, .zip)",
                    file_types=[".tar", ".tar.gz", ".tgz", ".zip"],
                    type="filepath",
                )
                hf_token = gr.Textbox(
                    label="HF Token (optional)",
                    type="password",
                    placeholder="Leave blank to use authenticated environment session",
                )
                run_ingestion_button = gr.Button("Run Ingestion", variant="primary")
                ingestion_status = gr.Markdown(value="ℹ️ Ready")

        segments_upload_start.click(
            fn=_start_segments_upload,
            inputs=[segments_upload_repo, segments_upload_file, segments_upload_token, segments_upload_batch_size],
            outputs=[segments_upload_status, segments_upload_progress],
        )

        segments_upload_pause.click(
            fn=_pause_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_progress],
        )

        segments_upload_resume.click(
            fn=_resume_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_progress],
        )

        segments_upload_cancel.click(
            fn=_cancel_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_progress],
        )

        segments_upload_refresh.click(
            fn=_refresh_segments_upload_status,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_progress],
        )

        run_ingestion_button.click(
            fn=_run_ingestion,
            inputs=[project_slug, dataset_repo, detections_csv, segments_zip, hf_token],
            outputs=[ingestion_status],
        )

    return demo
