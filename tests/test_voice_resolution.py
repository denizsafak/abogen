"""Tests for voice resolution helpers.

Tests import from domain.voice_resolution (new location).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# spec_to_voice_ids
# ---------------------------------------------------------------------------


class TestSpecToVoiceIds:
    """spec_to_voice_ids extracts voice identifiers from a spec string."""

    def test_empty_string(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        assert spec_to_voice_ids("") == set()

    def test_none(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        assert spec_to_voice_ids(None) == set()

    def test_custom_mix_returns_empty(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        assert spec_to_voice_ids("__custom_mix") == set()

    def test_single_known_voice(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        with patch("abogen.domain.voice_resolution.get_voices", return_value={"af_heart"}):
            assert spec_to_voice_ids("af_heart") == {"af_heart"}

    def test_unknown_single_voice_returns_empty(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        with patch("abogen.domain.voice_resolution.get_voices", return_value=set()):
            assert spec_to_voice_ids("nonexistent") == set()

    def test_formula_with_star(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        with patch("abogen.domain.voice_resolution.extract_voice_ids", return_value=["v1", "v2"]):
            result = spec_to_voice_ids("v1*v2")
            assert result == {"v1", "v2"}

    def test_formula_value_error_returns_empty(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        with patch("abogen.domain.voice_resolution.extract_voice_ids", side_effect=ValueError("bad")):
            assert spec_to_voice_ids("bad*spec") == set()

    def test_whitespace_stripped(self):
        from abogen.domain.voice_resolution import spec_to_voice_ids

        assert spec_to_voice_ids("  ") == set()


# ---------------------------------------------------------------------------
# job_voice_fallback
# ---------------------------------------------------------------------------


class TestJobVoiceFallback:
    """job_voice_fallback resolves a fallback voice from job attributes."""

    def test_direct_voice(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(voice="af_heart", speakers=None, chapters=[])
        assert job_voice_fallback(job) == "af_heart"

    def test_custom_mix_ignored(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(voice="__custom_mix", speakers=None, chapters=[])
        assert job_voice_fallback(job) == ""

    def test_narrator_speaker(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(
            voice="__custom_mix",
            speakers={"narrator": {"resolved_voice": "af_heart"}},
            chapters=[],
        )
        assert job_voice_fallback(job) == "af_heart"

    def test_speaker_voice_formula(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(
            voice="",
            speakers={"speaker1": {"voice_formula": "v1*v2"}},
            chapters=[],
        )
        assert job_voice_fallback(job) == "v1*v2"

    def test_chapter_voice(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(
            voice="",
            speakers=None,
            chapters=[{"resolved_voice": "af_bella"}],
        )
        assert job_voice_fallback(job) == "af_bella"

    def test_empty_job(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(voice="", speakers=None, chapters=[])
        assert job_voice_fallback(job) == ""

    def test_narrator_custom_mix_falls_through(self):
        from abogen.domain.voice_resolution import job_voice_fallback

        job = SimpleNamespace(
            voice="",
            speakers={"narrator": {"voice": "__custom_mix"}},
            chapters=[{"voice": "af_heart"}],
        )
        assert job_voice_fallback(job) == "af_heart"


# ---------------------------------------------------------------------------
# chapter_voice_spec
# ---------------------------------------------------------------------------


class TestChapterVoiceSpec:
    """chapter_voice_spec resolves voice for a chapter override."""

    def test_no_override_uses_fallback(self):
        from abogen.domain.voice_resolution import chapter_voice_spec

        job = SimpleNamespace(voice="af_heart", speakers=None, chapters=[])
        assert chapter_voice_spec(job, None) == "af_heart"

    def test_resolved_voice_wins(self):
        from abogen.domain.voice_resolution import chapter_voice_spec

        job = SimpleNamespace(voice="af_heart", speakers=None, chapters=[])
        override = {"resolved_voice": "af_bella", "voice_formula": "x", "voice": "y"}
        assert chapter_voice_spec(job, override) == "af_bella"

    def test_formula_second(self):
        from abogen.domain.voice_resolution import chapter_voice_spec

        job = SimpleNamespace(voice="", speakers=None, chapters=[])
        override = {"voice_formula": "v1*v2", "voice": "y"}
        assert chapter_voice_spec(job, override) == "v1*v2"

    def test_voice_third(self):
        from abogen.domain.voice_resolution import chapter_voice_spec

        job = SimpleNamespace(voice="", speakers=None, chapters=[])
        override = {"voice": "af_nicole"}
        assert chapter_voice_spec(job, override) == "af_nicole"

    def test_empty_override_falls_to_fallback(self):
        from abogen.domain.voice_resolution import chapter_voice_spec

        job = SimpleNamespace(voice="af_heart", speakers=None, chapters=[])
        assert chapter_voice_spec(job, {}) == "af_heart"


# ---------------------------------------------------------------------------
# chunk_voice_spec
# ---------------------------------------------------------------------------


class TestChunkVoiceSpec:
    """chunk_voice_spec resolves voice for a TTS chunk."""

    def test_chunk_direct_voice(self):
        from abogen.domain.voice_resolution import chunk_voice_spec

        job = SimpleNamespace(speakers=None)
        chunk = {"resolved_voice": "af_heart"}
        assert chunk_voice_spec(job, chunk, "fallback") == "af_heart"

    def test_chunk_speaker_lookup(self):
        from abogen.domain.voice_resolution import chunk_voice_spec

        job = SimpleNamespace(speakers={"narrator": {"resolved_voice": "af_bella"}})
        chunk = {"speaker_id": "narrator"}
        assert chunk_voice_spec(job, chunk, "") == "af_bella"

    def test_chunk_voice_profile_lookup(self):
        from abogen.domain.voice_resolution import chunk_voice_spec

        job = SimpleNamespace(speakers={"角色A": {"voice": "af_nicole"}})
        chunk = {"voice_profile": "角色A"}
        assert chunk_voice_spec(job, chunk, "") == "af_nicole"

    def test_uses_fallback_string(self):
        from abogen.domain.voice_resolution import chunk_voice_spec

        job = SimpleNamespace(speakers=None)
        chunk = {}
        assert chunk_voice_spec(job, chunk, "my_fallback") == "my_fallback"

    def test_fallback_to_job(self):
        from abogen.domain.voice_resolution import chunk_voice_spec

        job = SimpleNamespace(voice="af_heart", speakers=None, chapters=[])
        chunk = {}
        assert chunk_voice_spec(job, chunk, "") == "af_heart"


# ---------------------------------------------------------------------------
# collect_required_voice_ids
# ---------------------------------------------------------------------------


class TestCollectRequiredVoiceIds:
    """collect_required_voice_ids gathers all voice IDs from a job."""

    def test_includes_job_voice(self):
        from abogen.domain.voice_resolution import collect_required_voice_ids

        job = SimpleNamespace(voice="af_heart", chapters=[], chunks=[], speakers={})
        with patch("abogen.domain.voice_resolution.get_voices", return_value={"af_heart"}), \
             patch("abogen.domain.voice_resolution.job_voice_fallback", return_value=""):
            result = collect_required_voice_ids(job)
        assert "af_heart" in result

    def test_includes_chapter_voices(self):
        from abogen.domain.voice_resolution import collect_required_voice_ids

        job = SimpleNamespace(
            voice="",
            chapters=[{"resolved_voice": "af_bella"}],
            chunks=[],
            speakers={},
        )
        with patch("abogen.domain.voice_resolution.get_voices", return_value={"af_bella"}), \
             patch("abogen.domain.voice_resolution.job_voice_fallback", return_value=""):
            result = collect_required_voice_ids(job)
        assert "af_bella" in result

    def test_includes_chunk_voices(self):
        from abogen.domain.voice_resolution import collect_required_voice_ids

        job = SimpleNamespace(
            voice="",
            chapters=[],
            chunks=[{"voice": "af_nicole"}],
            speakers={},
        )
        with patch("abogen.domain.voice_resolution.get_voices", return_value={"af_nicole"}), \
             patch("abogen.domain.voice_resolution.job_voice_fallback", return_value=""):
            result = collect_required_voice_ids(job)
        assert "af_nicole" in result

    def test_always_includes_kokoro_voices(self):
        from abogen.domain.voice_resolution import collect_required_voice_ids

        job = SimpleNamespace(voice="", chapters=[], chunks=[], speakers={})
        with patch("abogen.domain.voice_resolution.get_voices", return_value={"af_heart", "af_bella"}), \
             patch("abogen.domain.voice_resolution.job_voice_fallback", return_value=""):
            result = collect_required_voice_ids(job)
        assert {"af_heart", "af_bella"}.issubset(result)
