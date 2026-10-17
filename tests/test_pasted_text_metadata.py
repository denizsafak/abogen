from io import BytesIO
import re
from pathlib import Path

from abogen.webui.app import create_app

UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _create_test_app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key",
            "OUTPUT_FOLDER": str(tmp_path / "output"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )


def test_pasted_text_without_headings_uses_user_supplied_title(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": "This is a single block of pasted text with no headings at all.",
                "title": "Paste Test",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    # Title tag and album tag use user-supplied title
    assert pending.metadata_tags.get("title") == "Paste Test"
    assert pending.metadata_tags.get("album") == "Paste Test"

    # Chapter 1 title uses user-supplied title
    assert len(pending.chapters) == 1
    assert pending.chapters[0]["title"] == "Paste Test"

    # Assert no UUID leak
    assert not UUID_PATTERN.match(str(pending.metadata_tags.get("album", "")))
    assert not UUID_PATTERN.match(str(pending.chapters[0]["title"]))


def test_pasted_text_without_user_title_defaults_to_pasted_text(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": "Pasted text with no title provided in form.",
                "title": "",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    assert pending.metadata_tags.get("title") == "Pasted Text"
    assert pending.metadata_tags.get("album") == "Pasted Text"
    assert pending.chapters[0]["title"] == "Pasted Text"
    assert not UUID_PATTERN.match(str(pending.metadata_tags.get("album", "")))
    assert not UUID_PATTERN.match(str(pending.chapters[0]["title"]))


def test_pasted_text_preserves_extracted_title_when_user_title_omitted(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    text_with_title = (
        "<<METADATA_TITLE:The Secret Chronicle>>\n"
        "A fascinating journey begins here without any explicit chapter markers."
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": text_with_title,
                "title": "",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    assert pending.metadata_tags.get("title") == "The Secret Chronicle"
    assert pending.metadata_tags.get("album") == "The Secret Chronicle"
    assert pending.chapters[0]["title"] == "The Secret Chronicle"
    assert not UUID_PATTERN.match(str(pending.metadata_tags.get("album", "")))
    assert not UUID_PATTERN.match(str(pending.chapters[0]["title"]))


def test_pasted_text_preserves_explicit_album_metadata(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    text_with_album = (
        "<<METADATA_TITLE:Episode Four>>\n"
        "<<METADATA_ALBUM:Season One Anthology>>\n"
        "Just the script lines for episode four."
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": text_with_album,
                "title": "Episode 4 Override",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    # User-supplied title overrides document title
    assert pending.metadata_tags.get("title") == "Episode 4 Override"
    # Explicit album tag from text is NOT clobbered
    assert pending.metadata_tags.get("album") == "Season One Anthology"
    # Single unheaded chapter fallback receives the user-supplied title
    assert pending.chapters[0]["title"] == "Episode 4 Override"


def test_pasted_text_multi_chapter_preserves_valid_chapter_titles(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    multi_chapter_text = (
        "<<CHAPTER_MARKER:Chapter 1: The Departure>>\n"
        "They set out into the misty morning.\n"
        "<<CHAPTER_MARKER:Chapter 2: The Crossing>>\n"
        "The river was wider than anticipated.\n"
        "<<CHAPTER_MARKER:Chapter 3: The Arrival>>\n"
        "They finally reached the ancient fortress.\n"
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": multi_chapter_text,
                "title": "The Long Journey",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    assert pending.metadata_tags.get("title") == "The Long Journey"
    assert pending.metadata_tags.get("album") == "The Long Journey"

    # All valid chapter titles must be preserved
    assert len(pending.chapters) == 3
    assert pending.chapters[0]["title"] == "Chapter 1: The Departure"
    assert pending.chapters[1]["title"] == "Chapter 2: The Crossing"
    assert pending.chapters[2]["title"] == "Chapter 3: The Arrival"


def test_pasted_text_with_unheaded_preface_and_headings(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    text_with_preface = (
        "Some preface remarks before chapter one begins.\n"
        "<<CHAPTER_MARKER:Chapter 1: Dawn>>\n"
        "The morning sun broke through the clouds.\n"
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": text_with_preface,
                "title": "Novel with Preface",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    assert len(pending.chapters) == 2
    # The first unheaded segment fallback receives the novel title instead of UUID
    assert pending.chapters[0]["title"] == "Novel with Preface"
    # The second segment retains its matched heading
    assert pending.chapters[1]["title"] == "Chapter 1: Dawn"


def test_pasted_text_accepts_meta_title_form_field(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    with app.test_client() as client:
        response = client.post(
            "/wizard/text?format=json",
            data={
                "text": "Plain text submission using meta_title key.",
                "meta_title": "Title From Meta Field",
            },
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None

    assert pending.metadata_tags.get("title") == "Title From Meta Field"
    assert pending.metadata_tags.get("album") == "Title From Meta Field"
    assert pending.chapters[0]["title"] == "Title From Meta Field"


def test_ordinary_file_upload_unaffected(tmp_path: Path):
    app = _create_test_app(tmp_path)
    service = app.extensions["conversion_service"]

    sample_content = b"Simple uploaded text without headings."
    file_data = {
        "source_file": (BytesIO(sample_content), "my_uploaded_file.txt"),
    }

    with app.test_client() as client:
        response = client.post(
            "/wizard/upload?format=json",
            data=file_data,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    pending_id = response.get_json()["pending_id"]
    pending = service.get_pending_job(pending_id)
    assert pending is not None
    assert pending.original_filename == "my_uploaded_file.txt"
