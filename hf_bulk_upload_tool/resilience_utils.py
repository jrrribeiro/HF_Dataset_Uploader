#!/usr/bin/env python3
"""
Enhanced resilience utilities for HF uploads.

Adds robustness against:
- HTTP timeouts and network interruptions
- Token expiration detection
- Improved retry strategies for different error types
- Monitoring/alerting hooks
"""

import time
from typing import Callable, Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta
import json


class TokenManager:
    """Manages HF token lifecycle and expiration."""
    
    def __init__(self, token: str, warning_days_before_expiry: int = 7):
        """
        Args:
            token: HF API token
            warning_days_before_expiry: Days before expiry to warn user
        """
        self.token = token
        self.warning_days_before_expiry = warning_days_before_expiry
    
    def check_token_expiry(self, logger: Callable[[str], None]) -> bool:
        """
        Check if token is about to expire and log warning.
        
        Note: HF tokens don't include expiry in the token itself.
        This is a placeholder for user to manually set expiry date in config.
        
        Returns:
            True if token is safe to use, False if expiring soon
        """
        # In practice, this would need to be set by the user in their config
        # Example: --token-expiry-date "2026-06-15"
        # For now, just warn to check manually
        logger("[TokenManager] HF tokens do not self-report expiry.")
        logger("[TokenManager] If you created your token >30 days ago, consider creating a new one.")
        return True


class SmartRetryStrategy:
    """
    Intelligent retry strategy that adapts to different error types.
    
    Handles:
    - 429 (Too Many Requests) - respect Retry-After header
    - 504 (Gateway Timeout) - exponential backoff up to 5 min
    - 503 (Service Unavailable) - slow backoff (GC detected)
    - 500-series - exponential backoff
    - Network errors - exponential backoff
    """
    
    def __init__(self, max_retries: int = 5, initial_backoff: float = 2.0):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.error_history: list[Dict[str, Any]] = []
    
    def should_retry(self, error_response: Dict[str, Any]) -> bool:
        """Determine if error is retryable."""
        status = error_response.get('status_code')
        
        # Retryable status codes
        retryable_statuses = [408, 429, 500, 502, 503, 504]
        return status in retryable_statuses
    
    def get_wait_time(self, error_response: Dict[str, Any], attempt: int) -> float:
        """
        Calculate wait time based on error type and attempt number.
        
        Returns:
            Seconds to wait before retry
        """
        status = error_response.get('status_code')
        
        # Check for Retry-After header (HF may suggest wait time)
        retry_after = error_response.get('retry_after_header')
        if retry_after:
            try:
                return max(float(retry_after), self.initial_backoff * (2 ** (attempt - 1)))
            except (ValueError, TypeError):
                pass
        
        # Status-specific backoff strategies
        if status == 429:
            # Rate limit: aggressive backoff
            return min(300, self.initial_backoff * (4 ** attempt))  # Cap at 5 min
        
        elif status == 503:
            # Service unavailable (likely GC): slow backoff
            return min(600, self.initial_backoff * (2 ** attempt))  # Cap at 10 min
        
        elif status == 504:
            # Gateway timeout: exponential backoff
            return min(300, self.initial_backoff * (3 ** attempt))  # Cap at 5 min
        
        elif status in [500, 502]:
            # Server error: standard exponential backoff
            return self.initial_backoff * (2 ** attempt)
        
        else:
            # Generic network error
            return self.initial_backoff * (2 ** attempt)
    
    def log_retry_decision(
        self,
        error_response: Dict[str, Any],
        attempt: int,
        wait_time: float,
        logger: Callable[[str], None]
    ) -> None:
        """Log retry decision for monitoring."""
        status = error_response.get('status_code')
        error_msg = error_response.get('message', 'Unknown error')
        
        logger(f"[SmartRetry] Attempt {attempt}/{self.max_retries} failed with status {status}")
        logger(f"[SmartRetry] Error: {error_msg}")
        logger(f"[SmartRetry] Waiting {wait_time:.0f}s before retry...")
        
        # Store for historical analysis
        self.error_history.append({
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'attempt': attempt,
            'wait_time': wait_time
        })


