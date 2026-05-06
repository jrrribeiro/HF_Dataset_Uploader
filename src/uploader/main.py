from __future__ import annotations

import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import click

from .auth_service import AuthService
from .error_handler import build_error_message
from .repo_service import RepositoryService
from .scanner import LocalScanner
from .session_manager import SessionManager


def handle_cli_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except click.ClickException:
            raise
        except Exception as exc:
            raise click.ClickException(build_error_message(exc)) from exc

    return wrapper


@click.group(help="BirdNET local uploader CLI")
def cli() -> None:
    pass


@cli.command("login")
@click.option("--token", prompt=True, hide_input=True, help="Hugging Face token")
@handle_cli_errors
def login_cmd(token: str) -> None:
    service = AuthService()
    user = service.authenticate(token)
    click.echo(f"OK: authenticated as {user['username']}")


@cli.command("init-repo")
@click.option("--repo-id", required=True, help="Dataset repo id in owner/name format")
@click.option("--private/--public", "private_repo", default=True, show_default=True)
@handle_cli_errors
def init_repo_cmd(repo_id: str, private_repo: bool) -> None:
    token = AuthService().require_token()

    created = RepositoryService(token).create_dataset(repo_id, private=private_repo)
    click.echo(f"OK: dataset ready at {created}")


