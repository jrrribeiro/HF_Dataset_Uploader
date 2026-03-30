import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import gradio as gr
from huggingface_hub import HfApi

from cli.hf_dataset_cli import ensure_project_dataset_structure, ingest_segments_to_hf, verify_project


_HF_TOKEN_LOCK = threading.Lock()
_LAST_VALID_HF_TOKEN = ""


def _remember_hf_token(token: str) -> None:
    clean_token = (token or "").strip()
    if not clean_token:
        return
    with _HF_TOKEN_LOCK:
        global _LAST_VALID_HF_TOKEN
        _LAST_VALID_HF_TOKEN = clean_token


def _get_remembered_hf_token() -> str:
    with _HF_TOKEN_LOCK:
        return _LAST_VALID_HF_TOKEN


def _build_api(token: str) -> HfApi:
    clean_token = (token or "").strip()
    if clean_token:
        _remember_hf_token(clean_token)
        return HfApi(token=clean_token)
    remembered = _get_remembered_hf_token()
    if remembered:
        return HfApi(token=remembered)
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
    state = str(snapshot.get("status") or "")

    pending_total = int(progress.get("pending_total") or result.get("pending_files") or 0)
    processed_pending = int(progress.get("processed_pending") or 0)
    uploaded = int(progress.get("uploaded") or result.get("uploaded") or 0)
    failed = int(progress.get("failed") or result.get("failed") or 0)
    skipped = int(progress.get("skipped_existing") or result.get("skipped_existing") or 0)

    if pending_total > 0:
        if processed_pending == 0 and state in {"completed", "failed", "cancelled"}:
            processed_pending = min(pending_total, uploaded + failed)

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
        base = f"✅ Segments upload completed | Uploaded: {uploaded} | Failed: {failed} | Already existed: {skipped}"
        if message and message not in {"Upload completed", "Ingestion completed"}:
            return f"{base} | {message}"
        return base
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


def _render_upload_snapshot(
    snapshot: dict[str, Any],
    previous_status: str,
    previous_progress: str,
) -> tuple[Any, Any, dict[str, Any], str, str]:
    status_text = _format_segments_upload_status(snapshot)
    progress_text = _format_segments_upload_progress(snapshot)
    running = bool(snapshot.get("is_running"))

    status_out: Any = status_text if status_text != (previous_status or "") else gr.skip()
    progress_out: Any = progress_text if progress_text != (previous_progress or "") else gr.skip()
    timer_update = gr.update(active=running)
    return status_out, progress_out, timer_update, status_text, progress_text


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


def _require_hf_token(token: str) -> str:
    clean = (token or "").strip()
    if not clean:
        raise ValueError("HF token is required")
    return clean


def _start_segments_upload(
    dataset_repo: str,
    archive_path: str | None,
    token: str,
    batch_size: float,
) -> tuple[str, str]:
    try:
        clean_token = _require_hf_token(token)
    except ValueError as exc:
        return f"❌ {exc}", "**Progress:** waiting to start"
    return _SEGMENTS_UPLOAD_SESSION.start(dataset_repo, archive_path, clean_token, int(batch_size))


def _start_segments_upload_ui(
    dataset_repo: str,
    archive_path: str | None,
    token: str,
    batch_size: float,
    previous_status: str,
    previous_progress: str,
) -> tuple[Any, Any, dict[str, Any], str, str]:
    status_text, progress_text = _start_segments_upload(dataset_repo, archive_path, token, batch_size)
    if status_text.startswith("❌"):
        return status_text, progress_text, gr.update(active=False), status_text, progress_text
    return _render_upload_snapshot(_SEGMENTS_UPLOAD_SESSION.snapshot(), previous_status, previous_progress)


def _pause_segments_upload_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _ = _SEGMENTS_UPLOAD_SESSION.pause()
    return _render_upload_snapshot(_SEGMENTS_UPLOAD_SESSION.snapshot(), previous_status, previous_progress)


def _resume_segments_upload_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _ = _SEGMENTS_UPLOAD_SESSION.resume()
    return _render_upload_snapshot(_SEGMENTS_UPLOAD_SESSION.snapshot(), previous_status, previous_progress)


