"""Invalid plugin: incompatible api_version (major version mismatch)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import EngineConfig

# api_version "2.0" has major version 2, but host expects major version 1
PLUGIN_MANIFEST = PluginManifest(
    id="invalid_api_version",
    name="Invalid API Version Plugin",
    version="1.0.0",
    api_version="2.0",  # Major version mismatch!
    description="Plugin with incompatible api_version",
    author="Test Author",
)

MODEL_REQUIREMENTS: list[Any] = []


def create_engine(
    context: Any,
    model_path: Path | None,
    config: EngineConfig,
) -> Any:
    raise NotImplementedError("This plugin is invalid")
