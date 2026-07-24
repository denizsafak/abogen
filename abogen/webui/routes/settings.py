from pathlib import Path

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, send_file, abort
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.settings import (
    load_integration_settings,
    load_settings,
    save_settings,
    SAVE_MODE_LABELS,
    llm_ready,
)
from abogen.webui.routes.utils.voice import template_options
from abogen.webui.services.settings_service import apply_form_to_settings
from abogen.webui.debug_tts_runner import run_debug_tts_wavs
from abogen.debug_tts_samples import DEBUG_TTS_SAMPLES
from abogen.utils import get_user_output_path

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
    apply_form_to_settings(current, request.form)
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
