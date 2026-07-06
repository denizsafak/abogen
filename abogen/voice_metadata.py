from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceMetadata:
    """
    Immutable metadata describing a voice from a TTS backend.

    This model describes a voice independently of any backend implementation.
    Backends populate these objects; the application consumes them.

    The ``backend_id`` field is set by the backend itself (via
    ``self.metadata.id``) — the application never hardcodes it.
    This ensures renaming a backend does not require touching voice definitions.
    """

    id: str
    """Unique voice identifier within the backend (e.g. ``"af_alloy"``, ``"M1"``)."""

    display_name: str
    """Human-readable display name (e.g. ``"Alloy"``, ``"Male 1"``)."""

    language: str
    """Language code — backend-specific format is acceptable (e.g. ``"a"``, ``"en"``)."""

    gender: str
    """Gender category: ``"female"``, ``"male"``, or ``"unknown"``."""

    backend_id: str
    """Identifier of the backend that owns this voice (e.g. ``"kokoro"``).

    Set automatically by the backend — never hardcoded in voice definitions.
    """
