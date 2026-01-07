"""Backwards-compatible re-export of conversion module.

The PyQt-based implementation lives in abogen.pyqt.conversion.
The web-based implementation is in abogen.webui.conversion_runner.
"""

from __future__ import annotations

# Re-export PyQt conversion classes for backwards compatibility
from abogen.pyqt.conversion import (  # noqa: F401
    ConversionThread,
    VoicePreviewThread,
    PlayAudioThread,
)

__all__ = ["ConversionThread", "VoicePreviewThread", "PlayAudioThread"]
