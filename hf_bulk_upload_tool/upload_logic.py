#!/usr/bin/env python3
"""
Upload logic refactored for GUI integration.
This module contains the core upload functionality extracted from upload_dataset.py
and refactored to accept a config dict and a logger callback instead of argparse.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import shutil
import subprocess
import time
import contextlib
from pathlib import Path
import concurrent.futures
from typing import List, Tuple, Callable, Optional
import json
import csv
from datetime import datetime
from urllib.parse import quote

try:
    import requests
except Exception:
    requests = None
try:
    from tqdm import tqdm
except Exception:
    tqdm = None

try:
    from sharding_utils import shard_directory, MAX_FILES_PER_DIR
    from progress_bar_utils import ProgressFilter, FilesProgressBar
except ImportError:
    # Fallback for relative imports during development
    from .sharding_utils import shard_directory, MAX_FILES_PER_DIR
    from .progress_bar_utils import ProgressFilter, FilesProgressBar


def configure_hf_env() -> None:
    """Configure Hugging Face environment variables."""
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")


configure_hf_env()


def _ensure_std_streams() -> None:
    """Ensure std streams exist in windowed/frozen runs.

    In PyInstaller windowed mode, sys.stderr/sys.stdout may be None.
    Some libraries (including logging handlers inside huggingface_hub flow)
    expect writable streams and crash otherwise.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


_ensure_std_streams()

from huggingface_hub import HfApi


class _CallbackWriter(io.TextIOBase):
    """File-like writer that forwards complete lines to a callback logger."""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback
        self._buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._callback(line)
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            self._callback(self._buffer.strip())
        self._buffer = ""


class RateLimiter:
    """Sliding window rate limiter for HF API (1000 requests per 5 minutes)."""
    def __init__(self, max_requests: int = 1000, window_seconds: int = 300):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_times: list[tuple[float, str]] = []
    
    def acquire(self, request_type: str = "upload") -> None:
        """Wait if necessary to stay within rate limits, then register the request."""
        now = time.time()
        
        self.request_times = [
            (ts, req_type) for ts, req_type in self.request_times
            if now - ts < self.window_seconds
        ]
        
        if len(self.request_times) >= self.max_requests:
            oldest_ts = self.request_times[0][0]
            wait_time = (oldest_ts + self.window_seconds) - now
            if wait_time > 0:
                time.sleep(wait_time)
                self.request_times = []
        
        self.request_times.append((now, request_type))
    
    def get_window_usage(self) -> tuple[int, int]:
        """Return (requests_in_window, max_requests)."""
        now = time.time()
        self.request_times = [
            (ts, req_type) for ts, req_type in self.request_times
            if now - ts < self.window_seconds
        ]
        return len(self.request_times), self.max_requests


def ensure_directory_link(link_path: Path, target_path: Path) -> None:
    """Create a directory link (Windows junction or Unix symlink)."""
    if link_path.exists() or link_path.is_symlink():
        try:
            if link_path.resolve() == target_path.resolve():
                return
        except Exception:
            pass
        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        else:
            shutil.rmtree(link_path)

    link_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
                check=True,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except Exception:
            pass

    os.symlink(target_path, link_path, target_is_directory=True)


def prepare_staging_folder(staging_root: Path, segments_path: Path, csv_path: Path | None) -> Path:
    """Build a persistent staging tree with the repo layout expected by HF."""
    staging_root.mkdir(parents=True, exist_ok=True)

    audio_link = staging_root / "audio"
    ensure_directory_link(audio_link, segments_path)

    if csv_path is not None:
        csv_dest = staging_root / "index" / "detections.csv"
        csv_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(csv_path, csv_dest)

    return staging_root


def _inventory_cache_path(checkpoint_dir: Path, segments_path: Path) -> Path:
    """Return cache file path for local inventory of a segments directory."""
    key = hashlib.sha1(str(segments_path).encode("utf-8")).hexdigest()[:12]
    return checkpoint_dir / f"inventory_{key}.json"


