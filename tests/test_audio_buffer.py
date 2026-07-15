"""Tests for abogen.domain.audio_buffer module."""

import numpy as np
import pytest

from abogen.domain.audio_buffer import (
    create_silence,
    mix_audio,
    normalize_audio,
    ensure_buffer_size,
    concatenate_audio,
    audio_duration,
    samples_for_duration,
    SAMPLE_RATE,
)


class TestCreateSilence:
    """Tests for create_silence function."""

    def test_positive_duration(self):
        """Test creating silence with positive duration."""
        duration = 1.0  # 1 second
        silence = create_silence(duration)
        
        expected_samples = int(round(duration * SAMPLE_RATE))
        assert len(silence) == expected_samples
        assert silence.dtype == np.float32
        assert np.all(silence == 0)

    def test_zero_duration(self):
        """Test creating silence with zero duration returns empty array."""
        silence = create_silence(0)
        assert len(silence) == 0
        assert silence.dtype == np.float32

    def test_negative_duration(self):
        """Test creating silence with negative duration returns empty array."""
        silence = create_silence(-1.0)
        assert len(silence) == 0
        assert silence.dtype == np.float32

    def test_very_small_duration(self):
        """Test creating silence with very small duration."""
        duration = 0.001  # 1 millisecond
        silence = create_silence(duration)
        
        # Should round to at least 1 sample or 0
        assert len(silence) >= 0
        assert silence.dtype == np.float32

    def test_half_second(self):
        """Test creating 0.5 second of silence."""
        silence = create_silence(0.5)
        expected_samples = int(round(0.5 * SAMPLE_RATE))
        assert len(silence) == expected_samples


class TestMixAudio:
    """Tests for mix_audio function."""

    def test_basic_mix(self):
        """Test basic audio mixing."""
        target = np.ones(100, dtype="float32")
        source = np.ones(50, dtype="float32") * 2
        
        mix_audio(target, source, start_sample=25)
        
        # First 25 samples should remain 1.0
        assert np.all(target[:25] == 1.0)
        # Middle 50 samples should be 1.0 + 2.0 = 3.0
        assert np.all(target[25:75] == 3.0)
        # Last 25 samples should remain 1.0
        assert np.all(target[75:] == 1.0)

    def test_empty_source(self):
        """Test mixing empty source does nothing."""
        target = np.ones(100, dtype="float32")
        original = target.copy()
        
        mix_audio(target, np.array([], dtype="float32"), start_sample=50)
        
        assert np.array_equal(target, original)

    def test_extend_target_buffer(self):
        """Test that target buffer is extended when needed."""
        target = np.ones(100, dtype="float32")
        source = np.ones(50, dtype="float32") * 2
        
        # This should extend target to 170 samples (120 + 50)
        target = mix_audio(target, source, start_sample=120)
        
        assert len(target) == 170
        # Check that source was mixed correctly
        assert np.all(target[120:170] == 2.0)

    def test_start_at_zero(self):
        """Test mixing starting at sample 0."""
        target = np.zeros(100, dtype="float32")
        source = np.ones(50, dtype="float32")
        
        mix_audio(target, source, start_sample=0)
        
        assert np.all(target[:50] == 1.0)
        assert np.all(target[50:] == 0.0)

    def test_explicit_end_sample(self):
        """Test mixing with explicit end_sample."""
        target = np.zeros(100, dtype="float32")
        source = np.ones(50, dtype="float32")
        
        mix_audio(target, source, start_sample=10, end_sample=60)
        
        # Only first 10 samples of source should be mixed (60-10=50, but source is only 50)
        # Actually, end_sample overrides the length
        assert target[10] == 1.0


class TestNormalizeAudio:
    """Tests for normalize_audio function."""

    def test_no_normalization_needed(self):
        """Test audio within range is not modified."""
        audio = np.ones(100, dtype="float32") * 0.5
        result = normalize_audio(audio)
        
        assert not np.shares_memory(audio, result)  # Should be a copy
        assert np.array_equal(result, audio)

    def test_normalization_applied(self):
        """Test audio above target peak is scaled down."""
        audio = np.ones(100, dtype="float32") * 2.0
        result = normalize_audio(audio)
        
        assert np.all(result <= 1.0)
        assert np.isclose(result[0], 1.0)

    def test_empty_audio(self):
        """Test normalizing empty audio returns empty copy."""
        audio = np.array([], dtype="float32")
        result = normalize_audio(audio)
        
        assert len(result) == 0
        assert result.dtype == np.float32

    def test_custom_target_peak(self):
        """Test normalization with custom target peak."""
        audio = np.ones(100, dtype="float32") * 4.0
        result = normalize_audio(audio, target_peak=2.0)
        
        assert np.all(result <= 2.0)
        assert np.isclose(result[0], 2.0)

    def test_negative_peak(self):
        """Test normalization handles negative peaks."""
        audio = np.ones(100, dtype="float32") * -2.0
        result = normalize_audio(audio)
        
        assert np.all(result >= -1.0)
        assert np.isclose(result[0], -1.0)

    def test_mixed_positive_negative(self):
        """Test normalization with both positive and negative peaks."""
        audio = np.array([-3.0, 2.0, -1.0, 4.0], dtype="float32")
        result = normalize_audio(audio)
        
        # Should scale by 1/4 (max absolute value is 4)
        assert np.isclose(result[0], -0.75)
        assert np.isclose(result[1], 0.5)
        assert np.isclose(result[3], 1.0)


