"""Integration tests for the LLM provider presets in the settings pipeline."""

from __future__ import annotations

from abogen.llm_providers import get_provider_presets, get_provider_by_id
from abogen.normalization_settings import (
    _extract_settings,
    build_llm_configuration,
)


def test_extract_settings_preserves_llm_provider():
    """When llm_provider is supplied it must survive _extract_settings()."""
    extracted = _extract_settings({"llm_provider": "minimax"})
    assert extracted["llm_provider"] == "minimax"


def test_extract_settings_defaults_llm_provider_to_empty():
    extracted = _extract_settings({})
    assert extracted["llm_provider"] == ""


def test_build_llm_configuration_with_minimax_preset():
    """Simulate choosing the MiniMax preset and building the LLM config."""
    preset = get_provider_by_id("minimax")
    settings = _extract_settings({
        "llm_provider": preset.id,
        "llm_base_url": preset.base_url,
        "llm_api_key": "test-key",
        "llm_model": preset.models[0],
    })
    config = build_llm_configuration(settings)
    assert config.base_url == "https://api.minimax.io/v1"
    assert config.api_key == "test-key"
    assert config.model == preset.models[0]
