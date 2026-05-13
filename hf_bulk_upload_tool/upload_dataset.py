#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
import time
from pathlib import Path
import concurrent.futures
from typing import List, Tuple
import json
import csv
from urllib.parse import quote

try:
    import requests
except Exception:
    requests = None


def configure_hf_env() -> None:
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")


configure_hf_env()

from huggingface_hub import HfApi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload a large BirdNET segment folder to a Hugging Face dataset "
            "while preserving the local species subfolder structure."
        )
    )
    parser.add_argument("--hf-username", help="Hugging Face username or organization name.")
    parser.add_argument("--hf-token", help="Hugging Face write token. If omitted, the script prompts for it.")
    parser.add_argument("--repo-name", help="Dataset name to create, for example birdnet-segments-2026.")
    parser.add_argument("--repo-id", help="Full dataset repo id, for example username/dataset-name.")
    parser.add_argument("--segments", required=True, help="Path to the local folder containing the species subfolders.")
    parser.add_argument("--csv", help="Optional CSV file to upload alongside the segments.")
    parser.add_argument("--segments-path-in-repo", default="audio", help="Destination folder inside the dataset repo.")
    parser.add_argument("--csv-path-in-repo", default="index/detections.csv", help="Destination path for the CSV inside the repo.")
    parser.add_argument("--private", action="store_true", help="Create the dataset as private. This is the default.")
    parser.add_argument("--public", action="store_true", help="Create the dataset as public.")
    parser.add_argument("--commit-message", default="Upload BirdNET segments", help="Commit message used for the upload.")
    parser.add_argument("--create-repo-attempts", type=int, default=3, help="Number of retries for repo creation.")
    parser.add_argument("--upload-attempts", type=int, default=3, help="Number of retries for folder and CSV uploads.")
    parser.add_argument("--retry-backoff", type=float, default=5.0, help="Base delay in seconds between retries.")
    parser.add_argument("--max-workers", type=int, default=4, help="Number of parallel worker threads for per-file uploads (fallback path).")
    parser.add_argument("--resume", action="store_true", help="Check repository and skip files that are already uploaded (resume mode).")
    parser.add_argument("--checkpoint-dir", default=None, help="Directory to store upload checkpoints. Defaults to ./hf_bulk_upload_tool/.checkpoints.")
    parser.add_argument("--verify-remote", action="store_true", help="When resuming, verify remote file size via HTTP HEAD to avoid skipping mismatched files.")
    parser.add_argument("--verify-etag", action="store_true", help="When resuming, prefer ETag comparison if available from the server.")
    parser.add_argument("--progress-log", default=None, help="Path to CSV progress log. Defaults to <checkpoint-dir>/progress.csv")
    parser.add_argument("--resume-only", action="store_true", help="Only compare local files with the repo and report what would be uploaded; do not upload anything.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned actions without uploading anything.")
    return parser.parse_args()


def resolve_repo_id(args: argparse.Namespace) -> str:
    if args.repo_id:
        return args.repo_id.strip()

    if not args.hf_username:
        args.hf_username = input("Hugging Face username/organization: ").strip()
    if not args.repo_name:
        args.repo_name = input("Dataset name: ").strip()

    if not args.hf_username or not args.repo_name:
        raise SystemExit("Both --hf-username and --repo-name are required when --repo-id is not provided.")

    return f"{args.hf_username.strip()}/{args.repo_name.strip()}"


def get_token(args: argparse.Namespace) -> str:
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if not token:
        token = getpass.getpass("Hugging Face token: ").strip()
    if not token:
        raise SystemExit("A Hugging Face token is required.")
    return token.strip()


def retry_call(label: str, attempts: int, backoff: float, func):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"[{label}] attempt {attempt}/{attempts}")
            return func()
        except Exception as exc:  # noqa: BLE001 - network operations can fail in many ways
            last_error = exc
            if attempt >= attempts:
                break
            wait_seconds = backoff * attempt
            print(f"[{label}] attempt {attempt} failed: {exc}")
            print(f"[{label}] retrying in {wait_seconds:.0f}s")
            time.sleep(wait_seconds)

    raise SystemExit(f"{label} failed after {attempts} attempts: {last_error}")


