"""Plugin contract for the TTS Plugin Architecture.

This module defines the plugin contract that all TTS plugins must implement.
Each plugin must export:
- PLUGIN_MANIFEST: PluginManifest instance
- MODEL_REQUIREMENTS: list of ModelManifest instances
- create_engine(): Factory function that creates an Engine

The create_engine() function is the entry point for plugin activation.
It must be atomic: succeed fully or raise and clean up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from abogen.tts_plugin.engine import Engine
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.types import EngineConfig


@runtime_checkable
class Plugin(Protocol):
    """Protocol defining the plugin contract.

    Every TTS plugin must implement this protocol by exporting:
    - PLUGIN_MANIFEST: PluginManifest
    - MODEL_REQUIREMENTS: list[ModelManifest]
    - create_engine: Callable[[HostContext, Path | None, EngineConfig], Engine]
    """

    def create_engine(
        self,
        context: HostContext,
        model_path: Path | None,
        config: EngineConfig,
    ) -> Engine:
        """Create an engine instance.

        This is the factory function that creates an Engine from a plugin.
        It must be atomic: succeed fully or raise EngineError and clean up.

        Args:
            context: Host services (config dir, logger, http client).
            model_path: Resolved model path, or None for cloud/no-model engines.
            config: Engine initialization settings.

        Returns:
            A fully initialized Engine instance.

        Raises:
            EngineError: On failure. Cleans up partially created resources.
        """
        ...
