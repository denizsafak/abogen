"""Fixtures for auto-discovery plugin tests.

This module provides shared fixtures for testing all plugins:
- plugin_ids: List of all plugin IDs from plugins/ directory
- plugin_dir: Path to a specific plugin directory (parametrized)
- loaded_plugin: Loaded plugin data (manifest, model_requirements, create_engine)
- host_context: Test HostContext with fake HTTP client
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.loader import load_plugin_from_dir


def _discover_plugin_ids() -> list[str]:
    """Discover all plugin IDs from the plugins/ directory.
    
    Returns:
        List of plugin IDs (directory names with __init__.py).
    """
    plugins_dir = Path(__file__).parent.parent.parent / "plugins"
    plugin_ids = []
    if plugins_dir.exists():
        for item in sorted(plugins_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                init_file = item / "__init__.py"
                if init_file.exists():
                    plugin_ids.append(item.name)
    return plugin_ids


@pytest.fixture(scope="module")
def plugins_dir() -> Path:
    """Return the path to the plugins directory."""
    return Path(__file__).parent.parent.parent / "plugins"


@pytest.fixture(scope="module")
def plugin_ids(plugins_dir: Path) -> list[str]:
    """Return a list of all plugin IDs from the plugins/ directory.
    
    This fixture discovers all subdirectories in plugins/ that contain
    an __init__.py file (i.e., valid plugin directories).
    
    Returns:
        List of plugin IDs (directory names).
    """
    return _discover_plugin_ids()


@pytest.fixture(params=_discover_plugin_ids())
def plugin_id(request: pytest.FixtureRequest) -> str:
    """Parametrized fixture returning each plugin ID.
    
    This fixture is parametrized to run tests for each plugin.
    """
    return request.param


@pytest.fixture
def plugin_dir(plugins_dir: Path, plugin_id: str) -> Path:
    """Return the path to a specific plugin directory.
    
    Args:
        plugins_dir: Base plugins directory.
        plugin_id: The plugin ID (directory name).
        
    Returns:
        Path to the plugin directory.
    """
    return plugins_dir / plugin_id


@pytest.fixture
def loaded_plugin(plugin_dir: Path):
    """Load a plugin and return its load result.
    
    This fixture loads the plugin using the loader, providing access to:
    - manifest: PluginManifest
    - model_requirements: tuple[ModelManifest, ...]
    - create_engine: Callable
    - module: The loaded module
    
    Args:
        plugin_dir: Path to the plugin directory.
        
    Returns:
        PluginLoadResult from load_plugin_from_dir.
        
    Raises:
        pytest.skip: If plugin fails to load (should not happen for valid plugins).
    """
    from abogen.tts_plugin.loader import PluginLoadResult
    
    result = load_plugin_from_dir(plugin_dir)
    if not result.success:
        pytest.fail(
            f"Plugin {plugin_dir.name} failed to load: "
            f"{result.error.errors if result.error else 'Unknown error'}"
        )
    return result


@pytest.fixture
def host_context(tmp_path: Path) -> HostContext:
    """Create a test HostContext with fake HTTP client.
    
    Args:
        tmp_path: Pytest tmp_path fixture for config directory.
        
    Returns:
        HostContext with fake HTTP client and test logger.
    """
    class FakeHttpClient:
        """Fake HTTP client for testing."""
        
        def get(self, url: str, **kwargs: object) -> object:
            """Fake GET request."""
            return None
        
        def post(self, url: str, **kwargs: object) -> object:
            """Fake POST request."""
            return None
    
    return HostContext(
        config_dir=tmp_path,
        logger=logging.getLogger("test"),
        http_client=FakeHttpClient(),
    )


@pytest.fixture
def engine_config() -> Any:
    """Return a default EngineConfig for testing.
    
    Returns:
        EngineConfig with device="cpu" for testing.
    """
    from abogen.tts_plugin.types import EngineConfig
    return EngineConfig(device="cpu")


@pytest.fixture
def create_engine(loaded_plugin, host_context, engine_config):
    """Create an engine instance from a loaded plugin.
    
    This fixture creates an engine and ensures proper cleanup via dispose.
    
    Args:
        loaded_plugin: Loaded plugin result.
        host_context: Test HostContext.
        engine_config: EngineConfig for engine creation.
        
    Yields:
        Engine instance.
    """
    from abogen.tts_plugin.engine import Engine
    
    engine = loaded_plugin.create_engine(host_context, None, engine_config)
    assert isinstance(engine, Engine)
    yield engine
    engine.dispose()