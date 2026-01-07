import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, cast

from flask import Blueprint, redirect, render_template, request, url_for, jsonify, current_app
from werkzeug.utils import secure_filename

from abogen.webui.service import PendingJob, JobStatus
from abogen.webui.routes.utils.service import get_service, remove_pending_job, submit_job
from abogen.webui.routes.utils.settings import load_settings
from abogen.webui.routes.utils.voice import template_options
from abogen.webui.routes.utils.form import (
    normalize_wizard_step,
    wants_wizard_json,
    render_wizard_partial,
    wizard_json_response,
    build_pending_job_from_extraction,
    apply_book_step_form,
    apply_prepare_form,
    render_jobs_panel,
)
from abogen.text_extractor import extract_from_path
from abogen.voice_profiles import serialize_profiles

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)

@main_bp.app_template_filter("datetimeformat")
def datetimeformat(value: float, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not value:
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(value).strftime(fmt)

@main_bp.app_template_filter("durationformat")
def durationformat(value: Optional[float]) -> str:
    if value is None:
        return ""
    seconds = int(value)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m"

@main_bp.route("/")
def index():
    pending_id = request.args.get("pending_id")
    pending = get_service().get_pending_job(pending_id) if pending_id else None
    
    # If we have a pending job, redirect to the wizard
    if pending:
        step_index = getattr(pending, "wizard_max_step_index", 0)
        # Map index to step name roughly
        steps = ["book", "chapters", "entities"]
        step_name = steps[min(step_index, len(steps)-1)]
        return redirect(url_for("main.wizard_step", step=step_name, pending_id=pending.id))

    jobs = get_service().list_jobs()
    stats = {
        "total": len(jobs),
        "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
        "running": sum(1 for j in jobs if j.status == JobStatus.RUNNING),
        "pending": sum(1 for j in jobs if j.status == JobStatus.PENDING),
        "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
    }

    return render_template(
        "index.html",
        options=template_options(),
        settings=load_settings(),
        jobs_panel=render_jobs_panel(),
        stats=stats,
    )

@main_bp.route("/wizard")
def wizard_start():
    pending_id = request.args.get("pending_id")
    step = request.args.get("step", "book")
    if pending_id:
        return redirect(url_for("main.wizard_step", step=step, pending_id=pending_id))
    return redirect(url_for("main.wizard_step", step=step))

@main_bp.route("/wizard/<step>")
def wizard_step(step: str):
    pending_id = request.args.get("pending_id")
    pending = get_service().get_pending_job(pending_id) if pending_id else None
    
    normalized_step = normalize_wizard_step(step, pending)
    if normalized_step != step:
        return redirect(url_for("main.wizard_step", step=normalized_step, pending_id=pending_id))

    if wants_wizard_json():
        return wizard_json_response(pending, normalized_step)

    return render_template(
        "index.html",
        options=template_options(),
        settings=load_settings(),
        jobs_panel=render_jobs_panel(),
        wizard_mode=True,
        wizard_step=normalized_step,
        wizard_partial=render_wizard_partial(pending, normalized_step),
    )

@main_bp.route("/wizard/upload", methods=["POST"])
def wizard_upload():
    pending_id = request.form.get("pending_id")
    pending = get_service().get_pending_job(pending_id) if pending_id else None
    
    file = request.files.get("file") or request.files.get("source_file")
    
    settings = load_settings()
    profiles = serialize_profiles()

    # Case 1: Updating existing job without new file
    if pending and (not file or not file.filename):
        try:
            apply_book_step_form(pending, request.form, settings=settings, profiles=profiles)
            get_service().store_pending_job(pending)
            
            if wants_wizard_json():
                return wizard_json_response(pending, "chapters")
            return redirect(url_for("main.wizard_step", step="chapters", pending_id=pending.id))
        except Exception as e:
            logger.exception("Error updating job settings")
            error_msg = f"Failed to update settings: {str(e)}"
            if wants_wizard_json():
                return wizard_json_response(pending, "book", error=error_msg, status=500)
            return render_template(
                "index.html",
                options=template_options(),
                settings=settings,
                jobs_panel=render_jobs_panel(),
                wizard_mode=True,
                wizard_step="book",
                wizard_partial=render_wizard_partial(pending, "book", error=error_msg),
            )

    # Case 2: New file upload (or replacing file on existing job)
    if not file or not file.filename:
        if wants_wizard_json():
            return wizard_json_response(None, "book", error="No file selected", status=400)
        return redirect(url_for("main.wizard_step", step="book"))

    filename = secure_filename(file.filename)
    temp_dir = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / f"{uuid.uuid4().hex}_{filename}"
    file.save(file_path)

    try:
        extraction = extract_from_path(file_path)
            
        result = build_pending_job_from_extraction(
            stored_path=file_path,
            original_name=filename,
            extraction=extraction,
            form=request.form,
            settings=settings,
            profiles=profiles,
        )
        
        # If we had a pending job, we might want to preserve its ID or other properties,
        # but for a new file it's safer to start fresh with the new extraction.
        # The frontend will handle the ID change via the redirect.
        
        get_service().store_pending_job(result.pending)
        
        if wants_wizard_json():
            return wizard_json_response(result.pending, "chapters")
            
        return redirect(url_for("main.wizard_step", step="chapters", pending_id=result.pending.id))
        
    except Exception as e:
        logger.exception("Error processing upload")
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
                
        error_msg = f"Failed to process file: {str(e)}"
        if wants_wizard_json():
            return wizard_json_response(None, "book", error=error_msg, status=500)
            
        return render_template(
            "index.html",
            options=template_options(),
            settings=settings,
            jobs_panel=render_jobs_panel(),
            wizard_mode=True,
            wizard_step="book",
            wizard_partial=render_wizard_partial(None, "book", error=error_msg),
        )

@main_bp.route("/wizard/text", methods=["POST"])
def wizard_text():
    text = request.form.get("text", "").strip()
    title = request.form.get("title", "").strip() or "Pasted Text"
    
    if not text:
        if wants_wizard_json():
            return wizard_json_response(None, "book", error="No text provided", status=400)
        return redirect(url_for("main.wizard_step", step="book"))

    temp_dir = Path(current_app.config.get("UPLOAD_FOLDER", "uploads"))
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / f"{uuid.uuid4().hex}.txt"
    file_path.write_text(text, encoding="utf-8")

    settings = load_settings()
    profiles = serialize_profiles()

    try:
        extraction = extract_from_path(file_path)
        # Override title since text extraction might not find one
        extraction.metadata["title"] = title
        
        result = build_pending_job_from_extraction(
            stored_path=file_path,
            original_name=f"{title}.txt",
            extraction=extraction,
            form=request.form,
            settings=settings,
            profiles=profiles,
        )
        
        get_service().store_pending_job(result.pending)
        
        if wants_wizard_json():
            return wizard_json_response(result.pending, "chapters")
            
        return redirect(url_for("main.wizard_step", step="chapters", pending_id=result.pending.id))
        
    except Exception as e:
        logger.exception("Error processing text")
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
                
        error_msg = f"Failed to process text: {str(e)}"
        if wants_wizard_json():
            return wizard_json_response(None, "book", error=error_msg, status=500)
            
        return render_template(
            "index.html",
            options=template_options(),
            settings=settings,
            jobs_panel=render_jobs_panel(),
            wizard_mode=True,
            wizard_step="book",
            wizard_partial=render_wizard_partial(None, "book", error=error_msg),
        )

@main_bp.route("/wizard/update", methods=["POST"])
def wizard_update():
    pending_id = request.values.get("pending_id")
    if not pending_id:
        if wants_wizard_json():
            return wizard_json_response(None, "book", error="Missing job ID", status=400)
        return redirect(url_for("main.wizard_step", step="book"))

    pending = get_service().get_pending_job(pending_id)
    if not pending:
        if wants_wizard_json():
            return wizard_json_response(None, "book", error="Job expired or not found", status=404)
        return redirect(url_for("main.wizard_step", step="book"))

    current_step = request.form.get("step", "book")
    next_step = request.form.get("next_step")
    
    settings = load_settings()
    profiles = serialize_profiles()

    try:
        if current_step == "book":
            apply_book_step_form(pending, request.form, settings=settings, profiles=profiles)
            target_step = next_step or "chapters"
            
        elif current_step == "chapters":
            # This step involves re-analyzing chunks if needed
            (
                chunk_level,
                overrides,
                enabled_overrides,
                errors,
                selected_total,
                selected_config,
                apply_config_requested,
                persist_config_requested,
            ) = apply_prepare_form(pending, request.form)
            
            if errors:
                if wants_wizard_json():
                    return wizard_json_response(pending, current_step, error="\n".join(errors), status=400)
                return render_template(
                    "index.html",
                    options=template_options(),
                    settings=settings,
                    jobs_panel=render_jobs_panel(),
                    wizard_mode=True,
                    wizard_step=current_step,
                    wizard_partial=render_wizard_partial(pending, current_step, error="\n".join(errors)),
                )
            
            target_step = next_step or "entities"
            
        elif current_step == "entities":
            # Just saving entity overrides
            apply_prepare_form(pending, request.form)
            target_step = next_step or "entities" # Stay or finish
            
        else:
            target_step = "book"

        get_service().store_pending_job(pending)
        
        if wants_wizard_json():
            return wizard_json_response(pending, target_step)
            
        return redirect(url_for("main.wizard_step", step=target_step, pending_id=pending.id))

    except Exception as e:
        logger.exception(f"Error updating wizard step {current_step}")
        error_msg = f"Update failed: {str(e)}"
        if wants_wizard_json():
            return wizard_json_response(pending, current_step, error=error_msg, status=500)
            
        return render_template(
            "index.html",
            options=template_options(),
            settings=settings,
            jobs_panel=render_jobs_panel(),
            wizard_mode=True,
            wizard_step=current_step,
            wizard_partial=render_wizard_partial(pending, current_step, error=error_msg),
        )

@main_bp.route("/wizard/cancel", methods=["POST"])
def wizard_cancel():
    pending_id = request.values.get("pending_id")
    if pending_id:
        remove_pending_job(pending_id)
    
    if wants_wizard_json():
        return jsonify({"status": "cancelled", "redirect_url": url_for("main.index")})
        
    return redirect(url_for("main.index"))

@main_bp.route("/wizard/finish", methods=["POST"])
def wizard_finish():
    pending_id = request.values.get("pending_id")
    if not pending_id:
        if wants_wizard_json():
            return jsonify({"error": "Missing job ID"}), 400
        return redirect(url_for("main.index"))

    pending = get_service().get_pending_job(pending_id)
    if not pending:
        if wants_wizard_json():
            return jsonify({"error": "Job not found"}), 404
        return redirect(url_for("main.index"))

    # Final update from form
    apply_prepare_form(pending, request.form)
    
    # Submit job
    job_id = submit_job(pending)
    
    if wants_wizard_json():
        return jsonify({
            "status": "submitted",
            "job_id": job_id,
            "redirect_url": url_for("main.index"),
            "jobs_panel": render_jobs_panel()
        })
        
    return redirect(url_for("main.index"))
