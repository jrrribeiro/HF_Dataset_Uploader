from __future__ import annotations

import os
import json
import time
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import click
import logging
import sys

from .hf_tuning import configure_hf_http_backoff
from .config import AUDIO_EXTENSIONS, INDEX_SHARD_SIZE

# Ensure HF backoff tuning is applied before importing modules that may import huggingface_hub
configure_hf_http_backoff()

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


@click.group(help="HF Dataset Uploader CLI")
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
@click.option(
    "--upload-mode",
    type=click.Choice(["direct", "legacy"], case_sensitive=False),
    default="direct",
    show_default=True,
    help="direct uploads the folder as-is; legacy keeps manifest/index generation",
)
@click.option("--dry-run", is_flag=True, default=False, help="Scan and report what would be uploaded, do not perform uploads")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show detailed logging for debugging")
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
    upload_mode: str,
    dry_run: bool,
    verbose: bool,
):
    """Upload local segments (and optional CSV) into the HF dataset.

    Token resolution (in order of priority):
    1. --token option (if provided)
    2. HF_TOKEN environment variable (useful for Docker/CI)
    3. Keyring secure storage (use 'hf-dataset-uploader login' to store)

    The command creates/uses a session checkpoint for resumable uploads.
    """
    if verbose:
        click.echo("[DEBUG] Verbose logging enabled")
        click.echo(f"[DEBUG] CLI module: {__file__}")
        # Configure logging to stdout so instrumented loggers are visible
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
        # Enable more verbose HTTP/hub logs to help debugging network issues
        logging.getLogger("huggingface_hub").setLevel(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)
        logging.getLogger("requests").setLevel(logging.DEBUG)

    # Keep HF Hub requests from hanging for too long on slow or unreachable links.
    # These are read by huggingface_hub at import time, so set them before any hub calls.
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "5")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    configure_hf_http_backoff()

    scanner = LocalScanner()
    summary = scanner.scan_folder(segments_dir)
    total_files = summary["total_files"]
    total_size = summary["total_size"]

    click.echo(f"Found {total_files} audio files ({total_size} bytes) under {segments_dir}")
    if verbose:
        click.echo(f"[DEBUG] Species breakdown: {list(summary['by_species'].keys())}")

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

    # Resolve token after dry-run check so we can scan without requiring network auth
    if token:
        hf_token = token
    else:
        hf_token = AuthService().require_token()

    api = None
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=hf_token)
    except Exception as exc:  # pragma: no cover - external
        raise click.ClickException(build_error_message(exc)) from exc

    # Safety-first normalization: direct is always the default unless legacy is explicitly requested.
    upload_mode = (upload_mode or "direct").strip().lower()
    use_legacy_mode = upload_mode == "legacy"
    if verbose:
        click.echo(f"[DEBUG] Effective upload mode: {'legacy' if use_legacy_mode else 'direct'}")

    if not use_legacy_mode:
        create_attempts = int(os.getenv("BNU_REPO_CREATE_ATTEMPTS", "3"))
        create_backoff = float(os.getenv("BNU_REPO_CREATE_BACKOFF", "1.0"))
        last_create_exc: Exception | None = None
        for attempt in range(1, create_attempts + 1):
            try:
                api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
                click.echo("[OK] Dataset repository ready for direct folder upload")
                last_create_exc = None
                break
            except Exception as exc:
                last_create_exc = exc
                if attempt >= create_attempts:
                    break
                wait_s = create_backoff * (2 ** (attempt - 1))
                if verbose:
                    click.echo(f"[DEBUG] create_repo failed (attempt {attempt}/{create_attempts}): {exc}. Retrying in {wait_s:.1f}s")
                time.sleep(wait_s)

        if last_create_exc is not None:
            msg = str(last_create_exc).lower()
            network_like = (
                "timed out" in msg
                or "timeout" in msg
                or "winerror 10060" in msg
                or "max retries exceeded" in msg
            )
            if network_like:
                click.echo(f"[WARN] Could not validate/create repo due to network timeout: {last_create_exc}")
                click.echo("[WARN] Continuing direct folder upload attempt anyway...")
            else:
                raise click.ClickException(f"Could not create or access dataset repository: {last_create_exc}") from last_create_exc

        def _upload_file_with_retry(path_or_fileobj: Any, path_in_repo: str) -> None:
            max_attempts = int(os.getenv("BNU_HUB_UPLOAD_ATTEMPTS", "3"))
            timeout_s = float(os.getenv("BNU_HUB_UPLOAD_TIMEOUT", "90"))
            base_backoff = float(os.getenv("BNU_HUB_UPLOAD_BACKOFF", "1.0"))
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    if verbose:
                        click.echo(f"[DEBUG] upload_file {path_in_repo} (attempt {attempt}/{max_attempts})")
                    result: dict[str, Any] = {"exc": None}

                    def _target() -> None:
                        try:
                            connect_timeout = float(os.getenv("BNU_HUB_CONNECT_TIMEOUT", "8"))
                            read_timeout = float(os.getenv("BNU_HUB_READ_TIMEOUT", "30"))
                            try:
                                api.upload_file(
                                    path_or_fileobj=path_or_fileobj,
                                    path_in_repo=path_in_repo,
                                    repo_id=repo_id,
                                    repo_type="dataset",
                                    timeout=(connect_timeout, read_timeout),
                                )
                            except TypeError:
                                # Some hf_hub versions don't accept a `timeout` kwarg; fall back
                                api.upload_file(
                                    path_or_fileobj=path_or_fileobj,
                                    path_in_repo=path_in_repo,
                                    repo_id=repo_id,
                                    repo_type="dataset",
                                )
                        except Exception as exc:  # pragma: no cover - network behavior
                            result["exc"] = exc

                    t = threading.Thread(target=_target, daemon=True)
                    t.start()
                    t.join(timeout_s)
                    if t.is_alive():
                        raise TimeoutError(f"upload_file timed out after {timeout_s}s")
                    if result["exc"] is not None:
                        raise result["exc"]
                    return
                except Exception as exc:  # pragma: no cover - network behavior
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    wait_s = base_backoff * (2 ** (attempt - 1))
                    if verbose:
                        click.echo(f"[DEBUG] upload_file failed for {path_in_repo}: {exc}. Retrying in {wait_s:.1f}s")
                    time.sleep(wait_s)

            raise click.ClickException(f"Upload failed for {path_in_repo}: {last_exc}")

        def _upload_folder_with_retry(folder_path: str, path_in_repo: str) -> None:
            max_attempts = int(os.getenv("BNU_HUB_UPLOAD_ATTEMPTS", "3"))
            timeout_s = float(os.getenv("BNU_FOLDER_UPLOAD_TIMEOUT", "600"))
            base_backoff = float(os.getenv("BNU_HUB_UPLOAD_BACKOFF", "1.0"))
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    if verbose:
                        click.echo(f"[DEBUG] upload_folder {folder_path} -> {path_in_repo or '/'} (attempt {attempt}/{max_attempts})")

                    result: dict[str, Any] = {"exc": None}

                    def _target() -> None:
                        try:
                            connect_timeout = float(os.getenv("BNU_HUB_CONNECT_TIMEOUT", "8"))
                            read_timeout = float(os.getenv("BNU_HUB_READ_TIMEOUT", "30"))
                            kwargs: dict[str, Any] = {
                                "folder_path": folder_path,
                                "repo_id": repo_id,
                                "repo_type": "dataset",
                            }
                            # Try passing timeout if supported by this hf_hub version
                            try:
                                api.upload_folder(**{**kwargs, **{"timeout": (connect_timeout, read_timeout)}})
                            except TypeError:
                                api.upload_folder(**kwargs)
                            if path_in_repo:
                                kwargs["path_in_repo"] = path_in_repo
                            api.upload_folder(**kwargs)
                        except Exception as exc:  # pragma: no cover - network behavior
                            result["exc"] = exc

                    t = threading.Thread(target=_target, daemon=True)
                    t.start()
                    t.join(timeout_s)
                    if t.is_alive():
                        raise TimeoutError(f"upload_folder timed out after {timeout_s}s")
                    if result["exc"] is not None:
                        raise result["exc"]
                    return
                except Exception as exc:  # pragma: no cover - network behavior
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    wait_s = base_backoff * (2 ** (attempt - 1))
                    if verbose:
                        click.echo(f"[DEBUG] upload_folder failed: {exc}. Retrying in {wait_s:.1f}s")
                    time.sleep(wait_s)

            raise click.ClickException(f"Folder upload failed: {last_exc}")

        if csv_file:
            click.echo("Uploading CSV to index/detections.csv...")
            try:
                _upload_file_with_retry(str(csv_file), "index/detections.csv")
                click.echo("CSV uploaded")
            except Exception as exc:
                click.echo(f"[WARN] CSV upload failed, continuing without CSV: {exc}")

        click.echo(f"Directly uploading folder '{segments_dir}' to repo path '{remote_base or '/'}'...")
        start_time = time.time()
        _upload_folder_with_retry(segments_dir, remote_base)
        elapsed = int(time.time() - start_time)

        click.echo("\n" + "=" * 60)
        click.echo("DIRECT FOLDER UPLOAD COMPLETE")
        click.echo("=" * 60)
        click.echo(f"Folder:    {segments_dir}")
        click.echo(f"Target:    {remote_base or '/'}")
        click.echo(f"Files:     {total_files}")
        click.echo(f"Size:      {total_size} bytes")
        click.echo(f"Time:      {elapsed} seconds")
        click.echo("=" * 60)
        return

    def _upload_with_retry(path_or_fileobj: Any, path_in_repo: str) -> None:
        max_attempts = int(os.getenv("BNU_HUB_UPLOAD_ATTEMPTS", "3"))
        timeout_s = float(os.getenv("BNU_HUB_UPLOAD_TIMEOUT", "90"))
        base_backoff = float(os.getenv("BNU_HUB_UPLOAD_BACKOFF", "1.0"))
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                if verbose:
                    click.echo(f"[DEBUG] upload_file {path_in_repo} (attempt {attempt}/{max_attempts})")
                result: dict[str, Any] = {"exc": None}

                def _target() -> None:
                        try:
                            connect_timeout = float(os.getenv("BNU_HUB_CONNECT_TIMEOUT", "8"))
                            read_timeout = float(os.getenv("BNU_HUB_READ_TIMEOUT", "30"))
                            api.upload_file(
                                path_or_fileobj=path_or_fileobj,
                                path_in_repo=path_in_repo,
                                repo_id=repo_id,
                                repo_type="dataset",
                                timeout=(connect_timeout, read_timeout),
                            )
                        except Exception as exc:  # pragma: no cover - network behavior
                            result["exc"] = exc

                t = threading.Thread(target=_target, daemon=True)
                t.start()
                t.join(timeout_s)
                if t.is_alive():
                    raise TimeoutError(f"upload_file timed out after {timeout_s}s")
                if result["exc"] is not None:
                    raise result["exc"]
                return
            except Exception as exc:  # pragma: no cover - network behavior
                last_exc = exc
                if attempt >= max_attempts:
                    break
                wait_s = base_backoff * (2 ** (attempt - 1))
                if verbose:
                    click.echo(f"[DEBUG] upload_file failed for {path_in_repo}: {exc}. Retrying in {wait_s:.1f}s")
                time.sleep(wait_s)

        raise click.ClickException(f"Upload failed for {path_in_repo}: {last_exc}")

    repo_service = RepositoryService(hf_token)
    try:
        validation = repo_service.validate_repo(repo_id)
        if not validation.get("is_valid"):
            click.echo("[WARN] Dataset structure incomplete. Attempting to initialize...")
            try:
                repo_service.create_dataset(repo_id, private=True)
                click.echo("[OK] Dataset structure created successfully!")
            except Exception as exc:
                raise click.ClickException(
                    f"Could not initialize dataset structure:\n{exc}\n\n"
                    f"Possible causes:\n"
                    f"- Invalid repo_id format (should be 'username/dataset-name')\n"
                    f"- No write permission\n"
                    f"- HuggingFace API error"
                ) from exc
    except Exception as exc:
        error_msg = str(exc)
        error_msg_lower = error_msg.lower()
        is_network_issue = (
            "read timed out" in error_msg_lower
            or "connection" in error_msg_lower and "timed out" in error_msg_lower
            or "winerror 10060" in error_msg_lower
            or "max retries exceeded" in error_msg_lower
        )
        # Dataset doesn't exist - try to create it
        if "404" in error_msg or "repository not found" in error_msg_lower or "not found" in error_msg_lower:
            click.echo(f"[WARN] Dataset '{repo_id}' not found. Creating...")
            try:
                repo_service.create_dataset(repo_id, private=True)
                click.echo("[OK] Dataset created and initialized successfully!")
            except Exception as create_exc:
                raise click.ClickException(
                    f"Dataset not found and could not be created:\n{create_exc}\n\n"
                    f"Please:\n"
                    f"1. Verify repo_id format: 'your-username/dataset-name'\n"
                    f"2. Check HuggingFace token has dataset creation permissions"
                ) from create_exc
        elif is_network_issue:
            click.echo(f"[WARN] Repository validation timed out/network issue: {error_msg}")
            click.echo("[WARN] Continuing upload flow despite validation timeout...")
        else:
            raise click.ClickException(f"Repository validation failed: {error_msg}") from exc

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
            _upload_with_retry(str(csv_file), "index/detections.csv")
            click.echo("CSV uploaded")
        except Exception as exc:
            click.echo(f"[WARN] CSV upload failed, continuing without CSV: {exc}")

    manifest_uploaded = False
    try:
        from .manifest import build_manifest_from_scan, manifest_to_bytes, summarize_csv_rows

        csv_stats = None
        if csv_file:
            import csv

            with open(csv_file, newline="", encoding="utf-8") as fh:
                csv_stats = summarize_csv_rows(csv.DictReader(fh))

        manifest = build_manifest_from_scan(repo_id, summary, csv_stats=csv_stats)
        _upload_with_retry(manifest_to_bytes(manifest), "index/manifest.json")
        manifest_uploaded = True
        click.echo("Manifest uploaded: index/manifest.json")
    except Exception as exc:  # pragma: no cover - external API
        click.echo(f"[WARN] Manifest upload failed, continuing with audio upload: {exc}")

    try:
        from .manifest import write_shards_from_csv_rows

        if csv_file and manifest_uploaded:
            click.echo("Generating index shards from CSV detections...")
            import csv

            with open(csv_file, newline="", encoding="utf-8") as fh:
                shards = write_shards_from_csv_rows(csv.DictReader(fh), shard_size=INDEX_SHARD_SIZE)
            for shard_path in shards:
                shard_name = shard_path.name
                click.echo(f"Uploading shard: index/shards/{shard_name}")
                try:
                    _upload_with_retry(str(shard_path), f"index/shards/{shard_name}")
                except Exception as exc:
                    click.echo(f"Warning: failed to upload shard {shard_name}: {exc}")
            click.echo(f"Uploaded {len(shards)} shards")
    except Exception as exc:  # pragma: no cover - external API
        raise click.ClickException(f"Shard generation/upload failed: {exc}") from exc

    click.echo("Starting upload of audio files...")

    # Track progress with elapsed time
    start_time = time.time()
    last_update = start_time
    last_state = {}
    
    def on_progress(state: dict) -> None:
        nonlocal last_update, last_state
        now = time.time()
        # Update display every second or when state changes
        if now - last_update >= 1.0 or state != last_state:
            uploaded = state.get('uploaded', 0)
            skipped = state.get('skipped', 0)
            failed = state.get('failed', 0)
            total = total_files
            percent = int(100 * uploaded / max(total, 1))
            elapsed = int(now - start_time)
            click.echo(f"[{percent:3d}%] Uploaded: {uploaded}/{total} | Skipped: {skipped} | Failed: {failed} | Elapsed: {elapsed}s")
            if verbose and state != last_state:
                click.echo(f"[DEBUG] State changed: {state}")
            last_update = now
            last_state = state.copy()

    try:
        result = uploader.upload_files(file_infos, remote_base=remote_base, batch_size=batch_size, on_progress=on_progress)
        
        # Final summary
        elapsed = int(time.time() - start_time)
        uploaded = result.get("uploaded", 0)
        skipped = result.get("skipped", 0)
        failed = result.get("failed", 0)
        
        click.echo("\n" + "="*60)
        click.echo("UPLOAD COMPLETE")
        click.echo("="*60)
        click.echo(f"Uploaded:  {uploaded} files")
        click.echo(f"Skipped:   {skipped} files (already in dataset)")
        click.echo(f"Failed:    {failed} files")
        click.echo(f"Total:     {uploaded + skipped + failed} files")
        click.echo(f"Time:      {elapsed} seconds")
        if uploaded > 0:
            rate = elapsed / uploaded if uploaded > 0 else 0
            click.echo(f"Rate:      {rate:.1f}s per file")
        click.echo("="*60)
        
        if failed > 0:
            click.echo(f"\nWarning: {failed} file(s) failed to upload. Check the session checkpoint for details.")
            click.echo(f"Session ID: {session.session_id}")
        
    except Exception as exc:
        elapsed = int(time.time() - start_time)
        click.echo(f"\nUpload interrupted after {elapsed}s")
        raise click.ClickException(f"Upload failed: {exc}") from exc


if __name__ == "__main__":
    cli()
