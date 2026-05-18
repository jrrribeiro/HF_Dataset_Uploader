from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from .config import AUDIO_EXTENSIONS
from .hash_utils import compute_file_hash

class LocalScanner:
    """Scan local directories and group files by inferred species."""

    def scan_folder(
        self,
        folder_path: str,
        *,
        include_hashes: bool = False,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        root_path = Path(folder_path).resolve()
        by_species: dict[str, list[dict[str, Any]]] = {}
        total_files = 0
        total_size = 0

        all_files: list[Path] = []
        for root, _, files in os.walk(root_path):
            current_root = Path(root)
            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in AUDIO_EXTENSIONS:
                    all_files.append(current_root / filename)

        total_candidates = len(all_files)
        if progress_callback:
            progress_callback(0.0, f"Scanning {total_candidates} audio files")

        for index, full_path in enumerate(all_files, start=1):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Upload cancelled")

            relative_path = full_path.relative_to(root_path)
            species = self._infer_species(root_path, full_path)
            item = {
                "name": full_path.name,
                "full_path": str(full_path),
                "relative_path": relative_path.as_posix(),
                "species": species,
                "size": full_path.stat().st_size,
            }
            if include_hashes:
                item["sha256"] = compute_file_hash(full_path)
            by_species.setdefault(species, []).append(item)
            total_files += 1
            total_size += item["size"]

            if progress_callback and (index == total_candidates or index % 25 == 0):
                progress_callback(index / max(total_candidates, 1), f"Scanning files: {index}/{total_candidates}")

        return {
            "total_files": total_files,
            "total_size": total_size,
            "by_species": by_species,
            "root_path": str(root_path),
        }

    def _infer_species(self, root_path: Path, file_path: Path) -> str:
        try:
            relative_parts = file_path.relative_to(root_path).parts
        except ValueError:
            relative_parts = file_path.parts

        if len(relative_parts) >= 2:
            return relative_parts[0]

        if len(relative_parts) == 1:
            return Path(relative_parts[0]).stem.split("_")[0] or "unknown"

        stem = file_path.stem
        return stem.split("_")[0] if "_" in stem else "unknown"