from typing import Mapping
from flask import Blueprint, request, jsonify, abort, render_template, redirect, url_for
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.service import require_pending_job, get_service
from abogen.webui.routes.utils.entity import (
    refresh_entity_summary,
    pending_entities_payload,
    upsert_manual_override,
    delete_manual_override,
    search_manual_override_candidates,
)
from abogen.webui.routes.utils.settings import coerce_int, load_settings
from abogen.webui.routes.utils.voice import template_options
from abogen.pronunciation_store import (
    delete_override as delete_pronunciation_override,
    save_override as save_pronunciation_override,
    get_override_stats,
    all_overrides,
)

entities_bp = Blueprint("entities", __name__)

@entities_bp.post("/analyze")
def analyze_entities() -> ResponseReturnValue:
    # This might be triggered via wizard update, but if there's a specific route:
    # In original routes.py, it was likely part of wizard logic or API.
    # I'll assume this is for the API endpoint /api/pending/<id>/entities/refresh
    pending_id = request.form.get("pending_id") or request.args.get("pending_id")
    if not pending_id:
        abort(400, "Pending ID required")
        
    pending = require_pending_job(pending_id)
    refresh_entity_summary(pending, pending.chapters)
    get_service().store_pending_job(pending)
    return jsonify(pending_entities_payload(pending))

@entities_bp.get("/pending/<pending_id>")
def get_entities(pending_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    refresh_flag = (request.args.get("refresh") or "").strip().lower()
    expected_cache = (request.args.get("cache_key") or "").strip()
    refresh_requested = refresh_flag in {"1", "true", "yes", "force"}
    
    if expected_cache and expected_cache != (pending.entity_cache_key or ""):
        refresh_requested = True
        
    if refresh_requested or not pending.entity_summary:
        refresh_entity_summary(pending, pending.chapters)
        get_service().store_pending_job(pending)
        
    return jsonify(pending_entities_payload(pending))

@entities_bp.post("/pending/<pending_id>/refresh")
def refresh_entities(pending_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    refresh_entity_summary(pending, pending.chapters)
    get_service().store_pending_job(pending)
    return jsonify(pending_entities_payload(pending))

@entities_bp.get("/pending/<pending_id>/overrides")
def list_manual_overrides(pending_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    return jsonify({
        "overrides": pending.manual_overrides or [],
        "pronunciation_overrides": pending.pronunciation_overrides or [],
        "heteronym_overrides": getattr(pending, "heteronym_overrides", None) or [],
        "language": pending.language or "en",
    })

@entities_bp.post("/pending/<pending_id>/overrides")
def upsert_override(pending_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, Mapping):
        abort(400, "Invalid override payload")
        
    try:
        override = upsert_manual_override(pending, payload)
    except ValueError as exc:
        abort(400, str(exc))
        
    get_service().store_pending_job(pending)
    return jsonify({"override": override, **pending_entities_payload(pending)})

@entities_bp.delete("/pending/<pending_id>/overrides/<override_id>")
def delete_override(pending_id: str, override_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    deleted = delete_manual_override(pending, override_id)
    if not deleted:
        abort(404)
        
    get_service().store_pending_job(pending)
    return jsonify({"deleted": True, **pending_entities_payload(pending)})

@entities_bp.get("/pending/<pending_id>/overrides/search")
def search_candidates(pending_id: str) -> ResponseReturnValue:
    pending = require_pending_job(pending_id)
    query = (request.args.get("q") or request.args.get("query") or "").strip()
    limit_param = request.args.get("limit")
    limit_value = coerce_int(limit_param, 15, minimum=1, maximum=50) if limit_param is not None else 15
    
    results = search_manual_override_candidates(pending, query, limit=limit_value)
    return jsonify({"query": query, "limit": limit_value, "results": results})

@entities_bp.post("/overrides")
def upsert_global_override() -> ResponseReturnValue:
    payload = request.form
    action = payload.get("action", "save")
    lang = payload.get("lang", "en")
    token = payload.get("token", "").strip()
    
    if action == "delete":
        if token:
            delete_pronunciation_override(token=token, language=lang)
    else:
        pronunciation = payload.get("pronunciation", "").strip()
        voice = payload.get("voice", "").strip()
        if token:
            save_pronunciation_override(
                token=token,
                pronunciation=pronunciation,
                voice=voice or None,
                language=lang
            )
        
    return redirect(url_for("entities.entities_page", lang=lang))

@entities_bp.get("/")
def entities_page() -> str:
    settings = load_settings()
    lang = request.args.get("lang") or settings.get("language", "en")
    voice_filter = request.args.get("voice", "")
    pronunciation_filter = request.args.get("pronunciation", "")

    options = template_options()
    stats = get_override_stats(lang)
    
    overrides = all_overrides(lang)
    
    if voice_filter == "assigned":
        overrides = [o for o in overrides if o.get("voice")]
    elif voice_filter == "unassigned":
        overrides = [o for o in overrides if not o.get("voice")]
        
    if pronunciation_filter == "defined":
        overrides = [o for o in overrides if o.get("pronunciation")]
    elif pronunciation_filter == "undefined":
        overrides = [o for o in overrides if not o.get("pronunciation")]

    voice_filter_options = [
        {"value": "", "label": "All voices"},
        {"value": "assigned", "label": "Assigned"},
        {"value": "unassigned", "label": "Unassigned"},
    ]
    pronunciation_filter_options = [
        {"value": "", "label": "All pronunciations"},
        {"value": "defined", "label": "Defined"},
        {"value": "undefined", "label": "Undefined"},
    ]

    language_label = options["languages"].get(lang, lang)
    return render_template(
        "entities.html",
        language=lang,
        language_label=language_label,
        options=options,
        languages=options["languages"].items(),
        stats=stats,
        overrides=overrides,
        voice_filter=voice_filter,
        pronunciation_filter=pronunciation_filter,
        voice_filter_options=voice_filter_options,
        pronunciation_filter_options=pronunciation_filter_options,
    )
