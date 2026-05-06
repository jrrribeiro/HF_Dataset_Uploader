"""Build, test, and optionally publish BirdNET Uploader release."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = PROJECT_ROOT / "build"
RELEASE_DIR = BUILD_DIR / "release"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run command and optionally check for errors."""
    return subprocess.run(cmd, cwd=PROJECT_ROOT, check=check)


def build_release(version: str) -> tuple[Path, Path]:
    """Build release bundle and return (bundle_path, checksum_path)."""
    print(f"\n{'='*60}")
    print(f"Building release v{version}")
    print(f"{'='*60}")
    
    run([sys.executable, "build/release_uploader.py", "--version", version])
    
    bundle = next(RELEASE_DIR.glob("*.zip"), None)
    checksum = next(RELEASE_DIR.glob("*.sha256"), None)
    
    if not bundle or not checksum:
        raise FileNotFoundError("Release bundle or checksum not found")
    
    print(f"✓ Built: {bundle}")
    print(f"✓ Checksum: {checksum}")
    return bundle, checksum


def run_smoke_test() -> bool:
    """Run executable smoke test on Windows."""
    if sys.platform != "win32":
        print("⊘ Skipping smoke test (Windows only)")
        return True
    
    print(f"\n{'='*60}")
    print("Running smoke test")
    print(f"{'='*60}")
    
    exe = next((PROJECT_ROOT / "dist").rglob("birdnet-uploader.exe"), None)
    if not exe:
        print("ERROR: Executable not found")
        return False
    
    print(f"Testing executable: {exe}")
    
    # Test --help
    result = subprocess.run([str(exe), "--help"], check=False)
    if result.returncode != 0:
        print("ERROR: --help command failed")
        return False
    
    # Create dummy segments directory
    with tempfile.TemporaryDirectory() as tmpdir:
        segments = Path(tmpdir) / "segments"
        segments.mkdir()
        (segments / "dummy.wav").touch()
        
        # Test dry-run
        result = subprocess.run(
            [
                str(exe),
                "upload",
                "--repo-id", "test/repo",
                "--segments", str(segments),
                "--token", "hf_test_token_smoke_test",
                "--dry-run",
            ],
            check=False,
        )
        
        if result.returncode != 0:
            print("ERROR: Smoke test (dry-run) failed")
            return False
    
    print("✓ Smoke test passed")
    return True


def publish_to_hf(bundle: Path, checksum: Path, version: str, repo_id: str) -> bool:
    """Publish release to Hugging Face."""
    print(f"\n{'='*60}")
    print(f"Publishing to Hugging Face: {repo_id}")
    print(f"{'='*60}")
    
    result = run(
        [
            sys.executable,
            "build/publish_release_to_hf.py",
            "--repo-id", repo_id,
            "--bundle", str(bundle),
            "--checksum", str(checksum),
            "--version", version,
        ],
        check=False,
    )
    
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, test, and publish BirdNET Uploader",
        epilog="Example: python build/build_and_publish.py --version 0.2.0 --smoke-test"
    )
    parser.add_argument("--version", required=True, help="Release version (e.g., 0.2.0)")
    parser.add_argument("--smoke-test", action="store_true", help="Run smoke test after build")
    parser.add_argument("--publish", action="store_true", help="Publish to Hugging Face after build")
    parser.add_argument("--hf-repo", help="Hugging Face repo ID (required if --publish is set)")
    parser.add_argument("--clean", action="store_true", help="Clean dist/ and build/release/ before building")
    args = parser.parse_args()
    
    # Validate inputs
    if args.publish and not args.hf_repo:
        print("ERROR: --hf-repo is required when --publish is set")
        return 1
    
    # Clean if requested
    if args.clean:
        print("Cleaning previous builds...")
        for path in [PROJECT_ROOT / "dist", RELEASE_DIR]:
            if path.exists():
                shutil.rmtree(path)
    
    try:
        # Build release
        bundle, checksum = build_release(args.version)
        
        # Run smoke test if requested
        if args.smoke_test:
            if not run_smoke_test():
                return 1
        
        # Publish if requested
        if args.publish:
            if not publish_to_hf(bundle, checksum, args.version, args.hf_repo):
                return 1
        
        print(f"\n{'='*60}")
        print(f"✓ Build complete: v{args.version}")
        print(f"Bundle: {bundle}")
        print(f"Checksum: {checksum}")
        print(f"{'='*60}\n")
        
        return 0
        
    except Exception as exc:
        print(f"\nERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
