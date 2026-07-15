"""Text normalization convenience helpers."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from abogen.kokoro_text_normalization import (
    ApostropheConfig,
    normalize_for_pipeline as _normalize_for_pipeline,
)
from abogen.normalization_settings import (
    build_apostrophe_config,
    get_runtime_settings,
    apply_overrides as _apply_overrides,
)

_BASE_APOSTROPHE_CONFIG = ApostropheConfig()


def normalize_text_for_pipeline(
    text: str,
    *,
    normalization_overrides: Optional[Mapping[str, Any]] = None,
) -> str:
    """Normalize text using runtime settings with optional overrides."""
    runtime_settings = get_runtime_settings()
    if normalization_overrides:
        runtime_settings = _apply_overrides(runtime_settings, normalization_overrides)
    apostrophe_config = build_apostrophe_config(settings=runtime_settings, base=_BASE_APOSTROPHE_CONFIG)
    return _normalize_for_pipeline(text, config=apostrophe_config, settings=runtime_settings)
