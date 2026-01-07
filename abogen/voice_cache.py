from __future__ import annotations

import os
import threading
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

try:  # pragma: no cover - optional dependency guard
    from huggingface_hub import hf_hub_download  # type: ignore
    from huggingface_hub.utils import LocalEntryNotFoundError  # type: ignore
except Exception:  # pragma: no cover - import fallback
    hf_hub_download = None  # type: ignore[assignment]
    LocalEntryNotFoundError = None  # type: ignore[assignment]

if LocalEntryNotFoundError is None:  # pragma: no cover - fallback for tests
    class LocalEntryNotFoundError(Exception):
        pass

from abogen.constants import VOICES_INTERNAL

_CACHE_LOCK = threading.Lock()
_CACHED_VOICES: Set[str] = set()
_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED = False


def _normalize_targets(voices: Optional[Iterable[str]]) -> Set[str]:
    if not voices:
        return set(VOICES_INTERNAL)
    normalized: Set[str] = set()
    for voice in voices:
        if not voice:
            continue
        voice_id = str(voice).strip()
        if not voice_id:
            continue
        if voice_id in VOICES_INTERNAL:
            normalized.add(voice_id)
    return normalized


def ensure_voice_assets(
    voices: Optional[Iterable[str]] = None,
    *,
    repo_id: str = "hexgrad/Kokoro-82M",
    cache_dir: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Set[str], Dict[str, str]]:
    """Ensure Kokoro voice weight files are present locally.

    Returns a tuple of (downloaded voices, errors) where errors maps the
    voice id to the underlying exception message.
    """

    if hf_hub_download is None:
        raise RuntimeError("huggingface_hub is required to cache voices")

    effective_cache_dir = cache_dir
    if effective_cache_dir is None:
        env_cache_dir = os.environ.get("ABOGEN_VOICE_CACHE_DIR", "").strip()
        effective_cache_dir = env_cache_dir or None

    targets = _normalize_targets(voices)
    if not targets:
        return set(), {}

    with _CACHE_LOCK:
        missing = [voice for voice in targets if voice not in _CACHED_VOICES]

    downloaded: Set[str] = set()
    errors: Dict[str, str] = {}

    for voice_id in missing:
        if on_progress:
            on_progress(f"Fetching voice asset '{voice_id}'")
        try:
            downloaded_flag = _ensure_single_voice_asset(
                voice_id,
                repo_id=repo_id,
                cache_dir=effective_cache_dir,
            )
        except Exception as exc:  # pragma: no cover - network variance
            errors[voice_id] = str(exc)
            continue

        if downloaded_flag:
            downloaded.add(voice_id)
        with _CACHE_LOCK:
            _CACHED_VOICES.add(voice_id)

    return downloaded, errors


def bootstrap_voice_cache(
    voices: Optional[Iterable[str]] = None,
    *,
    repo_id: str = "hexgrad/Kokoro-82M",
    cache_dir: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Set[str], Dict[str, str]]:
    """Ensure voices are cached once per process.

    Subsequent calls are no-ops and return empty structures.
    """

    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return set(), {}
        downloaded, errors = ensure_voice_assets(
            voices,
            repo_id=repo_id,
            cache_dir=cache_dir,
            on_progress=on_progress,
        )
        _BOOTSTRAPPED = True
        return downloaded, errors


def _ensure_single_voice_asset(
    voice_id: str,
    *,
    repo_id: str,
    cache_dir: Optional[str],
) -> bool:
    if hf_hub_download is None:
        raise RuntimeError("huggingface_hub is required to cache voices")

    filename = f"voices/{voice_id}.pt"
    common_kwargs = {
        "repo_id": repo_id,
        "filename": filename,
    }
    if cache_dir is not None:
        common_kwargs["cache_dir"] = cache_dir

    try:
        hf_hub_download(local_files_only=True, **common_kwargs)
        return False
    except LocalEntryNotFoundError:
        pass

    hf_hub_download(resume_download=True, **common_kwargs)
    return True