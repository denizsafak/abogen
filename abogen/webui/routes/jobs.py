import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, Response, abort, redirect, render_template, request, url_for, send_file
from flask.typing import ResponseReturnValue

from abogen.webui.service import (
    JobStatus,
    load_audiobookshelf_chapters,
    build_audiobookshelf_metadata,
)
from abogen.webui.routes.utils.service import get_service
from abogen.webui.routes.utils.form import render_jobs_panel
from abogen.webui.routes.utils.voice import template_options
from abogen.webui.routes.utils.epub import (
    job_download_flags,
    locate_job_epub,
    locate_job_audio,
)
from abogen.webui.routes.utils.settings import (
    stored_integration_config,
    build_audiobookshelf_config,
    coerce_bool,
)
from abogen.webui.routes.utils.common import existing_paths
from abogen.integrations.audiobookshelf import AudiobookshelfClient, AudiobookshelfUploadError

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)

@jobs_bp.get("/<job_id>")
def job_detail(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job:
        # Return a friendly page instead of 404 to avoid confusion from stale browser tabs
        return render_template("job_not_found.html"), 200
    return render_template(
        "job_detail.html",
        job=job,
        options=template_options(),
        JobStatus=JobStatus,
        downloads=job_download_flags(job),
    )

@jobs_bp.post("/<job_id>/pause")
def pause_job(job_id: str) -> ResponseReturnValue:
    get_service().pause(job_id)
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    return redirect(url_for("jobs.job_detail", job_id=job_id))

@jobs_bp.post("/<job_id>/resume")
def resume_job(job_id: str) -> ResponseReturnValue:
    get_service().resume(job_id)
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    return redirect(url_for("jobs.job_detail", job_id=job_id))

@jobs_bp.post("/<job_id>/cancel")
def cancel_job(job_id: str) -> ResponseReturnValue:
    get_service().cancel(job_id)
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    return redirect(url_for("jobs.job_detail", job_id=job_id))

@jobs_bp.post("/<job_id>/delete")
def delete_job(job_id: str) -> ResponseReturnValue:
    get_service().delete(job_id)
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    return redirect(url_for("main.index"))

@jobs_bp.post("/<job_id>/retry")
def retry_job(job_id: str) -> ResponseReturnValue:
    new_job = get_service().retry(job_id)
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    if new_job:
        return redirect(url_for("jobs.job_detail", job_id=new_job.id))
    return redirect(url_for("jobs.job_detail", job_id=job_id))

@jobs_bp.post("/<job_id>/audiobookshelf")
def send_job_to_audiobookshelf(job_id: str) -> ResponseReturnValue:
    service = get_service()
    job = service.get_job(job_id)
    if job is None:
        abort(404)

    def _panel_response() -> ResponseReturnValue:
        if request.headers.get("HX-Request"):
            return render_jobs_panel()
        return redirect(url_for("jobs.job_detail", job_id=job.id))

    if job.status != JobStatus.COMPLETED:
        return _panel_response()

    settings = stored_integration_config("audiobookshelf")
    if not settings or not coerce_bool(settings.get("enabled"), False):
        job.add_log("Audiobookshelf upload skipped: integration is disabled.", level="warning")
        service._persist_state()
        return _panel_response()

    config = build_audiobookshelf_config(settings)
    if config is None:
        job.add_log(
            "Audiobookshelf upload skipped: configure base URL, API token, and library ID first.",
            level="warning",
        )
        service._persist_state()
        return _panel_response()
    if not config.folder_id:
        job.add_log(
            "Audiobookshelf upload skipped: enter the folder name or ID in the Audiobookshelf settings.",
            level="warning",
        )
        service._persist_state()
        return _panel_response()

    audio_path = locate_job_audio(job)
    if not audio_path or not audio_path.exists():
        job.add_log("Audiobookshelf upload skipped: audio output not found.", level="warning")
        service._persist_state()
        return _panel_response()

    cover_path = None
    if config.send_cover and job.cover_image_path:
        cover_candidate = job.cover_image_path
        if not isinstance(cover_candidate, Path):
            cover_candidate = Path(str(cover_candidate))
        if cover_candidate.exists():
            cover_path = cover_candidate

    subtitles = existing_paths(job.result.subtitle_paths) if config.send_subtitles else None
    chapters = load_audiobookshelf_chapters(job) if config.send_chapters else None
    metadata = build_audiobookshelf_metadata(job)
    display_title = metadata.get("title") or audio_path.stem
    overwrite_requested = request.form.get("overwrite") == "true" or request.args.get("overwrite") == "true"

    try:
        client = AudiobookshelfClient(config)
    except ValueError as exc:
        job.add_log(f"Audiobookshelf configuration error: {exc}", level="error")
        service._persist_state()
        return _panel_response()

    try:
        existing_items = client.find_existing_items(display_title, folder_id=config.folder_id)
    except AudiobookshelfUploadError as exc:
        job.add_log(f"Audiobookshelf lookup failed: {exc}", level="error")
        service._persist_state()
        return _panel_response()

    if existing_items and not overwrite_requested:
        job.add_log(
            f"Audiobookshelf already contains '{display_title}'. Awaiting overwrite confirmation.",
            level="warning",
        )
        service._persist_state()
        if request.headers.get("HX-Request"):
            detail = {
                "jobId": job.id,
                "title": display_title,
                "url": url_for("jobs.send_job_to_audiobookshelf", job_id=job.id),
                "target": request.headers.get("HX-Target") or "#jobs-panel",
                "message": f'Audiobookshelf already contains "{display_title}". Overwrite?',
            }
            headers = {"HX-Trigger": json.dumps({"audiobookshelf-overwrite-prompt": detail})}
            return Response("", status=204, headers=headers)
        return _panel_response()

    if existing_items and overwrite_requested:
        try:
            client.delete_items(existing_items)
        except AudiobookshelfUploadError as exc:
            job.add_log(f"Audiobookshelf overwrite aborted: {exc}", level="error")
            service._persist_state()
            return _panel_response()
        else:
            job.add_log(
                f"Removed {len(existing_items)} existing Audiobookshelf item(s) prior to overwrite.",
                level="info",
            )

    job.add_log("Audiobookshelf upload triggered manually.", level="info")
    try:
        client.upload_audiobook(
            audio_path,
            metadata=metadata,
            cover_path=cover_path,
            chapters=chapters,
            subtitles=subtitles,
        )
    except AudiobookshelfUploadError as exc:
        job.add_log(f"Audiobookshelf upload failed: {exc}", level="error")
    except Exception as exc:
        job.add_log(f"Audiobookshelf integration error: {exc}", level="error")
    else:
        job.add_log("Audiobookshelf upload queued.", level="success")
    finally:
        service._persist_state()

    return _panel_response()

@jobs_bp.post("/clear-finished")
def clear_finished_jobs() -> ResponseReturnValue:
    get_service().clear_finished()
    if request.headers.get("HX-Request"):
        return render_jobs_panel()
    return redirect(url_for("main.index", _anchor="queue"))

@jobs_bp.get("/<job_id>/epub")
def job_epub(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if job is None or job.status != JobStatus.COMPLETED:
        abort(404)
    epub_path = locate_job_epub(job)
    if not epub_path:
        abort(404)
    return send_file(
        epub_path,
        as_attachment=True,
        download_name=epub_path.name,
        mimetype="application/epub+zip",
    )

@jobs_bp.get("/<job_id>/download/<file_type>")
def download_file(job_id: str, file_type: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job or job.status != JobStatus.COMPLETED:
        abort(404)

    if file_type == "audio":
        path = locate_job_audio(job)
        if not path or not path.exists():
            abort(404)
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
        )
    
    # Handle other file types if needed (subtitles, etc.)
    # For now, just audio and epub are explicitly handled
    abort(404)

@jobs_bp.get("/<job_id>/logs")
def job_logs(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job:
        # Return a simple page instead of 404 to avoid log spam from stale browser tabs
        return render_template("job_logs_missing.html"), 200
    return render_template("job_logs_static.html", job=job)


@jobs_bp.get("/<job_id>/logs/partial")
def job_logs_partial(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job:
        # Return a non-polling section so HTMX stops retrying.
        return render_template("partials/logs_section_missing.html"), 200
    return render_template("partials/logs_section.html", job=job)

@jobs_bp.get("/<job_id>/logs/stream")
def stream_logs(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job:
        abort(404)
        
    def generate():
        last_index = 0
        while True:
            current_logs = job.logs
            if len(current_logs) > last_index:
                for log in current_logs[last_index:]:
                    yield f"data: {json.dumps({'timestamp': log.timestamp, 'level': log.level, 'message': log.message})}\n\n"
                last_index = len(current_logs)
            
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                break
            
            import time
            time.sleep(0.5)
            
    return Response(generate(), mimetype="text/event-stream")

@jobs_bp.get("/<job_id>/reader")
def job_reader(job_id: str) -> ResponseReturnValue:
    job = get_service().get_job(job_id)
    if not job:
        abort(404)
    return render_template("reader_embed.html", job=job)

@jobs_bp.get("/queue")
def queue_page() -> str:
    return render_template(
        "queue.html",
        jobs_panel=render_jobs_panel(),
    )

@jobs_bp.get("/partial")
def jobs_partial() -> str:
    return render_jobs_panel()
