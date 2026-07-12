"""Invalid plugin: raises ImportError during import."""

from __future__ import annotations

# This plugin intentionally raises an ImportError
raise ImportError("Simulated import error for testing")

# The following code will never be reached, but is here for documentation
from abogen.tts_plugin.manifest import PluginManifest

PLUGIN_MANIFEST = PluginManifest(
    id="import_error",
    name="Import Error Plugin",
    version="1.0.0",
    api_version="1.0",
    description="Plugin that fails to import",
    author="Test Author",
)
