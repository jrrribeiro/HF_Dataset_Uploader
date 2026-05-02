from dataclasses import dataclass
import io
import math
from pathlib import Path
import struct
import wave

from huggingface_hub import hf_hub_download

from src.cache.ephemeral_cache_manager import EphemeralCacheManager


SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


@dataclass(slots=True)
class AudioFetchResult:
    cache_key: str
    local_path: str
    source: str


class AudioFetchService:
    def __init__(self, cache_manager: EphemeralCacheManager) -> None:
        self._cache = cache_manager

    def fetch(
        self,
        dataset_repo: str,
        audio_id: str,
        allow_demo_fallback: bool = False,
        hf_token: str | None = None,
    ) -> AudioFetchResult:
        cache_key = f"{dataset_repo}:{audio_id}"
        cached_path = self._cache.get(cache_key)
        if cached_path:
            return AudioFetchResult(cache_key=cache_key, local_path=str(cached_path), source="cache")

        if allow_demo_fallback and self._is_seeded_demo_audio_id(audio_id):
            fallback_bytes = self._build_demo_fallback_wav(audio_id=audio_id)
            local_path = self._cache.put_bytes(cache_key, fallback_bytes, suffix=".wav")
            return AudioFetchResult(cache_key=cache_key, local_path=str(local_path), source="demo-fallback")

        try:
            target_filename, downloaded_path = self._resolve_remote_filename(
                dataset_repo=dataset_repo,
                audio_id=audio_id,
                hf_token=hf_token,
            )
        except FileNotFoundError:
            if not allow_demo_fallback:
                raise

            fallback_bytes = self._build_demo_fallback_wav(audio_id=audio_id)
            local_path = self._cache.put_bytes(cache_key, fallback_bytes, suffix=".wav")
            return AudioFetchResult(cache_key=cache_key, local_path=str(local_path), source="demo-fallback")

        if downloaded_path is None:
            downloaded = self._download_dataset_file(
                dataset_repo=dataset_repo,
                filename=target_filename,
                hf_token=hf_token,
            )
            downloaded_path = Path(downloaded)

        suffix = downloaded_path.suffix if downloaded_path.suffix else ".bin"
        local_path = self._cache.put_bytes(cache_key, downloaded_path.read_bytes(), suffix=suffix)
        return AudioFetchResult(cache_key=cache_key, local_path=str(local_path), source="remote")

    def fetch_local(self, local_audio_path: str) -> AudioFetchResult:
        """Load audio from local filesystem (useful for testing with local segments).
        
        Args:
            local_audio_path: Full path to local audio file
            
        Returns:
            AudioFetchResult with cache_key based on file path
            
        Raises:
            FileNotFoundError: If local file doesn't exist or is not a supported audio format
        """
        audio_path = Path(local_audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Local audio file not found: {local_audio_path}")
        
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported audio format: {audio_path.suffix}. Supported: {SUPPORTED_AUDIO_EXTENSIONS}")
        
        cache_key = f"local:{audio_path.name}:{audio_path.stat().st_size}"
        cached_path = self._cache.get(cache_key)
        if cached_path:
            return AudioFetchResult(cache_key=cache_key, local_path=str(cached_path), source="cache")
        
        # Cache the local file by copying it into the ephemeral cache
        local_bytes = audio_path.read_bytes()
        cached_path = self._cache.put_bytes(cache_key, local_bytes, suffix=audio_path.suffix)
        return AudioFetchResult(cache_key=cache_key, local_path=str(cached_path), source="local")

    def cleanup_after_validation(self, cache_key: str) -> None:
        self._cache.cleanup_key(cache_key)

    def _resolve_remote_filename(
        self,
        dataset_repo: str,
        audio_id: str,
        hf_token: str | None = None,
    ) -> tuple[str, Path | None]:
        audio_path = Path(audio_id)
        if audio_path.suffix:
            return f"audio/{audio_id}", None

        for extension in SUPPORTED_AUDIO_EXTENSIONS:
            candidate = f"audio/{audio_id}{extension}"
            try:
                downloaded = self._download_dataset_file(
                    dataset_repo=dataset_repo,
                    filename=candidate,
                    hf_token=hf_token,
                )
                return candidate, Path(downloaded)
            except Exception:
                continue

        raise FileNotFoundError(f"Unable to locate audio file for audio_id: {audio_id}")

    def _build_demo_fallback_wav(self, audio_id: str, duration_seconds: float = 4.0, sample_rate: int = 16000) -> bytes:
        """Generate a short deterministic tone when demo audio files are missing."""
        frame_count = max(1, int(duration_seconds * sample_rate))

        # Derive deterministic frequencies from audio_id so each fallback sounds distinct.
        seed = sum(ord(ch) for ch in audio_id) % 200
        f1 = 440.0 + float(seed)
        f2 = f1 + 180.0

        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)

                frames = bytearray()
                for i in range(frame_count):
                    t = i / float(sample_rate)
                    # Blend two sines and apply light envelope to avoid clicks.
                    env = min(1.0, i / 400.0, (frame_count - i) / 400.0)
                    sample = env * (0.55 * math.sin(2.0 * math.pi * f1 * t) + 0.45 * math.sin(2.0 * math.pi * f2 * t))
                    pcm = int(max(-1.0, min(1.0, sample)) * 32767)
                    frames.extend(struct.pack("<h", pcm))

                wav_file.writeframes(bytes(frames))

            return buffer.getvalue()

    def _is_seeded_demo_audio_id(self, audio_id: str) -> bool:
        normalized = audio_id.strip().lower()
        return "_audio_" in normalized and normalized.endswith(("1001", "1002", "1003", "1004"))

    def _download_dataset_file(self, dataset_repo: str, filename: str, hf_token: str | None = None) -> str:
        if hf_token:
            return hf_hub_download(
                repo_id=dataset_repo,
                repo_type="dataset",
                filename=filename,
                token=hf_token,
            )
        return hf_hub_download(
            repo_id=dataset_repo,
            repo_type="dataset",
            filename=filename,
        )
