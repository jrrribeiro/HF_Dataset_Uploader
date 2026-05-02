import time
from pathlib import Path

from src.cache.ephemeral_cache_manager import EphemeralCacheManager


def test_put_and_get_bytes(tmp_path: Path) -> None:
    cache = EphemeralCacheManager(cache_dir=str(tmp_path), ttl_seconds=60, max_files=10)

    stored = cache.put_bytes("k1", b"hello", suffix=".wav")
    loaded = cache.get("k1")

    assert stored.exists()
    assert loaded is not None
    assert loaded.read_bytes() == b"hello"


def test_cleanup_key_removes_entry_and_file(tmp_path: Path) -> None:
    cache = EphemeralCacheManager(cache_dir=str(tmp_path), ttl_seconds=60, max_files=10)
    stored = cache.put_bytes("k1", b"abc")

    cache.cleanup_key("k1")

    assert cache.get("k1") is None
    assert not stored.exists()


def test_cleanup_expired_removes_old_files(tmp_path: Path) -> None:
    cache = EphemeralCacheManager(cache_dir=str(tmp_path), ttl_seconds=1, max_files=10)
    _ = cache.put_bytes("k1", b"abc")

    time.sleep(1.2)
    cache.cleanup_expired()

    assert cache.get("k1") is None


def test_capacity_eviction_removes_oldest(tmp_path: Path) -> None:
    cache = EphemeralCacheManager(cache_dir=str(tmp_path), ttl_seconds=60, max_files=1)
    first = cache.put_bytes("k1", b"1")
    _ = cache.put_bytes("k2", b"2")

    assert cache.get("k1") is None
    assert not first.exists()
    assert cache.get("k2") is not None
