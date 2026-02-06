"""Backwards-compatible re-export of the PyQt voice formula dialog.

The actual implementation lives in abogen.pyqt.voice_formula_gui.
"""

from __future__ import annotations

from abogen.pyqt.voice_formula_gui import *  # noqa: F401, F403
from abogen.pyqt.voice_formula_gui import VoiceFormulaDialog

__all__ = ["VoiceFormulaDialog"]
