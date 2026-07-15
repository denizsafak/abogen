"""Audio buffer operations for audiobook generation.

This module provides core audio buffer manipulation functions including:
- Silence generation
- Audio mixing
- Audio normalization
- Audio buffer resizing
"""

from __future__ import annotations

from typing import Optional

import numpy as np

# Standard sample rate used throughout the application
SAMPLE_RATE = 24000


def create_silence(duration_seconds: float) -> np.ndarray:
    """Create a silence audio buffer.
    
    Args:
        duration_seconds: Duration of silence in seconds.
        
    Returns:
        Numpy array of float32 zeros with length = duration_seconds * SAMPLE_RATE.
        Returns empty array if duration is <= 0.
    """
    if duration_seconds <= 0:
        return np.array([], dtype="float32")
    
    samples = int(round(duration_seconds * SAMPLE_RATE))
    if samples <= 0:
        return np.array([], dtype="float32")
    
    return np.zeros(samples, dtype="float32")


def mix_audio(
    target: np.ndarray,
    source: np.ndarray,
    start_sample: int,
    end_sample: Optional[int] = None,
) -> None:
    """Mix source audio into target buffer at specified position.
    
    This performs additive mixing (target += source). The target buffer
    is extended if necessary to accommodate the source audio.
    
    Args:
        target: The target audio buffer to mix into (modified in-place).
        source: The source audio buffer to mix.
        start_sample: Starting sample index in target buffer.
        end_sample: Optional end sample index. If None, calculated from source length.
    """
    if source.size == 0:
        return
    
    if end_sample is None:
        end_sample = start_sample + len(source)
    
    # Extend target buffer if needed
    if end_sample > len(target):
        new_length = end_sample
        target = np.concatenate([
            target,
            np.zeros(new_length - len(target), dtype="float32")
        ])
    
    # Perform the mix (additive)
    target[start_sample:end_sample] += source


def normalize_audio(
    audio: np.ndarray,
    target_peak: float = 1.0,
) -> np.ndarray:
    """Normalize audio buffer to prevent clipping.
    
    If the audio exceeds the target peak (default 1.0), it is scaled down
    proportionally to prevent distortion.
    
    Args:
        audio: Input audio buffer.
        target_peak: Target maximum amplitude (default 1.0).
        
    Returns:
        Normalized audio buffer (new array, original is not modified).
    """
    if audio.size == 0:
        return audio.copy()
    
    max_amplitude = float(np.abs(audio).max())
    
    if max_amplitude <= target_peak:
        return audio.copy()
    
    # Scale down to prevent clipping
    scale_factor = target_peak / max_amplitude
    return (audio * scale_factor).astype("float32")


def ensure_buffer_size(
    buffer: np.ndarray,
    min_samples: int,
) -> np.ndarray:
    """Ensure audio buffer is at least min_samples long.
    
    If buffer is shorter, it is extended with zeros.
    
    Args:
        buffer: Input audio buffer.
        min_samples: Minimum required length in samples.
        
    Returns:
        Buffer of at least min_samples length (new array if extended).
    """
    if len(buffer) >= min_samples:
        return buffer
    
    new_buffer = np.zeros(min_samples, dtype="float32")
    new_buffer[:len(buffer)] = buffer
    return new_buffer


def concatenate_audio(*buffers: np.ndarray) -> np.ndarray:
    """Concatenate multiple audio buffers.
    
    Args:
        *buffers: Audio buffers to concatenate.
        
    Returns:
        Single concatenated audio buffer.
    """
    non_empty = [b for b in buffers if b.size > 0]
    if not non_empty:
        return np.array([], dtype="float32")
    return np.concatenate(non_empty)


def audio_duration(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """Calculate duration of audio buffer in seconds.
    
    Args:
        audio: Audio buffer.
        sample_rate: Sample rate in Hz (default SAMPLE_RATE).
        
    Returns:
        Duration in seconds.
    """
    return len(audio) / sample_rate


def samples_for_duration(duration_seconds: float, sample_rate: int = SAMPLE_RATE) -> int:
    """Calculate number of samples for a given duration.
    
    Args:
        duration_seconds: Duration in seconds.
        sample_rate: Sample rate in Hz (default SAMPLE_RATE).
        
    Returns:
        Number of samples (rounded to nearest integer).
    """
    return int(round(duration_seconds * sample_rate))