def _scan_species_dir(species_dir: Path) -> tuple[int, int]:
    """Scan one species directory and return (file_count, total_bytes)."""
    count = 0
    total_bytes = 0
    for p in species_dir.rglob("*"):
        if p.is_file():
            count += 1
            try:
                total_bytes += p.stat().st_size
            except Exception:
                pass
    return count, total_bytes


def _build_species_inventory(segments_path: Path, checkpoint_dir: Path, logger: Callable[[str], None]) -> list[dict]:
    """Build per-species inventory with lightweight persistent cache.

    Cache key is based on top-level species folder mtime. If folder mtime changed,
    species is rescanned. This preserves correctness while avoiding repeated full scans
    across reruns.
    """
    cache_path = _inventory_cache_path(checkpoint_dir, segments_path)
    cached_species: dict = {}

    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            cached_species = payload.get("species", {}) if isinstance(payload, dict) else {}
        except Exception:
            cached_species = {}

    inventory: list[dict] = []
    cache_hits = 0
    total_species = 0
    new_cache_species: dict = {}

    for species_dir in sorted(segments_path.iterdir()):
        if not species_dir.is_dir():
            continue
        total_species += 1
        species_name = species_dir.name
        try:
            mtime_ns = species_dir.stat().st_mtime_ns
        except Exception:
            mtime_ns = 0

        cached = cached_species.get(species_name)
        if isinstance(cached, dict) and int(cached.get("mtime_ns", -1)) == int(mtime_ns):
            file_count = int(cached.get("file_count", 0))
            total_bytes = int(cached.get("total_bytes", 0))
            cache_hits += 1
        else:
            file_count, total_bytes = _scan_species_dir(species_dir)

        entry = {
            "species_name": species_name,
            "path": species_dir,
            "file_count": file_count,
            "total_bytes": total_bytes,
            "mtime_ns": int(mtime_ns),
        }
        inventory.append(entry)

        new_cache_species[species_name] = {
            "mtime_ns": int(mtime_ns),
            "file_count": int(file_count),
            "total_bytes": int(total_bytes),
        }

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "segments_root": str(segments_path),
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "species": new_cache_species,
                },
                fh,
                indent=2,
            )
    except Exception as e:
        logger(f"Warning: failed to save inventory cache {cache_path}: {e}")

    logger(f"[Scan] Species inventory cache hit: {cache_hits}/{total_species}")
    return inventory


