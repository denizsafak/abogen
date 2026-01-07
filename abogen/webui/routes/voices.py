from typing import Any, Dict, List, Optional
from flask import Blueprint, render_template, request, jsonify, abort, flash, redirect, url_for
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.voice import (
    template_options,
    resolve_voice_setting,
    resolve_voice_choice,
    parse_voice_formula,
)
from abogen.webui.routes.utils.settings import load_settings, coerce_bool
from abogen.webui.routes.utils.preview import synthesize_preview
from abogen.speaker_configs import (
    list_configs,
    get_config,
    load_configs,
    save_configs,
    delete_config,
)
from abogen.constants import VOICES_INTERNAL

voices_bp = Blueprint("voices", __name__)

@voices_bp.get("/")
def voice_profiles() -> ResponseReturnValue:
    return render_template("voices.html", options=template_options())

@voices_bp.post("/test")
def test_voice() -> ResponseReturnValue:
    text = (request.form.get("text") or "").strip()
    voice = (request.form.get("voice") or "").strip()
    speed = float(request.form.get("speed", 1.0))
    
    # This seems to be the form-based preview
    settings = load_settings()
    use_gpu = coerce_bool(settings.get("use_gpu"), True)
    
    try:
        return synthesize_preview(
            text=text,
            voice_spec=voice,
            language="a", # Default language
            speed=speed,
            use_gpu=use_gpu,
        )
    except Exception as e:
        abort(400, str(e))

@voices_bp.get("/configs")
def speaker_configs() -> ResponseReturnValue:
    return jsonify({"configs": list_configs()})

@voices_bp.post("/configs/save")
def save_speaker_config() -> ResponseReturnValue:
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    config = payload.get("config")
    
    if not name:
        abort(400, "Config name is required")
    if not config:
        abort(400, "Config data is required")
        
    configs = load_configs()
    configs[name] = config
    save_configs(configs)
    return jsonify({"status": "saved", "configs": list_configs()})

@voices_bp.post("/configs/delete")
def delete_speaker_config() -> ResponseReturnValue:
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    
    if not name:
        abort(400, "Config name is required")
        
    delete_config(name)
    return jsonify({"status": "deleted", "configs": list_configs()})

@voices_bp.route("/presets", methods=["GET", "POST"])
def speaker_configs_page() -> ResponseReturnValue:
    configs = load_configs()
    editing_name = request.args.get("config")
    message = None
    error = None

    if request.method == "POST":
        try:
            name = request.form.get("config_name", "").strip()
            if not name:
                raise ValueError("Preset name is required")
            
            language = request.form.get("config_language", "en")
            
            speakers = []
            row_keys = request.form.getlist("speaker_rows")
            for key in row_keys:
                s_id = request.form.get(f"speaker-{key}-id", key)
                label = request.form.get(f"speaker-{key}-label", "")
                gender = request.form.get(f"speaker-{key}-gender", "unknown")
                voice = request.form.get(f"speaker-{key}-voice", "")
                
                if label:
                    speakers.append({
                        "id": s_id,
                        "label": label,
                        "gender": gender,
                        "voice": voice or None
                    })
            
            config = {
                "name": name,
                "language": language,
                "speakers": speakers,
                "version": 1
            }
            
            configs[name] = config
            save_configs(configs)
            message = f"Preset '{name}' saved."
            editing_name = name
        except Exception as e:
            error = str(e)

    editing = configs.get(editing_name, {}) if editing_name else {}
    
    return render_template(
        "speakers.html",
        options=template_options(),
        configs=configs.values(),
        editing_name=editing_name,
        editing=editing,
        message=message,
        error=error
    )

@voices_bp.post("/presets/<name>/delete")
def delete_speaker_config_named(name: str) -> ResponseReturnValue:
    delete_config(name)
    return redirect(url_for("voices.speaker_configs_page"))
