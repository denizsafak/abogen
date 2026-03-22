"""Tests for the LLM provider presets module."""

from __future__ import annotations

import pytest

from abogen.llm_providers import (
    LLMProviderPreset,
    get_provider_presets,
    get_provider_by_id,
)


def test_get_provider_presets_returns_non_empty():
    presets = get_provider_presets()
    assert len(presets) >= 4


def test_minimax_preset_exists():
    preset = get_provider_by_id("minimax")
    assert preset is not None
    assert preset.name == "MiniMax"
    assert preset.base_url == "https://api.minimax.io/v1"
    assert preset.api_key_env == "MINIMAX_API_KEY"
    assert len(preset.models) >= 1
    assert "MiniMax-M2.7" in preset.models


def test_openai_preset_exists():
    preset = get_provider_by_id("openai")
    assert preset is not None
    assert preset.base_url == "https://api.openai.com/v1"


def test_ollama_preset_has_no_models():
    preset = get_provider_by_id("ollama")
    assert preset is not None
    assert preset.models == ()


def test_get_provider_by_id_returns_none_for_unknown():
    assert get_provider_by_id("nonexistent") is None
    assert get_provider_by_id("") is None


def test_preset_ids_are_unique():
    presets = get_provider_presets()
    ids = [p.id for p in presets]
    assert len(ids) == len(set(ids))


def test_to_dict_has_required_keys():
    preset = get_provider_by_id("minimax")
    d = preset.to_dict()
    assert set(d.keys()) == {"id", "name", "base_url", "api_key_env", "api_key_hint", "models"}
    assert isinstance(d["models"], list)
    assert d["id"] == "minimax"


def test_preset_is_frozen():
    preset = get_provider_by_id("minimax")
    with pytest.raises(AttributeError):
        preset.name = "changed"


def test_all_presets_have_base_url():
    for preset in get_provider_presets():
        assert preset.base_url, f"Preset {preset.id!r} missing base_url"


def test_normalization_settings_includes_llm_provider():
    """The llm_provider key must exist in the settings defaults."""
    from abogen.normalization_settings import _SETTINGS_DEFAULTS

    assert "llm_provider" in _SETTINGS_DEFAULTS
    assert _SETTINGS_DEFAULTS["llm_provider"] == ""
