"""Tests for voice profile language resolution."""

from __future__ import annotations

from abogen.domain.enums import Language
from abogen.voice_profiles import resolve_profile_language


class TestResolveProfileLanguage:

    def test_iso_code(self) -> None:
        assert resolve_profile_language({"language": "en-US"}) == Language.EN_US
        assert resolve_profile_language({"language": "es"}) == Language.ES

    def test_enum_value(self) -> None:
        assert resolve_profile_language({"language": Language.ZH}) == Language.ZH

    def test_legacy_kokoro_letter(self) -> None:
        assert resolve_profile_language({"language": "a"}) == Language.EN_US
        assert resolve_profile_language({"language": "e"}) == Language.ES
        assert resolve_profile_language({"language": "z"}) == Language.ZH

    def test_missing_or_unparseable_falls_back(self) -> None:
        assert resolve_profile_language({}) == Language.EN_US
        assert resolve_profile_language({"language": ""}) == Language.EN_US
        assert resolve_profile_language({"language": "xx"}) == Language.EN_US
        assert resolve_profile_language(None) == Language.EN_US
        assert resolve_profile_language([]) == Language.EN_US