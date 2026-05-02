from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a BirdNET uploader release bundle to Hugging Face")
    parser.add_argument("--repo-id", required=True, help="Target Hugging Face repo id, e.g. user/releases")
    parser.add_argument("--repo-type", default="dataset", choices=["dataset", "model", "space"])
    parser.add_argument("--bundle", required=True, type=Path, help="Path to the release zip bundle")
    parser.add_argument("--checksum", required=True, type=Path, help="Path to the checksum file")
    parser.add_argument("--version", required=True, help="Release version, e.g. 0.1.0")
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is required")

    if not args.bundle.exists():
        raise SystemExit(f"Bundle not found: {args.bundle}")
    if not args.checksum.exists():
        raise SystemExit(f"Checksum not found: {args.checksum}")

    api = HfApi(token=token)
    api.create_repo(repo_id=args.repo_id, repo_type=args.repo_type, exist_ok=True)

    release_prefix = f"releases/v{args.version}"
    uploads = [
        (args.bundle, f"{release_prefix}/{args.bundle.name}"),
        (args.checksum, f"{release_prefix}/{args.checksum.name}"),
    ]

    for source_path, path_in_repo in uploads:
        api.upload_file(
            path_or_fileobj=str(source_path),
            path_in_repo=path_in_repo,
            repo_id=args.repo_id,
            repo_type=args.repo_type,
        )

    print(f"Uploaded release artifacts to {args.repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
