"""Tests for application/integration_hooks.py — PostConversionHooks
and domain/settings_core.py — build_audiobookshelf_config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_result import ConversionResult
from abogen.application.integration_hooks import PostConversionHooks
from abogen.domain.enums import Language
from abogen.domain.settings_core import build_audiobookshelf_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**overrides: Any) -> ConversionRequest:
    defaults = dict(
        source_path=Path("/tmp/test.txt"),
        original_filename="test.txt",
        language=Language.EN_US,
        voice="M1",
        speed=1.0,
        use_gpu=False,
    )
    defaults.update(overrides)
    return ConversionRequest(**defaults)


def _make_result(**overrides: Any) -> ConversionResult:
    defaults: Dict[str, Any] = dict(
        metadata={"title": "Test Book"},
    )
    defaults.update(overrides)
    return ConversionResult(**defaults)


class _FakeEvents:
    def __init__(self) -> None:
        self.logs: List[tuple[str, str]] = []

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((message, level))

    def progress(self, pct: int, etr: str) -> None:
        pass

    def check_cancelled(self) -> None:
        pass


def _abs_settings(**overrides: Any) -> Dict[str, Any]:
    """Build a minimal Audiobookshelf settings dict."""
    settings: Dict[str, Any] = {
        "enabled": True,
        "auto_send": True,
        "base_url": "https://example.com",
        "api_token": "tok",
        "library_id": "lib",
        "folder_id": "fld",
    }
    settings.update(overrides)
    return settings


# ---------------------------------------------------------------------------
# build_audiobookshelf_config tests (domain layer)
# ---------------------------------------------------------------------------


class TestBuildAbsConfig:
    """build_audiobookshelf_config from domain.settings_core."""

    def test_returns_none_when_base_url_missing(self) -> None:
        result = build_audiobookshelf_config({
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is None

    def test_returns_none_when_api_token_missing(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is None

    def test_returns_none_when_library_id_missing(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "folder_id": "fld",
        })
        assert result is None

    def test_returns_none_when_folder_id_missing(self) -> None:
        # folder_id is optional in AudiobookshelfConfig, so this should succeed
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
        })
        assert result is not None

    def test_returns_config_when_all_required_fields_present(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        assert result.base_url == "https://example.com"
        assert result.api_token == "tok"
        assert result.library_id == "lib"
        assert result.folder_id == "fld"

    def test_preserves_trailing_slash_in_base_url(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com/",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        # normalization is done by AudiobookshelfClient, not config
        assert result.base_url == "https://example.com/"

    def test_preserves_api_suffix_in_base_url(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com/api",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        # normalization is done by AudiobookshelfClient, not config
        assert result.base_url == "https://example.com/api"

    def test_applies_default_timeout(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        assert result.timeout == 3600.0

    def test_applies_custom_timeout(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
            "timeout": 7200.0,
        })
        assert result is not None
        assert result.timeout == 7200.0

    def test_invalid_timeout_falls_back_to_default(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
            "timeout": "invalid",
        })
        assert result is not None
        assert result.timeout == 3600.0

    def test_collection_id_is_optional(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        assert result.collection_id is None

    def test_collection_id_when_provided(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
            "collection_id": "col123",
        })
        assert result is not None
        assert result.collection_id == "col123"

    def test_boolean_flags_default(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
        })
        assert result is not None
        assert result.verify_ssl is True
        assert result.send_cover is True
        assert result.send_chapters is True
        assert result.send_subtitles is False

    def test_boolean_flags_custom(self) -> None:
        result = build_audiobookshelf_config({
            "base_url": "https://example.com",
            "api_token": "tok",
            "library_id": "lib",
            "folder_id": "fld",
            "verify_ssl": False,
            "send_cover": False,
            "send_chapters": False,
            "send_subtitles": True,
        })
        assert result is not None
        assert result.verify_ssl is False
        assert result.send_cover is False
        assert result.send_chapters is False
        assert result.send_subtitles is True


# ---------------------------------------------------------------------------
# Hook skipping tests
# ---------------------------------------------------------------------------


class TestPostConversionHooks:
    """PostConversionHooks.run() skipping logic."""

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_no_audiobookshelf_config(self, mock_stored: MagicMock) -> None:
        mock_stored.return_value = {}
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result()
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert events.logs == []

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_enabled_false(self, mock_stored: MagicMock) -> None:
        mock_stored.return_value = _abs_settings(enabled=False)
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result()
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert events.logs == []

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_auto_send_false(self, mock_stored: MagicMock) -> None:
        mock_stored.return_value = _abs_settings(auto_send=False)
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result()
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert events.logs == []

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_config_incomplete(self, mock_stored: MagicMock) -> None:
        mock_stored.return_value = _abs_settings(base_url="")
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result()
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert len(events.logs) == 1
        assert "configure" in events.logs[0][0].lower()
        assert events.logs[0][1] == "warning"

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_audio_path_missing(self, mock_stored: MagicMock) -> None:
        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result(audio_path=None)
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert len(events.logs) == 1
        assert "audio output not found" in events.logs[0][0].lower()
        assert events.logs[0][1] == "warning"

    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_skip_when_audio_file_does_not_exist(self, mock_stored: MagicMock, tmp_path: Path) -> None:
        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request()
        result = _make_result(audio_path=tmp_path / "nonexistent.mp3")
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert len(events.logs) == 1
        assert "audio output not found" in events.logs[0][0].lower()


# ---------------------------------------------------------------------------
# Upload flow tests (mocked client)
# ---------------------------------------------------------------------------


class TestAudiobookshelfUpload:
    """Test the upload flow with mocked AudiobookshelfClient."""

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_successful_upload(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = []
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        mock_client.find_existing_items.assert_called_once()
        mock_client.upload_audiobook.assert_called_once()
        assert any("upload queued" in msg.lower() for msg, _ in events.logs)

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_deletes_existing_items_before_upload(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = [{"id": "existing-1"}]
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        mock_client.delete_items.assert_called_once_with([{"id": "existing-1"}])
        mock_client.upload_audiobook.assert_called_once()

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_lookup_error_logged_not_raised(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        from abogen.integrations.audiobookshelf import AudiobookshelfUploadError

        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.side_effect = AudiobookshelfUploadError("connection refused")
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert any("lookup failed" in msg.lower() for msg, _ in events.logs)
        mock_client.upload_audiobook.assert_not_called()

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_upload_error_logged_not_raised(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        from abogen.integrations.audiobookshelf import AudiobookshelfUploadError

        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = []
        mock_client.upload_audiobook.side_effect = AudiobookshelfUploadError("timeout")
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert any("upload failed" in msg.lower() for msg, _ in events.logs)

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_delete_error_logged_not_raised(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = [{"id": "old-item"}]
        mock_client.delete_items.side_effect = Exception("network error")
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings()
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        assert any("failed to remove" in msg.lower() for msg, _ in events.logs)
        mock_client.upload_audiobook.assert_called_once()

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_cover_included_when_exists(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"jpeg-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = []
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings(send_cover=True)
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        from abogen.application.conversion_config import CoverConfig
        request.cover = CoverConfig(path=cover_path, mime="image/jpeg")
        result = _make_result(audio_path=audio_path)
        events = _FakeEvents()

        hooks.run(request, result, events)

        call_kwargs = mock_client.upload_audiobook.call_args
        assert call_kwargs[1]["cover_path"] == cover_path

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_subtitles_included_when_enabled(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")
        subtitle_path = tmp_path / "book.srt"
        subtitle_path.write_bytes(b"srt-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = []
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings(send_subtitles=True)
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        result.subtitle_paths = [subtitle_path]
        events = _FakeEvents()

        hooks.run(request, result, events)

        call_kwargs = mock_client.upload_audiobook.call_args
        assert call_kwargs[1]["subtitles"] == [subtitle_path]

    @patch("abogen.application.integration_hooks.AudiobookshelfClient")
    @patch("abogen.application.integration_hooks.stored_integration_config")
    def test_subtitles_skipped_when_disabled(
        self, mock_stored: MagicMock, mock_client_cls: MagicMock, tmp_path: Path,
    ) -> None:
        audio_path = tmp_path / "book.mp3"
        audio_path.write_bytes(b"audio-content")
        subtitle_path = tmp_path / "book.srt"
        subtitle_path.write_bytes(b"srt-content")

        mock_client = MagicMock()
        mock_client.find_existing_items.return_value = []
        mock_client_cls.return_value = mock_client

        mock_stored.return_value = _abs_settings(send_subtitles=False)
        hooks = PostConversionHooks()
        request = _make_request(original_filename="book.mp3")
        result = _make_result(audio_path=audio_path)
        result.subtitle_paths = [subtitle_path]
        events = _FakeEvents()

        hooks.run(request, result, events)

        call_kwargs = mock_client.upload_audiobook.call_args
        assert call_kwargs[1]["subtitles"] is None
