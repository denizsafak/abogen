"""Host context for the TTS Plugin Architecture.

This module defines the HostContext dataclass that provides minimal
host services to plugins. It is the only interface through which
plugins can access host functionality.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class HttpClient(Protocol):
    """Protocol for HTTP client provided by host.

    Plugins can use this for network requests (e.g., API-based engines).
    """

    def get(self, url: str, **kwargs: object) -> object:
        """Perform an HTTP GET request."""
        ...

    def post(self, url: str, **kwargs: object) -> object:
        """Perform an HTTP POST request."""
        ...


@dataclass(frozen=True)
class HostContext:
    """Minimal host context provided to plugins.

    Contains only essential host services. No business logic.

    Attributes:
        config_dir: Directory for API keys, preferences, and configuration.
        logger: Logger for plugin logging.
        http_client: HTTP client for network requests.
    """

    config_dir: Path
    logger: logging.Logger
    http_client: HttpClient
