"""Invalid plugin: missing create_engine function."""

from __future__ import annotations

from abogen.tts_plugin.manifest import PluginManifest

PLUGIN_MANIFEST = PluginManifest(
    id="missing_create_engine",
    name="Missing Create Engine Plugin",
    version="1.0.0",
    api_version="1.0",
    description="Plugin missing create_engine",
    author="Test Author",
)

MODEL_REQUIREMENTS: list = []

# This plugin intentionally does NOT export create_engine