@cli.command("scan")
@click.option("--segments", "segments_dir", required=True, type=click.Path(exists=True, file_okay=False))
@handle_cli_errors
def scan_cmd(segments_dir: str) -> None:
    summary = LocalScanner().scan_folder(segments_dir)
    click.echo(
        json.dumps(
            {
                "total_files": summary["total_files"],
                "total_size": summary["total_size"],
                "species_count": len(summary["by_species"]),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


@cli.command("start")
@click.option("--repo-id", required=True)
@click.option("--segments", "segments_dir", required=True, type=click.Path(exists=True, file_okay=False))
@handle_cli_errors
def start_cmd(repo_id: str, segments_dir: str) -> None:
    scanner = LocalScanner()
    summary = scanner.scan_folder(segments_dir)
    session = SessionManager()
    payload = {
        "repo_id": repo_id,
        "segments_dir": str(Path(segments_dir).resolve()),
        "total_files": summary["total_files"],
        "total_size": summary["total_size"],
        "uploaded": 0,
        "failed": 0,
        "status": "ready",
    }
    session.save_checkpoint(payload)
    click.echo(f"OK: session created: {session.session_id}")
    click.echo(f"Checkpoint: {session.checkpoint_path}")


@cli.command("resume")
@click.argument("session_id")
@handle_cli_errors
def resume_cmd(session_id: str) -> None:
    session = SessionManager(session_id=session_id)
    payload = session.load_checkpoint()
    if not payload:
        raise click.ClickException(f"Session has no checkpoint: {session_id}")
    click.echo(json.dumps(payload, ensure_ascii=True, indent=2))


@cli.command("upload")
@click.option("--repo-id", required=True, help="Dataset repo id in owner/name format")
@click.option("--segments", "segments_dir", required=True, type=click.Path(exists=True, file_okay=False), help="Local folder with audio segments")
@click.option("--csv", "csv_file", required=False, type=click.Path(exists=True, dir_okay=False), help="Optional detections CSV to upload to the dataset")
@click.option("--token", required=False, help="Hugging Face token (falls back to HF_TOKEN env var or keyring storage)")
@click.option("--session-id", required=False, help="Use or create a session id for resumable uploads")
@click.option("--remote-base", default="audio", show_default=True, help="Remote base path inside the dataset")
@click.option("--batch-size", default=None, type=int, help="Override batch size for uploads")
@click.option("--workers", default=None, type=int, help="Number of parallel upload workers")
@click.option("--dry-run", is_flag=True, default=False, help="Scan and report what would be uploaded, do not perform uploads")
@handle_cli_errors
def upload_cmd(
    repo_id: str,
    segments_dir: str,
    csv_file: str | None,
    token: str | None,
    session_id: str | None,
    remote_base: str,
    batch_size: int | None,
    workers: int | None,
    dry_run: bool,
):
    """Upload local segments (and optional CSV) into the HF dataset.

    Token resolution (in order of priority):
    1. --token option (if provided)
    2. HF_TOKEN environment variable (useful for Docker/CI)
    3. Keyring secure storage (use 'birdnet-uploader login' to store)

    The command creates/uses a session checkpoint for resumable uploads.
    """
    if token:
        hf_token = token
    else:
        hf_token = AuthService().require_token()

    scanner = LocalScanner()
    summary = scanner.scan_folder(segments_dir)
    total_files = summary["total_files"]
    total_size = summary["total_size"]

    click.echo(f"Found {total_files} audio files ({total_size} bytes) under {segments_dir}")

    if dry_run:
        click.echo("Dry run: no files will be uploaded. Showing first 20 files:")
        count = 0
        for species, items in summary["by_species"].items():
            for it in items:
                if count >= 20:
                    break
                click.echo(f" - {it['relative_path']} ({it['size']} bytes)")
                count += 1
            if count >= 20:
                break
        if csv_file:
            click.echo(f"Would also upload CSV: {csv_file} -> index/detections.csv")
        return

    api = None
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=hf_token)
    except Exception as exc:  # pragma: no cover - external
        raise click.ClickException(build_error_message(exc)) from exc

    repo_service = RepositoryService(hf_token)
    validation = repo_service.validate_repo(repo_id)
    if not validation.get("is_valid"):
        click.echo(f"Warning: dataset {repo_id} may be missing structure: {validation.get('missing_prefixes')}")

    from .deduplicator import Deduplicator
    from .batch_uploader import BatchUploader

    dedup = Deduplicator(api=api, repo_id=repo_id)
    session = SessionManager(session_id=session_id) if session_id else SessionManager()
    uploader = BatchUploader(api=api, repo_id=repo_id, deduplicator=dedup, session=session, max_retries=None, initial_backoff=None, max_workers=workers)

    file_infos: list[dict] = []
    for species, items in summary["by_species"].items():
        for it in items:
            file_infos.append({"full_path": it["full_path"], "relative_path": it["relative_path"], "size": it.get("size", 0)})

    if csv_file:
        click.echo(f"Uploading CSV to index/detections.csv...")
        try:
            api.upload_file(path_or_file=str(csv_file), path_in_repo="index/detections.csv", repo_id=repo_id, repo_type="dataset")
            click.echo("CSV uploaded")
        except Exception as exc:
            raise click.ClickException(f"CSV upload failed: {exc}") from exc

    try:
        from .manifest import build_manifest_from_scan, manifest_to_bytes

        csv_rows = None
        if csv_file:
            import csv

            with open(csv_file, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                csv_rows = list(reader)

        manifest = build_manifest_from_scan(repo_id, summary, csv_rows=csv_rows)
        api.upload_file(path_or_fileobj=manifest_to_bytes(manifest), path_in_repo="index/manifest.json", repo_id=repo_id, repo_type="dataset")
        click.echo("Manifest uploaded: index/manifest.json")
    except Exception as exc:  # pragma: no cover - external API
        raise click.ClickException(f"Manifest upload failed: {exc}") from exc

    try:
        from .manifest import write_shards_from_csv_rows

        if csv_file and csv_rows:
            click.echo("Generating index shards from CSV detections...")
            shards = write_shards_from_csv_rows(csv_rows, shard_size=int(__import__("src.uploader.config", fromlist=["INDEX_SHARD_SIZE"]).INDEX_SHARD_SIZE))
            for shard_path in shards:
                shard_name = shard_path.name
                click.echo(f"Uploading shard: index/shards/{shard_name}")
                try:
                    api.upload_file(path_or_file=str(shard_path), path_in_repo=f"index/shards/{shard_name}", repo_id=repo_id, repo_type="dataset")
                except Exception as exc:
                    click.echo(f"Warning: failed to upload shard {shard_name}: {exc}")
            click.echo(f"Uploaded {len(shards)} shards")
    except Exception as exc:  # pragma: no cover - external API
        raise click.ClickException(f"Shard generation/upload failed: {exc}") from exc

    click.echo("Starting upload of audio files...")

    def on_progress(state: dict) -> None:
        click.echo(f"Progress: uploaded={state.get('uploaded')} skipped={state.get('skipped')} failed={state.get('failed')}", err=False)

    result = uploader.upload_files(file_infos, remote_base=remote_base, batch_size=batch_size, on_progress=on_progress)
    click.echo(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    cli()
