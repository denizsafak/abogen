"""
TTS Backend Registry

Provides a global registry for TTS backend factories.
Backends register themselves with metadata and a factory callable.
The registry is universal and does not know about backend constructors.
"""

from typing import Callable, Any

from abogen.tts_backend import TTSBackend, TTSBackendMetadata


class TTSBackendRegistry:
    """Registry of TTS backend factories.

    Stores metadata and factory callables for registered backends.
    """

    def __init__(self) -> None:
        self._backends: dict[str, TTSBackendMetadata] = {}
        self._factories: dict[str, Callable[..., TTSBackend]] = {}

    def register(
        self,
        metadata: TTSBackendMetadata,
        factory: Callable[..., TTSBackend],
    ) -> None:
        """Register a backend with its metadata and factory callable."""
        self._backends[metadata.id] = metadata
        self._factories[metadata.id] = factory

    def is_registered(self, backend_id: str) -> bool:
        """Return True if a backend with the given id is registered."""
        return backend_id in self._backends

    def list_backends(self) -> list[TTSBackendMetadata]:
        """Return metadata for all registered backends."""
        return list(self._backends.values())

    def get_metadata(self, backend_id: str) -> TTSBackendMetadata:
        """Get metadata for a specific backend.

        Raises:
            KeyError: If backend with given id is not registered.
        """
        if backend_id not in self._backends:
            raise KeyError(f"Unknown backend: {backend_id}")
        return self._backends[backend_id]

    def create_backend(self, backend_id: str, **kwargs: Any) -> TTSBackend:
        """Create a backend instance by id.

        Raises:
            KeyError: If backend with given id is not registered.
        """
        if backend_id not in self._factories:
            raise KeyError(f"Unknown backend: {backend_id}")
        return self._factories[backend_id](**kwargs)

    def resolve_backend_for_voice(
        self,
        spec: str,
        fallback: str = "kokoro",
    ) -> str:
        """Determine which backend owns the given voice specification.

        Resolution rules:
        1. Empty spec -> fallback
        2. Kokoro formula (contains '*' or '+') -> "kokoro"
        3. Exact voice ID match against registered backends -> backend id
        4. Unknown voice -> fallback
        """
        raw = str(spec or "").strip()
        if not raw:
            return fallback

        if "*" in raw or "+" in raw:
            return "kokoro"

        upper = raw.upper()
        for metadata in self._backends.values():
            if upper in metadata.voices:
                return metadata.id

        return fallback


_registry = TTSBackendRegistry()


def register_backend(
    metadata: TTSBackendMetadata,
    factory: Callable[..., TTSBackend],
) -> None:
    """Register a TTS backend in the global registry."""
    _registry.register(metadata, factory)


def get_metadata(backend_id: str) -> TTSBackendMetadata:
    """Get metadata for a specific backend by id.

    Ensures all backends are registered by importing the tts_backends
    package on first access.

    Raises:
        KeyError: If backend with given id is not registered.
    """
    import abogen.tts_backends  # noqa: F401  — triggers backend registration
    return _registry.get_metadata(backend_id)


def get_default_voice(backend_id: str, fallback: str = "") -> str:
    """Return the first voice of a backend, or *fallback* if none."""
    voices = get_metadata(backend_id).voices
    return voices[0] if voices else fallback


def create_backend(backend_id: str, **kwargs: Any) -> TTSBackend:
    """Create a TTS backend instance by provider id."""
    return _registry.create_backend(backend_id, **kwargs)


def is_registered_backend(backend_id: str) -> bool:
    """Return True if *backend_id* is a registered TTS backend."""
    import abogen.tts_backends  # noqa: F401  — triggers backend registration
    return _registry.is_registered(backend_id)


def resolve_backend_for_voice(
    spec: str,
    fallback: str = "kokoro",
) -> str:
    """Determine which backend owns the given voice specification.

    Ensures all backends are registered by importing the tts_backends
    package on first access.

    Resolution rules:
    1. Empty spec -> fallback
    2. Kokoro formula (contains '*' or '+') -> "kokoro"
    3. Exact voice ID match against registered backends -> backend id
    4. Unknown voice -> fallback
    """
    import abogen.tts_backends  # noqa: F401  — triggers backend registration
    return _registry.resolve_backend_for_voice(spec, fallback=fallback)
