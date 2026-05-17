#!/usr/bin/env python3
"""
Progress bar management for HF uploads.

Replaces verbose per-file logs with a clean progress bar and filters
trivial messages while preserving errors and warnings.
"""

import re
import io
from typing import Callable, Optional
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


class ProgressFilter(io.TextIOBase):
    """
    Filters upload_large_folder() output to show only a progress bar.
    
    - Captures "Uploaded X of Y files" patterns
    - Updates tqdm progress bar
    - Filters trivial per-file logs
    - Preserves error/warning messages
    
    Usage:
        pbar = tqdm(total=total_files, unit="file", desc="Uploading", leave=True)
        filter = ProgressFilter(pbar, logger_callback)
        
        with contextlib.redirect_stdout(filter):
            api.upload_large_folder(...)
    """
    
    def __init__(self, pbar: 'tqdm', logger: Callable[[str], None]):
        """
        Args:
            pbar: tqdm progress bar instance
            logger: Callback function for important messages (errors, warnings)
        """
        super().__init__()
        self.pbar = pbar
        self.logger = logger
        self._buffer = ""
        self.last_reported_files = 0
        self.last_reported_bytes = 0
        self.last_metadata_files = 0
        self.last_gui_progress_pct = -1.0
        self.last_gui_metadata_pct = -1.0
    
    def write(self, s: str) -> int:
        """Process output line by line."""
        if not s:
            return 0
        
        self._buffer += s
        
        # Process complete lines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._process_line(line)
        
        return len(s)
    
    def flush(self) -> None:
        """Flush any remaining buffered content."""
        if self._buffer.strip():
            self._process_line(self._buffer)
            self._buffer = ""
    
    def _process_line(self, line: str) -> None:
        """Process a single line of output."""
        if not line.strip():
            return

        # Strip common ANSI cursor/control sequences emitted by progress renderers
        line = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', line)
        if not line.strip():
            return
        
        # Try to extract progress: "Uploaded X of Y files"
        progress_match = re.search(
            r'Uploaded\s+(\d+)\s+of\s+(\d+)\s+files',
            line,
            re.IGNORECASE
        )
        
        if progress_match:
            uploaded = int(progress_match.group(1))
            total = int(progress_match.group(2))
            
            # Update progress bar if new files since last report
            if uploaded > self.last_reported_files:
                increment = uploaded - self.last_reported_files
                if self.pbar:
                    try:
                        self.pbar.update(increment)
                    except Exception:
                        pass
                self.last_reported_files = uploaded
            
            # Update description with percentage
            if total > 0:
                pct = (uploaded / total) * 100
                # If we have a console tqdm bar, update it; otherwise emit concise progress to logger
                if self.pbar:
                    try:
                        self.pbar.set_description(f"Uploading ({pct:.1f}%)")
                    except Exception:
                        pass
                else:
                    if pct >= 100.0 or (pct - self.last_gui_progress_pct) >= 0.5:
                        self.last_gui_progress_pct = pct
                        try:
                            self.logger(f"[Progress] Uploading ({pct:.1f}%) {uploaded}/{total} files")
                        except Exception:
                            pass
            
            return  # Don't log this line

        # HF metadata recovery progress: keep only a single dynamic line in GUI
        metadata_match = re.search(
            r'Recovering\s+from\s+metadata\s+files:.*?(\d+)\/(\d+)',
            line,
            re.IGNORECASE,
        )
        if metadata_match:
            current = int(metadata_match.group(1))
            total = int(metadata_match.group(2))
            if current >= self.last_metadata_files:
                self.last_metadata_files = current
                pct = (current / total) * 100 if total > 0 else 0.0
                if pct >= 100.0 or (pct - self.last_gui_metadata_pct) >= 0.5:
                    self.last_gui_metadata_pct = pct
                    self.logger(f"[Progress] Metadata recovery ({pct:.1f}%) {current}/{total}")
            return

        # HF periodic report blocks are useful but very noisy in GUI: compress to one status line.
        files_report = re.search(
            r'Files:\s+hashed\s+(\d+)\/(\d+).*?committed:\s+(\d+)\/(\d+)',
            line,
            re.IGNORECASE,
        )
        if files_report:
            hashed = int(files_report.group(1))
            total = int(files_report.group(2))
            committed = int(files_report.group(3))
            self.logger(f"[Status] Hashed {hashed}/{total} | Committed {committed}/{total}")
            return

        # Ignore report separators and worker summary lines
        if re.search(r'^-+\s+\d{4}-\d{2}-\d{2}|^Workers:|^-{10,}', line, re.IGNORECASE):
            return
        
        # Check for bytes uploaded pattern (optional)
        bytes_match = re.search(
            r'Uploaded\s+([\d.]+\s*[KMGT]?B)',
            line,
            re.IGNORECASE
        )
        
        # Filter trivial logs (per-file progress)
        trivial_patterns = [
            r'^\s*\[.*\]\s+Uploading.*\.wav',  # "[...] Uploading file.wav"
            r'^\s*Uploading\s+file.*to',       # "Uploading file to..."
            r'^\s*\d+%',                        # "50% uploaded"
            r'^\s*[├└┌┐]',                       # Tree characters
            r'Connection pooling',              # Connection messages
            r'Retry-After',                     # Rate limit header
            r'Commit message',                  # Commit messages
            r'^\s*100%',                        # Final percentage
            r'^\s*\|',                         # progress bar pipes
            r'\[A|\[K',                        # escaped cursor controls
        ]
        
        is_trivial = any(re.search(pattern, line, re.IGNORECASE) for pattern in trivial_patterns)
        
        if is_trivial:
            return  # Suppress trivial logs
        
        # Log important messages (errors, warnings, etc.)
        error_patterns = [
            r'error|exception|failed|traceback',
            r'warning|warn',
            r'timeout|504|500|503|429|too many',
            r'refused|connection reset|broken pipe',
        ]
        
        is_important = any(
            re.search(pattern, line, re.IGNORECASE)
            for pattern in error_patterns
        )
        
        if is_important or not any(
            re.search(p, line, re.IGNORECASE)
            for p in trivial_patterns + [
                r'progress',
                r'mb/s|kb/s',
                r'elapsed',
            ]
        ):
            # Log important messages or unknowns that aren't clearly trivial
            if len(line) > 3:  # Skip very short lines
                self.logger(f"[HF] {line.strip()}")


