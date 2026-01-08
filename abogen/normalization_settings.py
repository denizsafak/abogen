from __future__ import annotations

import os
from dataclasses import replace
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional

from abogen.kokoro_text_normalization import (
    ApostropheConfig,
    CONTRACTION_CATEGORY_DEFAULTS,
)
from abogen.llm_client import LLMConfiguration
from abogen.utils import load_config

DEFAULT_LLM_PROMPT = (
    "You are assisting with audiobook preparation. Analyze the sentence and identify any apostrophes or "
    "contractions that should be expanded for clarity. Call the apply_regex_replacements tool with precise "
    "regex substitutions for only the words that need adjustment. If no changes are required, return an empty list.\n"
    "Sentence: {{ sentence }}"
)

_LEGACY_REWRITE_ONLY_PROMPT = (
    "You are assisting with audiobook preparation. Rewrite the provided sentence so apostrophes and "
    "contractions are unambiguous for text-to-speech. Respond with only the rewritten sentence.\n"
    "Sentence: {{ sentence }}\n"
    "Context: {{ paragraph }}"
)

_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "",
    "llm_timeout": 30.0,
    "llm_prompt": DEFAULT_LLM_PROMPT,
    "llm_context_mode": "sentence",
    "normalization_numbers": True,
    "normalization_numbers_year_style": "american",
    "normalization_currency": True,
    "normalization_footnotes": True,
    "normalization_titles": True,
    "normalization_terminal": True,
    "normalization_phoneme_hints": True,
    "normalization_caps_quotes": True,
    "normalization_internet_slang": False,
    "normalization_apostrophes_contractions": True,
    "normalization_apostrophes_plural_possessives": True,
    "normalization_apostrophes_sibilant_possessives": True,
    "normalization_apostrophes_decades": True,
    "normalization_apostrophes_leading_elisions": True,
    "normalization_apostrophe_mode": "spacy",
    "normalization_contraction_aux_be": True,
    "normalization_contraction_aux_have": True,
    "normalization_contraction_modal_will": True,
    "normalization_contraction_modal_would": True,
    "normalization_contraction_negation_not": True,
    "normalization_contraction_let_us": True,
}

_CONTRACTION_SETTING_MAP: Dict[str, str] = {
    "normalization_contraction_aux_be": "contraction_aux_be",
    "normalization_contraction_aux_have": "contraction_aux_have",
    "normalization_contraction_modal_will": "contraction_modal_will",
    "normalization_contraction_modal_would": "contraction_modal_would",
    "normalization_contraction_negation_not": "contraction_negation_not",
    "normalization_contraction_let_us": "contraction_let_us",
}

_ENVIRONMENT_KEYS: Dict[str, str] = {
    "llm_base_url": "ABOGEN_LLM_BASE_URL",
    "llm_api_key": "ABOGEN_LLM_API_KEY",
    "llm_model": "ABOGEN_LLM_MODEL",
    "llm_timeout": "ABOGEN_LLM_TIMEOUT",
    "llm_prompt": "ABOGEN_LLM_PROMPT",
    "llm_context_mode": "ABOGEN_LLM_CONTEXT_MODE",
}

NORMALIZATION_SAMPLE_TEXTS: Dict[str, str] = {
    "apostrophes": "I've heard the captain'll arrive by dusk, but they'd said the same yesterday.",
    "numbers": "The ledger listed 1,204 outstanding debts totaling $57,890.",
    "titles": "Dr. Smith met Mr. O'Leary outside St. John's Church on Jan. 4th.",
    "punctuation": "Meet me at the docks tonight We'll decide then",  # missing punctuation
}


@lru_cache(maxsize=1)
def _environment_defaults() -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    for key, env_var in _ENVIRONMENT_KEYS.items():
        default = _SETTINGS_DEFAULTS.get(key)
        if default is None:
            continue
        value = os.environ.get(env_var)
        if value is None or value == "":
            continue
        if isinstance(default, bool):
            overrides[key] = _coerce_bool(value, default)
        elif isinstance(default, float):
            overrides[key] = _coerce_float(value, float(default))
        else:
            overrides[key] = value
    return overrides


