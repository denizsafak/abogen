"""Comprehensive tests for the plugin loader infrastructure.

These tests verify that the loader correctly:
- Discovers plugins in directories
- Imports plugin modules
- Validates PLUGIN_MANIFEST, MODEL_REQUIREMENTS, create_engine
- Validates api_version compatibility
- Validates capabilities
- Provides diagnostic messages for errors
- Rejects invalid plugins
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from abogen.tts_plugin.loader import (
    HOST_API_VERSION,
    PluginLoadError,
    PluginLoadResult,
    _check_api_version_compatibility,
    _parse_api_version,
    _validate_api_version,
    _validate_capabilities,
    _validate_manifest,
    discover_plugins,
    load_plugin,
    load_plugin_from_dir,
)
from abogen.tts_plugin.manifest import (
    EngineManifest,
    ModelManifest,
    PluginManifest,
)


# ──────────────────────────────────────────────────────────────
# Path fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def plugins_dir() -> Path:
    return Path(__file__).parent.parent / "plugins"


@pytest.fixture
def fake_plugin_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "fake_plugin"


@pytest.fixture
def missing_manifest_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "missing_manifest"


@pytest.fixture
def invalid_api_version_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "invalid_api_version"


@pytest.fixture
def invalid_capabilities_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "invalid_capabilities"


@pytest.fixture
def missing_create_engine_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "missing_create_engine"


@pytest.fixture
def import_error_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "import_error"


@pytest.fixture
def missing_model_requirements_dir(plugins_dir: Path) -> Path:
    return plugins_dir / "missing_model_requirements"


# ──────────────────────────────────────────────────────────────
# Unit tests: _parse_api_version
# ──────────────────────────────────────────────────────────────

class TestParseApiVersion:
    def test_valid_version(self) -> None:
        assert _parse_api_version("1.0") == (1, 0)
        assert _parse_api_version("2.5") == (2, 5)
        assert _parse_api_version("10.20") == (10, 20)

    def test_invalid_format(self) -> None:
        assert _parse_api_version("1") is None
        assert _parse_api_version("1.0.0") is None
        assert _parse_api_version("abc") is None
        assert _parse_api_version("") is None
        assert _parse_api_version("1.x") is None


# ──────────────────────────────────────────────────────────────
# Unit tests: _check_api_version_compatibility
# ──────────────────────────────────────────────────────────────

class TestCheckApiVersionCompatibility:
    def test_compatible_version(self) -> None:
        assert _check_api_version_compatibility("1.0") is None
        assert _check_api_version_compatibility("1.5") is None

    def test_major_mismatch(self) -> None:
        error = _check_api_version_compatibility("2.0")
        assert error is not None
        assert "major mismatch" in error

    def test_invalid_format(self) -> None:
        error = _check_api_version_compatibility("invalid")
        assert error is not None
        assert "Invalid api_version format" in error


# ──────────────────────────────────────────────────────────────
# Unit tests: _validate_manifest
# ──────────────────────────────────────────────────────────────

class TestValidateManifest:
    def test_valid_manifest(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            MODEL_REQUIREMENTS: list = []
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert errors == []

    def test_missing_manifest(self) -> None:
        class FakeModule:
            MODEL_REQUIREMENTS: list = []
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("Missing PLUGIN_MANIFEST" in e for e in errors)

    def test_wrong_manifest_type(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = "not a manifest"
            MODEL_REQUIREMENTS: list = []
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("PluginManifest instance" in e for e in errors)

    def test_missing_model_requirements(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("Missing MODEL_REQUIREMENTS" in e for e in errors)

    def test_wrong_model_requirements_type(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            MODEL_REQUIREMENTS = "not a list"
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("must be a list" in e for e in errors)

    def test_invalid_model_requirements_item(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            MODEL_REQUIREMENTS = ["not a model manifest"]
            create_engine = lambda *a, **kw: None

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("ModelManifest instance" in e for e in errors)

    def test_missing_create_engine(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            MODEL_REQUIREMENTS: list = []

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("Missing create_engine" in e for e in errors)

    def test_create_engine_not_callable(self) -> None:
        class FakeModule:
            PLUGIN_MANIFEST = PluginManifest(
                id="test", name="Test", version="1.0.0",
                api_version="1.0", description="Test", author="Test",
            )
            MODEL_REQUIREMENTS: list = []
            create_engine = "not callable"

        errors = _validate_manifest(FakeModule(), Path("/tmp"))
        assert any("must be callable" in e for e in errors)


# ──────────────────────────────────────────────────────────────
# Unit tests: _validate_capabilities
# ──────────────────────────────────────────────────────────────

class TestValidateCapabilities:
    def test_valid_capabilities(self) -> None:
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            api_version="1.0", description="Test", author="Test",
            capabilities=("voice_list", "preview"),
        )
        errors = _validate_capabilities(manifest)
        assert errors == []

    def test_unknown_capability(self) -> None:
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            api_version="1.0", description="Test", author="Test",
            capabilities=("voice_list", "unknown_cap"),
        )
        errors = _validate_capabilities(manifest)
        assert any("unknown_cap" in e for e in errors)

    def test_empty_capabilities(self) -> None:
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            api_version="1.0", description="Test", author="Test",
            capabilities=(),
        )
        errors = _validate_capabilities(manifest)
        assert errors == []


# ──────────────────────────────────────────────────────────────
# Unit tests: _validate_api_version
# ──────────────────────────────────────────────────────────────

class TestValidateApiVersion:
    def test_compatible(self) -> None:
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            api_version="1.0", description="Test", author="Test",
        )
        errors = _validate_api_version(manifest)
        assert errors == []

    def test_incompatible(self) -> None:
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            api_version="2.0", description="Test", author="Test",
        )
        errors = _validate_api_version(manifest)
        assert len(errors) > 0


# ──────────────────────────────────────────────────────────────
# Integration tests: load_plugin_from_dir
# ──────────────────────────────────────────────────────────────

class TestLoadPluginFromDir:
    def test_load_valid_plugin(self, fake_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(fake_plugin_dir)
        assert result.success is True
        assert result.manifest is not None
        assert result.manifest.id == "fake_plugin"
        assert result.model_requirements is not None
        assert result.create_engine is not None
        assert result.module is not None
        assert result.error is None

    def test_plugin_satisfies_protocol(self, fake_plugin_dir: Path) -> None:
        from abogen.tts_plugin.engine import Engine
        from abogen.tts_plugin.host_context import HostContext
        import logging

        result = load_plugin_from_dir(fake_plugin_dir)
        assert result.success is True

        # Create engine using the loaded create_engine function
        ctx = HostContext(
            config_dir=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            http_client=type("FakeClient", (), {"get": lambda s, **kw: None, "post": lambda s, **kw: None})(),
        )
        engine = result.create_engine(ctx, None, __import__("abogen.tts_plugin.types", fromlist=["EngineConfig"]).EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        result = load_plugin_from_dir(tmp_path / "nonexistent")
        assert result.success is False
        assert result.error is not None
        assert "does not exist" in result.error.errors[0]

    def test_missing_init_file(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "no_init"
        plugin_dir.mkdir()
        result = load_plugin_from_dir(plugin_dir)
        assert result.success is False
        assert result.error is not None
        assert "__init__.py" in result.error.errors[0]

    def test_import_error(self, import_error_dir: Path) -> None:
        result = load_plugin_from_dir(import_error_dir)
        assert result.success is False
        assert result.error is not None
        assert "Failed to import" in result.error.errors[0]


# ──────────────────────────────────────────────────────────────
# Integration tests: invalid plugins
# ──────────────────────────────────────────────────────────────

class TestInvalidPlugins:
    def test_missing_manifest(self, missing_manifest_dir: Path) -> None:
        result = load_plugin_from_dir(missing_manifest_dir)
        assert result.success is False
        assert result.error is not None
        assert any("Missing PLUGIN_MANIFEST" in e for e in result.error.errors)

    def test_invalid_api_version(self, invalid_api_version_dir: Path) -> None:
        result = load_plugin_from_dir(invalid_api_version_dir)
        assert result.success is False
        assert result.error is not None
        assert any("major mismatch" in e for e in result.error.errors)

    def test_invalid_capabilities(self, invalid_capabilities_dir: Path) -> None:
        result = load_plugin_from_dir(invalid_capabilities_dir)
        assert result.success is False
        assert result.error is not None
        assert any("Unknown capability" in e for e in result.error.errors)

    def test_missing_create_engine(self, missing_create_engine_dir: Path) -> None:
        result = load_plugin_from_dir(missing_create_engine_dir)
        assert result.success is False
        assert result.error is not None
        assert any("Missing create_engine" in e for e in result.error.errors)

    def test_missing_model_requirements(self, missing_model_requirements_dir: Path) -> None:
        result = load_plugin_from_dir(missing_model_requirements_dir)
        assert result.success is False
        assert result.error is not None
        assert any("Missing MODEL_REQUIREMENTS" in e for e in result.error.errors)


# ──────────────────────────────────────────────────────────────
# Integration tests: discover_plugins
# ──────────────────────────────────────────────────────────────

class TestDiscoverPlugins:
    def test_discover_from_valid_dir(self, plugins_dir: Path) -> None:
        results = discover_plugins([plugins_dir])
        # Should find multiple plugins (valid and invalid)
        assert len(results) > 0

    def test_discover_includes_valid_plugin(self, plugins_dir: Path) -> None:
        results = discover_plugins([plugins_dir])
        valid = [r for r in results if r.success]
        assert len(valid) >= 1
        assert any(r.manifest and r.manifest.id == "fake_plugin" for r in valid)

    def test_discover_includes_invalid_plugins(self, plugins_dir: Path) -> None:
        results = discover_plugins([plugins_dir])
        invalid = [r for r in results if not r.success]
        assert len(invalid) >= 1

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        results = discover_plugins([tmp_path / "nonexistent"])
        assert results == []

    def test_discover_multiple_dirs(self, plugins_dir: Path, tmp_path: Path) -> None:
        results = discover_plugins([plugins_dir, tmp_path / "nonexistent"])
        assert len(results) > 0


# ──────────────────────────────────────────────────────────────
# Diagnostic messages tests
# ──────────────────────────────────────────────────────────────

class TestDiagnosticMessages:
    def test_error_contains_plugin_id(self, missing_manifest_dir: Path) -> None:
        result = load_plugin_from_dir(missing_manifest_dir)
        assert result.error is not None
        assert result.error.plugin_id == "missing_manifest"

    def test_error_contains_path(self, missing_manifest_dir: Path) -> None:
        result = load_plugin_from_dir(missing_manifest_dir)
        assert result.error is not None
        assert result.error.path == missing_manifest_dir

    def test_error_contains_messages(self, missing_manifest_dir: Path) -> None:
        result = load_plugin_from_dir(missing_manifest_dir)
        assert result.error is not None
        assert len(result.error.errors) > 0

    def test_multiple_errors(self, invalid_api_version_dir: Path) -> None:
        # This plugin has multiple issues
        result = load_plugin_from_dir(invalid_api_version_dir)
        assert result.error is not None
        # Should have at least the api_version error
        assert len(result.error.errors) >= 1


# ──────────────────────────────────────────────────────────────
# No partial registration tests
# ──────────────────────────────────────────────────────────────

class TestNoPartialRegistration:
    def test_invalid_plugin_no_manifest_attr(self, missing_manifest_dir: Path) -> None:
        """After failed load, module should not remain in sys.modules."""
        result = load_plugin_from_dir(missing_manifest_dir)
        assert result.success is False
        # Module should not be registered
        module_name = f"abogen.tts_plugin._loaded.missing_manifest"
        assert module_name not in sys.modules

    def test_import_error_no_registration(self, import_error_dir: Path) -> None:
        """After import error, module should not remain in sys.modules."""
        result = load_plugin_from_dir(import_error_dir)
        assert result.success is False
        module_name = f"abogen.tts_plugin._loaded.import_error"
        assert module_name not in sys.modules