class NetworkResilience:
    """Handles network-specific issues."""
    
    @staticmethod
    def detect_slow_network(
        bytes_uploaded: int,
        elapsed_seconds: float,
        threshold_kbps: float = 100.0
    ) -> bool:
        """
        Detect if network is unusually slow.
        
        Args:
            bytes_uploaded: Total bytes successfully uploaded
            elapsed_seconds: Time elapsed
            threshold_kbps: Minimum expected speed (default 100 KB/s)
        
        Returns:
            True if network speed is below threshold
        """
        if elapsed_seconds < 1:
            return False
        
        kbps = (bytes_uploaded / 1024) / elapsed_seconds
        return kbps < threshold_kbps
    
    @staticmethod
    def estimate_remaining_time(
        bytes_remaining: int,
        current_speed_kbps: float
    ) -> float:
        """Estimate remaining upload time based on current speed."""
        if current_speed_kbps <= 0:
            return float('inf')
        return (bytes_remaining / 1024) / current_speed_kbps


class UploadMonitor:
    """Monitors upload progress and detects anomalies."""
    
    def __init__(self, checkpoint_file: Path, logger: Callable[[str], None]):
        self.checkpoint_file = checkpoint_file
        self.logger = logger
        self.start_time = time.time()
        self.last_checkpoint_time = self.start_time
        self.checkpoint_interval_seconds = 300  # Every 5 min
    
    def should_save_checkpoint(self) -> bool:
        """Determine if checkpoint should be saved based on time interval."""
        elapsed = time.time() - self.last_checkpoint_time
        return elapsed > self.checkpoint_interval_seconds
    
    def record_checkpoint(self, uploaded_count: int, total_count: int) -> None:
        """Save checkpoint with upload progress."""
        self.last_checkpoint_time = time.time()
        elapsed = time.time() - self.start_time
        
        progress = {
            'timestamp': datetime.now().isoformat(),
            'uploaded': uploaded_count,
            'total': total_count,
            'elapsed_seconds': elapsed,
            'rate_files_per_hour': (uploaded_count / elapsed * 3600) if elapsed > 0 else 0,
            'percent_complete': (uploaded_count / total_count * 100) if total_count > 0 else 0,
        }
        
        try:
            with open(self.checkpoint_file, 'w') as f:
                json.dump(progress, f, indent=2)
        except Exception as e:
            self.logger(f"[Monitor] Warning: Could not save checkpoint: {e}")
    
    def estimate_time_remaining(self, uploaded_count: int, total_count: int) -> str:
        """Estimate remaining upload time."""
        if uploaded_count == 0 or total_count == 0:
            return "unknown"
        
        elapsed = time.time() - self.start_time
        rate_per_sec = uploaded_count / elapsed if elapsed > 0 else 0
        remaining = total_count - uploaded_count
        remaining_seconds = remaining / rate_per_sec if rate_per_sec > 0 else 0
        
        hours = remaining_seconds / 3600
        minutes = (remaining_seconds % 3600) / 60
        
        return f"{hours:.1f}h {minutes:.0f}m"
    
    def log_progress(self, uploaded_count: int, total_count: int) -> None:
        """Log current progress."""
        elapsed = time.time() - self.start_time
        rate = (uploaded_count / elapsed * 3600) if elapsed > 0 else 0
        remaining = self.estimate_time_remaining(uploaded_count, total_count)
        
        self.logger(f"[Progress] {uploaded_count}/{total_count} files ({uploaded_count/total_count*100:.1f}%)")
        self.logger(f"[Progress] Rate: {rate:.0f} files/hour | ETA: {remaining}")


class GarbageCollectionDetector:
    """Detects when HF is doing garbage collection (repo locked state)."""
    
    def __init__(self):
        self.gc_indicators = []
    
    def record_error(self, status_code: int, retry_after: Optional[str] = None) -> None:
        """Record error that might indicate GC."""
        if status_code == 503 or (status_code == 429 and retry_after and int(retry_after) > 300):
            self.gc_indicators.append({
                'timestamp': datetime.now().isoformat(),
                'status': status_code,
                'retry_after': retry_after
            })
    
    def might_be_in_gc(self) -> bool:
        """Check if GC might be happening based on recent errors."""
        # If we have 503 errors in the last few minutes, likely GC
        if not self.gc_indicators:
            return False
        
        recent_errors = [
            e for e in self.gc_indicators
            if (datetime.now() - datetime.fromisoformat(e['timestamp'])).total_seconds() < 600
        ]
        
        return len(recent_errors) >= 2
    
    def suggest_action(self, logger: Callable[[str], None]) -> None:
        """Suggest action if GC detected."""
        if self.might_be_in_gc():
            logger("")
            logger("[GCDetector] ⚠️  Possible HF garbage collection detected!")
            logger("[GCDetector] Repository may be temporarily locked for optimization.")
            logger("[GCDetector] Switching to slower retry strategy (waiting longer between attempts)...")
            logger("")
