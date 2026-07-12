"""Contract tests for plugin manifest types.

These tests verify that manifest types satisfy the architectural requirements:
- All required fields are present
- api_version follows semver format
- capabilities are properly defined
- engine manifest describes the engine correctly
"""

import re

import pytest

from abogen.tts_plugin.manifest import (
    AudioFormatManifest,
    EngineManifest,
    EnumOption,
    GpuRequirement,
    ModelManifest,
    ParameterManifest,
    PluginManifest,
    RequirementManifest,
    VoiceManifest,
    VoiceSourceManifest,
)


class TestPluginManifestContract:
    """Contract tests for PluginManifest."""

    def test_required_fields(self) -> None:
        manifest = PluginManifest(
            id="test-plugin",
            name="Test Plugin",
            version="1.0.0",
            api_version="1.0",
            description="A test plugin",
            author="Test Author",
        )
        assert manifest.id == "test-plugin"
        assert manifest.name == "Test Plugin"
        assert manifest.version == "1.0.0"
        assert manifest.api_version == "1.0"
        assert manifest.description == "A test plugin"
        assert manifest.author == "Test Author"

    def test_api_version_semver_format(self) -> None:
        """Architecture spec: api_version format is semver (MAJOR.MINOR)."""
        valid_versions = ["1.0", "2.1", "10.5"]
        for version in valid_versions:
            manifest = PluginManifest(
                id="test",
                name="Test",
                version="1.0.0",
                api_version=version,
                description="Test",
                author="Test",
            )
            assert re.match(r"^\d+\.\d+$", manifest.api_version)

    def test_capabilities_default_empty(self) -> None:
        manifest = PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            api_version="1.0",
            description="Test",
            author="Test",
        )
        assert manifest.capabilities == ()

    def test_capabilities_tuple(self) -> None:
        manifest = PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            api_version="1.0",
            description="Test",
            author="Test",
            capabilities=("voice_list", "preview"),
        )
        assert "voice_list" in manifest.capabilities
        assert "preview" in manifest.capabilities

    def test_requires_default(self) -> None:
        manifest = PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            api_version="1.0",
            description="Test",
            author="Test",
        )
        assert isinstance(manifest.requires, RequirementManifest)

    def test_engine_default(self) -> None:
        manifest = PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            api_version="1.0",
            description="Test",
            author="Test",
        )
        assert isinstance(manifest.engine, EngineManifest)


class TestEngineManifestContract:
    """Contract tests for EngineManifest."""

    def test_required_fields(self) -> None:
        manifest = EngineManifest(
            voiceSources=(
                VoiceSourceManifest(id="builtin", name="Builtin", type="list"),
            ),
            parameters=(
                ParameterManifest(
                    id="speed", name="Speed", description="Speed", type="float", default=1.0
                ),
            ),
            audioFormats=(AudioFormatManifest(mime="audio/wav", extension="wav"),),
        )
        assert len(manifest.voiceSources) == 1
        assert len(manifest.parameters) == 1
        assert len(manifest.audioFormats) == 1

    def test_defaults_empty(self) -> None:
        manifest = EngineManifest()
        assert manifest.voiceSources == ()
        assert manifest.parameters == ()
        assert manifest.audioFormats == ()


class TestVoiceSourceManifestContract:
    """Contract tests for VoiceSourceManifest."""

    def test_required_fields(self) -> None:
        vs = VoiceSourceManifest(id="builtin", name="Builtin", type="list")
        assert vs.id == "builtin"
        assert vs.name == "Builtin"
        assert vs.type == "list"

    def test_valid_types(self) -> None:
        valid_types = ["list", "speaker_id", "clone", "blend", "generate", "none"]
        for vtype in valid_types:
            vs = VoiceSourceManifest(id="test", name="Test", type=vtype)
            assert vs.type == vtype

    def test_config_optional(self) -> None:
        vs = VoiceSourceManifest(id="test", name="Test", type="list")
        assert vs.config is None

    def test_config_any(self) -> None:
        config = {"voices": ["af_nova", "af_sky"]}
        vs = VoiceSourceManifest(id="test", name="Test", type="list", config=config)
        assert vs.config == config


