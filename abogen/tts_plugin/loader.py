"""Plugin loader infrastructure for the TTS Plugin Architecture.

This module provides functionality to discover, import, validate, and load
TTS plugins. It handles both valid and invalid plugins, providing diagnostic
messages for errors.

The loader does NOT:
- Create Engine instances (that's the plugin's create_engine() responsibility)
- Manage plugin lifecycle (that's the Plugin Manager's responsibility)
- Implement any TTS engine functionality
"""

from __future__ import annotations

import importlib
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from abogen.tts_plugin.manifest import ModelManifest, PluginManifest


# Host API version for compatibility checking
HOST_API_VERSION = "1.0"


@dataclass(frozen=True)
class PluginLoadError:
    """Diagnostic information for a failed plugin load.

    Attributes:
        plugin_id: Plugin identifier if available, otherwise directory name.
        path: Path to the plugin directory.
        errors: List of error messages describing what went wrong.
    """

    plugin_id: str
    path: Path
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginLoadResult:
    """Result of loading a plugin.

    Attributes:
        success: Whether the plugin loaded successfully.
        manifest: The plugin manifest if successful.
        model_requirements: Model requirements if successful.
        create_engine: The create_engine function if successful.
        module: The plugin module if successful.
        error: Error information if failed.
    """

    success: bool
    manifest: PluginManifest | None = None
    model_requirements: tuple[ModelManifest, ...] | None = None
    create_engine: Callable[..., Any] | None = None
    module: types.ModuleType | None = None
    error: PluginLoadError | None = None


def _parse_api_version(version: str) -> tuple[int, int] | None:
    """Parse an api_version string into (major, minor) tuple.

    Args:
        version: Version string in format "MAJOR.MINOR".

    Returns:
        Tuple of (major, minor) or None if invalid format.
    """
    match = re.match(r"^(\d+)\.(\d+)$", version)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _check_api_version_compatibility(plugin_version: str) -> str | None:
    """Check if plugin api_version is compatible with host.

    Architecture spec:
    - Format: semver (MAJOR.MINOR)
    - Compatibility: Host rejects plugin if major version differs
    - Minor version: backward compatible, Host accepts higher minor

    Args:
        plugin_version: Plugin's api_version string.

    Returns:
        Error message if incompatible, None if compatible.
    """
    plugin_ver = _parse_api_version(plugin_version)
    if plugin_ver is None:
        return f"Invalid api_version format: '{plugin_version}'. Expected format: MAJOR.MINOR"

    host_ver = _parse_api_version(HOST_API_VERSION)
    if host_ver is None:
        return f"Invalid host api_version format: '{HOST_API_VERSION}'"

    if plugin_ver[0] != host_ver[0]:
        return (
            f"api_version major mismatch: plugin={plugin_ver[0]}, host={host_ver[0]}. "
            f"Major version must match for compatibility."
        )

    return None


def _validate_manifest(module: types.ModuleType, plugin_dir: Path) -> list[str]:
    """Validate that a plugin module has required exports.

    Args:
        module: The imported plugin module.
        plugin_dir: Path to the plugin directory.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    # Check PLUGIN_MANIFEST
    manifest = getattr(module, "PLUGIN_MANIFEST", None)
    if manifest is None:
        errors.append("Missing PLUGIN_MANIFEST export")
    elif not isinstance(manifest, PluginManifest):
        errors.append(
            f"PLUGIN_MANIFEST must be a PluginManifest instance, "
            f"got {type(manifest).__name__}"
        )

    # Check MODEL_REQUIREMENTS
    model_reqs = getattr(module, "MODEL_REQUIREMENTS", None)
    if model_reqs is None:
        errors.append("Missing MODEL_REQUIREMENTS export")
    elif not isinstance(model_reqs, list):
        errors.append(
            f"MODEL_REQUIREMENTS must be a list, got {type(model_reqs).__name__}"
        )
    else:
        for i, req in enumerate(model_reqs):
            if not isinstance(req, ModelManifest):
                errors.append(
                    f"MODEL_REQUIREMENTS[{i}] must be a ModelManifest instance, "
                    f"got {type(req).__name__}"
                )

    # Check create_engine
    create_engine = getattr(module, "create_engine", None)
    if create_engine is None:
        errors.append("Missing create_engine export")
    elif not callable(create_engine):
        errors.append(
            f"create_engine must be callable, got {type(create_engine).__name__}"
        )

    return errors


def _validate_capabilities(manifest: PluginManifest) -> list[str]:
    """Validate plugin capabilities.

    Args:
        manifest: The plugin manifest to validate.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    # Known capabilities (can be extended)
    known_capabilities = frozenset({
        "voice_list",
        "preview",
        "voice_clone",
        "voice_blend",
        "streaming",
        "cancel",
    })

    for cap in manifest.capabilities:
        if cap not in known_capabilities:
            errors.append(f"Unknown capability: '{cap}'")

    return errors


