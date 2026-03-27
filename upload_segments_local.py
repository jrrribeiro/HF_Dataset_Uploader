#!/usr/bin/env python3
"""
Simple CLI to upload segments folder to HF dataset locally.
Usage: python upload_segments_local.py <segments_folder> <dataset_repo> [--token TOKEN]

Example:
  python upload_segments_local.py "C:\\path\\to\\BirdNET Segments" username/ppbio-dataset
  python upload_segments_local.py "/Volumes/path/to/segments" org/dataset-repo --token hf_12345abcde
"""

import argparse
import sys
from pathlib import Path

from huggingface_hub import HfApi

from cli.hf_dataset_cli import upload_segments_to_hf


def main():
    parser = argparse.ArgumentParser(
        description="Upload BirdNET segments folder to Hugging Face dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("segments_folder", help="Path to segments root folder")
    parser.add_argument("dataset_repo", help="Target dataset repo (owner/repo)")
    parser.add_argument("--token", default=None, help="HF token (optional)")
    parser.add_argument("--batch-size", type=int, default=50, help="Upload batch size")

    args = parser.parse_args()

    segments_path = Path(args.segments_folder)
    if not segments_path.exists() or not segments_path.is_dir():
        print(f"❌ Segments folder not found: {segments_folder}")
        return 1

    if "/" not in args.dataset_repo:
        print(f"❌ Invalid dataset repo format. Use: owner/repo-name")
        return 1

    try:
        api = HfApi(token=args.token)
        project_slug = args.dataset_repo.split("/")[1].replace("-dataset", "")
        
        print(f"📤 Starting upload...")
        print(f"   Segments: {segments_path}")
        print(f"   Dataset:  {args.dataset_repo}")
        print(f"   Project:  {project_slug}")
        print()

        result = upload_segments_to_hf(
            api=api,
            project_slug=project_slug,
            dataset_repo=args.dataset_repo,
            segments_root=str(segments_path),
            batch_size=args.batch_size,
        )

        print()
        print(f"✅ Upload complete!")
        print(f"   Total files: {result['total_files']}")
        print(f"   Uploaded:    {result['uploaded']}")
        print(f"   Failed:      {result['failed']}")
        
        return 0 if result["failed"] == 0 else 1

    except Exception as exc:
        print(f"❌ Upload failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
