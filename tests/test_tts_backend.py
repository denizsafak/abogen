from dataclasses import dataclass

from abogen.tts_backend import TTSBackendMetadata
from abogen.tts_backend_registry import TTSBackendRegistry


class TestTTSBackendMetadata:
    def test_is_frozen_dataclass(self):
        assert dataclass(TTSBackendMetadata)

    def test_fields_are_present(self):
        meta = TTSBackendMetadata(
            id="test",
            name="Test Backend",
            description="A test backend",
        )
        assert meta.id == "test"
        assert meta.name == "Test Backend"
        assert meta.description == "A test backend"

    def test_voices_field_default_empty(self):
        meta = TTSBackendMetadata(
            id="test",
            name="Test",
            description="Test backend",
        )
        assert meta.voices == ()

    def test_voices_field_stored(self):
        meta = TTSBackendMetadata(
            id="test",
            name="Test",
            description="Test backend",
            voices=("v1", "v2"),
        )
        assert meta.voices == ("v1", "v2")

    def test_is_immutable(self):
        import pytest

        meta = TTSBackendMetadata(
            id="kokoro",
            name="Kokoro",
            description="Test",
        )
        with pytest.raises(Exception):
            meta.id = "changed"


class TestTTSBackendRegistry:
    def test_register_and_list(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(id="a", name="A", description="Backend A")
        registry.register(metadata=meta, factory=lambda: None)

        backends = registry.list_backends()
        assert len(backends) == 1
        assert backends[0].id == "a"

    def test_list_multiple(self):
        registry = TTSBackendRegistry()
        meta_a = TTSBackendMetadata(id="a", name="A", description="A")
        meta_b = TTSBackendMetadata(id="b", name="B", description="B")
        registry.register(metadata=meta_a, factory=lambda: None)
        registry.register(metadata=meta_b, factory=lambda: None)

        backends = registry.list_backends()
        ids = [b.id for b in backends]
        assert "a" in ids
        assert "b" in ids

    def test_get_metadata(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(id="x", name="X", description="X backend")
        registry.register(metadata=meta, factory=lambda: None)

        result = registry.get_metadata("x")
        assert result.id == "x"
        assert result.name == "X"

    def test_get_metadata_unknown_raises(self):
        import pytest

        registry = TTSBackendRegistry()
        with pytest.raises(KeyError, match="Unknown backend: nope"):
            registry.get_metadata("nope")

    def test_create_backend(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(id="test", name="Test", description="Test backend")

        def factory(**kwargs):
            return {"created": True, "kwargs": kwargs}

        registry.register(metadata=meta, factory=factory)
        result = registry.create_backend("test", foo="bar")

        assert result == {"created": True, "kwargs": {"foo": "bar"}}

    def test_create_backend_unknown_raises(self):
        import pytest

        registry = TTSBackendRegistry()
        with pytest.raises(KeyError, match="Unknown backend: missing"):
            registry.create_backend("missing")

    def test_register_overwrites(self):
        registry = TTSBackendRegistry()
        meta1 = TTSBackendMetadata(id="x", name="V1", description="First")
        meta2 = TTSBackendMetadata(id="x", name="V2", description="Second")
        registry.register(metadata=meta1, factory=lambda: "v1")
        registry.register(metadata=meta2, factory=lambda: "v2")

        result = registry.get_metadata("x")
        assert result.name == "V2"
        assert registry.create_backend("x") == "v2"


class TestBackendRegistration:
    """Tests that existing backends are auto-registered."""

    def test_import_triggers_registration(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        backends = _registry.list_backends()
        ids = [b.id for b in backends]
        assert "kokoro" in ids
        assert "supertonic" in ids

    def test_kokoro_metadata(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        meta = _registry.get_metadata("kokoro")
        assert meta.id == "kokoro"
        assert meta.name == "Kokoro"
        assert "Kokoro" in meta.description

    def test_supertonic_metadata(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        meta = _registry.get_metadata("supertonic")
        assert meta.id == "supertonic"
        assert meta.name == "SuperTonic"
        assert "SuperTonic" in meta.description

    def test_kokoro_metadata_has_voices(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        meta = _registry.get_metadata("kokoro")
        assert isinstance(meta.voices, tuple)
        assert len(meta.voices) > 0
        assert all(isinstance(v, str) for v in meta.voices)

    def test_supertonic_metadata_has_voices(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        meta = _registry.get_metadata("supertonic")
        assert isinstance(meta.voices, tuple)
        assert len(meta.voices) == 10
        assert meta.voices == ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")

    def test_kokoro_factory_callable(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        factory = _registry._factories["kokoro"]
        assert callable(factory)

    def test_supertonic_factory_callable(self):
        import abogen.tts_backends  # noqa: F401

        from abogen.tts_backend_registry import _registry

        factory = _registry._factories["supertonic"]
        assert callable(factory)

    def test_kokoro_metadata_voices_match_registry(self):
        """Ensure the metadata property on the instance shares voices with registry."""
        from abogen.tts_backends.kokoro import _KOKORO_METADATA
        from abogen.tts_backend_registry import _registry

        registry_meta = _registry.get_metadata("kokoro")
        assert _KOKORO_METADATA is registry_meta
        assert _KOKORO_METADATA.voices == registry_meta.voices

    def test_supertonic_metadata_voices_match_registry(self):
        """Ensure the metadata property on the instance shares voices with registry."""
        from abogen.tts_backends.supertonic import _SUPERTONIC_METADATA
        from abogen.tts_backend_registry import _registry

        registry_meta = _registry.get_metadata("supertonic")
        assert _SUPERTONIC_METADATA is registry_meta
        assert _SUPERTONIC_METADATA.voices == registry_meta.voices


class TestResolveBackendForVoice:
    """Tests for the resolve_backend_for_voice method."""

    def test_empty_spec_returns_fallback(self):
        registry = TTSBackendRegistry()
        assert registry.resolve_backend_for_voice("", fallback="kokoro") == "kokoro"
        assert registry.resolve_backend_for_voice("", fallback="supertonic") == "supertonic"

    def test_none_spec_returns_fallback(self):
        registry = TTSBackendRegistry()
        assert registry.resolve_backend_for_voice(None, fallback="kokoro") == "kokoro"

    def test_kokoro_formula_with_star_returns_kokoro(self):
        registry = TTSBackendRegistry()
        assert registry.resolve_backend_for_voice("af_nova*0.7") == "kokoro"

    def test_kokoro_formula_with_plus_returns_kokoro(self):
        registry = TTSBackendRegistry()
        assert registry.resolve_backend_for_voice("af_nova*0.7+am_liam*0.3") == "kokoro"

    def test_kokoro_voice_id_resolves_to_kokoro(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(
            id="kokoro",
            name="Kokoro",
            description="Kokoro TTS",
            voices=("af_nova", "am_liam"),
        )
        registry.register(metadata=meta, factory=lambda: None)

        assert registry.resolve_backend_for_voice("af_nova") == "kokoro"
        assert registry.resolve_backend_for_voice("am_liam") == "kokoro"

    def test_supertonic_voice_id_resolves_to_supertonic(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(
            id="supertonic",
            name="SuperTonic",
            description="SuperTonic TTS",
            voices=("M1", "M2", "F1", "F2"),
        )
        registry.register(metadata=meta, factory=lambda: None)

        assert registry.resolve_backend_for_voice("M1") == "supertonic"
        assert registry.resolve_backend_for_voice("F2") == "supertonic"

    def test_unknown_voice_returns_fallback(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(
            id="kokoro",
            name="Kokoro",
            description="Kokoro TTS",
            voices=("af_nova",),
        )
        registry.register(metadata=meta, factory=lambda: None)

        assert registry.resolve_backend_for_voice("unknown_voice") == "kokoro"
        assert registry.resolve_backend_for_voice("unknown_voice", fallback="supertonic") == "supertonic"

    def test_case_insensitive_matching(self):
        registry = TTSBackendRegistry()
        meta = TTSBackendMetadata(
            id="supertonic",
            name="SuperTonic",
            description="SuperTonic TTS",
            voices=("M1", "F1"),
        )
        registry.register(metadata=meta, factory=lambda: None)

        assert registry.resolve_backend_for_voice("m1") == "supertonic"
        assert registry.resolve_backend_for_voice("f1") == "supertonic"

    def test_default_fallback_is_kokoro(self):
        registry = TTSBackendRegistry()
        assert registry.resolve_backend_for_voice("unknown") == "kokoro"

    def test_multiple_backends_resolution(self):
        registry = TTSBackendRegistry()
        kokoro_meta = TTSBackendMetadata(
            id="kokoro",
            name="Kokoro",
            description="Kokoro TTS",
            voices=("af_nova",),
        )
        supertonic_meta = TTSBackendMetadata(
            id="supertonic",
            name="SuperTonic",
            description="SuperTonic TTS",
            voices=("M1",),
        )
        registry.register(metadata=kokoro_meta, factory=lambda: None)
        registry.register(metadata=supertonic_meta, factory=lambda: None)

        assert registry.resolve_backend_for_voice("af_nova") == "kokoro"
        assert registry.resolve_backend_for_voice("M1") == "supertonic"

    def test_global_wrapper_resolve_backend_for_voice(self):
        from abogen.tts_backend_registry import resolve_backend_for_voice

        # Test with empty spec
        assert resolve_backend_for_voice("") == "kokoro"

        # Test with formula
        assert resolve_backend_for_voice("af_nova*0.7") == "kokoro"

        # Test with a registered voice
        assert resolve_backend_for_voice("af_nova") == "kokoro"
        assert resolve_backend_for_voice("M1") == "supertonic"
