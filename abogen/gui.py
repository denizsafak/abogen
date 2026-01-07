"""Backwards-compatible re-export of the PyQt GUI.

The actual implementation lives in abogen.pyqt.gui.
"""

from __future__ import annotations

from abogen.pyqt.gui import *  # noqa: F401, F403
from abogen.pyqt.gui import abogen

__all__ = ["abogen"]
