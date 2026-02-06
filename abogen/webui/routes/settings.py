from pathlib import Path

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, send_file, abort
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.settings import (
    load_settings,
    load_integration_settings,
    save_settings,
    stored_integration_config,
    coerce_bool,
    coerce_int,
    SAVE_MODE_LABELS,
    llm_ready,
    _NORMALIZATION_BOOLEAN_KEYS,
    _NORMALIZATION_STRING_KEYS,
    _DEFAULT_ANALYSIS_THRESHOLD,
)
from abogen.webui.routes.utils.voice import template_options
from abogen.webui.debug_tts_runner import run_debug_tts_wavs
from abogen.debug_tts_samples import DEBUG_TTS_SAMPLES
from abogen.utils import get_user_output_path, load_config

settings_bp = Blueprint("settings", __name__)

_NORMALIZATION_SAMPLES = {
    "apostrophes": "It's a beautiful day, isn't it? 'Yes,' she said, 'it is.'",
    "currency": "The price is $10.50, but it was £8.00 yesterday.",
    "dates": "On 2023-01-01, we celebrated the new year.",
    "numbers": "There are 123 apples and 456 oranges.",
    "abbreviations": "Dr. Smith lives on Elm St. near the U.S. border.",
}

@settings_bp.post("/update")
def update_settings() -> ResponseReturnValue:
    current = load_settings()
    form = request.form

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
        _DEFAULT_ANALYSIS_THRESHOLD,
        minimum=1,
        maximum=25,
    )

    def _extract_checkbox(name: str, default: bool) -> bool:
        values = form.getlist(name) if hasattr(form, "getlist") else []
        if values:
            return coerce_bool(values[-1], default)
        if hasattr(form, "__contains__") and name in form:
            return False
        return default

    # Normalization settings
    for key in _NORMALIZATION_BOOLEAN_KEYS:
        current[key] = _extract_checkbox(key, bool(current.get(key, True)))
    for key in _NORMALIZATION_STRING_KEYS:
        if hasattr(form, "__contains__") and key in form:
            current[key] = (form.get(key) or "").strip()

    # Integrations
    # `load_settings()` returns only the general settings subset and intentionally
    # does not include stored integrations. Seed them from the stored config so
    # saving unrelated settings cannot wipe credentials/tokens.
    current_integrations: dict[str, dict[str, Any]] = {}
    cfg = load_config() or {}
    stored_integrations = cfg.get("integrations")
    if isinstance(stored_integrations, Mapping):
        for name, payload in stored_integrations.items():
            if isinstance(name, str) and isinstance(payload, Mapping):
                current_integrations[name] = dict(payload)
    # Ensure known integrations are loaded even if the config is still in legacy format.
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

    # Preserve existing token if not provided and not cleared
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
    
    # Preserve existing password if not provided and not cleared
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

    save_settings(current)
    flash("Settings updated successfully.", "success")
    return redirect(url_for("settings.settings_page"))

@settings_bp.route("/", methods=["GET", "POST"])
def settings_page() -> str | ResponseReturnValue:
    if request.method == "POST":
        return update_settings()

    debug_run_id = (request.args.get("debug_run_id") or "").strip()
    debug_manifest = None
    if debug_run_id:
        run_dir = Path(current_app.config.get("OUTPUT_FOLDER") or get_user_output_path("web")) / "debug" / debug_run_id
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                import json

                debug_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                debug_manifest = None

    save_locations = [{"value": key, "label": label} for key, label in SAVE_MODE_LABELS.items()]
    default_output_dir = str(Path(get_user_output_path()).resolve())

    return render_template(
        "settings.html",
        settings=load_settings(),
        integrations=load_integration_settings(),
        options=template_options(),
        normalization_samples=_NORMALIZATION_SAMPLES,
        save_locations=save_locations,
        default_output_dir=default_output_dir,
        llm_ready=llm_ready(load_settings()),
        debug_samples=DEBUG_TTS_SAMPLES,
        debug_manifest=debug_manifest,
    )


@settings_bp.post("/debug/run")
def run_debug_wavs() -> ResponseReturnValue:
    settings = load_settings()
    output_root = Path(current_app.config.get("OUTPUT_FOLDER") or get_user_output_path("web"))
    try:
        manifest = run_debug_tts_wavs(output_root=output_root, settings=settings)
    except Exception as exc:
        flash(f"Debug WAV generation failed: {exc}", "error")
        return redirect(url_for("settings.settings_page", _anchor="debug"))

    flash("Debug WAV generation completed.", "success")
    return redirect(url_for("settings.debug_wavs_page", run_id=str(manifest.get("run_id") or "")))


@settings_bp.get("/debug/<run_id>")
def debug_wavs_page(run_id: str) -> ResponseReturnValue:
    safe_run = (run_id or "").strip()
    if not safe_run:
        abort(404)

    root = Path(current_app.config.get("OUTPUT_FOLDER") or get_user_output_path("web"))
    run_dir = (root / "debug" / safe_run).resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        abort(404)

    try:
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        abort(404)

    artifacts = manifest.get("artifacts") or []
    # Precompute download URLs for each artifact.
    for item in artifacts:
        filename = str(item.get("filename") or "")
        item["url"] = url_for("settings.download_debug_wav", run_id=safe_run, filename=filename)

    return render_template(
        "debug_wavs.html",
        run_id=safe_run,
        artifacts=artifacts,
    )


@settings_bp.get("/debug/<run_id>/<filename>")
def download_debug_wav(run_id: str, filename: str) -> ResponseReturnValue:
    safe_run = (run_id or "").strip()
    safe_name = (filename or "").strip()
    if not safe_run or not safe_name or "/" in safe_name or "\\" in safe_name:
        abort(404)
    is_wav = safe_name.lower().endswith(".wav")
    if not is_wav and safe_name != "manifest.json":
        abort(404)

    root = Path(current_app.config.get("OUTPUT_FOLDER") or get_user_output_path("web"))
    path = (root / "debug" / safe_run / safe_name).resolve()
    if not path.exists() or not path.is_file():
        abort(404)
    # Ensure path is within root/debug/run_id
    expected_dir = (root / "debug" / safe_run).resolve()
    if expected_dir not in path.parents:
        abort(404)
    wants_download = str(request.args.get("download") or "").strip().lower() in {"1", "true", "yes"}
    mimetype = "audio/wav" if is_wav else "application/json"
    # Inline playback should work for WAVs; allow explicit downloads via ?download=1.
    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=wants_download,
        download_name=path.name,
    )
