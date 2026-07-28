"""Graceful shutdown — process-level hooks and orchestration.

Responsibilities:
- Install atexit/signal/Qt hooks
- Stop WebUI ConversionService (worker thread)
- Restore sleep prevention
- Terminate child processes (ffmpeg, etc.)
- Delegate GPU/engine/UI cleanup to application.cleanup

App-layer cleanup (GPU, engines, UI callbacks) lives in application/cleanup.py.
Per-conversion cleanup lives in run_conversion() finally block.
"""

from __future__ import annotations

import atexit
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


# ---- Process-level cleanup functions ----


def _stop_conversion_service() -> None:
    """Stop WebUI ConversionService worker thread."""
    try:
        from abogen.webui.service import get_service
        svc = get_service()
        if svc is not None:
            svc.shutdown()
    except Exception:
        pass


def _restore_sleep() -> None:
    """Restore system sleep prevention (caffeinate/systemd-inhibit/Windows)."""
    try:
        from abogen.utils import prevent_sleep_end
        prevent_sleep_end()
    except Exception:
        pass


def _terminate_subprocesses() -> None:
    """Terminate all child processes (ffmpeg, etc.)."""
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


def _app_cleanup() -> None:
    """Delegate to application-layer cleanup (engines, GPU, UI callbacks)."""
    try:
        from abogen.application.cleanup import cleanup
        cleanup()
    except Exception:
        pass


# Register in execution order
register_cleanup(_stop_conversion_service)
register_cleanup(_app_cleanup)
register_cleanup(_restore_sleep)
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

    # Qt hook — connect AFTER QApplication is created
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
