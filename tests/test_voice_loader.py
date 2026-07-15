"""Tests for abogen.domain.voice_loader module."""

import pytest

from abogen.domain.voice_loader import (
    VoiceCache,
    resolve_voice,
    load_voice_cached,
)


class TestVoiceCache:
    """Tests for VoiceCache class."""

    def test_get_set(self):
        """Test basic get/set operations."""
        cache = VoiceCache()
        cache.set("test_voice", "loaded_voice")
        assert cache.get("test_voice") == "loaded_voice"

    def test_get_missing(self):
        """Test get returns None for missing voice."""
        cache = VoiceCache()
        assert cache.get("missing_voice") is None

    def test_contains(self):
        """Test contains method."""
        cache = VoiceCache()
        cache.set("test_voice", "loaded_voice")
        assert cache.contains("test_voice")
        assert not cache.contains("missing_voice")

    def test_in_operator(self):
        """Test __contains__ (in operator)."""
        cache = VoiceCache()
        cache.set("test_voice", "loaded_voice")
        assert "test_voice" in cache
        assert "missing_voice" not in cache

    def test_clear(self):
        """Test clear method."""
        cache = VoiceCache()
        cache.set("voice1", "loaded1")
        cache.set("voice2", "loaded2")
        cache.clear()
        assert not cache.contains("voice1")
        assert not cache.contains("voice2")


class TestResolveVoice:
    """Tests for resolve_voice function."""

    def test_simple_voice_name(self):
        """Test that simple voice names are returned as-is."""
        result = resolve_voice(
            voice_spec="test_voice",
            pipeline=None,
            use_gpu=False,
        )
        assert result == "test_voice"

    def test_formula_voice_without_pipeline(self):
        """Test formula voice returns spec when no pipeline."""
        result = resolve_voice(
            voice_spec="model*0.5+0.3*other",
            pipeline=None,
            use_gpu=False,
        )
        assert result == "model*0.5+0.3*other"

    def test_caching(self):
        """Test that voices are cached."""
        cache = VoiceCache()
        
        # First call should load (we'll mock with simple name)
        result1 = resolve_voice(
            voice_spec="test_voice",
            pipeline=None,
            use_gpu=False,
            cache=cache,
        )
        assert result1 == "test_voice"
        assert cache.contains("test_voice")
        
        # Second call should use cache
        result2 = resolve_voice(
            voice_spec="test_voice",
            pipeline=None,
            use_gpu=False,
            cache=cache,
        )
        assert result2 == "test_voice"


class TestLoadVoiceCached:
    """Tests for load_voice_cached function."""

    def test_simple_voice_name(self):
        """Test that simple voice names are returned as-is."""
        result = load_voice_cached(
            voice_name="test_voice",
            pipeline=None,
            use_gpu=False,
        )
        assert result == "test_voice"

    def test_dict_cache(self):
        """Test caching with dict."""
        cache = {}
        
        result1 = load_voice_cached(
            voice_name="test_voice",
            pipeline=None,
            use_gpu=False,
            cache=cache,
        )
        assert result1 == "test_voice"
        assert "test_voice" in cache
        
        result2 = load_voice_cached(
            voice_name="test_voice",
            pipeline=None,
            use_gpu=False,
            cache=cache,
        )
        assert result2 == "test_voice"
        assert cache["test_voice"] == "test_voice"

    def test_no_cache(self):
        """Test without cache parameter."""
        result = load_voice_cached(
            voice_name="test_voice",
            pipeline=None,
            use_gpu=False,
            cache=None,
        )
        assert result == "test_voice"
