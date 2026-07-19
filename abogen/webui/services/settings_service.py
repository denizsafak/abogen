"""Settings form-to-dict mapping.

Pure functions that convert form data into a settings dict.
No Flask dependencies — testable without a request context.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def apply_form_to_settings(current: dict, form: Mapping[str, Any]) -> dict:
    """Apply form data to a settings dict.

    Pure function: takes a current settings dict and a form-like mapping,
    returns the updated settings dict. No Flask dependencies.

    Args:
        current: Current settings dict (will be mutated).
        form: Form-like mapping (e.g. request.form.to_dict()).

    Returns:
        Updated settings dict (same object as input).
    """
    from abogen.domain.settings_core import (
        coerce_bool,
        coerce_int,
        DEFAULT_ANALYSIS_THRESHOLD,
        _NORMALIZATION_BOOLEAN_KEYS,
        _NORMALIZATION_STRING_KEYS,
    )
    from abogen.webui.routes.utils.settings import stored_integration_config
    from abogen.webui.routes.utils.common import extract_checkbox
    from abogen.utils import load_config
    # General settings
    current["language"] = (form.get("language") or "en").strip()
    current["default_speaker"] = (form.get("default_speaker") or "").strip()
    current["default_voice"] = (form.get("default_voice") or "").strip()
    try:
        current["supertonic_total_steps"] = max(2, min(15, int(form.get("supertonic_total_steps", current.get("supertonic_total_steps", 5)))))
    except (TypeError, ValueError):
        pass
    try:
        current["supertonic_speed"] = max(0.7, min(2.0, float(form.get("supertonic_speed", current.get("supertonic_speed", 1.0)))))
    except (TypeError, ValueError):
        pass
    current["output_format"] = (form.get("output_format") or "mp3").strip()
    current["subtitle_mode"] = (form.get("subtitle_mode") or "Disabled").strip()
    current["subtitle_format"] = (form.get("subtitle_format") or "srt").strip()
    current["save_mode"] = (form.get("save_mode") or "save_next_to_input").strip()

    current["replace_single_newlines"] = coerce_bool(form.get("replace_single_newlines"), False)
    current["use_gpu"] = coerce_bool(form.get("use_gpu"), False)
    current["save_chapters_separately"] = coerce_bool(form.get("save_chapters_separately"), False)
    current["merge_chapters_at_end"] = coerce_bool(form.get("merge_chapters_at_end"), True)
    current["save_as_project"] = coerce_bool(form.get("save_as_project"), False)
    current["separate_chapters_format"] = (form.get("separate_chapters_format") or "wav").strip()

    try:
        current["silence_between_chapters"] = max(0.0, float(form.get("silence_between_chapters", 2.0)))
    except ValueError:
        pass

    try:
        current["chapter_intro_delay"] = max(0.0, float(form.get("chapter_intro_delay", 0.5)))
    except ValueError:
        pass

    current["read_title_intro"] = coerce_bool(form.get("read_title_intro"), False)
    current["read_closing_outro"] = coerce_bool(form.get("read_closing_outro"), True)
    current["normalize_chapter_opening_caps"] = coerce_bool(form.get("normalize_chapter_opening_caps"), True)
    current["auto_prefix_chapter_titles"] = coerce_bool(form.get("auto_prefix_chapter_titles"), True)

    try:
        current["max_subtitle_words"] = max(1, int(form.get("max_subtitle_words", 50)))
    except ValueError:
        pass

    current["chunk_level"] = (form.get("chunk_level") or "paragraph").strip()
    current["generate_epub3"] = coerce_bool(form.get("generate_epub3"), False)

    current["speaker_analysis_threshold"] = coerce_int(
        form.get("speaker_analysis_threshold"),
        DEFAULT_ANALYSIS_THRESHOLD,
        minimum=1,
        maximum=25,
    )

    # Normalization settings
    for key in _NORMALIZATION_BOOLEAN_KEYS:
        current[key] = extract_checkbox(form, key, bool(current.get(key, True)))
    for key in _NORMALIZATION_STRING_KEYS:
        if key in form:
            current[key] = (form.get(key) or "").strip()

    # Integrations — seed from stored config to prevent wiping credentials
    current_integrations: dict[str, dict[str, Any]] = {}
    cfg = load_config() or {}
    stored_integrations = cfg.get("integrations")
    if isinstance(stored_integrations, Mapping):
        for name, payload in stored_integrations.items():
            if isinstance(name, str) and isinstance(payload, Mapping):
                current_integrations[name] = dict(payload)
    for name in ("audiobookshelf", "calibre_opds"):
        stored = stored_integration_config(name)
        if stored and name not in current_integrations:
            current_integrations[name] = dict(stored)
    current["integrations"] = current_integrations

    # Audiobookshelf
    abs_enabled = coerce_bool(form.get("audiobookshelf_enabled"), False)
    abs_url = (form.get("audiobookshelf_base_url") or "").strip()
    abs_token = (form.get("audiobookshelf_api_token") or "").strip()
    abs_library = (form.get("audiobookshelf_library_id") or "").strip()
    abs_folder = (form.get("audiobookshelf_folder_id") or "").strip()
    abs_verify = coerce_bool(form.get("audiobookshelf_verify_ssl"), True)
    abs_auto_send = coerce_bool(form.get("audiobookshelf_auto_send"), False)
    abs_cover = coerce_bool(form.get("audiobookshelf_send_cover"), True)
    abs_chapters = coerce_bool(form.get("audiobookshelf_send_chapters"), True)
    abs_subtitles = coerce_bool(form.get("audiobookshelf_send_subtitles"), False)

    try:
        abs_timeout = max(1.0, float(form.get("audiobookshelf_timeout", 30.0)))
    except ValueError:
        abs_timeout = 30.0

    if not abs_token and not coerce_bool(form.get("audiobookshelf_api_token_clear"), False):
        existing_abs = current["integrations"].get("audiobookshelf", {})
        abs_token = existing_abs.get("api_token", "")

    current["integrations"]["audiobookshelf"] = {
        "enabled": abs_enabled,
        "base_url": abs_url,
        "api_token": abs_token,
        "library_id": abs_library,
        "folder_id": abs_folder,
        "verify_ssl": abs_verify,
        "auto_send": abs_auto_send,
        "send_cover": abs_cover,
        "send_chapters": abs_chapters,
        "send_subtitles": abs_subtitles,
        "timeout": abs_timeout,
    }

    # Calibre OPDS
    calibre_enabled = coerce_bool(form.get("calibre_opds_enabled"), False)
    calibre_url = (form.get("calibre_opds_base_url") or "").strip()
    calibre_user = (form.get("calibre_opds_username") or "").strip()
    calibre_pass = (form.get("calibre_opds_password") or "").strip()
    calibre_verify = coerce_bool(form.get("calibre_opds_verify_ssl"), True)

    if not calibre_pass and not coerce_bool(form.get("calibre_opds_password_clear"), False):
        existing_calibre = current["integrations"].get("calibre_opds", {})
        calibre_pass = existing_calibre.get("password", "")

    current["integrations"]["calibre_opds"] = {
        "enabled": calibre_enabled,
        "base_url": calibre_url,
        "username": calibre_user,
        "password": calibre_pass,
        "verify_ssl": calibre_verify,
    }

    return current
