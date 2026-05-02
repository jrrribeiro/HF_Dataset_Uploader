from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
RELEASE_ROOT = BUILD_DIR / "release"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def clean_release_dirs() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    pycache = PROJECT_ROOT / "build" / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)


def build_executable() -> Path:
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(BUILD_DIR / "pyinstaller_uploader.spec")])
    exe_path = DIST_DIR / "birdnet-uploader" / ("birdnet-uploader.exe" if sys.platform.startswith("win") else "birdnet-uploader")
    if not exe_path.exists():
        raise FileNotFoundError(f"Expected executable not found: {exe_path}")
    return exe_path


def make_release_bundle(executable_path: Path, version: str) -> tuple[Path, Path]:
    bundle_name = f"birdnet-uploader-{version}-{'windows' if sys.platform.startswith('win') else 'linux'}.zip"
    bundle_path = RELEASE_ROOT / bundle_name
    sha256_path = RELEASE_ROOT / f"{bundle_name}.sha256"

    # PyInstaller is configured as one-folder build, so zip the whole folder,
    # not only the executable, otherwise runtime DLLs (_internal) are missing.
    app_dir = executable_path.parent
    dist_root = app_dir.parent

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in app_dir.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(dist_root)))

    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    sha256_path.write_text(f"{digest}  {bundle_name}\n", encoding="utf-8")
    return bundle_path, sha256_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a release bundle for BirdNET uploader")
    parser.add_argument("--version", required=True, help="Release version, e.g. 0.1.0")
    args = parser.parse_args()

    clean_release_dirs()
    executable_path = build_executable()
    bundle_path, sha256_path = make_release_bundle(executable_path, args.version)
    print(f"Release bundle: {bundle_path}")
    print(f"Checksum file: {sha256_path}")
    print(f"Built at: {datetime.now(UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