def environment_llm_defaults() -> Dict[str, Any]:
    defaults = dict(_environment_defaults())
    if defaults:
        _apply_llm_migrations(defaults)
    return defaults


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _apply_llm_migrations(settings: Dict[str, Any]) -> None:
    prompt_value = str(settings.get("llm_prompt") or "")
    if prompt_value.strip() == _LEGACY_REWRITE_ONLY_PROMPT.strip():
        settings["llm_prompt"] = DEFAULT_LLM_PROMPT

    context_mode = str(settings.get("llm_context_mode") or "").strip().lower()
    if context_mode != "sentence":
        settings["llm_context_mode"] = "sentence"


def _extract_settings(source: Mapping[str, Any]) -> Dict[str, Any]:
    env_defaults = _environment_defaults()
    extracted: Dict[str, Any] = {}
    for key, default in _SETTINGS_DEFAULTS.items():
        if key in source:
            raw_value = source.get(key)
        elif key in env_defaults:
            raw_value = env_defaults[key]
        else:
            raw_value = default
        if isinstance(default, bool):
            extracted[key] = _coerce_bool(raw_value, default)
        elif isinstance(default, float):
            extracted[key] = _coerce_float(raw_value, default)
        else:
            extracted[key] = (
                str(raw_value or "") if isinstance(default, str) else raw_value
            )
    _apply_llm_migrations(extracted)
    return extracted


@lru_cache(maxsize=1)
def _cached_settings() -> Dict[str, Any]:
    config = load_config() or {}
    return _extract_settings(config)


def get_runtime_settings() -> Dict[str, Any]:
    return dict(_cached_settings())


def clear_cached_settings() -> None:
    _cached_settings.cache_clear()


def build_apostrophe_config(
    *,
    settings: Mapping[str, Any],
    base: Optional[ApostropheConfig] = None,
) -> ApostropheConfig:
    config = replace(base or ApostropheConfig())
    config.convert_numbers = bool(settings.get("normalization_numbers", True))
    config.convert_currency = bool(settings.get("normalization_currency", True))
    config.remove_footnotes = bool(settings.get("normalization_footnotes", True))
    config.year_pronunciation_mode = (
        str(settings.get("normalization_numbers_year_style", "american") or "")
        .strip()
        .lower()
    )
    config.add_phoneme_hints = bool(settings.get("normalization_phoneme_hints", True))
    config.contraction_mode = (
        "expand"
        if settings.get("normalization_apostrophes_contractions", True)
        else "keep"
    )
    config.plural_possessive_mode = (
        "collapse"
        if settings.get("normalization_apostrophes_plural_possessives", True)
        else "keep"
    )
    config.sibilant_possessive_mode = (
        "mark"
        if settings.get("normalization_apostrophes_sibilant_possessives", True)
        else "keep"
    )
    config.decades_mode = (
        "expand" if settings.get("normalization_apostrophes_decades", True) else "keep"
    )
    config.leading_elision_mode = (
        "expand"
        if settings.get("normalization_apostrophes_leading_elisions", True)
        else "keep"
    )
    config.ambiguous_past_modal_mode = (
        "contextual" if config.contraction_mode == "expand" else "keep"
    )
    category_flags = dict(CONTRACTION_CATEGORY_DEFAULTS)
    for setting_key, category in _CONTRACTION_SETTING_MAP.items():
        default_value = bool(_SETTINGS_DEFAULTS.get(setting_key, True))
        raw_value = settings.get(setting_key, default_value)
        category_flags[category] = _coerce_bool(raw_value, default_value)
    config.contraction_categories = category_flags
    return config


def build_llm_configuration(settings: Mapping[str, Any]) -> LLMConfiguration:
    return LLMConfiguration(
        base_url=str(settings.get("llm_base_url") or ""),
        api_key=str(settings.get("llm_api_key") or ""),
        model=str(settings.get("llm_model") or ""),
        timeout=_coerce_float(
            settings.get("llm_timeout"), float(_SETTINGS_DEFAULTS["llm_timeout"])
        ),
    )


def apply_overrides(
    base: Mapping[str, Any], overrides: Mapping[str, Any]
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in overrides.items():
        if key not in _SETTINGS_DEFAULTS:
            continue
        merged[key] = value
    _apply_llm_migrations(merged)
    return merged
