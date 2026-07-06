"""
TTS Backend Interface

This module defines the protocol for TTS backends.
"""

from typing import Protocol, List, Dict, Any


class TTSBackend(Protocol):
    """
    Protocol for TTS backends.

    All TTS backends must implement this interface to be compatible
    with the application.
    """

    def __init__(self, **kwargs) -> None:
        """
        Initialize the TTS backend.

        Args:
            **kwargs: Backend-specific configuration parameters
        """
        ...

    def synthesize(self, text: str, **kwargs) -> bytes:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize
            **kwargs: Additional parameters for synthesis

        Returns:
            Audio data as bytes
        """
        ...

    def get_available_voices(self) -> List[str]:
        """
        Get list of available voices.

        Returns:
            List of voice identifiers
        """
        ...

    def get_supported_formats(self) -> List[str]:
        """
        Get list of supported audio formats.

        Returns:
            List of supported audio formats
        """
        ...

    def get_info(self) -> Dict[str, Any]:
        """
        Get backend information.

        Returns:
            Dictionary with backend information
        """
        ...
