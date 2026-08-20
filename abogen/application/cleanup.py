"""Application-layer cleanup — global resource disposal.

Handles:
- GPU/CUDA memory flush
- TTS engine disposal (PluginManager)
- UI-specific cleanup callbacks (registered by entry points)

Called by shutdown.py at process exit and by run_conversion() per-conversion.
"""

from __future__ import annotations

import gc
import sys
from typing import Callable

_UI_CLEANUPS: list[Callable[[], None]] = []


def flush_cuda() -> None:
    """Run GC and release CUDA cache. Safe to call multiple times."""
    gc.collect()
    # Skip entirely if torch was never imported — importing it here just to
    # check would add several seconds to shutdown with nothing to flush.
    if "torch" not in sys.modules:
        return
    try:
        torch = sys.modules["torch"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def dispose_engines() -> None:
    """Dispose all cached TTS engines via PluginManager."""
    try:
        from abogen.tts_plugin.plugin_manager import get_plugin_manager
        get_plugin_manager().dispose_all()
    except Exception:
        pass


def _clear_global_voice_cache() -> None:
    """Reset the global voice download cache state."""
    try:
        from abogen.voice_cache import clear_voice_cache
        clear_voice_cache()
    except Exception:
        pass


def register_ui_cleanup(fn: Callable[[], None]) -> None:
    """Register a UI-specific cleanup callback (e.g. preview threads, temp files)."""
    _UI_CLEANUPS.append(fn)


def cleanup() -> None:
    """Run all application-level cleanups. Idempotent."""
    dispose_engines()
    flush_cuda()
    _clear_global_voice_cache()

    for fn in _UI_CLEANUPS:
        try:
            fn()
        except Exception:
            pass
    _UI_CLEANUPS.clear()


__all__ = [
    "flush_cuda",
    "dispose_engines",
    "register_ui_cleanup",
    "cleanup",
]
