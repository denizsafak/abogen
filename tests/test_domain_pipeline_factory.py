from __future__ import annotations

from unittest.mock import MagicMock, patch

from abogen.domain.pipeline_factory import (
    PipelinePool,
    create_pipeline_for_job,
    dispose_pipelines,
    resolve_device,
)


class TestResolveDevice:
    @patch("abogen.utils.load_config", return_value={"use_gpu": True})
    @patch("abogen.domain.pipeline_factory.select_device", return_value="cuda:0")
    def test_gpu_enabled(self, _sel, _cfg):
        assert resolve_device(use_gpu=True) == "cuda:0"

    @patch("abogen.utils.load_config", return_value={"use_gpu": True})
    def test_gpu_disabled_by_job(self, _cfg):
        assert resolve_device(use_gpu=False) == "cpu"

    @patch("abogen.utils.load_config", return_value={"use_gpu": False})
    @patch("abogen.domain.pipeline_factory.select_device", return_value="cuda:0")
    def test_gpu_disabled_by_config(self, _sel, _cfg):
        assert resolve_device(use_gpu=True) == "cpu"


class TestCreatePipelineForJob:
    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=True)
    def test_supertonic_provider(self, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job("supertonic", "en", use_gpu=True)
        mock_create.assert_called_once_with("supertonic")
        assert result is mock_create.return_value

    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=True)
    @patch("abogen.domain.pipeline_factory.resolve_device", return_value="cpu")
    def test_kokoro_provider(self, _dev, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job("kokoro", "en", use_gpu=False)
        # "en" → fallback to EN_US → kokoro code "a"
        mock_create.assert_called_once_with("kokoro", lang_code="a", device="cpu")
        assert result is mock_create.return_value

    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=True)
    @patch("abogen.domain.pipeline_factory.resolve_device", return_value="cpu")
    def test_kokoro_provider_iso_code(self, _dev, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job("kokoro", "en-GB", use_gpu=False)
        # "en-GB" → EN_GB → kokoro code "b"
        mock_create.assert_called_once_with("kokoro", lang_code="b", device="cpu")

    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=False)
    @patch("abogen.domain.pipeline_factory.resolve_device", return_value="cpu")
    def test_unknown_provider_falls_back_to_kokoro(self, _dev, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job("unknown_provider", "en", use_gpu=False)
        mock_create.assert_called_once_with("kokoro", lang_code="a", device="cpu")

    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=True)
    @patch("abogen.domain.pipeline_factory.resolve_device", return_value="cpu")
    def test_empty_provider_defaults_to_kokoro(self, _dev, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job("", "en", use_gpu=False)
        mock_create.assert_called_once_with("kokoro", lang_code="a", device="cpu")

    @patch("abogen.domain.pipeline_factory.create_pipeline")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=True)
    @patch("abogen.domain.pipeline_factory.resolve_device", return_value="cpu")
    def test_none_provider_defaults_to_kokoro(self, _dev, _reg, mock_create):
        mock_create.return_value = MagicMock()
        result = create_pipeline_for_job(None, "en", use_gpu=False)
        mock_create.assert_called_once_with("kokoro", lang_code="a", device="cpu")


class TestDisposePipelines:
    def test_disposes_all_and_clears(self):
        p1 = MagicMock()
        p2 = MagicMock()
        pipelines = {"kokoro": p1, "supertonic": p2}
        dispose_pipelines(pipelines)
        p1.dispose.assert_called_once()
        p2.dispose.assert_called_once()
        assert pipelines == {}

    def test_handles_dispose_error(self):
        p1 = MagicMock()
        p1.dispose.side_effect = RuntimeError("boom")
        pipelines = {"kokoro": p1}
        dispose_pipelines(pipelines)
        assert pipelines == {}

    def test_empty_dict(self):
        pipelines = {}
        dispose_pipelines(pipelines)
        assert pipelines == {}


class TestPipelinePool:
    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_get_creates_and_caches(self, _cache, mock_create):
        mock_pipeline = MagicMock()
        mock_create.return_value = mock_pipeline
        pool = PipelinePool()

        result = pool.get("kokoro", "en", use_gpu=True)
        assert result is mock_pipeline
        mock_create.assert_called_once()

        result2 = pool.get("kokoro", "en", use_gpu=True)
        assert result2 is mock_pipeline
        assert mock_create.call_count == 1

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_get_initializes_voice_cache_once(self, mock_cache, mock_create):
        mock_create.return_value = MagicMock()
        pool = PipelinePool()

        job = MagicMock()
        pool.get("kokoro", "en", use_gpu=True, job=job)
        assert mock_cache.call_count == 1

        pool.get("kokoro", "en", use_gpu=True, job=job)
        assert mock_cache.call_count == 1

    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    def test_get_no_job_skips_voice_cache(self, mock_create, mock_cache):
        mock_create.return_value = MagicMock()
        pool = PipelinePool()
        pool.get("kokoro", "en", use_gpu=True)
        mock_cache.assert_not_called()

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    def test_get_separately_per_provider(self, mock_create):
        p1 = MagicMock(name="kokoro")
        p2 = MagicMock(name="supertonic")
        mock_create.side_effect = [p1, p2]
        pool = PipelinePool()

        r1 = pool.get("kokoro", "en", use_gpu=True)
        r2 = pool.get("supertonic", "en", use_gpu=True)
        assert r1 is p1
        assert r2 is p2
        assert mock_create.call_count == 2

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    def test_dispose_all(self, mock_cache, mock_create):
        p1 = MagicMock(name="kokoro")
        p2 = MagicMock(name="supertonic")
        mock_create.side_effect = [p1, p2]
        pool = PipelinePool()

        pool.get("kokoro", "en", use_gpu=True)
        pool.get("supertonic", "en", use_gpu=True)
        pool.dispose_all()

        p1.dispose.assert_called_once()
        p2.dispose.assert_called_once()
        assert pool._pipelines == {}
        assert pool._voice_cache_initialized is False

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    def test_dispose_empty_pool(self, mock_create):
        pool = PipelinePool()
        pool.dispose_all()
        mock_create.assert_not_called()

    @patch("abogen.domain.pipeline_factory.create_pipeline_for_job")
    @patch("abogen.domain.pipeline_factory.initialize_voice_cache")
    @patch("abogen.domain.pipeline_factory.is_plugin_registered", return_value=False)
    def test_unknown_provider_falls_back(self, _reg, _cache, mock_create):
        mock_create.return_value = MagicMock()
        pool = PipelinePool()
        pool.get("bogus_provider", "en", use_gpu=True)
        mock_create.assert_called_once_with("kokoro", "en", True)
