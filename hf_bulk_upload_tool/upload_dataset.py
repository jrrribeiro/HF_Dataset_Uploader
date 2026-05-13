#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path


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

    def create_repo() -> None:
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=is_private, exist_ok=True)

    retry_call("create_repo", args.create_repo_attempts, args.retry_backoff, create_repo)

    def upload_segments() -> None:
        api.upload_folder(
            folder_path=str(segments_path),
            repo_id=repo_id,
            repo_type="dataset",
            path_in_repo=args.segments_path_in_repo,
            commit_message=args.commit_message,
        )

    retry_call("upload_segments", args.upload_attempts, args.retry_backoff, upload_segments)

    if csv_path:

        def upload_csv() -> None:
            api.upload_file(
                path_or_fileobj=str(csv_path),
                path_in_repo=args.csv_path_in_repo,
                repo_id=repo_id,
                repo_type="dataset",
                commit_message=f"Upload CSV for {repo_id}",
            )

        retry_call("upload_csv", args.upload_attempts, args.retry_backoff, upload_csv)

    print()
    print("Upload complete.")
    print(f"Dataset URL: https://huggingface.co/datasets/{repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())