from typing import Any, Dict, Mapping, List, Optional
import base64
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file, url_for, current_app
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.settings import (
    load_settings,
    load_integration_settings,
    coerce_float,
    coerce_bool,
    audiobookshelf_settings_from_payload,
    calibre_settings_from_payload,
)
from abogen.voice_profiles import (
    load_profiles,
    save_profiles,
    delete_profile,
    duplicate_profile,
    serialize_profiles,
    import_profiles_data,
    export_profiles_payload,
    normalize_profile_entry,
)
from abogen.webui.routes.utils.common import split_profile_spec
from abogen.webui.routes.utils.preview import synthesize_preview, generate_preview_audio
from abogen.webui.routes.utils.voice import formula_from_profile
from abogen.normalization_settings import (
    build_llm_configuration,
    build_apostrophe_config,
    apply_overrides,
)
from abogen.llm_client import list_models, LLMClientError
from abogen.kokoro_text_normalization import normalize_for_pipeline
from abogen.integrations.audiobookshelf import AudiobookshelfClient, AudiobookshelfConfig
from abogen.integrations.calibre_opds import (
    CalibreOPDSClient,
    CalibreOPDSError,
)
from abogen.webui.routes.utils.service import get_service
from abogen.webui.routes.utils.form import build_pending_job_from_extraction
from abogen.text_extractor import extract_from_path
from werkzeug.utils import secure_filename

api_bp = Blueprint("api", __name__)

# --- Voice Profile Routes ---

@api_bp.get("/voice-profiles")
def api_get_voice_profiles() -> ResponseReturnValue:
    profiles = load_profiles()
    return jsonify(profiles)

@api_bp.post("/voice-profiles")
def api_save_voice_profile() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name") or "").strip()
    original_name = str(payload.get("originalName") or "").strip() or None

    profile = payload.get("profile")
    if profile is None:
        # Speaker Studio payload format
        provider = str(payload.get("provider") or "kokoro").strip().lower()
        if provider not in {"kokoro", "supertonic"}:
            provider = "kokoro"
        if provider == "supertonic":
            profile = {
                "provider": "supertonic",
                "language": str(payload.get("language") or "a").strip().lower() or "a",
                "voice": payload.get("voice"),
                "total_steps": payload.get("total_steps") or payload.get("supertonic_total_steps"),
                "speed": payload.get("speed") or payload.get("supertonic_speed"),
            }
        else:
            profile = {
                "provider": "kokoro",
                "language": str(payload.get("language") or "a").strip().lower() or "a",
                "voices": payload.get("voices") or [],
            }
    
    if not name or not profile:
        return jsonify({"error": "Name and profile are required"}), 400
        
    profiles = load_profiles()

    normalized = normalize_profile_entry(profile)
    if not normalized:
        return jsonify({"error": "Invalid profile payload"}), 400

    if original_name and original_name in profiles and original_name != name:
        del profiles[original_name]

    profiles[name] = normalized
    save_profiles(profiles)

    return jsonify({"success": True, "profile": name, "profiles": serialize_profiles()})

@api_bp.delete("/voice-profiles/<path:name>")
def api_delete_voice_profile(name: str) -> ResponseReturnValue:
    delete_profile(name)
    return jsonify({"success": True, "profiles": serialize_profiles()})


@api_bp.post("/voice-profiles/<path:name>/duplicate")
def api_duplicate_voice_profile(name: str) -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    new_name = str(payload.get("name") or "").strip()
    if not new_name:
        return jsonify({"error": "Name is required"}), 400
    duplicate_profile(name, new_name)
    return jsonify({"success": True, "profile": new_name, "profiles": serialize_profiles()})


@api_bp.post("/voice-profiles/import")
def api_import_voice_profiles() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    data = payload.get("data")
    replace_existing = bool(payload.get("replace_existing"))
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid profile payload"}), 400
    try:
        imported = import_profiles_data(data, replace_existing=replace_existing)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "imported": imported, "profiles": serialize_profiles()})


@api_bp.get("/voice-profiles/export")
def api_export_voice_profiles() -> ResponseReturnValue:
    names_param = request.args.get("names")
    names = None
    if names_param:
        names = [item.strip() for item in names_param.split(",") if item.strip()]
    payload = export_profiles_payload(names)
    import io
    import json

    data = json.dumps(payload, indent=2).encode("utf-8")
    filename = "voice_profiles.json" if not names else "voice_profiles_export.json"
    return send_file(
        io.BytesIO(data),
        mimetype="application/json",
        as_attachment=True,
        download_name=filename,
    )


