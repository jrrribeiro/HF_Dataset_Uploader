from __future__ import annotations

from functools import partial


def configure_hf_http_backoff() -> None:
    """Reduce Hugging Face Hub retry backoff for upload-time requests.

    The Hub's preupload path retries several times with exponential backoff by
    default, which can look like a hang on slow or unreachable networks.
    This narrows the retry window so uploads fail fast instead of stalling.
    """
    from huggingface_hub import _commit_api
    from huggingface_hub.utils import _http

    fast_backoff = partial(
        _http.http_backoff,
        max_retries=1,
        base_wait_time=0.5,
        max_wait_time=1.0,
    )
    _commit_api.http_backoff = fast_backoff
    # Prefer the higher-throughput Xet upload path when available.
    import os

    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    # Ensure HF Hub HTTP calls have reasonable default timeouts to avoid
    # hanging with no read timeout (which yields ReadTimeoutError with
    # "read timeout=None"). We monkeypatch requests.Session.request to
    # supply a default timeout tuple (connect, read) when none is provided.
    try:
        import requests

        connect_timeout = float(os.getenv("BNU_HUB_CONNECT_TIMEOUT", "8"))
        read_timeout = float(os.getenv("BNU_HUB_READ_TIMEOUT", "30"))
        _orig_session_request = requests.Session.request

        def _session_request_with_default_timeout(self, method, url, *args, **kwargs):
            if "timeout" not in kwargs or kwargs.get("timeout") is None:
                kwargs["timeout"] = (connect_timeout, read_timeout)
            return _orig_session_request(self, method, url, *args, **kwargs)

        requests.Session.request = _session_request_with_default_timeout
    except Exception:
        # If requests isn't available or monkeypatch fails, continue without
        # crashing; calling code will handle timeouts as best it can.
        pass
