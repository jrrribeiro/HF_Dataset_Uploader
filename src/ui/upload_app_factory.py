import json
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import gradio as gr
from huggingface_hub import HfApi

from cli.hf_dataset_cli import ingest_segments_to_hf, run_ingest_segments_dry_run


def _as_pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


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
    segments_path: str,
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
        return (
            f"**Progresso:** {percent:.1f}%  |  "
            f"Processados: {processed_pending}/{pending_total}  |  "
            f"Enviados: {uploaded}  |  Falhas: {failed}  |  Ja existentes: {skipped}"
        )

    total_files = int(progress.get("total_files") or result.get("total_files") or 0)
    if total_files > 0:
        return f"**Progresso:** preparando upload ({total_files} arquivos detectados)"

    return "**Progresso:** aguardando inicio"


class SegmentsUploadSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pause = False
        self._cancel = False
        self._status = "idle"
        self._message = "Pronto"
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

    def start(self, dataset_repo: str, archive_path: str | None, token: str, batch_size: int) -> tuple[str, str, str]:
        repo = (dataset_repo or "").strip()
        if not repo or "/" not in repo:
            return "❌ Informe dataset repo no formato owner/repo", "{}", "**Progresso:** aguardando inicio"
        if not archive_path:
            return "❌ Envie um arquivo (.tar, .tar.gz, ou .zip) de segmentos", "{}", "**Progresso:** aguardando inicio"

        with self._lock:
            if self._is_running():
                snap = self.snapshot()
                return "⏳ Ja existe upload em andamento", _as_pretty_json(snap), _format_segments_upload_progress(snap)

            segments_root, temp_dir = _extract_compressed_segments(archive_path)
            if segments_root is None or temp_dir is None:
                return "❌ Arquivo compactado invalido", "{}", "**Progresso:** aguardando inicio"

            self._pause = False
            self._cancel = False
            self._status = "running"
            self._message = "Upload iniciado"
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
                            self._message = "Upload cancelado"
                        else:
                            self._status = "completed"
                            self._message = "Upload finalizado"
                        self._result = result
                except Exception as exc:
                    with self._lock:
                        self._status = "failed"
                        self._message = f"Upload falhou: {exc}"
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
        return "🚀 Upload iniciado em background", _as_pretty_json(snap), _format_segments_upload_progress(snap)

    def pause(self) -> tuple[str, str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return "ℹ️ Nenhum upload em andamento", _as_pretty_json(snap), _format_segments_upload_progress(snap)
            self._pause = True
            self._status = "paused"
            self._message = "Upload pausado"
        snap = self.snapshot()
        return "⏸️ Upload pausado", _as_pretty_json(snap), _format_segments_upload_progress(snap)

    def resume(self) -> tuple[str, str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return "ℹ️ Nenhum upload em andamento", _as_pretty_json(snap), _format_segments_upload_progress(snap)
            self._pause = False
            self._status = "running"
            self._message = "Upload retomado"
        snap = self.snapshot()
        return "▶️ Upload retomado", _as_pretty_json(snap), _format_segments_upload_progress(snap)

    def cancel(self) -> tuple[str, str, str]:
        with self._lock:
            if not self._is_running():
                snap = self.snapshot()
                return "ℹ️ Nenhum upload em andamento", _as_pretty_json(snap), _format_segments_upload_progress(snap)
            self._cancel = True
            self._pause = False
            self._status = "cancelling"
            self._message = "Cancelamento solicitado"
        snap = self.snapshot()
        return "🛑 Cancelamento solicitado", _as_pretty_json(snap), _format_segments_upload_progress(snap)

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "message": self._message,
            "progress": self._progress,
            "result": self._result,
            "is_running": self._is_running(),
            "timestamp": int(time.time()),
        }

    def status(self) -> tuple[str, str, str]:
        snap = self.snapshot()
        state = snap.get("status", "idle")
        if state == "running":
            msg = "⏳ Upload em andamento"
        elif state == "paused":
            msg = "⏸️ Upload pausado"
        elif state == "completed":
            msg = "✅ Upload concluido"
        elif state == "failed":
            msg = "❌ Upload falhou"
        elif state == "cancelled":
            msg = "🛑 Upload cancelado"
        elif state == "cancelling":
            msg = "🛑 Cancelando upload..."
        else:
            msg = "ℹ️ Pronto"
        return msg, _as_pretty_json(snap), _format_segments_upload_progress(snap)


_SEGMENTS_UPLOAD_SESSION = SegmentsUploadSession()


def _start_segments_upload(
    dataset_repo: str,
    archive_path: str | None,
    token: str,
    batch_size: float,
) -> tuple[str, str, str]:
    return _SEGMENTS_UPLOAD_SESSION.start(dataset_repo, archive_path, token, int(batch_size))


def _pause_segments_upload() -> tuple[str, str, str]:
    return _SEGMENTS_UPLOAD_SESSION.pause()


def _resume_segments_upload() -> tuple[str, str, str]:
    return _SEGMENTS_UPLOAD_SESSION.resume()


def _cancel_segments_upload() -> tuple[str, str, str]:
    return _SEGMENTS_UPLOAD_SESSION.cancel()


def _refresh_segments_upload_status() -> tuple[str, str, str]:
    return _SEGMENTS_UPLOAD_SESSION.status()


def build_upload_app() -> gr.Blocks:
    with gr.Blocks(title="BirdNET Segments Uploader") as demo:
        gr.Markdown("# BirdNET Segments Uploader")
        gr.Markdown(
            "Use esta ferramenta para importar segmentos + CSV de deteccoes por projeto. "
            "Recomendado: executar dry-run antes do upload real."
        )

        with gr.Row():
            project_slug = gr.Textbox(label="Project Slug", placeholder="ex: ppbio-aiuaba")
            dataset_repo = gr.Textbox(label="Dataset Repo (HF)", placeholder="owner/repo")

        detections_csv = gr.File(label="CSV de deteccoes", file_types=[".csv"], type="filepath")
        segments_zip = gr.File(
            label="Arquivo compactado de segmentos (.tar, .tar.gz, ou .zip)",
            file_types=[".tar", ".tar.gz", ".tgz", ".zip"],
            type="filepath",
        )
        gr.Markdown(
            "**Opção 1 (no Space):** Use o arquivo compactado acima e proceda com dry-run + upload.  "
            "**Opção 2 (Upload prévio de segmentos):** Use a seção abaixo para enviar os segmentos para um dataset HF antes de ingerir dados."
        )

        with gr.Group():
            gr.Markdown(
                "### Upload de Segmentos (execução prévia recomendada)\n"
                "Envie arquivo compactado (.tar.gz, .tar, ou .zip) com os segmentos para um dataset HF. "
                "Use .tar.gz para melhor compressão (50GB fica com ~30GB)."
            )
            with gr.Row():
                segments_upload_repo = gr.Textbox(label="Dataset Repo (HF)", placeholder="owner/repo-dataset")
                segments_upload_file = gr.File(
                    label="Arquivo (.tar.gz, .tar ou .zip)",
                    file_types=[".tar", ".tar.gz", ".tgz", ".zip"],
                    type="filepath",
                )
            segments_upload_token = gr.Textbox(
                label="HF Token (opcional)",
                type="password",
                placeholder="Se vazio, usa sessao ja autenticada",
            )
            segments_upload_batch_size = gr.Number(label="Batch size upload segmentos", value=50, precision=0)
            with gr.Row():
                segments_upload_start = gr.Button("Iniciar Upload", variant="primary")
                segments_upload_pause = gr.Button("Pausar", variant="secondary")
                segments_upload_resume = gr.Button("Retomar", variant="secondary")
                segments_upload_cancel = gr.Button("Cancelar", variant="stop")
                segments_upload_refresh = gr.Button("Atualizar Status", variant="secondary")
            segments_upload_status = gr.Markdown(value="Pronto")
            segments_upload_progress = gr.Markdown(value="**Progresso:** aguardando inicio")
            segments_upload_result = gr.Code(label="Resultado JSON", language="json")

        with gr.Accordion("Configuracao avancada", open=False):
            hf_token = gr.Textbox(
                label="HF Token (opcional)",
                type="password",
                placeholder="Se vazio, usa sessao ja autenticada no ambiente",
            )
            with gr.Row():
                batch_size = gr.Number(label="Batch size", value=200, precision=0)
                shard_size = gr.Number(label="Shard size", value=10000, precision=0)
            with gr.Row():
                max_retries = gr.Number(label="Max retries", value=3, precision=0)
                retry_backoff_seconds = gr.Number(label="Retry backoff (s)", value=1.0)
            resume_state_file = gr.Textbox(
                label="Resume state file",
                value=".ingest-segments-state.json",
            )
            report_file = gr.Textbox(
                label="Report file local (opcional)",
                placeholder="ex: .ingest-run-report.json",
            )

        with gr.Row():
            dry_run_button = gr.Button("Dry-run", variant="secondary")
            upload_button = gr.Button("Upload real", variant="primary")

        status = gr.Markdown(value="Pronto")
        result_json = gr.Code(label="Resultado JSON", language="json")

        def run_dry_run(
            project: str,
            repo: str,
            csv_path: str | None,
            segments_path: str,
            segments_zip_path: str | None,
            report_path: str,
        ) -> tuple[str, str]:
            project = (project or "").strip()
            if not project:
                return "❌ Informe o project slug", "{}"

            if not csv_path:
                return "❌ Selecione o CSV de deteccoes", "{}"

            segments_root, temp_dir = _resolve_segments_root(segments_path, segments_zip_path)
            if segments_root is None:
                return "❌ Pasta de segmentos invalida. No Space, envie .tar.gz, .tar ou .zip.", "{}"

            try:
                result = run_ingest_segments_dry_run(
                    project_slug=project,
                    detections_csv=csv_path,
                    segments_root=str(segments_root),
                )
                if report_path.strip():
                    Path(report_path).write_text(_as_pretty_json(result), encoding="utf-8")
                summary = (
                    "✅ Dry-run finalizado | "
                    f"Matched: {result['matched_rows']} | "
                    f"Unmatched: {result['unmatched_rows']} | "
                    f"Ambiguous: {result['ambiguous_rows']}"
                )
                return summary, _as_pretty_json(result)
            except Exception as exc:
                return f"❌ Dry-run falhou: {exc}", "{}"
            finally:
                if temp_dir is not None:
                    temp_dir.cleanup()

        def run_upload(
            project: str,
            repo: str,
            csv_path: str | None,
            segments_path: str,
            segments_zip_path: str | None,
            token: str,
            batch: float,
            shard: float,
            retries: float,
            backoff: float,
            resume_file: str,
            report_path: str,
        ) -> tuple[str, str]:
            project = (project or "").strip()
            repo = (repo or "").strip()
            if not project:
                return "❌ Informe o project slug", "{}"
            if not repo or "/" not in repo:
                return "❌ Informe dataset repo no formato owner/repo", "{}"
            if not csv_path:
                return "❌ Selecione o CSV de deteccoes", "{}"

            segments_root, temp_dir = _resolve_segments_root(segments_path, segments_zip_path)
            if segments_root is None:
                return "❌ Pasta de segmentos invalida. No Space, envie .tar.gz, .tar ou .zip.", "{}"

            try:
                api = _build_api(token)
                result = ingest_segments_to_hf(
                    api=api,
                    project_slug=project,
                    dataset_repo=repo,
                    detections_csv=csv_path,
                    segments_root=str(segments_root),
                    batch_size=int(batch),
                    shard_size=int(shard),
                    max_retries=int(retries),
                    retry_backoff_seconds=float(backoff),
                    resume_state_file=resume_file,
                )
                if report_path.strip():
                    Path(report_path).write_text(_as_pretty_json(result), encoding="utf-8")
                summary = (
                    "✅ Upload finalizado | "
                    f"Uploaded now: {result['uploaded_audio_now']} | "
                    f"Skipped existing: {result['uploaded_audio_skipped_existing']} | "
                    f"Failed uploads: {result['failed_uploads']}"
                )
                return summary, _as_pretty_json(result)
            except Exception as exc:
                return f"❌ Upload falhou: {exc}", "{}"
            finally:
                if temp_dir is not None:
                    temp_dir.cleanup()

        dry_run_button.click(
            fn=run_dry_run,
            inputs=[project_slug, dataset_repo, detections_csv, "", segments_zip, report_file],
            outputs=[status, result_json],
        )

        segments_upload_start.click(
            fn=_start_segments_upload,
            inputs=[segments_upload_repo, segments_upload_file, segments_upload_token, segments_upload_batch_size],
            outputs=[segments_upload_status, segments_upload_result, segments_upload_progress],
        )

        segments_upload_pause.click(
            fn=_pause_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_result, segments_upload_progress],
        )

        segments_upload_resume.click(
            fn=_resume_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_result, segments_upload_progress],
        )

        segments_upload_cancel.click(
            fn=_cancel_segments_upload,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_result, segments_upload_progress],
        )

        segments_upload_refresh.click(
            fn=_refresh_segments_upload_status,
            inputs=[],
            outputs=[segments_upload_status, segments_upload_result, segments_upload_progress],
        )

        upload_button.click(
            fn=run_upload,
            inputs=[
                project_slug,
                dataset_repo,
                detections_csv,
                "",
                segments_zip,
                hf_token,
                batch_size,
                shard_size,
                max_retries,
                retry_backoff_seconds,
                resume_state_file,
                report_file,
            ],
            outputs=[status, result_json],
        )

    return demo
