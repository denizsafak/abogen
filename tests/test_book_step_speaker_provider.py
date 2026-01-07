from pathlib import Path

from werkzeug.datastructures import MultiDict

from abogen.webui.routes.utils.form import apply_book_step_form
from abogen.webui.service import PendingJob


def _make_pending_job() -> PendingJob:
    pending = PendingJob(
        id="pending",
        original_filename="example.epub",
        stored_path=Path("example.epub"),
        language="a",
        voice="af_nova",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="none",
        output_format="mp3",
        save_mode="save_next_to_input",
        output_folder=None,
        replace_single_newlines=False,
        subtitle_format="srt",
        total_characters=0,
        save_chapters_separately=False,
        merge_chapters_at_end=True,
        separate_chapters_format="wav",
        silence_between_chapters=2.0,
        save_as_project=False,
        voice_profile=None,
        max_subtitle_words=50,
        metadata_tags={},
        chapters=[],
        normalization_overrides={},
        created_at=0.0,
        read_title_intro=False,
        normalize_chapter_opening_caps=True,
    )
    pending.tts_provider = "kokoro"
    return pending


def test_book_step_supertonic_profile_becomes_speaker_reference() -> None:
    pending = _make_pending_job()

    settings = {
        "language": "a",
        "chunk_level": "paragraph",
        "speaker_analysis_threshold": 3,
        "default_voice": "af_nova",
        "default_speaker": "",
        "default_speed": 1.0,
        "read_title_intro": False,
        "read_closing_outro": True,
        "normalize_chapter_opening_caps": True,
    }

    profiles = {
        "Female HQ": {
            "provider": "supertonic",
            "voice": "F3",
            "speed": 1.0,
            "total_steps": 5,
            "language": "a",
        }
    }

    form = MultiDict(
        {
            "language": "a",
            "voice_profile": "Female HQ",
            "speed": "1.0",
        }
    )

    apply_book_step_form(pending, form, settings=settings, profiles=profiles)

    # Voice is stored as a speaker reference so provider can be resolved per-speaker.
    assert pending.voice == "speaker:Female HQ"
    assert pending.voice_profile == "Female HQ"

    # Book-level provider should not be overridden by narrator defaults.
    assert pending.tts_provider == "kokoro"
