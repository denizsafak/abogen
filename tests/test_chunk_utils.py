"""Tests for chunk processing utilities.

Tests import from domain.chunk_utils (new location).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------


class TestSafeInt:
    """safe_int safely converts to int with a default."""

    def test_int_value(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int(42) == 42

    def test_string_number(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int("7") == 7

    def test_float_truncated(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int(3.9) == 3

    def test_none_returns_default(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int(None) == 0

    def test_garbage_returns_default(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int("abc") == 0

    def test_custom_default(self):
        from abogen.domain.chunk_utils import safe_int

        assert safe_int(None, default=-1) == -1


# ---------------------------------------------------------------------------
# chunk_text_for_tts (supplement existing tests)
# ---------------------------------------------------------------------------


class TestChunkTextForTts:
    """chunk_text_for_tts selects the best text source."""

    def test_non_mapping_returns_empty(self):
        from abogen.domain.chunk_utils import chunk_text_for_tts

        assert chunk_text_for_tts("not a dict") == ""

    def test_none_returns_empty(self):
        from abogen.domain.chunk_utils import chunk_text_for_tts

        assert chunk_text_for_tts(None) == ""

    def test_empty_dict_returns_empty(self):
        from abogen.domain.chunk_utils import chunk_text_for_tts

        assert chunk_text_for_tts({}) == ""

    def test_whitespace_only_returns_empty(self):
        from abogen.domain.chunk_utils import chunk_text_for_tts

        assert chunk_text_for_tts({"text": "  "}) == ""


# ---------------------------------------------------------------------------
# record_override_usage
# ---------------------------------------------------------------------------


class TestRecordOverrideUsage:
    """record_override_usage records pronunciation override usage."""

    def test_noop_when_empty(self):
        from abogen.domain.chunk_utils import record_override_usage

        job = SimpleNamespace(language="en")
        record_override_usage(job, {}, {})

    def test_noop_when_all_zero(self):
        from abogen.domain.chunk_utils import record_override_usage

        job = SimpleNamespace(language="en")
        record_override_usage(job, {"hello": 0}, {"hello": "hi"})

    def test_records_usage(self):
        from abogen.domain.chunk_utils import record_override_usage

        job = SimpleNamespace(language="en", add_log=lambda *a, **kw: None)
        with patch("abogen.domain.chunk_utils.increment_usage") as mock_inc:
            record_override_usage(job, {"hello": 2}, {"hello": "hi"})
            mock_inc.assert_called_once_with(language="en", token="hi", amount=2)

    def test_fallback_token_from_normalized(self):
        from abogen.domain.chunk_utils import record_override_usage

        job = SimpleNamespace(language="ja", add_log=lambda *a, **kw: None)
        with patch("abogen.domain.chunk_utils.increment_usage") as mock_inc:
            record_override_usage(job, {"test": 1}, {})
            mock_inc.assert_called_once_with(language="ja", token="test", amount=1)

    def test_handles_exception_gracefully(self):
        from abogen.domain.chunk_utils import record_override_usage

        job = SimpleNamespace(language="en", add_log=lambda *a, **kw: None)
        with patch("abogen.domain.chunk_utils.increment_usage", side_effect=RuntimeError("db error")):
            record_override_usage(job, {"hello": 1}, {"hello": "hi"})
