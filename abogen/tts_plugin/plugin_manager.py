"""Plugin Manager

Provides a simple interface for consumers to access TTS engines via the
new Plugin Architecture. Discovers, loads, and manages plugins from the
plugins directory.

Usage:
    from abogen.tts_plugin.plugin_manager import get_plugin_manager

    manager = get_plugin_manager()
    engine = manager.create_engine("kokoro", lang_code="a", device="cpu")
    session = engine.create_session()
    try:
        result = session.synthesize("Hello world")
    finally:
        session.dispose()
"""

from typing import Any, Dict, List, Optional, Type

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import AudioFormat


class PluginManager:
    """Manages TTS plugins and provides a simple interface for consumers."""

    def __init__(self) -> None:
        self._plugins: Dict[str, dict] = {}
        self._engines: Dict[str, Engine] = {}
        self._loaded = False

    def discover(self, plugins_dir: str = "plugins") -> None:
        """Discover and load all plugins from the given directory."""
        import os
        from pathlib import Path
        from abogen.tts_plugin.loader import load_plugin_from_dir

        self._plugins.clear()
        self._engines.clear()

        plugins_path = Path(plugins_dir)
        if not plugins_path.exists():
            self._loaded = True
            return

        for entry in plugins_path.iterdir():
            if entry.is_dir() and (entry / "__init__.py").exists():
                try:
                    result = load_plugin_from_dir(entry)
                    if result.success and result.manifest is not None:
                        self._plugins[result.manifest.id] = {
                            "manifest": result.manifest,
                            "create_engine": result.create_engine,
                            "module": result.module,
                        }
                except Exception as e:
                    # Log error but continue with other plugins
                    print(f"Warning: Failed to load plugin from {entry}: {e}")

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Ensure plugins have been discovered."""
        if not self._loaded:
            self.discover()

    def list_plugins(self) -> List[PluginManifest]:
        """Return manifests for all loaded plugins."""
        self._ensure_loaded()
        return [info["manifest"] for info in self._plugins.values()]

    def get_plugin(self, plugin_id: str) -> Optional[dict]:
        """Get plugin info by ID."""
        self._ensure_loaded()
        return self._plugins.get(plugin_id)

    def has_plugin(self, plugin_id: str) -> bool:
        """Check if a plugin is loaded."""
        self._ensure_loaded()
        return plugin_id in self._plugins

    def create_engine(self, plugin_id: str, **kwargs: Any) -> Engine:
        """Create an engine instance for the given plugin.

        Args:
            plugin_id: The plugin identifier (e.g., "kokoro")
            **kwargs: Arguments passed to the engine constructor

        Returns:
            An Engine instance

        Raises:
            KeyError: If plugin_id is not found
            Exception: If engine creation fails
        """
        self._ensure_loaded()

        if plugin_id not in self._plugins:
            raise KeyError(f"Plugin not found: {plugin_id}")

        plugin_info = self._plugins[plugin_id]
        create_engine_func = plugin_info["create_engine"]

        # Create engine using the plugin's factory
        engine = create_engine_func(**kwargs)
        return engine

    def get_or_create_engine(self, plugin_id: str, **kwargs: Any) -> Engine:
        """Get an existing engine or create a new one.

        Engines are cached by plugin_id. If you need multiple instances
        with different parameters, use create_engine() directly.
        """
        self._ensure_loaded()

        cache_key = plugin_id
        if cache_key in self._engines:
            return self._engines[cache_key]

        engine = self.create_engine(plugin_id, **kwargs)
        self._engines[cache_key] = engine
        return engine

    def dispose_all(self) -> None:
        """Dispose all cached engines."""
        for engine in self._engines.values():
            try:
                engine.dispose()
            except Exception:
                pass  # dispose() should never raise
        self._engines.clear()


# Global singleton
_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get the global PluginManager instance."""
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager


def reset_plugin_manager() -> None:
    """Reset the global PluginManager (for testing)."""
    global _manager
    if _manager is not None:
        _manager.dispose_all()
    _manager = None
