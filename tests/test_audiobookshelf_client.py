from __future__ import annotations

import json

from abogen.integrations.audiobookshelf import AudiobookshelfClient, AudiobookshelfConfig


def test_upload_fields_include_series_sequence(tmp_path):
    audio_path = tmp_path / "book.mp3"
    audio_path.write_bytes(b"audio")

    config = AudiobookshelfConfig(
        base_url="https://example.test",
        api_token="token",
        library_id="library-id",
        folder_id="folder-id",
    )
    client = AudiobookshelfClient(config)

    client._folder_cache = ("folder-id", "Folder", "Library")

    metadata = {
        "title": "Example Title",
        "seriesName": "Example Saga",
        "seriesSequence": "7",
    }

    fields = client._build_upload_fields(audio_path, metadata, chapters=None)

    assert fields["series"] == "Example Saga"
    assert fields["seriesSequence"] == "7"

    assert "metadata" in fields
    payload = json.loads(fields["metadata"])
    assert payload["seriesSequence"] == "7"


def test_upload_fields_normalize_alternate_sequence_keys(tmp_path):
    audio_path = tmp_path / "book.mp3"
    audio_path.write_bytes(b"audio")

    config = AudiobookshelfConfig(
        base_url="https://example.test",
        api_token="token",
        library_id="library-id",
        folder_id="folder-id",
    )
    client = AudiobookshelfClient(config)
    client._folder_cache = ("folder-id", "Folder", "Library")

    metadata = {
        "title": "Example Title",
        "seriesName": "Example Saga",
        "series_index": "Book 3",
    }

    fields = client._build_upload_fields(audio_path, metadata, chapters=None)

    assert fields["series"] == "Example Saga"
    assert fields["seriesSequence"] == "3"


def test_upload_fields_preserve_decimal_sequence(tmp_path):
    audio_path = tmp_path / "book.mp3"
    audio_path.write_bytes(b"audio")

    config = AudiobookshelfConfig(
        base_url="https://example.test",
        api_token="token",
        library_id="library-id",
        folder_id="folder-id",
    )
    client = AudiobookshelfClient(config)
    client._folder_cache = ("folder-id", "Folder", "Library")

    metadata = {
        "title": "Example Title",
        "seriesName": "Example Saga",
        "seriesSequence": "0.5",
    }

    fields = client._build_upload_fields(audio_path, metadata, chapters=None)

    assert fields["seriesSequence"] == "0.5"
