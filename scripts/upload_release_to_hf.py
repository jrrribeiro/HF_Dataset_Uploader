#!/usr/bin/env python3
"""
Upload Windows portable release to Hugging Face Dataset.

Usage:
    python scripts/upload_release_to_hf.py \
        --repo-id jrrribeiro/birdnet-uploader-releases \
        --version 1.0.0
"""

import argparse
import hashlib
import os
from pathlib import Path
from huggingface_hub import HfApi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = PROJECT_ROOT / "build" / "release"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def upload_release(repo_id: str, version: str, token: str = None) -> None:
    """Upload release files to Hugging Face."""
    
    api = HfApi(token=token) if token else HfApi()
    
    # Find the release files
    zip_file = RELEASE_DIR / f"birdnet-uploader-{version}-windows.zip"
    
    if not zip_file.exists():
        raise FileNotFoundError(f"Release file not found: {zip_file}")
    
    print(f"📦 Uploading: {zip_file.name}")
    print(f"   Size: {zip_file.stat().st_size / (1024**3):.2f} GB")
    
    # Compute checksum
    checksum = compute_sha256(zip_file)
    print(f"   SHA256: {checksum}")
    
    # Create remote path: releases/v{version}/
    remote_base = f"releases/v{version}"
    remote_zip_path = f"{remote_base}/{zip_file.name}"
    remote_checksum_path = f"{remote_base}/{zip_file.name}.sha256"
    
    try:
        # Upload zip file
        print(f"\n📤 Uploading to {repo_id}/{remote_zip_path}...")
        api.upload_file(
            path_or_fileobj=str(zip_file),
            path_in_repo=remote_zip_path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Release {version} - Windows portable",
        )
        print("✅ ZIP uploaded successfully")
        
        # Upload checksum file
        print(f"\n📤 Uploading checksum to {repo_id}/{remote_checksum_path}...")
        checksum_content = f"{checksum}  {zip_file.name}\n"
        api.upload_file(
            path_or_fileobj=checksum_content.encode(),
            path_in_repo=remote_checksum_path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Release {version} - Checksum",
        )
        print("✅ Checksum uploaded successfully")
        
        # Print download URLs
        print(f"\n🎉 Release uploaded successfully!")
        print(f"\n📥 Download URLs:")
        print(f"   ZIP: https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_zip_path}")
        print(f"   SHA256: https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_checksum_path}")
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Upload Windows portable release to Hugging Face"
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Hugging Face dataset repo ID (format: owner/dataset-name)",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version (e.g., 1.0.0)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("HF_TOKEN"),
        help="Hugging Face API token (can also set HF_TOKEN env var)",
    )
    
    args = parser.parse_args()
    
    if not args.token:
        print("⚠️  HF_TOKEN not found. Using public access.")
        print("   To upload, set HF_TOKEN environment variable.")
        print("   Get your token from: https://huggingface.co/settings/tokens")
    
    upload_release(args.repo_id, args.version, args.token)


if __name__ == "__main__":
    main()
