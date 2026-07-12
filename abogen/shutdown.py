"""Graceful shutdown - single module, no over-engineering."""
from __future__ import annotations

import atexit
import gc
import signal
import sys
from typing import Callable

_CLEANUP_FUNCS: list[Callable[[], None]] = []
_EXECUTED = False


def register_cleanup(fn: Callable[[], None]) -> None:
    """Register a cleanup function to run on shutdown."""
    _CLEANUP_FUNCS.append(fn)


def _run_cleanups() -> None:
    global _EXECUTED
    if _EXECUTED:
        return
    _EXECUTED = True
    for fn in _CLEANUP_FUNCS:
        try:
            fn()
        except Exception:
            pass


# ---- Register built-in cleanup functions ----

# 1. Restore sleep prevention
def _restore_sleep() -> None:
    try:
        from abogen.utils import prevent_sleep_end
        prevent_sleep_end()
    except Exception:
        pass

register_cleanup(_restore_sleep)

# 2. Shutdown web UI ConversionService
def _shutdown_conversion_service() -> None:
    try:
        from abogen.webui.service import get_service
        svc = get_service()
        if svc is not None:
            svc.shutdown()
    except Exception:
        pass

register_cleanup(_shutdown_conversion_service)

# 3. Clear TTS pipelines and GPU memory
def _cleanup_tts_pipelines() -> None:
    # Clear web UI pipeline cache
    try:
        from abogen.webui.conversion_runner import _PIPELINES
        _PIPELINES.clear()
    except Exception:
        pass

    # Clear PyQt conversion thread voice cache
    try:
        from abogen.pyqt.conversion import ConversionThread
        if hasattr(ConversionThread, "voice_cache"):
            ConversionThread.voice_cache.clear()
    except Exception:
        pass

    gc.collect()

    # Release CUDA cache
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass

register_cleanup(_cleanup_tts_pipelines)

# 4. Clear global voice cache
def _clear_voice_cache() -> None:
    try:
        from abogen.voice_cache import clear_voice_cache
        clear_voice_cache()
    except Exception:
        pass

register_cleanup(_clear_voice_cache)

# 5. Terminate child processes (ffmpeg, etc.)
def _terminate_subprocesses() -> None:
    try:
        import psutil
    except Exception:
        return

    try:
        current = psutil.Process()
        for child in current.children(recursive=True):
            try:
                child.terminate()
            except Exception:
                pass
        gone, alive = psutil.wait_procs(current.children(recursive=True), timeout=3)
        for proc in alive:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        pass

register_cleanup(_terminate_subprocesses)


def register_shutdown() -> None:
    """Install process-wide shutdown hooks (atexit, signals, Qt)."""
    if register_shutdown._registered:
        return
    register_shutdown._registered = True

    atexit.register(_run_cleanups)

    # POSIX signals
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except Exception:
            pass

    # Qt hook
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_run_cleanups)
    except Exception:
        pass


register_shutdown._registered = False


def _on_signal(signum: int, _frame) -> None:
    _run_cleanups()
    sys.exit(0)


def request_shutdown() -> None:
    """Programmatically trigger cleanup (e.g., from GUI closeEvent)."""
    _run_cleanups()


__all__ = ["register_shutdown", "request_shutdown", "register_cleanup"]