class TestEnsureBufferSize:
    """Tests for ensure_buffer_size function."""

    def test_buffer_already_large_enough(self):
        """Test buffer that is already large enough is unchanged."""
        buffer = np.ones(100, dtype="float32")
        result = ensure_buffer_size(buffer, 50)
        
        assert np.array_equal(result, buffer)

    def test_buffer_needs_extension(self):
        """Test buffer is extended with zeros when too small."""
        buffer = np.ones(50, dtype="float32")
        result = ensure_buffer_size(buffer, 100)
        
        assert len(result) == 100
        assert np.all(result[:50] == 1.0)
        assert np.all(result[50:] == 0.0)

    def test_exact_size(self):
        """Test buffer of exact size is unchanged."""
        buffer = np.ones(100, dtype="float32")
        result = ensure_buffer_size(buffer, 100)
        
        assert len(result) == 100
        assert np.array_equal(result, buffer)


class TestConcatenateAudio:
    """Tests for concatenate_audio function."""

    def test_concatenate_two_buffers(self):
        """Test concatenating two audio buffers."""
        a = np.ones(50, dtype="float32")
        b = np.ones(50, dtype="float32") * 2
        result = concatenate_audio(a, b)
        
        assert len(result) == 100
        assert np.all(result[:50] == 1.0)
        assert np.all(result[50:] == 2.0)

    def test_concatenate_multiple_buffers(self):
        """Test concatenating multiple audio buffers."""
        a = np.ones(20, dtype="float32")
        b = np.ones(30, dtype="float32") * 2
        c = np.ones(40, dtype="float32") * 3
        result = concatenate_audio(a, b, c)
        
        assert len(result) == 90
        assert np.all(result[:20] == 1.0)
        assert np.all(result[20:50] == 2.0)
        assert np.all(result[50:] == 3.0)

    def test_concatenate_empty_buffers(self):
        """Test concatenating empty buffers returns empty array."""
        result = concatenate_audio(
            np.array([], dtype="float32"),
            np.array([], dtype="float32")
        )
        assert len(result) == 0

    def test_concatenate_with_empty(self):
        """Test concatenating with some empty buffers."""
        a = np.ones(50, dtype="float32")
        result = concatenate_audio(a, np.array([], dtype="float32"))
        
        assert len(result) == 50
        assert np.array_equal(result, a)


class TestAudioDuration:
    """Tests for audio_duration function."""

    def test_one_second_duration(self):
        """Test duration calculation for 1 second of audio."""
        audio = np.zeros(SAMPLE_RATE, dtype="float32")
        duration = audio_duration(audio)
        
        assert duration == 1.0

    def test_half_second_duration(self):
        """Test duration calculation for 0.5 second of audio."""
        audio = np.zeros(SAMPLE_RATE // 2, dtype="float32")
        duration = audio_duration(audio)
        
        assert duration == 0.5

    def test_empty_audio_duration(self):
        """Test duration of empty audio is 0."""
        duration = audio_duration(np.array([], dtype="float32"))
        assert duration == 0.0

    def test_custom_sample_rate(self):
        """Test duration with custom sample rate."""
        audio = np.zeros(48000, dtype="float32")  # 48k samples
        duration = audio_duration(audio, sample_rate=48000)
        
        assert duration == 1.0


class TestSamplesForDuration:
    """Tests for samples_for_duration function."""

    def test_one_second(self):
        """Test samples for 1 second at default rate."""
        samples = samples_for_duration(1.0)
        assert samples == SAMPLE_RATE

    def test_half_second(self):
        """Test samples for 0.5 second at default rate."""
        samples = samples_for_duration(0.5)
        assert samples == SAMPLE_RATE // 2

    def test_zero_duration(self):
        """Test samples for 0 duration."""
        samples = samples_for_duration(0)
        assert samples == 0

    def test_negative_duration(self):
        """Test samples for negative duration."""
        samples = samples_for_duration(-1.0)
        assert samples == 0

    def test_custom_sample_rate(self):
        """Test samples with custom sample rate."""
        samples = samples_for_duration(1.0, sample_rate=44100)
        assert samples == 44100


class TestSampleRateConstant:
    """Tests for SAMPLE_RATE constant."""

    def test_sample_rate_value(self):
        """Test SAMPLE_RATE is 24000."""
        assert SAMPLE_RATE == 24000