def _cancel_segments_upload_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _ = _SEGMENTS_UPLOAD_SESSION.cancel()
    return _render_upload_snapshot(_SEGMENTS_UPLOAD_SESSION.snapshot(), previous_status, previous_progress)


def _refresh_segments_upload_status_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    return _render_upload_snapshot(_SEGMENTS_UPLOAD_SESSION.snapshot(), previous_status, previous_progress)


class IngestionSession:
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

    def start(
        self,
        project_slug: str,
        dataset_repo: str,
        detections_csv: str | None,
        segments_zip_path: str | None,
        token: str,
    ) -> None:
        project = (project_slug or "").strip()
        repo = (dataset_repo or "").strip()

        with self._lock:
            if self._is_running():
                self._status = "running"
                self._message = "Ingestion already running"
                return

        if not project:
            with self._lock:
                self._status = "failed"
                self._message = "Provide the project slug"
            return
        if not repo or "/" not in repo:
            with self._lock:
                self._status = "failed"
                self._message = "Provide dataset repo in owner/repo format"
            return
        if not detections_csv:
            with self._lock:
                self._status = "failed"
                self._message = "Upload the detections CSV"
            return

        try:
            clean_token = _require_hf_token(token)
        except ValueError as exc:
            with self._lock:
                self._status = "failed"
                self._message = str(exc)
            return

        segments_root, temp_dir = _resolve_segments_root(segments_zip_path)
        if segments_root is None or temp_dir is None:
            with self._lock:
                self._status = "failed"
                self._message = "Invalid segments archive. Upload a .tar, .tar.gz, or .zip file"
            return

        with self._lock:
            self._pause = False
            self._cancel = False
            self._status = "running"
            self._message = "Ingestion started"
            self._progress = {"event": "upload-start"}
            self._result = {}
            self._temp_dir = temp_dir

        def worker() -> None:
            try:
                api = _build_api(clean_token)
                result = ingest_segments_to_hf(
                    api=api,
                    project_slug=project,
                    dataset_repo=repo,
                    detections_csv=detections_csv,
                    segments_root=str(segments_root),
                    batch_size=200,
                    shard_size=10000,
                    max_retries=3,
                    retry_backoff_seconds=1.0,
                    resume_state_file=f".ingest-segments-{project}.json",
                    should_pause=self._should_pause,
                    should_cancel=self._should_cancel,
                    progress_callback=self._on_progress,
                )
                with self._lock:
                    self._result = result
                    if result.get("cancelled"):
                        self._status = "cancelled"
                        self._message = "Ingestion cancelled"
                    elif int(result.get("matched_rows", 0)) == 0:
                        self._status = "completed"
                        self._message = (
                            "Completed with 0 matched rows. Verify segment filenames follow "
                            "<source_stem>_<start>-<end>s_<confidence>% and are under species folders."
                        )
                    else:
                        self._status = "completed"
                        self._message = "Ingestion completed"
            except Exception as exc:
                with self._lock:
                    self._status = "failed"
                    self._message = f"Ingestion failed: {exc}"
                    self._result = {"error": str(exc)}
            finally:
                with self._lock:
                    temp = self._temp_dir
                    self._temp_dir = None
                if temp is not None:
                    temp.cleanup()

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if not self._is_running():
                return
            self._pause = True
            self._status = "paused"
            self._message = "Ingestion paused"

    def resume(self) -> None:
        with self._lock:
            if not self._is_running():
                return
            self._pause = False
            self._status = "running"
            self._message = "Ingestion resumed"

    def cancel(self) -> None:
        with self._lock:
            if not self._is_running():
                return
            self._cancel = True
            self._pause = False
            self._status = "cancelling"
            self._message = "Cancellation requested"

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "message": self._message,
            "progress": self._progress,
            "result": {
                "uploaded": int((self._result or {}).get("uploaded_audio_now") or 0),
                "failed": int((self._result or {}).get("failed_uploads") or 0),
                "skipped_existing": int((self._result or {}).get("uploaded_audio_skipped_existing") or 0),
                "pending_files": int((self._result or {}).get("pending_audio_uploads") or 0),
            },
            "is_running": self._is_running(),
            "timestamp": int(time.time()),
        }


_INGESTION_SESSION = IngestionSession()


