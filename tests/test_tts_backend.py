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
