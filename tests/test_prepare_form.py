from pathlib import Path

from werkzeug.datastructures import MultiDict

from abogen.webui.routes.utils.form import apply_prepare_form
from abogen.webui.routes.utils.voice import resolve_voice_setting
from abogen.webui.service import PendingJob


def _make_pending_job() -> PendingJob:
    return PendingJob(
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


def test_apply_prepare_form_handles_custom_mix_for_speakers():
    pending = _make_pending_job()
    pending.speakers = {
        "hero": {
            "id": "hero",
            "label": "Hero",
        }
    }

    form = MultiDict(
        {
            "chapter_intro_delay": "0.5",
            "speaker-hero-voice": "__custom_mix",
            "speaker-hero-formula": "af_nova*0.6+am_liam*0.4",
        }
    )

    _, _, _, errors, *_ = apply_prepare_form(pending, form)

    assert not errors
    hero = pending.speakers["hero"]
    assert hero["voice_formula"] == "af_nova*0.6+am_liam*0.4"
    assert hero["resolved_voice"] == "af_nova*0.6+am_liam*0.4"
    assert "voice" not in hero or hero["voice"] != "__custom_mix"


def test_apply_prepare_form_accepts_saved_speaker_reference_for_voice():
    pending = _make_pending_job()
    pending.speakers = {
        "hero": {
            "id": "hero",
            "label": "Hero",
        }
    }

    form = MultiDict(
        {
            "chapter_intro_delay": "0.5",
            "speaker-hero-voice": "speaker:Female HQ",
            "speaker-hero-formula": "",
        }
    )

    _, _, _, errors, *_ = apply_prepare_form(pending, form)

    assert not errors
    hero = pending.speakers["hero"]
    assert hero["voice"] == "speaker:Female HQ"
    assert hero["resolved_voice"] == "speaker:Female HQ"
    assert "voice_formula" not in hero


def test_resolve_voice_setting_handles_profile_reference():
    profiles = {
        "Blend": {
            "language": "b",
            "voices": [
                ("af_nova", 1.0),
                ("am_liam", 1.0),
            ],
        }
    }

    voice, profile_name, language = resolve_voice_setting("profile:Blend", profiles=profiles)

    assert voice == "af_nova*0.5+am_liam*0.5"
    assert profile_name == "Blend"
    assert language == "b"


def test_apply_prepare_form_updates_closing_outro_flag():
    pending = _make_pending_job()
    pending.read_closing_outro = True
    form = MultiDict({
        "read_closing_outro": "false",
    })

    apply_prepare_form(pending, form)

    assert pending.read_closing_outro is False