class TestVoiceManifestContract:
    """Contract tests for VoiceManifest."""

    def test_required_fields(self) -> None:
        v = VoiceManifest(id="af_nova", name="Nova")
        assert v.id == "af_nova"
        assert v.name == "Nova"

    def test_tags_default_empty(self) -> None:
        v = VoiceManifest(id="af_nova", name="Nova")
        assert v.tags == ()

    def test_tags_tuple(self) -> None:
        v = VoiceManifest(id="af_nova", name="Nova", tags=("en", "female"))
        assert "en" in v.tags
        assert "female" in v.tags


class TestParameterManifestContract:
    """Contract tests for ParameterManifest."""

    def test_required_fields(self) -> None:
        p = ParameterManifest(
            id="speed", name="Speed", description="Speech speed", type="float", default=1.0
        )
        assert p.id == "speed"
        assert p.name == "Speed"
        assert p.description == "Speech speed"
        assert p.type == "float"
        assert p.default == 1.0

    def test_valid_types(self) -> None:
        valid_types = ["float", "int", "string", "boolean", "enum"]
        for ptype in valid_types:
            p = ParameterManifest(
                id="test", name="Test", description="Test", type=ptype, default=None
            )
            assert p.type == ptype

    def test_optional_numeric_bounds(self) -> None:
        p = ParameterManifest(
            id="speed",
            name="Speed",
            description="Speed",
            type="float",
            default=1.0,
            min=0.5,
            max=2.0,
            step=0.1,
        )
        assert p.min == 0.5
        assert p.max == 2.0
        assert p.step == 0.1

    def test_enum_options(self) -> None:
        options = (
            EnumOption(value="low", label="Low"),
            EnumOption(value="high", label="High"),
        )
        p = ParameterManifest(
            id="quality",
            name="Quality",
            description="Quality",
            type="enum",
            default="low",
            options=options,
        )
        assert len(p.options) == 2
        assert p.options[0].value == "low"


class TestAudioFormatManifestContract:
    """Contract tests for AudioFormatManifest."""

    def test_required_fields(self) -> None:
        af = AudioFormatManifest(mime="audio/wav", extension="wav")
        assert af.mime == "audio/wav"
        assert af.extension == "wav"


class TestEnumOptionContract:
    """Contract tests for EnumOption."""

    def test_required_fields(self) -> None:
        opt = EnumOption(value="low", label="Low Quality")
        assert opt.value == "low"
        assert opt.label == "Low Quality"


class TestRequirementManifestContract:
    """Contract tests for RequirementManifest."""

    def test_defaults(self) -> None:
        req = RequirementManifest()
        assert req.gpu is None
        assert req.memory is None
        assert req.internet is None

    def test_with_gpu(self) -> None:
        gpu = GpuRequirement(required=True, type="cuda", memory=8.0)
        req = RequirementManifest(gpu=gpu)
        assert req.gpu.required is True
        assert req.gpu.type == "cuda"
        assert req.gpu.memory == 8.0

    def test_with_internet(self) -> None:
        req = RequirementManifest(internet=True)
        assert req.internet is True


class TestGpuRequirementContract:
    """Contract tests for GpuRequirement."""

    def test_defaults(self) -> None:
        gpu = GpuRequirement()
        assert gpu.required is False
        assert gpu.type is None
        assert gpu.memory is None

    def test_required_gpu(self) -> None:
        gpu = GpuRequirement(required=True, type="cuda", memory=8.0)
        assert gpu.required is True


class TestModelManifestContract:
    """Contract tests for ModelManifest."""

    def test_required_fields(self) -> None:
        m = ModelManifest(id="xtts_v2", name="XTTS v2", size="2GB")
        assert m.id == "xtts_v2"
        assert m.name == "XTTS v2"
        assert m.size == "2GB"
