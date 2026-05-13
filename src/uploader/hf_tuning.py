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