def _prepare_sharded_staging(
    staging_root: Path,
    segments_path: Path,
    csv_path: Path | None,
    logger: Callable[[str], None],
    inventory: list[dict] | None = None,
) -> Path:
    """Prepare staging folder with automatic sharding for large species directories.
    
    Detects species folders with >9500 files and automatically shards them into
    numbered subdirectories to comply with HF's 10k files per directory limit.
    Validation tools can transparently read shards via sharding_utils.
    
    Args:
        staging_root: Root directory for staging
        segments_path: Path to source segments (species directories)
        csv_path: Optional path to CSV to copy
        logger: Callback function for logging messages
    
    Returns:
        Path to the prepared staging root directory
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    audio_staging = staging_root / "audio"
    audio_staging.mkdir(parents=True, exist_ok=True)
    
    sharded_species = []
    
    # Check each species folder for sharding using precomputed inventory when available
    source_items = inventory
    if source_items is None:
        source_items = []
        for species_dir in sorted(segments_path.iterdir()):
            if species_dir.is_dir():
                source_items.append(
                    {
                        "species_name": species_dir.name,
                        "path": species_dir,
                        "file_count": 0,
                    }
                )

    for item in source_items:
        species_dir = Path(item["path"])
        file_count = int(item.get("file_count", 0))

        if file_count > MAX_FILES_PER_DIR:
            # Need to shard this species
            logger(f"[Sharding] {species_dir.name} exceeds {MAX_FILES_PER_DIR} files, dividing into shards...")
            try:
                shards = shard_directory(species_dir, audio_staging)
                sharded_species.append((species_dir.name, len(shards)))
                logger(f"[Sharding] Created {len(shards)} shards for {species_dir.name}")
            except Exception as e:
                logger(f"[Sharding] ERROR sharding {species_dir.name}: {e}")
                logger(f"[Sharding] Falling back to single directory link")
                ensure_directory_link(audio_staging / species_dir.name, species_dir)
        else:
            # Small species, just link it
            ensure_directory_link(audio_staging / species_dir.name, species_dir)
    
    # Log sharding summary
    if sharded_species:
        logger(f"")
        logger(f"[Sharding] Summary: {len(sharded_species)} species were divided")
        for species_name, num_shards in sharded_species:
            logger(f"  - {species_name}: {num_shards} shards")
        logger(f"[Sharding] Validation tools will transparently read all shards as single species")
        logger(f"")
    
    # Copy CSV if provided
    if csv_path is not None:
        csv_dest = staging_root / "index" / "detections.csv"
        csv_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(csv_path, csv_dest)
    
    return staging_root


def retry_call(label: str, attempts: int, backoff: float, func, logger: Callable[[str], None], stop_event=None):
    """Execute a function with retry logic, logging via callback."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        # If cancellation requested, abort immediately
        try:
            if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                raise Exception(f"{label} cancelled by user")
        except Exception:
            raise
        try:
            logger(f"[{label}] attempt {attempt}/{attempts}")
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            
            wait_seconds = backoff * attempt
            try:
                resp = getattr(exc, 'response', None)
                if resp is not None:
                    status = getattr(resp, 'status_code', None)
                    if status == 429:
                        ra = resp.headers.get('Retry-After') if hasattr(resp, 'headers') else None
                        if ra:
                            try:
                                wait_seconds = max(wait_seconds, int(ra))
                            except Exception:
                                wait_seconds = max(wait_seconds, backoff * attempt * 4)
                        else:
                            wait_seconds = max(wait_seconds, backoff * attempt * 4)
                elif '429' in str(exc) or 'Too Many Requests' in str(exc):
                    wait_seconds = max(wait_seconds, backoff * attempt * 4)
            except Exception:
                pass
            
            logger(f"[{label}] attempt {attempt} failed: {exc}")
            logger(f"[{label}] retrying in {wait_seconds:.0f}s")
            time.sleep(wait_seconds)

    raise Exception(f"{label} failed after {attempts} attempts: {last_error}")


