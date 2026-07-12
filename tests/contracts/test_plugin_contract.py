"""Contract tests for plugin contract.

These tests verify that plugin modules satisfy the architectural requirements:
- Must export PLUGIN_MANIFEST: PluginManifest
- Must export MODEL_REQUIREMENTS: list[ModelManifest]
- Must export create_engine: Callable[[HostContext, Path | None, EngineConfig], Engine]
- create_engine() must be atomic
"""

import logging
from pathlib import Path
from typing import Any

import pytest

from abogen.tts_plugin.engine import Engine
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.manifest import EngineManifest, ModelManifest, PluginManifest
from abogen.tts_plugin.plugin import Plugin
from abogen.tts_plugin.types import EngineConfig

from .conftest import FakeEngine


class FakePluginModule:
    """Stub plugin module that satisfies the plugin contract."""

    PLUGIN_MANIFEST = PluginManifest(
        id="fake-plugin",
        name="Fake Plugin",
        version="1.0.0",
        api_version="1.0",
        description="A fake plugin for testing",
        author="Test Author",
        capabilities=(),
        engine=EngineManifest(),
    )

    MODEL_REQUIREMENTS: list[ModelManifest] = []

    @staticmethod
    def create_engine(
        context: HostContext,
        model_path: Path | None,
        config: EngineConfig,
    ) -> Engine:
        return FakeEngine()


class TestPluginProtocolContract:
    """Contract tests for the Plugin protocol."""

    def test_plugin_is_protocol(self) -> None:
        assert hasattr(Plugin, "__protocol_attrs__")


class TestPluginExportsContract:
    """Contract tests for required plugin exports."""

    def test_plugin_has_plugin_manifest(self) -> None:
        """Architecture spec: Plugin must export PLUGIN_MANIFEST."""
        assert hasattr(FakePluginModule, "PLUGIN_MANIFEST")
        assert isinstance(FakePluginModule.PLUGIN_MANIFEST, PluginManifest)

    def test_plugin_has_model_requirements(self) -> None:
        """Architecture spec: Plugin must export MODEL_REQUIREMENTS."""
        assert hasattr(FakePluginModule, "MODEL_REQUIREMENTS")
        assert isinstance(FakePluginModule.MODEL_REQUIREMENTS, list)

    def test_plugin_has_create_engine(self) -> None:
        """Architecture spec: Plugin must export create_engine."""
        assert hasattr(FakePluginModule, "create_engine")
        assert callable(FakePluginModule.create_engine)

    def test_plugin_manifest_required_fields(self) -> None:
        """Architecture spec: PluginManifest has required fields."""
        manifest = FakePluginModule.PLUGIN_MANIFEST
        assert manifest.id
        assert manifest.name
        assert manifest.version
        assert manifest.api_version
        assert manifest.description
        assert manifest.author

    def test_plugin_manifest_capabilities_is_tuple(self) -> None:
        manifest = FakePluginModule.PLUGIN_MANIFEST
        assert isinstance(manifest.capabilities, tuple)


class TestCreateEngineContract:
    """Contract tests for create_engine() function."""

    def test_create_engine_returns_engine(self) -> None:
        """Architecture spec: create_engine() returns Engine."""
        ctx = HostContext(
            config_dir=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            http_client=type("FakeClient", (), {"get": lambda self, **kw: None, "post": lambda self, **kw: None})(),
        )
        engine = FakePluginModule.create_engine(ctx, None, EngineConfig())
        assert isinstance(engine, Engine)

    def test_create_engine_atomic(self) -> None:
        """Architecture spec: create_engine() is atomic (all-or-nothing)."""
        ctx = HostContext(
            config_dir=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            http_client=type("FakeClient", (), {"get": lambda self, **kw: None, "post": lambda self, **kw: None})(),
        )
        engine = FakePluginModule.create_engine(ctx, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    def test_create_engine_with_none_model_path(self) -> None:
        """Architecture spec: model_path can be None for cloud/no-model engines."""
        ctx = HostContext(
            config_dir=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            http_client=type("FakeClient", (), {"get": lambda self, **kw: None, "post": lambda self, **kw: None})(),
        )
        engine = FakePluginModule.create_engine(ctx, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    def test_create_engine_with_model_path(self) -> None:
        """Architecture spec: model_path is Path | None."""
        ctx = HostContext(
            config_dir=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            http_client=type("FakeClient", (), {"get": lambda self, **kw: None, "post": lambda self, **kw: None})(),
        )
        engine = FakePluginModule.create_engine(ctx, Path("/models/test"), EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()


class TestModelRequirementsContract:
    """Contract tests for MODEL_REQUIREMENTS."""

    def test_model_requirements_is_list(self) -> None:
        assert isinstance(FakePluginModule.MODEL_REQUIREMENTS, list)

    def test_model_requirements_contains_model_manifests(self) -> None:
        """If non-empty, each item must be a ModelManifest."""
        for req in FakePluginModule.MODEL_REQUIREMENTS:
            assert isinstance(req, ModelManifest)
