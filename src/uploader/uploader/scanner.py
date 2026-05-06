from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import AUDIO_EXTENSIONS
from .hash_utils import compute_file_hash


class LocalScanner:
	"""Scan local directories and group files by inferred species."""

	def scan_folder(self, folder_path: str) -> dict[str, Any]:
		root_path = Path(folder_path).resolve()
		by_species: dict[str, list[dict[str, Any]]] = {}
		total_files = 0
		total_size = 0

		for root, _, files in os.walk(root_path):
			current_root = Path(root)
			for filename in files:
				ext = Path(filename).suffix.lower()
				if ext not in AUDIO_EXTENSIONS:
					continue

				full_path = current_root / filename
				relative_path = full_path.relative_to(root_path)
				species = self._infer_species(root_path, full_path)
				item = {
					"name": filename,
					"full_path": str(full_path),
					"relative_path": relative_path.as_posix(),
					"species": species,
					"size": full_path.stat().st_size,
					"sha256": compute_file_hash(full_path),
				}
				by_species.setdefault(species, []).append(item)
				total_files += 1
				total_size += item["size"]

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
