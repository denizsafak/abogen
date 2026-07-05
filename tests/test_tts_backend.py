from dataclasses import dataclass

from abogen.tts_backend import TTSBackendMetadata


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
