from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "app.py"
DIST = ROOT / "dist"

def main():
    if not ENTRY.exists():
        print("Entrypoint app.py not found; aborting.")
        raise SystemExit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--noconfirm",
        "--name",
        "birdnet-uploader",
        str(ENTRY),
    ]

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("Build finished. See dist/ for output.")


if __name__ == "__main__":
    main()
