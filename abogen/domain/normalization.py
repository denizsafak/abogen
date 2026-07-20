"""Text normalization convenience helpers.

Provides both the simple ``normalize_text_for_pipeline`` (apostrophe + LLM only)
and the comprehensive ``prepare_text_for_tts`` that chains all three normalization
stages used during conversion: heteronym rules → pronunciation rules → pipeline
normalization.  The latter is the single entry point that both the Web UI and
PyQt Desktop GUI should use.

Also provides ``TTSContext`` — a dataclass bundling all pre-compiled normalization
resources so they can be created once and passed as a single object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

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


@dataclass
class TTSContext:
    """Bundles pre-compiled normalization resources for TTS processing.

    Created once per conversion job and passed to ``prepare_text_for_tts``
    instead of threading 5 separate parameters.
    """

    split_pattern: str = r"(?<=[.!?\-])\s+"
    pronunciation_rules: Optional[List[Dict[str, Any]]] = None
    heteronym_rules: Optional[List[Dict[str, Any]]] = None
    normalization_overrides: Optional[Mapping[str, Any]] = None
    usage_counter: Dict[str, int] = field(default_factory=dict)

    def normalize(self, text: str) -> str:
        """Shorthand: normalize text using this context's compiled rules."""
        return prepare_text_for_tts(
            text,
            heteronym_rules=self.heteronym_rules,
            pronunciation_rules=self.pronunciation_rules,
            normalization_overrides=self.normalization_overrides,
            usage_counter=self.usage_counter,
        )


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


def prepare_text_for_tts(
    text: str,
    *,
    heteronym_rules: Optional[List[Dict[str, Any]]] = None,
    pronunciation_rules: Optional[List[Dict[str, Any]]] = None,
    normalization_overrides: Optional[Mapping[str, Any]] = None,
    usage_counter: Optional[Dict[str, int]] = None,
) -> str:
    """Apply the full text normalization pipeline before TTS synthesis.

    Chains three stages in order:
      1. Heteronym sentence rules (context-dependent pronunciation)
      2. Pronunciation rules (token-level replacements)
      3. Pipeline normalization (apostrophe handling, LLM normalization)

    This is the **single entry point** that both the Web UI conversion runner
    and the PyQt conversion thread should call before passing text to the TTS
    backend.

    Parameters
    ----------
    text:
        Raw text to normalize.
    heteronym_rules:
        Compiled heteronym rules from ``compile_heteronym_sentence_rules``.
    pronunciation_rules:
        Compiled pronunciation rules from ``compile_pronunciation_rules``.
    normalization_overrides:
        User-level overrides for normalization settings (apostrophe mode, etc.).
    usage_counter:
        Mutable dict that tracks how many times each pronunciation override was
        applied.  Passed through to ``apply_pronunciation_rules``.

    Returns
    -------
    str
        Fully normalized text ready for TTS.
    """
    from abogen.domain.pronunciation import (
        apply_heteronym_sentence_rules,
        apply_pronunciation_rules,
    )

    result = str(text or "")

    if heteronym_rules:
        result = apply_heteronym_sentence_rules(result, heteronym_rules)

    if pronunciation_rules:
        result = apply_pronunciation_rules(result, pronunciation_rules, usage_counter)

    runtime_settings = get_runtime_settings()
    if normalization_overrides:
        runtime_settings = _apply_overrides(runtime_settings, normalization_overrides)
    apostrophe_config = build_apostrophe_config(settings=runtime_settings, base=_BASE_APOSTROPHE_CONFIG)

    return _normalize_for_pipeline(result, config=apostrophe_config, settings=runtime_settings)