def run_upload_logic(config: dict, logger: Callable[[str], None]) -> int:
    """
    Core upload logic refactored for GUI integration.
    
    Args:
        config: Dictionary with keys:
            - hf_token: str (required)
            - repo_id: str (required, format: "username/repo-name")
            - segments: str or Path (required, directory with audio files)
            - csv: str or Path (optional, path to CSV file)
            - segments_path_in_repo: str (default: "audio")
            - csv_path_in_repo: str (default: "index/detections.csv")
            - private: bool (default: True)
            - resume: bool (default: False)
            - verify_remote: bool (default: False)
            - verify_etag: bool (default: False)
            - dry_run: bool (default: False)
            - rate_limit_aware: bool (default: True)
            - rate_limit_max_requests: int (default: 950)
            - rate_limit_window: int (default: 300)
            - create_repo_attempts: int (default: 3)
            - upload_attempts: int (default: 3)
            - retry_backoff: float (default: 5.0)
            - max_workers: int (default: 1)
            - checkpoint_dir: str or Path (default: .checkpoints)
            - commit_message: str (default: "Upload BirdNET segments")
        
        logger: Callable that accepts a string message (for GUI textbox updates)
    
    Returns:
        0 on success, raises Exception on failure
    """
    
    # Extract and validate config
    token = config.get("hf_token")
    if not token:
        raise ValueError("hf_token is required")
    
    repo_id = config.get("repo_id")
    if not repo_id:
        raise ValueError("repo_id is required")
    
    segments = config.get("segments")
    if not segments:
        raise ValueError("segments is required")
    
    segments_path = Path(segments).expanduser().resolve()
    if not segments_path.is_dir():
        raise ValueError(f"Segments path does not exist or is not a directory: {segments_path}")
    
    csv_path = None
    if config.get("csv"):
        csv_path = Path(config.get("csv")).expanduser().resolve()
        if not csv_path.is_file():
            raise ValueError(f"CSV path does not exist or is not a file: {csv_path}")
    
    # Config parameters
    segments_path_in_repo = config.get("segments_path_in_repo", "audio")
    csv_path_in_repo = config.get("csv_path_in_repo", "index/detections.csv")
    is_private = config.get("private", True)
    resume = config.get("resume", False)
    verify_remote = config.get("verify_remote", False)
    verify_etag = config.get("verify_etag", False)
    dry_run = config.get("dry_run", False)
    rate_limit_aware = config.get("rate_limit_aware", True)
    rate_limit_max_requests = config.get("rate_limit_max_requests", 950)
    rate_limit_window = config.get("rate_limit_window", 300)
    create_repo_attempts = config.get("create_repo_attempts", 3)
    upload_attempts = config.get("upload_attempts", 3)
    retry_backoff = config.get("retry_backoff", 5.0)
    max_workers = config.get("max_workers", 1)
    checkpoint_dir = Path(config.get("checkpoint_dir", Path(__file__).parent / ".checkpoints"))
    commit_message = config.get("commit_message", "Upload BirdNET segments")
    
    # Log configuration
    logger(f"Repository: {repo_id}")
    logger(f"Segments: {segments_path}")
    logger(f"Segments destination: {segments_path_in_repo}")
    
    csv_uploaded_with_segments = False
    if csv_path and not csv_uploaded_with_segments:
        logger(f"CSV: {csv_path}")
        logger(f"CSV destination: {csv_path_in_repo}")
    
    logger(f"Visibility: {'private' if is_private else 'public'}")
    
    if dry_run:
        logger("Dry run selected. No network calls will be made.")
        return 0

    # Cancellation event (optional). GUI should pass a threading.Event via config['stop_event']
    stop_event = config.get('stop_event')
    # Suppress console progress (GUI mode): when True, do not create tqdm bars
    suppress_console = config.get('suppress_console_progress', False)
    
    api = HfApi(token=token)
    
    # Initialize rate limiter
    rate_limiter = None
    if rate_limit_aware:
        rate_limiter = RateLimiter(max_requests=rate_limit_max_requests, window_seconds=rate_limit_window)
        logger(f"[RateLimit] Enabled: max {rate_limit_max_requests} requests per {rate_limit_window}s")
    
    def list_existing_files() -> set:
        try:
            logger("Listing files in target repo to determine already-uploaded files...")
            if rate_limiter:
                rate_limiter.acquire("list_repo_files")
            files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
            return set(files or [])
        except Exception as e:
            logger(f"Warning: could not list repo files: {e}")
            return set()
    
    # Checkpoint management
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"{repo_id.replace('/', '__')}.json"
    progress_log_path = checkpoint_dir / 'progress.csv'
    
    def load_checkpoint() -> tuple[set, dict[str, str]]:
        if not checkpoint_file.exists():
            return set(), {}
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return set(data), {}
            uploaded = set(data.get('uploaded', []))
            file_hashes = data.get('file_hashes', {})
            if not isinstance(file_hashes, dict):
                file_hashes = {}
            return uploaded, {str(k): str(v) for k, v in file_hashes.items()}
        except Exception as e:
            logger(f"Warning: failed to load checkpoint {checkpoint_file}: {e}")
            return set(), {}
    
    def save_checkpoint(uploaded_set: set, file_hashes: dict[str, str]) -> None:
        try:
            with open(checkpoint_file, 'w', encoding='utf-8') as fh:
                json.dump({'uploaded': sorted(list(uploaded_set)), 'file_hashes': file_hashes}, fh, indent=2)
        except Exception as e:
            logger(f"Warning: failed to save checkpoint {checkpoint_file}: {e}")
    
    def compute_sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    
    def remote_file_info(repo_path: str) -> Tuple[int | None, str | None]:
        """Return (size, etag) for a repo file via HTTP HEAD, or (None, None)."""
        if requests is None:
            return None, None
        quoted = '/'.join(quote(p) for p in repo_path.split('/'))
        url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{quoted}"
        try:
            r = requests.head(url, allow_redirects=True, timeout=10)
            if r.status_code >= 400:
                return None, None
            cl = r.headers.get('content-length')
            etag = r.headers.get('etag')
            size = int(cl) if cl is not None else None
            return size, etag
        except Exception:
            return None, None
    
    def append_progress(local_path: Path | None, repo_path: str, status: str, msg: str | None = None, elapsed: float | None = None) -> None:
        header = ['timestamp','local_path','repo_path','status','message','elapsed_seconds']
        row = [time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), str(local_path) if local_path else '', repo_path, status, (msg or '').replace('\n',' '), f"{elapsed:.2f}" if elapsed is not None else '']
        write_header = not progress_log_path.exists()
        try:
            with open(progress_log_path, 'a', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh)
                if write_header:
                    writer.writerow(header)
                writer.writerow(row)
        except Exception as e:
            logger(f"Warning: failed to write progress log {progress_log_path}: {e}")
    
    run_stats = {
        'planned': 0,
        'skipped': 0,
        'uploaded': 0,
        'failed': 0,
        'bytes_planned': 0,
        'bytes_uploaded': 0,
        'started_at': time.time(),
    }
    
    def record_summary() -> None:
        elapsed = time.time() - run_stats['started_at']
        summary_message = (
            f"planned={run_stats['planned']} skipped={run_stats['skipped']} "
            f"uploaded={run_stats['uploaded']} failed={run_stats['failed']} "
            f"bytes_planned={run_stats['bytes_planned']} bytes_uploaded={run_stats['bytes_uploaded']}"
        )
        append_progress(None, '', 'summary', summary_message, elapsed)
        try:
            summary_json = checkpoint_dir / f"{repo_id.replace('/', '__')}.summary.json"
            with open(summary_json, 'w', encoding='utf-8') as fh:
                json.dump({
                    'repo_id': repo_id,
                    'planned': run_stats['planned'],
                    'skipped': run_stats['skipped'],
                    'uploaded': run_stats['uploaded'],
                    'failed': run_stats['failed'],
                    'bytes_planned': run_stats['bytes_planned'],
                    'bytes_uploaded': run_stats['bytes_uploaded'],
                    'elapsed_seconds': round(elapsed, 2),
                }, fh, indent=2)
        except Exception as e:
            logger(f"Warning: failed to write summary json: {e}")
    
    # Create repo
    def create_repo() -> None:
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=is_private, exist_ok=True)
    
    # Create repo (with retry and cancellation support)
    retry_call("create_repo", create_repo_attempts, retry_backoff, create_repo, logger, stop_event)
    
    # Load checkpoints
    existing_files: set = set()
    checkpoint_uploaded: set = set()
    checkpoint_hashes: dict[str, str] = {}
    existing_files_loaded = False
    if resume:
        checkpoint_uploaded, checkpoint_hashes = load_checkpoint()
    
    already_uploaded = existing_files.union(checkpoint_uploaded)

    def ensure_existing_files_loaded() -> None:
        nonlocal existing_files_loaded, existing_files, already_uploaded
        if not resume or existing_files_loaded:
            return
        existing_files = list_existing_files()
        existing_files_loaded = True
        already_uploaded = existing_files.union(checkpoint_uploaded)
    
    def upload_segments() -> None:
        nonlocal csv_uploaded_with_segments
        
        if hasattr(api, "upload_large_folder"):
            staging_root = checkpoint_dir / "staging" / repo_id.replace("/", "__")
            logger(f"Preparing persistent staging folder at {staging_root} ...")
            logger(f"Checking for large species directories that need sharding...\n")
            inventory = _build_species_inventory(segments_path, checkpoint_dir, logger)
            staged_root = _prepare_sharded_staging(staging_root, segments_path, csv_path, logger, inventory=inventory)

            total_files = sum(int(item.get("file_count", 0)) for item in inventory)
            total_bytes = sum(int(item.get("total_bytes", 0)) for item in inventory)
            if csv_path is not None:
                total_files += 1
                try:
                    total_bytes += csv_path.stat().st_size
                except Exception:
                    pass
            
            logger(f"Found {total_files} staged files to upload with upload_large_folder()")
            
            kwargs = {
                "folder_path": str(staged_root),
                "repo_id": repo_id,
                "repo_type": "dataset",
                "private": is_private,
                "num_workers": max(1, max_workers),
                # Keep HF periodic reports disabled; GUI receives compact status via ProgressFilter.
                "print_report": False,
            }
            
            def _run_upload():
                # Create progress bar and filter
                if tqdm is not None and not suppress_console:
                    pbar = tqdm(total=total_files, unit="file", unit_scale=False, desc="Uploading", leave=True)
                    filter_writer = ProgressFilter(pbar, logger)
                else:
                    pbar = None
                    filter_writer = ProgressFilter(None, logger)
                
                try:
                    if filter_writer:
                        with contextlib.redirect_stdout(filter_writer), contextlib.redirect_stderr(filter_writer):
                            retry_call("upload_large_folder", upload_attempts, retry_backoff, lambda: api.upload_large_folder(**kwargs), logger, stop_event)
                        filter_writer.flush()
                    else:
                        retry_call("upload_large_folder", upload_attempts, retry_backoff, lambda: api.upload_large_folder(**kwargs), logger, stop_event)
                finally:
                    if pbar:
                        try:
                            pbar.close()
                        except Exception:
                            pass
            
            try:
                # Check cancellation before starting heavy upload
                if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                    raise Exception("Upload cancelled by user before starting batch upload")
                _run_upload()
            except Exception as upload_exc:
                logger(f"upload_large_folder failed: {upload_exc}; falling back to per-file upload with throttling.")
            else:
                logger("upload_large_folder completed successfully.")
                run_stats['planned'] = total_files
                run_stats['bytes_planned'] = total_bytes
                run_stats['uploaded'] = total_files
                run_stats['bytes_uploaded'] = total_bytes
                csv_uploaded_with_segments = True
                return
        
        # Per-file fallback
        logger("Performing per-file upload (skipping already uploaded files if any)...")

        # Remote repo listing is only needed for per-file resume logic.
        ensure_existing_files_loaded()
        
        files: List[Tuple[Path, str]] = []
        for p in segments_path.rglob("*"):
            if p.is_file():
                rel = p.relative_to(segments_path).as_posix()
                repo_path = f"{segments_path_in_repo}/{rel}"
                run_stats['bytes_planned'] += p.stat().st_size
                skip = False
                if repo_path in already_uploaded:
                    checkpoint_hash = checkpoint_hashes.get(repo_path)
                    if checkpoint_hash:
                        local_hash = compute_sha256(p)
                        if local_hash != checkpoint_hash:
                            skip = False
                            logger(f"Hash mismatch for {repo_path}; will re-upload.")
                        else:
                            skip = True
                    elif verify_remote and requests is not None:
                        local_size = p.stat().st_size
                        if rate_limiter:
                            rate_limiter.acquire("verify_remote")
                        remote_size, remote_etag = remote_file_info(repo_path)
                        if verify_etag and remote_etag:
                            skip = (remote_size is not None and local_size == remote_size)
                        else:
                            skip = (remote_size is not None and local_size == remote_size)
                    else:
                        skip = True
                
                if skip:
                    run_stats['skipped'] += 1
                    append_progress(p, repo_path, 'skipped', 'already uploaded')
                    continue
                files.append((p, repo_path))
        
        run_stats['planned'] = len(files)
        logger(f"Found {len(files)} files to upload; launching {max_workers} workers")
        
        # Progress bar for per-file uploads (counts files, not bytes)
        file_pbar = FilesProgressBar(total_files=len(files), logger=logger, suppress_console=suppress_console)
        
        def upload_one(pair: Tuple[Path, str]):
            local_path, repo_path = pair
            start = time.time()
            try:
                def do_upload():
                    if rate_limiter:
                        rate_limiter.acquire("file_upload")
                    api.upload_file(
                        path_or_fileobj=str(local_path),
                        path_in_repo=repo_path,
                        repo_id=repo_id,
                        repo_type="dataset",
                        commit_message=commit_message,
                    )
                
                retry_call(f"upload_file:{repo_path}", upload_attempts, retry_backoff, do_upload, logger, stop_event)
            except Exception as e:
                elapsed = time.time() - start
                # Log error to CSV for tracking
                append_progress(local_path, repo_path, 'failed', str(e), elapsed)
                # Update progress bar with error
                file_pbar.update_file_error(1, f"{repo_path}: {str(e)[:60]}")
                raise
            else:
                elapsed = time.time() - start
                # Only log successful uploads to CSV (optional, can be verbose)
                # append_progress(local_path, repo_path, 'uploaded', None, elapsed)
                # Update progress bar
                file_pbar.update_file(1)
                return repo_path, local_path
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(upload_one, f) for f in files]
                for fut in concurrent.futures.as_completed(futures):
                    # Respect cancellation
                    if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                        logger("[Control] Cancellation requested; cancelling pending uploads...")
                        # Attempt to cancel pending futures
                        for f in futures:
                            try:
                                f.cancel()
                            except Exception:
                                pass
                        try:
                            ex.shutdown(wait=False, cancel_futures=True)
                        except Exception:
                            pass
                        raise Exception("Upload cancelled by user")

                    try:
                        repo_path, local_path = fut.result()
                    except Exception as e:
                        # Error already logged above, just continue
                        continue

                    if repo_path:
                        already_uploaded.add(repo_path)
                        try:
                            checkpoint_hashes[repo_path] = compute_sha256(local_path)
                        except Exception as e:
                            logger(f"Warning: failed to hash {repo_path} after upload: {e}")
                        run_stats['uploaded'] += 1
                        try:
                            run_stats['bytes_uploaded'] += Path(local_path).stat().st_size
                        except Exception:
                            pass
                        save_checkpoint(already_uploaded, checkpoint_hashes)
        finally:
            file_pbar.close()
            file_pbar.log_errors()
    
    retry_call("upload_segments", upload_attempts, retry_backoff, upload_segments, logger, stop_event)
    
    # Upload CSV if not already uploaded with segments
    if csv_path and not csv_uploaded_with_segments:
        def upload_csv() -> None:
            skip_csv = False
            if resume:
                ensure_existing_files_loaded()
            if resume and csv_path_in_repo in already_uploaded:
                if verify_remote and requests is not None:
                    local_size = csv_path.stat().st_size
                    if rate_limiter:
                        rate_limiter.acquire("verify_remote")
                    remote_size, remote_etag = remote_file_info(csv_path_in_repo)
                    if verify_etag and remote_etag:
                        if remote_size is not None and local_size == remote_size:
                            skip_csv = True
                    else:
                        if remote_size is not None and local_size == remote_size:
                            skip_csv = True
            
            if skip_csv:
                logger(f"CSV already exists at {csv_path_in_repo}; skipping upload.")
                run_stats['skipped'] += 1
                append_progress(csv_path, csv_path_in_repo, 'skipped', 'already uploaded')
                return
            
            start = time.time()
            try:
                if rate_limiter:
                    rate_limiter.acquire("csv_upload")
                api.upload_file(
                    path_or_fileobj=str(csv_path),
                    path_in_repo=csv_path_in_repo,
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"Upload CSV for {repo_id}",
                )
            except Exception as e:
                elapsed = time.time() - start
                run_stats['failed'] += 1
                append_progress(csv_path, csv_path_in_repo, 'failed', str(e), elapsed)
                raise
            else:
                elapsed = time.time() - start
                run_stats['uploaded'] += 1
                try:
                    run_stats['bytes_uploaded'] += csv_path.stat().st_size
                except Exception:
                    pass
                try:
                    checkpoint_hashes[csv_path_in_repo] = compute_sha256(csv_path)
                    save_checkpoint(already_uploaded.union({csv_path_in_repo}), checkpoint_hashes)
                except Exception as e:
                    logger(f"Warning: failed to update CSV checkpoint hash: {e}")
                append_progress(csv_path, csv_path_in_repo, 'uploaded', None, elapsed)
        
        retry_call("upload_csv", upload_attempts, retry_backoff, upload_csv, logger, stop_event)
    
    logger("")
    logger("Upload complete.")
    logger(f"Dataset URL: https://huggingface.co/datasets/{repo_id}")
    record_summary()
    
    return 0
