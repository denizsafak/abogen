"""Intro/outro text building and voice resolution for audiobook conversion.

Both UIs (WebUI and Desktop) need to:
1. Build intro/outro text from book metadata
2. Resolve which voice to use for intro/outro synthesis

This module provides the shared domain logic. The actual TTS synthesis
and audio writing remain UI-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from abogen.domain.title_builder import build_title_intro_text, build_outro_text
from abogen.domain.voice_resolution import resolve_fallback_voice_spec


@dataclass
class IntroOutroSpec:
    """Resolved intro or outro specification ready for TTS synthesis."""
    text: str
    voice_spec: str
    enabled: bool


def resolve_intro(
    metadata: Optional[Dict[str, Any]],
    original_filename: str,
    read_title_intro: bool,
    base_voice_spec: str,
    job_voice: str,
    voice_cache_keys: list[str],
) -> IntroOutroSpec:
    """Resolve the intro specification from job settings and metadata.

    Returns an IntroOutroSpec with text and voice_spec populated,
    or enabled=False if intro is disabled or text cannot be built.
    """
    if not read_title_intro:
        return IntroOutroSpec(text="", voice_spec="", enabled=False)

    text = build_title_intro_text(metadata, original_filename)
    if not text:
        return IntroOutroSpec(text="", voice_spec="", enabled=False)

    voice_spec = resolve_fallback_voice_spec(
        base_voice_spec, job_voice, voice_cache_keys
    )
    if not voice_spec:
        return IntroOutroSpec(text=text, voice_spec="", enabled=False)

    return IntroOutroSpec(text=text, voice_spec=voice_spec, enabled=True)


def resolve_outro(
    metadata: Optional[Dict[str, Any]],
    original_filename: str,
    read_closing_outro: bool,
    base_voice_spec: str,
    job_voice: str,
    voice_cache_keys: list[str],
) -> IntroOutroSpec:
    """Resolve the outro specification from job settings and metadata.

    Returns an IntroOutroSpec with text and voice_spec populated,
    or enabled=False if outro is disabled or text cannot be built.
    """
    if not read_closing_outro:
        return IntroOutroSpec(text="", voice_spec="", enabled=False)

    text = build_outro_text(metadata, original_filename)
    if not text:
        return IntroOutroSpec(text="", voice_spec="", enabled=False)

    voice_spec = resolve_fallback_voice_spec(
        base_voice_spec, job_voice, voice_cache_keys
    )
    if not voice_spec:
        return IntroOutroSpec(text=text, voice_spec="", enabled=False)

    return IntroOutroSpec(text=text, voice_spec=voice_spec, enabled=True)
