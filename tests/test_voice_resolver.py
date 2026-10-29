"""Tests for AppVoiceResolver (abogen/application/voice_resolver.py)."""

import logging
from unittest.mock import MagicMock

from abogen.application.conversion_request import ConversionRequest
from abogen.application.voice_resolver import AppVoiceResolver
from abogen.domain.voice_loader import VoiceCache


def _resolver(voice: str, profiles=None, provider: str = "kokoro") -> AppVoiceResolver:
    req = ConversionRequest(direct_text="x", voice=voice, tts_provider=provider, speed=1.0)
    return AppVoiceResolver(req, profiles or {}, MagicMock(), VoiceCache())


class TestResolveLogging:
    """caplog's handler re-raises formatting errors (like RichHandler, the WebUI
    console handler), so unsafe diagnostics on optional values fail here."""

    def test_kokoro_voice_keeps_speed_none(self, caplog):
        caplog.set_level(logging.INFO)

        resolved = _resolver("af_heart").resolve("af_heart")

        assert resolved.provider == "kokoro"
        assert resolved.resolved_spec == "af_heart"
        assert resolved.speed is None
        assert "provider=kokoro resolved=af_heart speed=None" in caplog.text

    def test_supertonic_profile_speed_is_numeric(self, caplog):
        caplog.set_level(logging.INFO)
        profiles = {"Narr": {"provider": "supertonic", "voice": "M1", "speed": 1.25, "total_steps": 5}}

        resolved = _resolver("profile:Narr", profiles, "supertonic").resolve("profile:Narr")

        assert resolved.provider == "supertonic"
        assert resolved.speed == 1.25
        assert "speed=1.25" in caplog.text
