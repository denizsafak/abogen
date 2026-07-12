"""Invalid plugin: unknown capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import EngineConfig

PLUGIN_MANIFEST = PluginManifest(
    id="invalid_capabilities",
    name="Invalid Capabilities Plugin",
    version="1.0.0",
    api_version="1.0",
    description="Plugin with unknown capabilities",
    author="Test Author",
    capabilities=("voice_list", "unknown_capability", "another_unknown"),
)

MODEL_REQUIREMENTS: list[Any] = []


def create_engine(
    context: Any,
    model_path: Path | None,
    config: EngineConfig,
) -> Any:
    raise NotImplementedError("This plugin is invalid")
