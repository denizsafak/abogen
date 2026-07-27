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
from typing import Any, Callable, Dict, List, Mapping, Optional

from abogen.domain.enums import Language
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


def build_tts_context(
    *,
    language: Language,
    subtitle_mode: str = "Disabled",
    pronunciation_overrides: Optional[List[Dict[str, Any]]] = None,
    manual_overrides: Optional[List[Dict[str, Any]]] = None,
    heteronym_overrides: Optional[List[Dict[str, Any]]] = None,
    speakers: Optional[Dict[str, Any]] = None,
    normalization_overrides: Optional[Mapping[str, Any]] = None,
    usage_counter: Optional[Dict[str, int]] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> TTSContext:
    """Build a TTSContext from raw data. Single entry point for both UIs.

    Loads normalization settings, applies overrides, validates configuration,
    merges pronunciation overrides, and compiles all rules.

    Args:
        language: Language enum value.
        subtitle_mode: Subtitle mode string.
        pronunciation_overrides: List of pronunciation override dicts.
        manual_overrides: List of manual override dicts.
        heteronym_overrides: List of heteronym override dicts.
        speakers: Speaker profile mapping.
        normalization_overrides: Per-job normalization setting overrides.
        usage_counter: Mutable dict for tracking override usage.
        log_callback: Callable(level, message) for warnings.

    Returns:
        TTSContext ready for text normalization.
    """
    from abogen.domain.enums import Language, SubtitleMode
    from abogen.domain.pronunciation import (
        compile_heteronym_sentence_rules,
        compile_pronunciation_rules,
        merge_pronunciation_overrides,
    )
    from abogen.domain.split_pattern import get_split_pattern

    def _log(msg: str, level: str = "warning") -> None:
        if log_callback:
            log_callback(level, msg)

    # Get runtime normalization settings
    runtime_settings = get_runtime_settings()

    # Apply per-job normalization overrides
    if normalization_overrides:
        runtime_settings = _apply_overrides(runtime_settings, normalization_overrides)

    # Build apostrophe config
    apostrophe_config = build_apostrophe_config(settings=runtime_settings)

    # Validate LLM apostrophe mode
    apostrophe_mode = str(runtime_settings.get("normalization_apostrophe_mode", "spacy")).lower()
    if apostrophe_mode == "llm":
        from abogen.normalization_settings import build_llm_configuration
        llm_config = build_llm_configuration(runtime_settings)
        if not llm_config.is_configured():
            raise RuntimeError(
                "LLM-based apostrophe normalization is selected, but the LLM configuration is incomplete."
            )

    # Check for num2words availability
    if apostrophe_config.convert_numbers:
        try:
            import num2words  # noqa: F401
        except ImportError:
            _log(
                "Number normalization is enabled but 'num2words' library is not available. "
                "Numbers will NOT be converted to words."
            )

    # Compute split pattern
    if not isinstance(language, Language):
        raise TypeError(f"language must be Language enum, got {type(language).__name__}: {language!r}")
    try:
        mode = SubtitleMode.from_str(subtitle_mode) if not isinstance(subtitle_mode, SubtitleMode) else subtitle_mode
    except ValueError:
        mode = SubtitleMode.DISABLED
    split_pattern = get_split_pattern(language, mode)

    # Merge pronunciation overrides (accepts dict or object)
    source = {
        "pronunciation_overrides": pronunciation_overrides or [],
        "manual_overrides": manual_overrides or [],
        "speakers": speakers or {},
        "language": language,
    }
    merged_overrides = merge_pronunciation_overrides(source)

    # Compile rules
    pronunciation_rules = compile_pronunciation_rules(merged_overrides)
    heteronym_rules = compile_heteronym_sentence_rules(heteronym_overrides or [])

    if heteronym_rules:
        _log(
            f"Applying {len(heteronym_rules)} heteronym override(s) during conversion.",
            level="debug",
        )
    if pronunciation_rules:
        _log(
            f"Applying {len(pronunciation_rules)} pronunciation override(s) during conversion.",
            level="debug",
        )

    return TTSContext(
        split_pattern=split_pattern,
        pronunciation_rules=pronunciation_rules,
        heteronym_rules=heteronym_rules,
        normalization_overrides=normalization_overrides,
        usage_counter=usage_counter if usage_counter is not None else {},
    )