@api_bp.post("/voice-profiles/preview")
def api_voice_profiles_preview() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    text = str(payload.get("text") or "").strip() or "Hello world"
    language = str(payload.get("language") or "a").strip().lower() or "a"
    speed = coerce_float(payload.get("speed"), 1.0)
    max_seconds = coerce_float(payload.get("max_seconds"), 8.0)

    settings = load_settings()
    use_gpu = settings.get("use_gpu", False)

    # Accept a direct formula string or a full profile entry.
    formula = str(payload.get("formula") or "").strip()
    profile_name = str(payload.get("profile") or "").strip()
    provider = str(payload.get("tts_provider") or payload.get("provider") or "").strip().lower() or None
    supertonic_total_steps = int(payload.get("supertonic_total_steps") or payload.get("total_steps") or settings.get("supertonic_total_steps") or 5)

    voice_spec = ""
    resolved_provider = provider or "kokoro"

    profiles = load_profiles()
    if resolved_provider == "supertonic" and not profile_name:
        voice_spec = str(payload.get("voice") or payload.get("supertonic_voice") or "M1").strip() or "M1"
        # Allow per-speaker overrides via payload.
        supertonic_total_steps = int(payload.get("supertonic_total_steps") or payload.get("total_steps") or supertonic_total_steps)
        speed = coerce_float(payload.get("supertonic_speed") or payload.get("speed"), speed)
    elif profile_name:
        entry = profiles.get(profile_name)
        normalized_entry = normalize_profile_entry(entry)
        if not normalized_entry:
            return jsonify({"error": "Unknown profile"}), 404
        resolved_provider = str(normalized_entry.get("provider") or "kokoro")
        if resolved_provider == "supertonic":
            voice_spec = str(normalized_entry.get("voice") or "M1")
            supertonic_total_steps = int(normalized_entry.get("total_steps") or supertonic_total_steps)
            speed = float(normalized_entry.get("speed") or speed)
        else:
            voice_spec = formula_from_profile(normalized_entry) or ""
            language = str(normalized_entry.get("language") or language)
    elif formula:
        voice_spec = formula
        resolved_provider = "kokoro"
    else:
        # Raw voices payload -> Kokoro mix.
        voices = payload.get("voices") or []
        pseudo = {"provider": "kokoro", "language": language, "voices": voices}
        normalized_entry = normalize_profile_entry(pseudo)
        voice_spec = formula_from_profile(normalized_entry) or ""
        resolved_provider = "kokoro"

    if not voice_spec:
        return jsonify({"error": "Unable to resolve preview voice"}), 400

    try:
        return synthesize_preview(
            text=text,
            voice_spec=voice_spec,
            language=language,
            speed=speed,
            use_gpu=use_gpu,
            tts_provider=resolved_provider,
            supertonic_total_steps=supertonic_total_steps,
            max_seconds=max_seconds,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@api_bp.post("/speaker-preview")
def api_speaker_preview() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    pending_id = str(payload.get("pending_id") or "").strip()
    text = payload.get("text", "Hello world")
    voice = payload.get("voice", "af_heart")
    language = payload.get("language", "a")
    speed_value = payload.get("speed")
    speed = coerce_float(speed_value, 1.0)
    tts_provider = str(payload.get("tts_provider") or "").strip().lower()
    supertonic_total_steps = int(payload.get("supertonic_total_steps") or 5)
    
    settings = load_settings()
    use_gpu = settings.get("use_gpu", False)

    base_spec, speaker_name = split_profile_spec(voice)
    resolved_provider = tts_provider if tts_provider in {"kokoro", "supertonic"} else ""

    if speaker_name:
        entry = normalize_profile_entry(load_profiles().get(speaker_name))
        if entry:
            resolved_provider = str(entry.get("provider") or resolved_provider or "")
            if resolved_provider == "supertonic":
                voice = str(entry.get("voice") or "M1")
                supertonic_total_steps = int(entry.get("total_steps") or supertonic_total_steps)
                if speed_value is None:
                    speed = coerce_float(entry.get("speed"), speed)
            elif resolved_provider == "kokoro":
                voice = formula_from_profile(entry) or (base_spec or voice)

    if not resolved_provider:
        resolved_provider = "supertonic" if str(base_spec or "").strip() in {"M1","M2","M3","M4","M5","F1","F2","F3","F4","F5"} else "kokoro"

    pronunciation_overrides = None
    manual_overrides = None
    speakers = None
    if pending_id:
        try:
            pending = get_service().get_pending_job(pending_id)
        except Exception:
            pending = None
        if pending is not None:
            manual_overrides = getattr(pending, "manual_overrides", None)
            pronunciation_overrides = getattr(pending, "pronunciation_overrides", None)
            speakers = getattr(pending, "speakers", None)
    
    try:
        return synthesize_preview(
            text=text,
            voice_spec=voice,
            language=language,
            speed=speed,
            use_gpu=use_gpu
            ,
            tts_provider=resolved_provider,
            supertonic_total_steps=supertonic_total_steps or int(settings.get("supertonic_total_steps") or 5),
            pronunciation_overrides=pronunciation_overrides,
            manual_overrides=manual_overrides,
            speakers=speakers,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Integration Routes ---


def _opds_metadata_overrides(metadata_payload: Mapping[str, Any]) -> Dict[str, Any]:
    metadata_overrides: Dict[str, Any] = {}

    def _stringify_metadata_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item is not None]
            parts = [part for part in parts if part]
            return ", ".join(parts)
        return str(value).strip()

    raw_series = metadata_payload.get("series") or metadata_payload.get("series_name")
    series_name = str(raw_series or "").strip()
    if series_name:
        metadata_overrides["series"] = series_name
        metadata_overrides.setdefault("series_name", series_name)

    series_index_value = (
        metadata_payload.get("series_index")
        or metadata_payload.get("series_position")
        or metadata_payload.get("series_sequence")
        or metadata_payload.get("book_number")
    )
    if series_index_value is not None:
        series_index_text = str(series_index_value).strip()
        if series_index_text:
            metadata_overrides.setdefault("series_index", series_index_text)
            metadata_overrides.setdefault("series_position", series_index_text)
            metadata_overrides.setdefault("series_sequence", series_index_text)
            metadata_overrides.setdefault("book_number", series_index_text)

    tags_value = metadata_payload.get("tags") or metadata_payload.get("keywords")
    if tags_value:
        tags_text = _stringify_metadata_value(tags_value)
        if tags_text:
            metadata_overrides.setdefault("tags", tags_text)
            metadata_overrides.setdefault("keywords", tags_text)
            metadata_overrides.setdefault("genre", tags_text)

    description_value = metadata_payload.get("description") or metadata_payload.get("summary")
    if description_value:
        description_text = _stringify_metadata_value(description_value)
        if description_text:
            metadata_overrides.setdefault("description", description_text)
            metadata_overrides.setdefault("summary", description_text)

    subtitle_value = (
        metadata_payload.get("subtitle")
        or metadata_payload.get("sub_title")
        or metadata_payload.get("calibre_subtitle")
    )
    if subtitle_value:
        subtitle_text = _stringify_metadata_value(subtitle_value)
        if subtitle_text:
            metadata_overrides.setdefault("subtitle", subtitle_text)

    publisher_value = metadata_payload.get("publisher")
    if publisher_value:
        publisher_text = _stringify_metadata_value(publisher_value)
        if publisher_text:
            metadata_overrides.setdefault("publisher", publisher_text)

    # Author mapping: Abogen templates look for either 'authors' or 'author'.
    authors_value = (
        metadata_payload.get("authors")
        or metadata_payload.get("author")
        or metadata_payload.get("creator")
        or metadata_payload.get("dc_creator")
    )
    if authors_value:
        authors_text = _stringify_metadata_value(authors_value)
        if authors_text:
            metadata_overrides.setdefault("authors", authors_text)
            metadata_overrides.setdefault("author", authors_text)

    return metadata_overrides

@api_bp.get("/integrations/calibre-opds/feed")
def api_calibre_opds_feed() -> ResponseReturnValue:
    integrations = load_integration_settings()
    calibre_settings = integrations.get("calibre_opds", {})
    
    payload = {
        "base_url": calibre_settings.get("base_url"),
        "username": calibre_settings.get("username"),
        "password": calibre_settings.get("password"),
        "verify_ssl": calibre_settings.get("verify_ssl", True),
    }
    
    if not payload.get("base_url"):
        return jsonify({"error": "Calibre OPDS base URL is not configured."}), 400
        
    try:
        client = CalibreOPDSClient(
            base_url=payload.get("base_url") or "",
            username=payload.get("username"),
            password=payload.get("password"),
            verify=bool(payload.get("verify_ssl", True)),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    href = request.args.get("href", type=str)
    query = request.args.get("q", type=str)
    letter = request.args.get("letter", type=str)
    
    try:
        if letter:
            feed = client.browse_letter(letter, start_href=href)
        elif query:
            feed = client.search(query, start_href=href)
        else:
            feed = client.fetch_feed(href)
    except CalibreOPDSError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {str(exc)}"}), 500

    return jsonify({
        "feed": feed.to_dict(),
        "href": href or "",
        "query": query or "",
    })

@api_bp.post("/integrations/audiobookshelf/folders")
def api_abs_folders() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    # Use the helper to resolve saved tokens when use_saved_token is set
    settings = audiobookshelf_settings_from_payload(payload)
    host = settings.get("base_url")
    token = settings.get("api_token")
    library_id = settings.get("library_id")
    
    if not host or not token:
        return jsonify({"error": "Base URL and API token are required"}), 400
    
    if not library_id:
        return jsonify({"error": "Library ID is required to list folders"}), 400
        
    try:
        config = AudiobookshelfConfig(base_url=host, api_token=token, library_id=library_id)
        client = AudiobookshelfClient(config)
        folders = client.list_folders()
        return jsonify({"folders": folders})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@api_bp.post("/integrations/audiobookshelf/test")
def api_abs_test() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    # Use the helper to resolve saved tokens when use_saved_token is set
    settings = audiobookshelf_settings_from_payload(payload)
    host = settings.get("base_url")
    token = settings.get("api_token")
    
    if not host or not token:
        return jsonify({"error": "Base URL and API token are required"}), 400
        
    try:
        config = AudiobookshelfConfig(base_url=host, api_token=token)
        client = AudiobookshelfClient(config)
        # Just getting libraries is a good enough test
        client.get_libraries()
        return jsonify({"success": True, "message": "Connection successful."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@api_bp.post("/integrations/calibre-opds/test")
def api_calibre_opds_test() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    # Use the helper to resolve saved passwords when use_saved_password is set
    settings = calibre_settings_from_payload(payload)
    base_url = settings.get("base_url")
    username = settings.get("username")
    password = settings.get("password")
    verify_ssl = settings.get("verify_ssl", False)
    
    if not base_url:
        return jsonify({"error": "Base URL is required"}), 400
        
    try:
        client = CalibreOPDSClient(
            base_url=base_url,
            username=username,
            password=password,
            verify=verify_ssl,
            timeout=10.0
        )
        client.fetch_feed()
        return jsonify({"success": True, "message": "Connection successful."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@api_bp.post("/integrations/calibre-opds/import")
def api_calibre_opds_import() -> ResponseReturnValue:
    if not request.is_json:
        return jsonify({"error": "Expected JSON payload."}), 400
    
    data = request.get_json(force=True, silent=True) or {}
    href = str(data.get("href") or "").strip()
    
    if not href:
        return jsonify({"error": "Download URL (href) is required."}), 400
        
    metadata_payload = data.get("metadata") if isinstance(data, Mapping) else None
    metadata_overrides: Dict[str, Any] = {}
    if isinstance(metadata_payload, Mapping):
        metadata_overrides = _opds_metadata_overrides(metadata_payload)

    settings = load_settings()
    integrations = load_integration_settings()
    calibre_settings = integrations.get("calibre_opds", {})
    
    try:
        client = CalibreOPDSClient(
            base_url=calibre_settings.get("base_url") or "",
            username=calibre_settings.get("username"),
            password=calibre_settings.get("password"),
            verify=bool(calibre_settings.get("verify_ssl", True)),
        )
        
        temp_dir = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
        temp_dir.mkdir(exist_ok=True)
        
        resource = client.download(href)
        filename = resource.filename
        content = resource.content
        
        if not filename:
            filename = f"{uuid.uuid4().hex}.epub"
            
        file_path = temp_dir / f"{uuid.uuid4().hex}_{filename}"
        file_path.write_bytes(content)
        
        extraction = extract_from_path(file_path)
        
        if metadata_overrides:
            extraction.metadata.update(metadata_overrides)
            
        result = build_pending_job_from_extraction(
            stored_path=file_path,
            original_name=filename,
            extraction=extraction,
            form={},
            settings=settings,
            profiles=serialize_profiles(),
            metadata_overrides=metadata_overrides,
        )
        
        get_service().store_pending_job(result.pending)
        
        return jsonify({
            "success": True,
            "status": "imported",
            "pending_id": result.pending.id,
            "redirect_url": url_for("main.wizard_step", step="book", pending_id=result.pending.id)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- LLM Routes ---

@api_bp.post("/llm/models")
def api_llm_models() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=False) or {}
    current_settings = load_settings()

    base_url = str(payload.get("base_url") or payload.get("llm_base_url") or current_settings.get("llm_base_url") or "").strip()
    if not base_url:
        return jsonify({"error": "LLM base URL is required."}), 400

    api_key = str(payload.get("api_key") or payload.get("llm_api_key") or current_settings.get("llm_api_key") or "")
    timeout = coerce_float(payload.get("timeout"), current_settings.get("llm_timeout", 30.0))

    overrides = {
        "llm_base_url": base_url,
        "llm_api_key": api_key,
        "llm_timeout": timeout,
    }

    merged = apply_overrides(current_settings, overrides)
    configuration = build_llm_configuration(merged)
    try:
        models = list_models(configuration)
    except LLMClientError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"models": models})

@api_bp.post("/llm/preview")
def api_llm_preview() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=False) or {}
    sample_text = str(payload.get("text") or "").strip()
    if not sample_text:
        return jsonify({"error": "Text is required."}), 400

    base_settings = load_settings()
    overrides: Dict[str, Any] = {
        "llm_base_url": str(
            payload.get("base_url")
            or payload.get("llm_base_url")
            or base_settings.get("llm_base_url")
            or ""
        ).strip(),
        "llm_api_key": str(
            payload.get("api_key")
            or payload.get("llm_api_key")
            or base_settings.get("llm_api_key")
            or ""
        ),
        "llm_model": str(
            payload.get("model")
            or payload.get("llm_model")
            or base_settings.get("llm_model")
            or ""
        ),
        "llm_prompt": payload.get("prompt") or payload.get("llm_prompt") or base_settings.get("llm_prompt"),
        "llm_context_mode": payload.get("context_mode") or base_settings.get("llm_context_mode"),
        "llm_timeout": coerce_float(payload.get("timeout"), base_settings.get("llm_timeout", 30.0)),
        "normalization_apostrophe_mode": "llm",
    }

    merged = apply_overrides(base_settings, overrides)
    if not merged.get("llm_base_url"):
        return jsonify({"error": "LLM base URL is required."}), 400
    if not merged.get("llm_model"):
        return jsonify({"error": "Select an LLM model before previewing."}), 400

    apostrophe_config = build_apostrophe_config(settings=merged)
    try:
        normalized_text = normalize_for_pipeline(sample_text, config=apostrophe_config, settings=merged)
    except LLMClientError as exc:
        return jsonify({"error": str(exc)}), 400

    context = {
        "text": sample_text,
        "normalized_text": normalized_text,
    }
    return jsonify(context)

# --- Normalization Routes ---

@api_bp.post("/normalization/preview")
def api_normalization_preview() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=False) or {}
    sample_text = str(payload.get("text") or "").strip()
    if not sample_text:
        return jsonify({"error": "Sample text is required."}), 400

    base_settings = load_settings()
    # We might want to apply overrides from payload if any normalization settings are passed
    # For now, just use base settings as in original code (presumably)
    
    apostrophe_config = build_apostrophe_config(settings=base_settings)
    try:
        normalized_text = normalize_for_pipeline(sample_text, config=apostrophe_config, settings=base_settings)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "text": sample_text,
        "normalized_text": normalized_text,
    })

@api_bp.post("/entity-pronunciation/preview")
def api_entity_pronunciation_preview() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    token = payload.get("token", "").strip()
    pronunciation = payload.get("pronunciation", "").strip()
    voice = payload.get("voice", "").strip()
    language = payload.get("language", "a").strip()
    
    if not token and not pronunciation:
        return jsonify({"error": "Token or pronunciation required"}), 400
        
    text_to_speak = pronunciation if pronunciation else token
    
    if not voice:
        settings = load_settings()
        voice = settings.get("default_voice", "af_heart")
        
    try:
        # Check GPU setting
        settings = load_settings()
        use_gpu = coerce_bool(settings.get("use_gpu"), False)
        
        audio_bytes = generate_preview_audio(
            text=text_to_speak,
            voice_spec=voice,
            language=language,
            speed=1.0,
            use_gpu=use_gpu,
        )
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return jsonify({"audio_base64": audio_base64})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
