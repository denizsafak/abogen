"""Shared token stubs for TTS processing."""

from __future__ import annotations


class FakeToken:
    """Minimal token stub for languages without per-word token support."""

    def __init__(self, text: str, start: float, end: float):
        self.text = text
        self.start_ts = start
        self.end_ts = end
        self.whitespace = ""