def _validate_api_version(manifest: PluginManifest) -> list[str]:
    """Validate api_version compatibility.

    Args:
        manifest: The plugin manifest to validate.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    error = _check_api_version_compatibility(manifest.api_version)
    if error:
        errors.append(error)
    return errors


def load_plugin_from_dir(plugin_dir: Path) -> PluginLoadResult:
    """Load and validate a plugin from a directory.

    The plugin directory must contain an __init__.py that exports:
    - PLUGIN_MANIFEST: PluginManifest
    - MODEL_REQUIREMENTS: list[ModelManifest]
    - create_engine: Callable

    Args:
        plugin_dir: Path to the plugin directory.

    Returns:
        PluginLoadResult with success status and either plugin data or error info.
    """
    plugin_id = plugin_dir.name
    errors: list[str] = []

    # Check if directory exists
    if not plugin_dir.exists():
        return PluginLoadResult(
            success=False,
            error=PluginLoadError(
                plugin_id=plugin_id,
                path=plugin_dir,
                errors=(f"Plugin directory does not exist: {plugin_dir}",),
            ),
        )

    # Check for __init__.py
    init_file = plugin_dir / "__init__.py"
    if not init_file.exists():
        return PluginLoadResult(
            success=False,
            error=PluginLoadError(
                plugin_id=plugin_id,
                path=plugin_dir,
                errors=("Missing __init__.py in plugin directory",),
            ),
        )

    # Import the module
    module_name = f"abogen.tts_plugin._loaded.{plugin_id}"
    try:
        # Remove from cache if already imported (for testing)
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(
            module_name, init_file, submodule_search_locations=[]
        )
        if spec is None or spec.loader is None:
            return PluginLoadResult(
                success=False,
                error=PluginLoadError(
                    plugin_id=plugin_id,
                    path=plugin_dir,
                    errors=(f"Failed to create module spec for {init_file}",),
                ),
            )

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        # Clean up module from sys.modules on import failure
        if module_name in sys.modules:
            del sys.modules[module_name]
        return PluginLoadResult(
            success=False,
            error=PluginLoadError(
                plugin_id=plugin_id,
                path=plugin_dir,
                errors=(f"Failed to import plugin module: {e}",),
            ),
        )

    # Validate manifest
    manifest_errors = _validate_manifest(module, plugin_dir)
    errors.extend(manifest_errors)

    # If manifest is valid, perform additional validation
    manifest = getattr(module, "PLUGIN_MANIFEST", None)
    if isinstance(manifest, PluginManifest):
        # Validate api_version
        api_errors = _validate_api_version(manifest)
        errors.extend(api_errors)

        # Validate capabilities
        cap_errors = _validate_capabilities(manifest)
        errors.extend(cap_errors)

        # Use manifest id if available
        plugin_id = manifest.id

    # Check if any errors occurred
    if errors:
        # Clean up module from sys.modules
        if module_name in sys.modules:
            del sys.modules[module_name]

        return PluginLoadResult(
            success=False,
            error=PluginLoadError(
                plugin_id=plugin_id,
                path=plugin_dir,
                errors=tuple(errors),
            ),
        )

    # Get MODEL_REQUIREMENTS
    model_requirements = tuple(getattr(module, "MODEL_REQUIREMENTS", []))
    create_engine = getattr(module, "create_engine", None)

    return PluginLoadResult(
        success=True,
        manifest=manifest,
        model_requirements=model_requirements,
        create_engine=create_engine,
        module=module,
    )


def discover_plugins(plugin_dirs: list[Path]) -> list[PluginLoadResult]:
    """Discover and load plugins from multiple directories.

    Args:
        plugin_dirs: List of directories to scan for plugins.

    Returns:
        List of PluginLoadResult, one per plugin directory found.
    """
    results: list[PluginLoadResult] = []

    for plugin_dir in plugin_dirs:
        if not plugin_dir.exists():
            continue

        # Scan for subdirectories (each is a potential plugin)
        for item in sorted(plugin_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                result = load_plugin_from_dir(item)
                results.append(result)

    return results


def load_plugin(
    plugin_dir: Path,
) -> PluginLoadResult:
    """Load a single plugin from a directory.

    This is the main entry point for loading a plugin.

    Args:
        plugin_dir: Path to the plugin directory.

    Returns:
        PluginLoadResult with success status and either plugin data or error info.
    """
    return load_plugin_from_dir(plugin_dir)
