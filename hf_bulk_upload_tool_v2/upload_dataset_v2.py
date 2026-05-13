#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from huggingface_hub import HfApi


def configure_hf_env() -> None:
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")


configure_hf_env()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a HF dataset repo and upload a large BirdNET segment folder plus optional CSV."
    )
    parser.add_argument("--repo-id", required=True, help="Dataset repo id, for example username/dataset-name.")
    parser.add_argument("--segments", required=True, help="Path to the local BirdNET segments folder.")
    parser.add_argument("--csv", help="Optional CSV file to upload as index/detections.csv.")
    parser.add_argument("--hf-token", help="Hugging Face write token. If omitted, the script uses HF_TOKEN or prompts.")
    parser.add_argument("--private", action="store_true", help="Create the dataset as private. This is the default.")
    parser.add_argument("--public", action="store_true", help="Create the dataset as public.")
    parser.add_argument("--max-workers", type=int, default=4, help="Worker threads for upload_large_folder.")
    parser.add_argument("--commit-message", default="Upload BirdNET data", help="Commit message for the CSV upload fallback.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without uploading anything.")
    parser.add_argument("--ignore-patterns", default=None, help="Optional ignore patterns passed to upload_large_folder.")
    parser.add_argument("--allow-patterns", default=None, help="Optional allow patterns passed to upload_large_folder.")
    return parser.parse_args()


def get_token(args: argparse.Namespace) -> str:
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if token:
        return token.strip()
    return getpass.getpass("Hugging Face token: ").strip()


def retry(label: str, attempts: int, backoff_seconds: float, func):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"[{label}] attempt {attempt}/{attempts}")
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts:
                break
            wait_seconds = backoff_seconds * attempt
            print(f"[{label}] failed: {exc}")
            print(f"[{label}] retrying in {wait_seconds:.0f}s")
            time.sleep(wait_seconds)
    raise SystemExit(f"{label} failed after {attempts} attempts: {last_error}")


def create_audio_junction(staging_root: Path, segments_path: Path) -> Path:
    audio_link = staging_root / "audio"
    if audio_link.exists():
        if audio_link.is_symlink() or audio_link.is_dir():
            shutil.rmtree(audio_link)
        else:
            audio_link.unlink()

    # Prefer a directory junction on Windows so we do not duplicate the dataset on disk.
    command = ["cmd", "/c", "mklink", "/J", str(audio_link), str(segments_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Failed to create audio junction: {result.stderr.strip() or result.stdout.strip()}")
    return audio_link


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

    is_private = True if args.private or not args.public else False

    print(f"Repository: {args.repo_id}")
    print(f"Segments: {segments_path}")
    if csv_path:
        print(f"CSV: {csv_path}")
    print(f"Visibility: {'private' if is_private else 'public'}")

    if args.dry_run:
        print("Dry run selected. No network calls will be made.")
        print("Dataset layout will be staged as audio/* plus index/detections.csv.")
        return 0

    token = get_token(args)
    api = HfApi(token=token)

    def create_repo() -> None:
        api.create_repo(repo_id=args.repo_id, repo_type="dataset", private=is_private, exist_ok=True)

    retry("create_repo", 3, 5.0, create_repo)

    allow_patterns = args.allow_patterns
    ignore_patterns = args.ignore_patterns

    def upload_segments() -> None:
        print("Uploading large folder with upload_large_folder (HF optimized path)...")
        with tempfile.TemporaryDirectory(prefix="birdnet_upload_stage_") as temp_dir:
            staging_root = Path(temp_dir)
            create_audio_junction(staging_root, segments_path)
            kwargs = {
                "repo_id": args.repo_id,
                "folder_path": str(staging_root),
                "repo_type": "dataset",
                "private": is_private,
                "num_workers": args.max_workers,
                "print_report": True,
            }
            if allow_patterns:
                kwargs["allow_patterns"] = allow_patterns
            if ignore_patterns:
                kwargs["ignore_patterns"] = ignore_patterns
            api.upload_large_folder(**kwargs)

    retry("upload_segments", 3, 5.0, upload_segments)

    if csv_path:
        def upload_csv() -> None:
            api.upload_file(
                repo_id=args.repo_id,
                repo_type="dataset",
                path_or_fileobj=str(csv_path),
                path_in_repo="index/detections.csv",
                commit_message=args.commit_message,
            )

        retry("upload_csv", 3, 5.0, upload_csv)

    print()
    print("Upload complete.")
    print(f"Dataset URL: https://huggingface.co/datasets/{args.repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())