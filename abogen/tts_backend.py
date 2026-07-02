"""
Minimal TTS Backend Interface

This module defines a minimal interface for TTS backends to enable future
extensibility while maintaining backward compatibility with existing Kokoro
implementation.
"""

from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional, Union


class TTSBackend(ABC):
    """
    Minimal interface for TTS backends.
    
    This interface is designed to be minimal and focused on the essential
    operations needed for text-to-speech conversion.
    """

    @abstractmethod
    def __call__(
        self,
        text: str,
        voice: Union[str, Any],
        speed: float = 1.0,
        **kwargs: Any
    ) -> Iterator[Any]:
        """
        Generate speech segments from text.
        
        Args:
            text: Text to convert to speech
            voice: Voice specification or object
            speed: Speed multiplier for speech
            **kwargs: Additional backend-specific parameters
            
        Yields:
            Speech segments (audio data, timing info, etc.)
        """
        pass


class KokoroTTSBackend(TTSBackend):
    """
    Implementation of TTSBackend using Kokoro.
    
    This class provides the concrete implementation that maintains
    the existing behavior while conforming to the TTSBackend interface.
    """

    def __init__(self, lang_code: str, repo_id: str = "hexgrad/Kokoro-82M", device: str = "cpu"):
        """
        Initialize Kokoro backend.
        
        Args:
            lang_code: Language code for the model
            repo_id: Repository ID for the Kokoro model
            device: Device to run the model on (cpu, cuda, etc.)
        """
        self.lang_code = lang_code
        self.repo_id = repo_id
        self.device = device
        self._pipeline = None

    def _get_pipeline(self):
        """Lazy initialization of the Kokoro pipeline."""
        if self._pipeline is None:
            from abogen.utils import load_numpy_kpipeline
            _, KPipeline = load_numpy_kpipeline()
            try:
                self._pipeline = KPipeline(
                    lang_code=self.lang_code,
                    repo_id=self.repo_id,
                    device=self.device
                )
            except RuntimeError as e:
                if "CUDA" in str(e) and self.device != "cpu":
                    # Fall back to CPU if CUDA fails
                    self._pipeline = KPipeline(
                        lang_code=self.lang_code,
                        repo_id=self.repo_id,
                        device="cpu"
                    )
                else:
                    raise
        return self._pipeline

    def __call__(
        self,
        text: str,
        voice: Union[str, Any],
        speed: float = 1.0,
        split_pattern: str = r"\n+",
        **kwargs: Any
    ) -> Iterator[Any]:
        """
        Generate speech segments from text using Kokoro.
        
        Args:
            text: Text to convert to speech
            voice: Voice specification or object
            speed: Speed multiplier for speech
            split_pattern: Pattern to split text into segments
            **kwargs: Additional parameters passed to the pipeline
            
        Yields:
            Speech segments
        """
        pipeline = self._get_pipeline()
        return pipeline(
            text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
            **kwargs
        )
