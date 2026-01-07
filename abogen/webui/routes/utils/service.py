from typing import cast
from flask import current_app, abort
from abogen.webui.service import ConversionService, PendingJob

def get_service() -> ConversionService:
    return current_app.extensions["conversion_service"]

def require_pending_job(pending_id: str) -> PendingJob:
    pending = get_service().get_pending_job(pending_id)
    if not pending:
        abort(404)
    return cast(PendingJob, pending)

def remove_pending_job(pending_id: str) -> None:
    get_service().pop_pending_job(pending_id)

def submit_job(pending: PendingJob) -> str:
    service = get_service()
    service.pop_pending_job(pending.id)
    
    job = service.enqueue(
        original_filename=pending.original_filename,
        stored_path=pending.stored_path,
        language=pending.language,
        tts_provider=getattr(pending, "tts_provider", "kokoro"),
        voice=pending.voice,
        speed=pending.speed,
        supertonic_total_steps=getattr(pending, "supertonic_total_steps", 5),
        use_gpu=pending.use_gpu,
        subtitle_mode=pending.subtitle_mode,
        output_format=pending.output_format,
        save_mode=pending.save_mode,
        output_folder=pending.output_folder,
        replace_single_newlines=pending.replace_single_newlines,
        subtitle_format=pending.subtitle_format,
        total_characters=pending.total_characters,
        chapters=pending.chapters,
        save_chapters_separately=pending.save_chapters_separately,
        merge_chapters_at_end=pending.merge_chapters_at_end,
        separate_chapters_format=pending.separate_chapters_format,
        silence_between_chapters=pending.silence_between_chapters,
        save_as_project=pending.save_as_project,
        voice_profile=pending.voice_profile,
        max_subtitle_words=pending.max_subtitle_words,
        metadata_tags=pending.metadata_tags,
        cover_image_path=pending.cover_image_path,
        cover_image_mime=pending.cover_image_mime,
        chapter_intro_delay=pending.chapter_intro_delay,
        read_title_intro=pending.read_title_intro,
        read_closing_outro=pending.read_closing_outro,
        auto_prefix_chapter_titles=pending.auto_prefix_chapter_titles,
        normalize_chapter_opening_caps=pending.normalize_chapter_opening_caps,
        chunk_level=pending.chunk_level,
        chunks=pending.chunks,
        speakers=pending.speakers,
        speaker_mode=pending.speaker_mode,
        generate_epub3=pending.generate_epub3,
        speaker_analysis=pending.speaker_analysis,
        speaker_analysis_threshold=pending.speaker_analysis_threshold,
        analysis_requested=pending.analysis_requested,
        entity_summary=getattr(pending, "entity_summary", None),
        manual_overrides=getattr(pending, "manual_overrides", None),
        pronunciation_overrides=getattr(pending, "pronunciation_overrides", None),
        heteronym_overrides=getattr(pending, "heteronym_overrides", None),
        normalization_overrides=pending.normalization_overrides,
    )
    return job.id
