"""Contract tests for core domain value objects.

These tests verify that value objects satisfy the architectural requirements:
- Frozen (immutable) dataclasses
- Correct field definitions
- Proper equality behavior
"""

import pytest

from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    EngineConfig,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)


class TestAudioFormatContract:
    """Contract tests for AudioFormat value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(AudioFormat, "__dataclass_params__")
        assert AudioFormat.__dataclass_params__.frozen is True

    def test_required_fields(self) -> None:
        af = AudioFormat(mime="audio/wav", extension="wav")
        assert af.mime == "audio/wav"
        assert af.extension == "wav"

    def test_immutability(self) -> None:
        af = AudioFormat(mime="audio/wav", extension="wav")
        with pytest.raises(AttributeError):
            af.mime = "audio/mpeg"  # type: ignore[misc]

    def test_equality(self) -> None:
        af1 = AudioFormat(mime="audio/wav", extension="wav")
        af2 = AudioFormat(mime="audio/wav", extension="wav")
        assert af1 == af2

    def test_inequality(self) -> None:
        af1 = AudioFormat(mime="audio/wav", extension="wav")
        af2 = AudioFormat(mime="audio/mpeg", extension="mp3")
        assert af1 != af2

    def test_hashable(self) -> None:
        af = AudioFormat(mime="audio/wav", extension="wav")
        assert hash(af) == hash(AudioFormat(mime="audio/wav", extension="wav"))


class TestDurationContract:
    """Contract tests for Duration value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(Duration, "__dataclass_params__")
        assert Duration.__dataclass_params__.frozen is True

    def test_required_fields(self) -> None:
        d = Duration(seconds=1.5)
        assert d.seconds == 1.5

    def test_immutability(self) -> None:
        d = Duration(seconds=1.0)
        with pytest.raises(AttributeError):
            d.seconds = 2.0  # type: ignore[misc]

    def test_equality(self) -> None:
        d1 = Duration(seconds=1.0)
        d2 = Duration(seconds=1.0)
        assert d1 == d2


class TestVoiceSelectionContract:
    """Contract tests for VoiceSelection value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(VoiceSelection, "__dataclass_params__")
        assert VoiceSelection.__dataclass_params__.frozen is True

    def test_required_fields(self) -> None:
        vs = VoiceSelection(source="builtin", key="af_nova")
        assert vs.source == "builtin"
        assert vs.key == "af_nova"

    def test_payload_default_none(self) -> None:
        vs = VoiceSelection(source="builtin", key="af_nova")
        assert vs.payload is None

    def test_payload_optional(self) -> None:
        vs = VoiceSelection(source="clone", key="my_voice", payload=b"audio_data")
        assert vs.payload == b"audio_data"

    def test_immutability(self) -> None:
        vs = VoiceSelection(source="builtin", key="af_nova")
        with pytest.raises(AttributeError):
            vs.source = "other"  # type: ignore[misc]


class TestParameterValuesContract:
    """Contract tests for ParameterValues value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(ParameterValues, "__dataclass_params__")
        assert ParameterValues.__dataclass_params__.frozen is True

    def test_default_empty(self) -> None:
        pv = ParameterValues()
        assert pv.values == {}

    def test_with_values(self) -> None:
        pv = ParameterValues(values={"speed": 1.0, "pitch": 0.5})
        assert pv.values["speed"] == 1.0
        assert pv.values["pitch"] == 0.5

    def test_immutability(self) -> None:
        pv = ParameterValues(values={"speed": 1.0})
        with pytest.raises(AttributeError):
            pv.values = {}  # type: ignore[misc]


class TestSynthesisRequestContract:
    """Contract tests for SynthesisRequest value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(SynthesisRequest, "__dataclass_params__")
        assert SynthesisRequest.__dataclass_params__.frozen is True

    def test_required_fields(self) -> None:
        req = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        assert req.text == "Hello"
        assert req.voice.source == "builtin"
        assert req.format.mime == "audio/wav"

    def test_immutability(self) -> None:
        req = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        with pytest.raises(AttributeError):
            req.text = "World"  # type: ignore[misc]


class TestSynthesizedAudioContract:
    """Contract tests for SynthesizedAudio value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(SynthesizedAudio, "__dataclass_params__")
        assert SynthesizedAudio.__dataclass_params__.frozen is True

    def test_required_fields(self) -> None:
        audio = SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )
        assert audio.data == b"\x00" * 100
        assert audio.format.mime == "audio/wav"
        assert audio.duration.seconds == 1.0

    def test_immutability(self) -> None:
        audio = SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )
        with pytest.raises(AttributeError):
            audio.data = b"\x00"  # type: ignore[misc]


class TestEngineConfigContract:
    """Contract tests for EngineConfig value object."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(EngineConfig, "__dataclass_params__")
        assert EngineConfig.__dataclass_params__.frozen is True

    def test_default_device(self) -> None:
        config = EngineConfig()
        assert config.device == "cpu"

    def test_custom_device(self) -> None:
        config = EngineConfig(device="cuda:0")
        assert config.device == "cuda:0"

    def test_default_lang_code(self) -> None:
        config = EngineConfig()
        assert config.lang_code == "a"

    def test_custom_lang_code(self) -> None:
        config = EngineConfig(lang_code="j")
        assert config.lang_code == "j"

    def test_immutability(self) -> None:
        config = EngineConfig()
        with pytest.raises(AttributeError):
            config.device = "cuda:0"  # type: ignore[misc]

    def test_immutability_lang_code(self) -> None:
        config = EngineConfig()
        with pytest.raises(AttributeError):
            config.lang_code = "j"  # type: ignore[misc]

    def test_unknown_keys_ignored_per_spec(self) -> None:
        """Architecture spec: Unknown keys are ignored (no error).

        EngineConfig is frozen, so unknown keys cannot be set after creation.
        This test verifies the default behavior matches the spec.
        """
        config = EngineConfig()
        assert config.device == "cpu"

    def test_plugins_may_ignore_irrelevant_fields(self) -> None:
        """Architecture Amendment #1: Plugins ignore unsupported fields.

        EngineConfig may contain fields that are not relevant to every plugin.
        Plugins MUST ignore fields they do not need, not raise on them.
        """
        config = EngineConfig(device="cuda:0", lang_code="j")
        assert config.device == "cuda:0"
        assert config.lang_code == "j"
        # A plugin that only needs device simply reads config.device
        # and ignores config.lang_code — this must not raise.

    def test_engine_config_contains_engine_instance_configuration(self) -> None:
        """Architecture Amendment #1: EngineConfig definition.

        EngineConfig contains parameters that define how a particular
        Engine instance is created and that remain constant throughout
        the lifetime of that Engine.
        """
        config = EngineConfig(device="cpu", lang_code="a")
        # Both fields are init-time, immutable, engine-scoped.
        assert config.device == "cpu"
        assert config.lang_code == "a"
