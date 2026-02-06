"""Backwards-compatible entry point that now launches the web UI."""

from __future__ import annotations

import atexit
import os
import platform
import signal
import sys

from abogen.utils import load_config, prevent_sleep_end
from abogen.webui.app import main as _run_web_ui

# Configure Hugging Face Hub behaviour (mirrors legacy GUI defaults).
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
if load_config().get("disable_kokoro_internet", False):
    os.environ["HF_HUB_OFFLINE"] = "1"

# Prefer faster ROCm tuning defaults when available.
os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
os.environ.setdefault("MIOPEN_CONV_PRECISE_ROCM_TUNING", "0")

# Enable MPS GPU acceleration on Apple Silicon.
if platform.system() == "Darwin" and platform.processor() == "arm":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

atexit.register(prevent_sleep_end)


def _cleanup_sleep(signum, _frame):
    prevent_sleep_end()
    sys.exit(0)


signal.signal(signal.SIGINT, _cleanup_sleep)
signal.signal(signal.SIGTERM, _cleanup_sleep)


def main() -> None:
    """Launch the Flask-based web UI."""

    _run_web_ui()


if __name__ == "__main__":  # pragma: no cover - manual execution hook
    main()
