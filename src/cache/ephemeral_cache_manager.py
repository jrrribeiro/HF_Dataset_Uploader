import hashlib
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CacheEntry:
    key: str
    path: Path
    created_at: float
    expires_at: float
    size_bytes: int


class EphemeralCacheManager:
    def __init__(
        self,
        cache_dir: str | None = None,
        ttl_seconds: int = 300,
        max_files: int = 256,
    ) -> None:
        self._base_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "birdnet-validator-cache"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._ttl_seconds = ttl_seconds
        self._max_files = max_files
        self._entries: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Path | None:
        self.cleanup_expired()
        entry = self._entries.get(key)
        if not entry:
            return None
        if not entry.path.exists():
            self._entries.pop(key, None)
            return None
        return entry.path

    def put_bytes(self, key: str, data: bytes, suffix: str = ".bin") -> Path:
        self.cleanup_expired()
        self._enforce_capacity()

        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        file_path = self._base_dir / f"{digest}{suffix}"
        file_path.write_bytes(data)

        now = time.time()
        self._entries[key] = CacheEntry(
            key=key,
            path=file_path,
            created_at=now,
            expires_at=now + self._ttl_seconds,
            size_bytes=len(data),
        )
        return file_path

    def cleanup_key(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if not entry:
            return
        if entry.path.exists():
            entry.path.unlink()

    def cleanup_expired(self) -> None:
        now = time.time()
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now or not entry.path.exists()]
        for key in expired_keys:
            self.cleanup_key(key)

    def clear(self) -> None:
        for key in list(self._entries.keys()):
            self.cleanup_key(key)

    def _enforce_capacity(self) -> None:
        if len(self._entries) < self._max_files:
            return

        oldest_keys = sorted(self._entries.keys(), key=lambda key: self._entries[key].created_at)
        overflow = (len(self._entries) - self._max_files) + 1
        for key in oldest_keys[:overflow]:
            self.cleanup_key(key)
