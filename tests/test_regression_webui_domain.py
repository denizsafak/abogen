"""Regression tests: domain extraction must not break webui conversion_runner.

These tests verify that the refactored WebUI code paths still call into the
correct domain functions and produce the same results as the old inline logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from abogen.domain.voice_utils import resolve_voice_target
from abogen.domain.pipeline_factory import PipelinePool


class TestResolveVoiceTargetRegression:
    """Verify that the domain resolve_voice_target produces the same results
    as the old closure in conversion_runner.py."""

    def test_empty_spec_returns_kokoro_default(self):
        provider, spec, speed, steps = resolve_voice_target(
            "", {}, job_voice="af_sarah", job_tts_provider="kokoro",
        )
        assert provider == "kokoro"
        assert spec == ""

    def test_speaker_in_profile_kokoro(self):
        profiles = {
            "narrator": {
                "provider": "kokoro",
                "voices": [["af_sarah", 0.7], ["bf_emma", 0.3]],
            },
        }
        provider, spec, speed, steps = resolve_voice_target(
            "speaker:narrator", profiles,
        )
        assert provider == "kokoro"
        assert "af_sarah" in spec
        assert speed is None
        assert steps is None

    def test_speaker_in_profile_supertonic(self):
        profiles = {
            "narrator": {
                "provider": "supertonic",
                "voice": "F1",
                "speed": 1.2,
                "total_steps": 10,
            },
        }
        provider, spec, speed, steps = resolve_voice_target(
            "speaker:narrator", profiles,
            job_voice="M1", job_speed=1.0, job_supertonic_total_steps=5,
        )
        assert provider == "supertonic"
        assert spec == "F1"
        assert speed == 1.2
        assert steps == 10

    def test_unknown_speaker_infers_from_spec(self):
        with patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"]):
            provider, spec, speed, steps = resolve_voice_target(
                "af_sarah", {}, job_tts_provider="kokoro",
            )
            assert provider == "kokoro"
            assert spec == "af_sarah"

    def test_uppercase_spec_infers_supertonic(self):
        with patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"]):
            provider, spec, speed, steps = resolve_voice_target(
                "M1", {}, job_voice="M1",
            )
            assert provider == "supertonic"
            assert spec == "M1"


class TestPipelinePoolRegression:
    """Verify that PipelinePool behaves like the old inline get_pipeline closure."""

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_same_provider_returns_cached_pipeline(self, _cache, mock_create):
        mock_pipeline = MagicMock()
        mock_create.return_value = mock_pipeline
        pool = PipelinePool()

        r1 = pool.get("kokoro", "en", use_gpu=True)
        r2 = pool.get("kokoro", "en", use_gpu=True)
        assert r1 is r2
        assert mock_create.call_count == 1

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_different_providers_get_separate_pipelines(self, _cache, mock_create):
        p1 = MagicMock(name="kokoro")
        p2 = MagicMock(name="supertonic")
        mock_create.side_effect = [p1, p2]
        pool = PipelinePool()

        r1 = pool.get("kokoro", "en", use_gpu=True)
        r2 = pool.get("supertonic", "en", use_gpu=True)
        assert r1 is p1
        assert r2 is p2

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_dispose_all_cleans_up(self, _cache, mock_create):
        p1 = MagicMock()
        p2 = MagicMock()
        mock_create.side_effect = [p1, p2]
        pool = PipelinePool()

        pool.get("kokoro", "en", use_gpu=True)
        pool.get("supertonic", "en", use_gpu=True)
        pool.dispose_all()

        p1.dispose.assert_called_once()
        p2.dispose.assert_called_once()
        assert pool._pipelines == {}

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_voice_cache_initialized_only_once(self, mock_cache, mock_create):
        mock_create.return_value = MagicMock()
        pool = PipelinePool()
        job = MagicMock()

        pool.get("kokoro", "en", use_gpu=True, job=job)
        pool.get("kokoro", "en", use_gpu=True, job=job)
        assert mock_cache.call_count == 1

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_after_dispose_voice_cache_can_reinitialize(self, mock_cache, mock_create):
        mock_create.return_value = MagicMock()
        pool = PipelinePool()
        job = MagicMock()

        pool.get("kokoro", "en", use_gpu=True, job=job)
        assert mock_cache.call_count == 1

        pool.dispose_all()
        assert pool._voice_cache_initialized is False

        pool.get("kokoro", "en", use_gpu=True, job=job)
        assert mock_cache.call_count == 2