def main() -> int:
    args = parse_args()

    if args.private and args.public:
        raise SystemExit("Choose either --private or --public, not both.")

    segments_path = Path(args.segments).expanduser().resolve()
    if not segments_path.is_dir():
        raise SystemExit(f"Segments path does not exist or is not a directory: {segments_path}")

    csv_path = None
    if args.csv:
        csv_path = Path(args.csv).expanduser().resolve()
        if not csv_path.is_file():
            raise SystemExit(f"CSV path does not exist or is not a file: {csv_path}")

    repo_id = resolve_repo_id(args)
    token = get_token(args)
    is_private = True if args.private or not args.public else False

    print(f"Repository: {repo_id}")
    print(f"Segments: {segments_path}")
    print(f"Segments destination: {args.segments_path_in_repo}")
    if csv_path:
        print(f"CSV: {csv_path}")
        print(f"CSV destination: {args.csv_path_in_repo}")
    print(f"Visibility: {'private' if is_private else 'public'}")

    if args.dry_run:
        print("Dry run selected. No network calls will be made.")
        return 0

    api = HfApi(token=token)

    def list_existing_files() -> set:
        try:
            print("Listing files in target repo to determine already-uploaded files...")
            files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
            return set(files or [])
        except Exception as e:
            print(f"Warning: could not list repo files: {e}")
            return set()


    # Checkpoint helpers
    default_checkpoint_dir = Path(__file__).parent / ".checkpoints"
    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else default_checkpoint_dir
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"{repo_id.replace('/', '__')}.json"

    def load_checkpoint() -> tuple[set, dict[str, str]]:
        if not checkpoint_file.exists():
            return set(), {}
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return set(data), {}
            uploaded = set(data.get('uploaded', []))
            file_hashes = data.get('file_hashes', {})
            if not isinstance(file_hashes, dict):
                file_hashes = {}
            return uploaded, {str(k): str(v) for k, v in file_hashes.items()}
        except Exception as e:
            print(f"Warning: failed to load checkpoint {checkpoint_file}: {e}")
            return set(), {}

    def save_checkpoint(uploaded_set: set, file_hashes: dict[str, str]) -> None:
        try:
            with open(checkpoint_file, 'w', encoding='utf-8') as fh:
                json.dump({'uploaded': sorted(list(uploaded_set)), 'file_hashes': file_hashes}, fh, indent=2)
        except Exception as e:
            print(f"Warning: failed to save checkpoint {checkpoint_file}: {e}")

    def compute_sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def remote_file_info(repo_path: str) -> Tuple[int | None, str | None]:
        """Return (size, etag) for a repo file via HTTP HEAD, or (None, None)."""
        if requests is None:
            return None, None
        quoted = '/'.join(quote(p) for p in repo_path.split('/'))
        url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{quoted}"
        try:
            r = requests.head(url, allow_redirects=True, timeout=10)
            if r.status_code >= 400:
                return None, None
            cl = r.headers.get('content-length')
            etag = r.headers.get('etag')
            size = int(cl) if cl is not None else None
            return size, etag
        except Exception:
            return None, None

    # Progress logging
    progress_log_path = Path(args.progress_log) if args.progress_log else (checkpoint_dir / 'progress.csv')
    def append_progress(local_path: Path | None, repo_path: str, status: str, msg: str | None = None, elapsed: float | None = None) -> None:
        header = ['timestamp','local_path','repo_path','status','message','elapsed_seconds']
        row = [time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), str(local_path) if local_path else '', repo_path, status, (msg or '').replace('\n',' '), f"{elapsed:.2f}" if elapsed is not None else '']
        write_header = not progress_log_path.exists()
        try:
            with open(progress_log_path, 'a', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh)
                if write_header:
                    writer.writerow(header)
                writer.writerow(row)
        except Exception as e:
            print(f"Warning: failed to write progress log {progress_log_path}: {e}")

    run_stats = {
        'planned': 0,
        'skipped': 0,
        'uploaded': 0,
        'failed': 0,
        'bytes_planned': 0,
        'bytes_uploaded': 0,
        'started_at': time.time(),
    }

    def record_summary() -> None:
        elapsed = time.time() - run_stats['started_at']
        summary_message = (
            f"planned={run_stats['planned']} skipped={run_stats['skipped']} "
            f"uploaded={run_stats['uploaded']} failed={run_stats['failed']} "
            f"bytes_planned={run_stats['bytes_planned']} bytes_uploaded={run_stats['bytes_uploaded']}"
        )
        append_progress(None, '', 'summary', summary_message, elapsed)
        try:
            summary_json = checkpoint_dir / f"{repo_id.replace('/', '__')}.summary.json"
            with open(summary_json, 'w', encoding='utf-8') as fh:
                json.dump({
                    'repo_id': repo_id,
                    'planned': run_stats['planned'],
                    'skipped': run_stats['skipped'],
                    'uploaded': run_stats['uploaded'],
                    'failed': run_stats['failed'],
                    'bytes_planned': run_stats['bytes_planned'],
                    'bytes_uploaded': run_stats['bytes_uploaded'],
                    'elapsed_seconds': round(elapsed, 2),
                }, fh, indent=2)
        except Exception as e:
            print(f"Warning: failed to write summary json: {e}")

    def remote_file_size(repo_path: str) -> int | None:
        if requests is None:
            return None
        # Construct raw file URL: https://huggingface.co/datasets/{repo_id}/resolve/main/{path}
        # Path components must be URL-quoted
        quoted = '/'.join(quote(p) for p in repo_path.split('/'))
        url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{quoted}"
        try:
            r = requests.head(url, allow_redirects=True, timeout=10)
            if r.status_code >= 400:
                return None
            cl = r.headers.get('content-length')
            if cl is None:
                return None
            return int(cl)
        except Exception:
            return None

    def create_repo() -> None:
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=is_private, exist_ok=True)

    retry_call("create_repo", args.create_repo_attempts, args.retry_backoff, create_repo)
    # Prepare set of existing files if resume requested
    existing_files: set = set()
    checkpoint_uploaded: set = set()
    checkpoint_hashes: dict[str, str] = {}
    if args.resume:
        existing_files = list_existing_files()
        checkpoint_uploaded, checkpoint_hashes = load_checkpoint()

    # union of already-known uploaded files
    already_uploaded = existing_files.union(checkpoint_uploaded)

    def upload_segments() -> None:
        # existing_files is computed above when resume is requested

        # If not resuming and hf offers upload_large_folder, use it for speed
        if not args.resume and hasattr(api, "upload_large_folder"):
            print("Using HfApi.upload_large_folder for optimized large uploads...")
            api.upload_large_folder(
                folder_path=str(segments_path),
                repo_id=repo_id,
                repo_type="dataset",
                path_in_repo=args.segments_path_in_repo,
                commit_message=args.commit_message,
            )
            return

        # Otherwise, perform per-file upload and skip existing files
        print("Performing per-file upload (skipping already uploaded files if any)...")

        files: List[Tuple[Path, str]] = []
        for p in segments_path.rglob("*"):
            if p.is_file():
                rel = p.relative_to(segments_path).as_posix()
                repo_path = f"{args.segments_path_in_repo}/{rel}"
                run_stats['bytes_planned'] += p.stat().st_size
                skip = False
                if repo_path in already_uploaded:
                    local_hash = None
                    checkpoint_hash = checkpoint_hashes.get(repo_path)
                    if checkpoint_hash:
                        local_hash = compute_sha256(p)
                        if local_hash != checkpoint_hash:
                            skip = False
                            print(f"Hash mismatch for {repo_path}; will re-upload.")
                        else:
                            skip = True
                    elif args.verify_remote and requests is not None:
                        local_size = p.stat().st_size
                        remote_size, remote_etag = remote_file_info(repo_path)
                        if args.verify_etag and remote_etag:
                            # We do not compute a remote-matching hash locally here; rely on size and the checkpoint hash path.
                            skip = (remote_size is not None and local_size == remote_size)
                        else:
                            skip = (remote_size is not None and local_size == remote_size)
                    else:
                        skip = True

                if skip:
                    run_stats['skipped'] += 1
                    append_progress(p, repo_path, 'skipped', 'already uploaded')
                    continue
                files.append((p, repo_path))

        run_stats['planned'] = len(files)

        if args.resume_only:
            print("Resume-only mode: no upload will be performed.")
            for local_path, repo_path in files:
                append_progress(local_path, repo_path, 'planned', 'resume-only')
            return

        print(f"Found {len(files)} files to upload; launching {args.max_workers} workers")

        def upload_one(pair: Tuple[Path, str]):
            local_path, repo_path = pair
            start = time.time()
            try:
                def do_upload():
                    api.upload_file(
                        path_or_fileobj=str(local_path),
                        path_in_repo=repo_path,
                        repo_id=repo_id,
                        repo_type="dataset",
                        commit_message=args.commit_message,
                    )

                retry_call(f"upload_file:{repo_path}", args.upload_attempts, args.retry_backoff, do_upload)
            except Exception as e:
                elapsed = time.time() - start
                append_progress(local_path, repo_path, 'failed', str(e), elapsed)
                raise
            else:
                elapsed = time.time() - start
                append_progress(local_path, repo_path, 'uploaded', None, elapsed)
                return repo_path, local_path

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
            futures = [ex.submit(upload_one, f) for f in files]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    repo_path, local_path = fut.result()
                except Exception as e:
                    print(f"Error uploading file: {e}")
                    continue
                # mark as uploaded in checkpoint
                if repo_path:
                    already_uploaded.add(repo_path)
                    try:
                        checkpoint_hashes[repo_path] = compute_sha256(local_path)
                    except Exception as e:
                        print(f"Warning: failed to hash {repo_path} after upload: {e}")
                    run_stats['uploaded'] += 1
                    try:
                        run_stats['bytes_uploaded'] += Path(local_path).stat().st_size
                    except Exception:
                        pass
                    save_checkpoint(already_uploaded, checkpoint_hashes)

    retry_call("upload_segments", args.upload_attempts, args.retry_backoff, upload_segments)

    if args.resume_only:
        print("Resume-only mode completed; no uploads were performed.")
        record_summary()
        print()
        print("Upload complete.")
        print(f"Dataset URL: https://huggingface.co/datasets/{repo_id}")
        return 0

    if csv_path:

        def upload_csv() -> None:
            skip_csv = False
            if args.resume and args.csv_path_in_repo in already_uploaded:
                if args.verify_remote and requests is not None:
                    local_size = csv_path.stat().st_size
                    remote_size, remote_etag = remote_file_info(args.csv_path_in_repo)
                    if args.verify_etag and remote_etag:
                        # no local etag available -> fall back to size check
                        if remote_size is not None and local_size == remote_size:
                            skip_csv = True
                    else:
                        if remote_size is not None and local_size == remote_size:
                            skip_csv = True

            if skip_csv:
                print(f"CSV already exists at {args.csv_path_in_repo}; skipping upload.")
                run_stats['skipped'] += 1
                append_progress(csv_path, args.csv_path_in_repo, 'skipped', 'already uploaded')
                return

            start = time.time()
            try:
                api.upload_file(
                    path_or_fileobj=str(csv_path),
                    path_in_repo=args.csv_path_in_repo,
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"Upload CSV for {repo_id}",
                )
            except Exception as e:
                elapsed = time.time() - start
                run_stats['failed'] += 1
                append_progress(csv_path, args.csv_path_in_repo, 'failed', str(e), elapsed)
                raise
            else:
                elapsed = time.time() - start
                run_stats['uploaded'] += 1
                try:
                    run_stats['bytes_uploaded'] += csv_path.stat().st_size
                except Exception:
                    pass
                try:
                    checkpoint_hashes[args.csv_path_in_repo] = compute_sha256(csv_path)
                    save_checkpoint(already_uploaded.union({args.csv_path_in_repo}), checkpoint_hashes)
                except Exception as e:
                    print(f"Warning: failed to update CSV checkpoint hash: {e}")
                append_progress(csv_path, args.csv_path_in_repo, 'uploaded', None, elapsed)

        retry_call("upload_csv", args.upload_attempts, args.retry_backoff, upload_csv)

    print()
    print("Upload complete.")
    print(f"Dataset URL: https://huggingface.co/datasets/{repo_id}")
    record_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())