class FilesProgressBar:
    """
    Manages a clean progress bar for file uploads.
    
    - Shows: "Uploading [████████..] 1,234 / 5,000 files | ETA: 2m 30s"
    - Updates when files complete
    - Thread-safe
    
    Usage (for per-file upload fallback):
        bar = FilesProgressBar(total_files=5000, logger=print)
        for file in files:
            try:
                upload_file(file)
                bar.update_file(1)
            except Exception as e:
                bar.update_file_error(1, str(e))
    """
    
    def __init__(self, total_files: int, logger: Callable[[str], None], suppress_console: bool = False):
        """
        Args:
            total_files: Total number of files to upload
            logger: Callback function for logging
        """
        self.total_files = total_files
        self.logger = logger
        self.uploaded = 0
        self.errors = []
        self.pbar = None
        self.suppress_console = bool(suppress_console)
        
        if not self.suppress_console and tqdm is not None:
            try:
                self.pbar = tqdm(
                    total=total_files,
                    unit="file",
                    unit_scale=False,
                    desc="Uploading",
                    leave=True,
                    ncols=80,
                    miniters=1,
                )
            except Exception:
                self.pbar = None
    
    def update_file(self, count: int = 1) -> None:
        """Mark files as successfully uploaded."""
        self.uploaded += count
        if self.pbar:
            try:
                self.pbar.update(count)
                pct = (self.uploaded / self.total_files) * 100 if self.total_files > 0 else 0
                self.pbar.set_description(f"Uploading ({pct:.1f}%)")
            except Exception:
                pass
        else:
            # Emit concise progress to logger for GUI mode
            try:
                pct = (self.uploaded / self.total_files) * 100 if self.total_files > 0 else 0
                if pct >= 100.0 or pct == 0.0 or (pct - getattr(self, "_last_gui_file_pct", -1.0)) >= 0.5:
                    self._last_gui_file_pct = pct
                    self.logger(f"[Progress] Uploading ({pct:.1f}%) {self.uploaded}/{self.total_files} files")
            except Exception:
                pass
    
    def update_file_error(self, count: int, error_msg: str) -> None:
        """Mark files as failed with error message."""
        self.errors.append(error_msg)
        # Still count as "processed" (though failed) for progress
        self.update_file(count)
    
    def close(self) -> None:
        """Close the progress bar."""
        if self.pbar:
            try:
                self.pbar.close()
            except Exception:
                pass
    
    def log_errors(self) -> None:
        """Print all collected errors/warnings below progress bar."""
        if not self.errors:
            return
        
        self.logger("")
        self.logger("=" * 70)
        self.logger(f"Upload completed with {len(self.errors)} error(s):")
        self.logger("=" * 70)
        
        for error in self.errors:
            self.logger(f"  ⚠️  {error}")
        
        self.logger("=" * 70)


class BytesProgressBar:
    """
    Progress bar for byte-based uploads (alternative metric).
    
    Usage:
        bar = BytesProgressBar(total_bytes=5_000_000, logger=print)
        bar.update_bytes(1_000_000)  # Update with bytes uploaded
    """
    
    def __init__(self, total_bytes: int, logger: Callable[[str], None]):
        """
        Args:
            total_bytes: Total bytes to upload
            logger: Callback function for logging
        """
        self.total_bytes = total_bytes
        self.logger = logger
        self.uploaded_bytes = 0
        self.pbar = None
        
        if tqdm is not None:
            try:
                self.pbar = tqdm(
                    total=total_bytes,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="Uploading",
                    leave=True,
                    ncols=80,
                )
            except Exception:
                pass
    
    def update_bytes(self, byte_count: int) -> None:
        """Update progress with bytes uploaded."""
        self.uploaded_bytes += byte_count
        if self.pbar:
            try:
                self.pbar.update(byte_count)
                pct = (self.uploaded_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0
                self.pbar.set_description(f"Uploading ({pct:.1f}%)")
            except Exception:
                pass
    
    def close(self) -> None:
        """Close the progress bar."""
        if self.pbar:
            try:
                self.pbar.close()
            except Exception:
                pass
