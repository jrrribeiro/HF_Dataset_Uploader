from __future__ import annotations

import hashlib
from pathlib import Path


def compute_file_hash(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
	"""Compute a streaming SHA-256 hash for a file."""
	digest = hashlib.sha256()
	file_path = Path(path)

	with file_path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(chunk_size), b""):
			digest.update(chunk)

	return digest.hexdigest()


def verify_file_integrity(path: str | Path, expected_hash: str, *, chunk_size: int = 1024 * 1024) -> bool:
	"""Return True when a file's SHA-256 matches the expected hash."""
	return compute_file_hash(path, chunk_size=chunk_size) == expected_hash
