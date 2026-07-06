import pytest

from abogen.voice_metadata import VoiceMetadata


class TestVoiceMetadataCreation:
    def test_create_with_all_fields(self):
        voice = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        assert voice.id == "af_alloy"
        assert voice.display_name == "Alloy"
        assert voice.language == "a"
        assert voice.gender == "female"
        assert voice.backend_id == "kokoro"

    def test_create_supertonic_voice(self):
        voice = VoiceMetadata(
            id="M1",
            display_name="Male 1",
            language="en",
            gender="male",
            backend_id="supertonic",
        )
        assert voice.id == "M1"
        assert voice.backend_id == "supertonic"

    def test_create_with_unknown_gender(self):
        voice = VoiceMetadata(
            id="custom_voice",
            display_name="Custom",
            language="en",
            gender="unknown",
            backend_id="custom_backend",
        )
        assert voice.gender == "unknown"


class TestVoiceMetadataImmutability:
    def test_frozen_dataclass(self):
        voice = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        with pytest.raises(AttributeError):
            voice.id = "new_id"

    def test_cannot_modify_display_name(self):
        voice = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        with pytest.raises(AttributeError):
            voice.display_name = "New Name"

    def test_cannot_modify_backend_id(self):
        voice = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        with pytest.raises(AttributeError):
            voice.backend_id = "new_backend"


class TestVoiceMetadataEquality:
    def test_equal_voices_are_equal(self):
        voice1 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        voice2 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        assert voice1 == voice2

    def test_different_voices_are_not_equal(self):
        voice1 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        voice2 = VoiceMetadata(
            id="am_adam",
            display_name="Adam",
            language="a",
            gender="male",
            backend_id="kokoro",
        )
        assert voice1 != voice2

    def test_different_backend_id_not_equal(self):
        voice1 = VoiceMetadata(
            id="custom",
            display_name="Custom",
            language="en",
            gender="unknown",
            backend_id="backend_a",
        )
        voice2 = VoiceMetadata(
            id="custom",
            display_name="Custom",
            language="en",
            gender="unknown",
            backend_id="backend_b",
        )
        assert voice1 != voice2


class TestVoiceMetadataHashing:
    def test_hashable(self):
        voice = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        assert hash(voice) is not None

    def test_equal_voices_same_hash(self):
        voice1 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        voice2 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        assert hash(voice1) == hash(voice2)

    def test_usable_in_set(self):
        voice1 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        voice2 = VoiceMetadata(
            id="af_alloy",
            display_name="Alloy",
            language="a",
            gender="female",
            backend_id="kokoro",
        )
        voice3 = VoiceMetadata(
            id="am_adam",
            display_name="Adam",
            language="a",
            gender="male",
            backend_id="kokoro",
        )
        voice_set = {voice1, voice2, voice3}
        assert len(voice_set) == 2


class TestVoiceMetadataUseCases:
    def test_backend_populates_backend_id(self):
        """Simulate how a backend would populate backend_id automatically."""

        class MockBackend:
            def __init__(self):
                self._backend_id = "kokoro"

            def get_voices(self):
                return [
                    VoiceMetadata(
                        id="af_alloy",
                        display_name="Alloy",
                        language="a",
                        gender="female",
                        backend_id=self._backend_id,
                    ),
                ]

        backend = MockBackend()
        voices = backend.get_voices()
        assert voices[0].backend_id == "kokoro"

    def test_filter_by_language(self):
        voices = [
            VoiceMetadata(id="af_alloy", display_name="Alloy", language="a", gender="female", backend_id="kokoro"),
            VoiceMetadata(id="jf_alpha", display_name="Alpha", language="j", gender="female", backend_id="kokoro"),
            VoiceMetadata(id="am_adam", display_name="Adam", language="a", gender="male", backend_id="kokoro"),
        ]
        english_voices = [v for v in voices if v.language == "a"]
        assert len(english_voices) == 2

    def test_filter_by_gender(self):
        voices = [
            VoiceMetadata(id="af_alloy", display_name="Alloy", language="a", gender="female", backend_id="kokoro"),
            VoiceMetadata(id="am_adam", display_name="Adam", language="a", gender="male", backend_id="kokoro"),
            VoiceMetadata(id="am_puck", display_name="Puck", language="a", gender="male", backend_id="kokoro"),
        ]
        male_voices = [v for v in voices if v.gender == "male"]
        assert len(male_voices) == 2

    def test_filter_by_backend(self):
        voices = [
            VoiceMetadata(id="af_alloy", display_name="Alloy", language="a", gender="female", backend_id="kokoro"),
            VoiceMetadata(id="M1", display_name="Male 1", language="en", gender="male", backend_id="supertonic"),
        ]
        kokoro_voices = [v for v in voices if v.backend_id == "kokoro"]
        assert len(kokoro_voices) == 1
        assert kokoro_voices[0].id == "af_alloy"