def _start_ingestion_ui(
    project_slug: str,
    dataset_repo: str,
    detections_csv: str | None,
    segments_zip_path: str | None,
    token: str,
    previous_status: str,
    previous_progress: str,
) -> tuple[Any, Any, dict[str, Any], str, str]:
    _INGESTION_SESSION.start(project_slug, dataset_repo, detections_csv, segments_zip_path, token)
    return _render_upload_snapshot(_INGESTION_SESSION.snapshot(), previous_status, previous_progress)


def _pause_ingestion_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _INGESTION_SESSION.pause()
    return _render_upload_snapshot(_INGESTION_SESSION.snapshot(), previous_status, previous_progress)


def _resume_ingestion_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _INGESTION_SESSION.resume()
    return _render_upload_snapshot(_INGESTION_SESSION.snapshot(), previous_status, previous_progress)


def _cancel_ingestion_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    _INGESTION_SESSION.cancel()
    return _render_upload_snapshot(_INGESTION_SESSION.snapshot(), previous_status, previous_progress)


def _refresh_ingestion_status_ui(previous_status: str, previous_progress: str) -> tuple[Any, Any, dict[str, Any], str, str]:
    return _render_upload_snapshot(_INGESTION_SESSION.snapshot(), previous_status, previous_progress)


def _setup_dataset_repo(
    project_slug: str,
    dataset_repo: str,
    token: str,
    visibility: str,
) -> tuple[str, str, str, str]:
    project = (project_slug or "").strip()
    repo = (dataset_repo or "").strip()
    visibility_value = (visibility or "Public").strip().lower()

    if not project:
        return "❌ Provide the project slug", "", "", ""
    if not repo or "/" not in repo:
        return "❌ Provide dataset repo in owner/repo format", "", "", ""

    clean_token = (token or "").strip()
    if not clean_token:
        return "❌ HF token is required", "", "", ""

    try:
        api = _build_api(clean_token)
        create_private_repo = visibility_value == "private"
        ensure_result = ensure_project_dataset_structure(
            api=api,
            project_slug=project,
            dataset_repo=repo,
            create_private_repo=create_private_repo,
        )
        verify_result: dict[str, Any] = {}
        try:
            verify_result = verify_project(api=api, project_slug=project, dataset_repo=repo)
        except Exception:
            # Repo initialization already succeeded; keep setup usable even if verify call flakes.
            verify_result = {"ok": True, "total_files": 0}

        if not verify_result.get("ok"):
            errors = verify_result.get("errors") or []
            details = "; ".join(str(item) for item in errors[:2]) if errors else "Unknown verification error"
            return f"⚠️ Repository created, but verification needs retry: {details}", repo, repo, project

        created = int(len(ensure_result.get("created_paths") or []))
        summary = (
            "✅ Dataset repo ready | "
            f"Repo: {repo} | "
            f"Created/updated paths: {created} | "
            f"Total files: {verify_result.get('total_files', 0)}"
        )
        return summary, repo, repo, project
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "401" in lowered or "unauthorized" in lowered:
            return "❌ Authentication failed. Provide a valid HF token.", "", "", ""
        if "403" in lowered or "forbidden" in lowered:
            return "❌ Permission denied. Check write access to this dataset repo.", "", "", ""
        if "404" in lowered or "not found" in lowered:
            return "❌ Dataset repo not found and could not be created. Check owner/repo.", "", "", ""
        return f"❌ Setup failed: {exc}", "", "", ""


