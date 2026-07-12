"""Error hierarchy for the TTS Plugin Architecture.

This module defines typed exceptions that engines raise.
Engines should never raise raw exceptions; they must use EngineError or its subtypes.
"""

from __future__ import annotations


class EngineError(Exception):
    """Base exception for all engine errors.

    All engine operations that can fail should raise EngineError or one of its subtypes.
    After dispose(), all methods except dispose() raise EngineError.
    """

    pass


class ModelNotFoundError(EngineError):
    """Raised when a required model is not found."""

    pass


class ModelLoadError(EngineError):
    """Raised when a model fails to load."""

    pass


class NetworkError(EngineError):
    """Raised when a network operation fails."""

    pass


class InvalidInputError(EngineError):
    """Raised when invalid input is provided to the engine."""

    pass


class ConfigurationError(EngineError):
    """Raised when there is a configuration error."""

    pass


class CancelledError(EngineError):
    """Raised when an operation is cancelled.

    This is raised by synthesize() when cancel() is called during synthesis.
    """

    pass


class InternalError(EngineError):
    """Raised when an internal engine error occurs."""

    pass
