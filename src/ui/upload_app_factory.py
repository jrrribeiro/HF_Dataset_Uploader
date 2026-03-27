import json
import os
import tarfile
import tempfile
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


def _run_segments_upload(
    dataset_repo: str,
    archive_path: str | None,
    token: str,
) -> tuple[str, str]:
    dataset_repo = (dataset_repo or "").strip()
    if not dataset_repo or "/" not in dataset_repo:
        return "❌ Informe dataset repo no formato owner/repo", "{}"
    if not archive_path:
        return "❌ Envie um arquivo (.tar, .tar.gz, ou .zip) de segmentos", "{}"

    try:
        segments_root, temp_dir = _extract_compressed_segments(archive_path)
        if segments_root is None:
            return "❌ Arquivo compactado invalido", "{}"

        try:
            from cli.hf_dataset_cli import upload_segments_to_hf
            project_slug = dataset_repo.split("/")[1].replace("-dataset", "")
            api = _build_api(token)
            result = upload_segments_to_hf(
                api=api,
                project_slug=project_slug,
                dataset_repo=dataset_repo,
                segments_root=str(segments_root),
            )
            summary = (
                f"✅ Upload de segmentos completo | "
                f"Total: {result['total_files']} | "
                f"Enviados: {result['uploaded']} | "
                f"Falhas: {result['failed']}"
            )
            return summary, _as_pretty_json(result)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()
    except Exception as exc:
        return f"❌ Upload falhou: {exc}", "{}"


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
            segments_upload_button = gr.Button("Enviar Segmentos para Dataset", variant="primary")
            segments_upload_status = gr.Markdown(value="Pronto")
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
                return "❌ Pasta de segmentos invalida. No Space, envie ZIP da pasta.", "{}"

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
                return "❌ Pasta de segmentos invalida. No Space, envie ZIP da pasta.", "{}"

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

        segments_upload_button.click(
            fn=_run_segments_upload,
            inputs=[segments_upload_repo, segments_upload_file, segments_upload_token],
            outputs=[segments_upload_status, segments_upload_result],
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
