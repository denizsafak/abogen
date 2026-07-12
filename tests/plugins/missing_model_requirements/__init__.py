"""Invalid plugin: missing MODEL_REQUIREMENTS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import EngineConfig

PLUGIN_MANIFEST = PluginManifest(
    id="missing_model_requirements",
    name="Missing Model Requirements Plugin",
    version="1.0.0",
    api_version="1.0",
    description="Plugin missing MODEL_REQUIREMENTS",
    author="Test Author",
)

# This plugin intentionally does NOT export MODEL_REQUIREMENTS


def create_engine(
    context: Any,
    model_path: Path | None,
    config: EngineConfig,
) -> Any:
    raise NotImplementedError("This plugin is invalid")