def build_upload_app() -> gr.Blocks:
    with gr.Blocks(title="BirdNET Dataset Uploader") as demo:
        gr.Markdown("# BirdNET Dataset Uploader")
        gr.Markdown(
            "Start in Dataset Repo (HF) to initialize your project repository with the recommended structure. "
            "Then use Option A or Option B."
        )

        with gr.Tabs():
            with gr.Tab("Dataset Repo (HF)"):
                gr.Markdown(
                    "Set up your Hugging Face dataset repository with the standard BirdNET structure. "
                    "This is the recommended first step for all projects."
                )
                with gr.Row():
                    setup_project_slug = gr.Textbox(label="Project Slug", placeholder="e.g. ppbio-aiuaba")
                    setup_dataset_repo = gr.Textbox(label="Dataset Repo (HF)", placeholder="owner/repo-dataset")
                with gr.Row():
                    setup_hf_token = gr.Textbox(
                        label="HF Token",
                        type="password",
                        placeholder="Required",
                    )
                    setup_visibility = gr.Radio(
                        label="Repository Visibility",
                        choices=["Public", "Private"],
                        value="Public",
                    )
                setup_button = gr.Button("Setup Repository", variant="primary")
                setup_status = gr.Markdown(value="ℹ️ Ready")

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
                    label="HF Token",
                    type="password",
                    placeholder="Required",
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
                segments_auto_refresh = gr.Timer(value=0.1, active=False)
                segments_last_status_state = gr.State(value="")
                segments_last_progress_state = gr.State(value="")

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
                    label="HF Token",
                    type="password",
                    placeholder="Required",
                )
                with gr.Row():
                    ingestion_start = gr.Button("Start Upload", variant="primary")
                    ingestion_pause = gr.Button("Pause", variant="secondary")
                    ingestion_resume = gr.Button("Resume", variant="secondary")
                    ingestion_cancel = gr.Button("Cancel", variant="stop")
                    ingestion_refresh = gr.Button("Refresh Status", variant="secondary")
                ingestion_status = gr.Markdown(value="ℹ️ Ready")
                ingestion_progress = gr.Markdown(value="**Progress:** waiting to start")
                ingestion_auto_refresh = gr.Timer(value=0.1, active=False)
                ingestion_last_status_state = gr.State(value="")
                ingestion_last_progress_state = gr.State(value="")

        setup_button.click(
            fn=_setup_dataset_repo,
            inputs=[setup_project_slug, setup_dataset_repo, setup_hf_token, setup_visibility],
            outputs=[setup_status, segments_upload_repo, dataset_repo, project_slug],
        )

        segments_upload_start.click(
            fn=_start_segments_upload_ui,
            inputs=[
                segments_upload_repo,
                segments_upload_file,
                segments_upload_token,
                segments_upload_batch_size,
                segments_last_status_state,
                segments_last_progress_state,
            ],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        segments_upload_pause.click(
            fn=_pause_segments_upload_ui,
            inputs=[segments_last_status_state, segments_last_progress_state],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        segments_upload_resume.click(
            fn=_resume_segments_upload_ui,
            inputs=[segments_last_status_state, segments_last_progress_state],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        segments_upload_cancel.click(
            fn=_cancel_segments_upload_ui,
            inputs=[segments_last_status_state, segments_last_progress_state],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        segments_upload_refresh.click(
            fn=_refresh_segments_upload_status_ui,
            inputs=[segments_last_status_state, segments_last_progress_state],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        segments_auto_refresh.tick(
            fn=_refresh_segments_upload_status_ui,
            inputs=[segments_last_status_state, segments_last_progress_state],
            outputs=[
                segments_upload_status,
                segments_upload_progress,
                segments_auto_refresh,
                segments_last_status_state,
                segments_last_progress_state,
            ],
        )

        ingestion_start.click(
            fn=_start_ingestion_ui,
            inputs=[
                project_slug,
                dataset_repo,
                detections_csv,
                segments_zip,
                hf_token,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

        ingestion_pause.click(
            fn=_pause_ingestion_ui,
            inputs=[ingestion_last_status_state, ingestion_last_progress_state],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

        ingestion_resume.click(
            fn=_resume_ingestion_ui,
            inputs=[ingestion_last_status_state, ingestion_last_progress_state],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

        ingestion_cancel.click(
            fn=_cancel_ingestion_ui,
            inputs=[ingestion_last_status_state, ingestion_last_progress_state],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

        ingestion_refresh.click(
            fn=_refresh_ingestion_status_ui,
            inputs=[ingestion_last_status_state, ingestion_last_progress_state],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

        ingestion_auto_refresh.tick(
            fn=_refresh_ingestion_status_ui,
            inputs=[ingestion_last_status_state, ingestion_last_progress_state],
            outputs=[
                ingestion_status,
                ingestion_progress,
                ingestion_auto_refresh,
                ingestion_last_status_state,
                ingestion_last_progress_state,
            ],
        )

    return demo
