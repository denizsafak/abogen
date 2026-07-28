"""ConversionService — main orchestrator for the conversion flow.

Ties together planner, executor, and finalizers into a single entry point.
Both UIs (PyQt, WebUI) call ConversionService.run() to execute a conversion.

Responsibilities:
- Prepare TTSContext (normalization settings, pronunciation rules)
- Build ConversionPlan via planner
- Execute conversion via executor
- Handle lifecycle (cleanup, error handling)
- Return ConversionResult

The service NEVER imports from PyQt or WebUI.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

from abogen.application.conversion_executor import execute_conversion
from abogen.application.conversion_models import ConversionPlan
from abogen.application.conversion_planner import build_conversion_plan
from abogen.application.conversion_ports import ConversionEvents
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_result import ConversionResult
from abogen.domain.normalization import build_tts_context


def run_conversion(
    request: ConversionRequest,
    events: ConversionEvents,
) -> ConversionResult:
    """Execute a conversion request and return the result.

    This is the single entry point for both UIs. It orchestrates:
    1. Voice infrastructure setup (pool, cache, resolver)
    2. TTS context preparation
    3. Conversion planning
    4. Conversion execution
    5. Resource cleanup

    Args:
        request: Normalized conversion request
        events: UI-specific callbacks (log, progress, check_cancelled)

    Returns:
        ConversionResult with paths and markers

    Raises:
        ConversionCancelled: If conversion was cancelled
        ValueError: If request is invalid
        Exception: On TTS or I/O errors
    """
    from abogen.domain.pipeline_factory import PipelinePool
    from abogen.domain.voice_loader import VoiceCache

    pool = PipelinePool()
    voice_cache = VoiceCache()

    try:
        # Stage 0: Create voice resolver
        events.log("Preparing conversion pipeline")
        resolver = _create_voice_resolver(request, pool, voice_cache)

        # Stage 1: Prepare TTS context
        usage_counter: Dict[str, int] = defaultdict(int)
        tts_context = build_tts_context(
            language=request.language,
            subtitle_mode=request.subtitle_mode.value if request.subtitle_mode else "Disabled",
            pronunciation_overrides=request.pronunciation_overrides,
            manual_overrides=request.manual_overrides,
            heteronym_overrides=request.heteronym_overrides,
            normalization_overrides=request.normalization_overrides,
            usage_counter=usage_counter,
            log_callback=lambda level, msg: events.log(msg, level=level),
        )

        # Stage 2: Build conversion plan
        events.log("Building conversion plan")
        plan = build_conversion_plan(request)

        # Stage 3: Execute conversion
        events.log("Starting conversion")
        result = execute_conversion(
            plan=plan,
            events=events,
            pipeline_provider=pool,
            voice_resolver=resolver,
            tts_context=tts_context,
        )

        # Propagate usage counter to result
        result.usage_counter = dict(usage_counter)

        # Stage 4: Finalize (m4b metadata embedding, EPUB3 generation)
        _finalize(request, result, plan, events)

        events.log("Conversion complete")
        return result

    except Exception as e:
        events.log(f"Conversion failed: {e}", level="error")
        raise
    finally:
        pool.dispose_all()
        voice_cache.clear()
        from abogen.application.cleanup import flush_cuda
        flush_cuda()


def _create_voice_resolver(
    request: ConversionRequest,
    pool: Any,
    cache: Any,
) -> Any:
    """Create AppVoiceResolver with loaded profiles.

    Loads voice profiles from disk, normalizes them, and creates
    an AppVoiceResolver that can resolve voice specs into loaded voices.
    """
    from abogen.application.voice_resolver import AppVoiceResolver
    from abogen.voice_profiles import load_profiles, normalize_profile_entry

    try:
        profiles = load_profiles()
    except Exception:
        profiles = {}

    normalized_profiles: Dict[str, Dict[str, Any]] = {}
    for name, entry in (profiles or {}).items():
        normalized = normalize_profile_entry(entry)
        if normalized:
            normalized_profiles[str(name)] = normalized

    return AppVoiceResolver(request, normalized_profiles, pool, cache)


def _finalize(
    request: ConversionRequest,
    result: ConversionResult,
    plan: ConversionPlan,
    events: ConversionEvents,
) -> None:
    """Post-conversion finalization (m4b metadata embedding, EPUB3 generation, etc.)."""
    from abogen.domain.enums import OutputFormat

    # m4b metadata embedding
    if (
        result.audio_path
        and request.output_format == OutputFormat.M4B
    ):

        from abogen.infrastructure.exporters import ExportService

        export_svc = ExportService()
        cover_path = request.cover_image_path if request.cover_image_path and request.cover_image_path.exists() else None

        try:
            export_svc.embed_m4b_metadata(
                audio_path=result.audio_path,
                metadata=result.metadata or {},
                chapters=result.chapter_markers or [],
                cover_path=cover_path,
                cover_mime=request.cover_image_mime,
                log_callback=lambda msg, level="info": events.log(msg, level=level),
            )
        except Exception as exc:
            events.log(f"Failed to embed m4b metadata: {exc}", level="error")
            raise RuntimeError(f"Failed to embed m4b metadata: {exc}") from exc

    # EPUB3 generation
    if request.epub3_export and plan.extraction:
        audio_asset = result.audio_path
        if not audio_asset and result.chapter_paths:
            audio_asset = result.chapter_paths[0]

        if audio_asset:
            try:

                from abogen.epub3.exporter import build_epub3_package

                epub_root = result.project_root or plan.output_layout.parent_dir
                from abogen.domain.output_paths import build_output_path

                epub_output_path = build_output_path(epub_root, request.original_filename, "epub")
                events.log("Generating EPUB 3 package...")
                epub_path = build_epub3_package(
                    output_path=epub_output_path,
                    book_id=request.epub3_export.book_id,
                    extraction=plan.extraction,
                    metadata_tags=result.metadata or {},
                    chapter_markers=result.chapter_markers or [],
                    chunk_markers=result.chunk_markers or [],
                    chunks=request.chapter_chunk.chunks if request.chapter_chunk else [],
                    audio_path=audio_asset,
                    speaker_mode=request.chapter_chunk.speaker_mode if request.chapter_chunk else "single",
                    cover_image_path=request.cover_image_path,
                    cover_image_mime=request.cover_image_mime,
                )
                result.epub_path = epub_path
                result.artifacts["epub3"] = epub_path
                events.log(f"EPUB 3 package created at {epub_path}")
            except Exception as exc:
                events.log(f"Failed to generate EPUB 3: {exc}", level="error")
        else:
            events.log("Skipped EPUB 3 generation: audio output unavailable.", level="warning")

    # Build metadata payload and write metadata.json
    if plan.output_layout and plan.output_layout.metadata_dir:
        from abogen.domain.metadata_helpers import build_metadata_payload

        metadata_payload = build_metadata_payload(
            metadata=result.metadata,
            chapter_markers=result.chapter_markers,
            chunk_markers=result.chunk_markers,
            chunk_level=request.chapter_chunk.chunk_level if request.chapter_chunk else None,
            speaker_mode=request.chapter_chunk.speaker_mode if request.chapter_chunk else None,
            speakers=request.chapter_chunk.speakers if request.chapter_chunk else None,
            generate_epub3=bool(request.epub3_export),
        )

        metadata_dir = plan.output_layout.metadata_dir
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_file = metadata_dir / "metadata.json"

        import json

        metadata_file.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
        result.artifacts["metadata"] = metadata_file
        events.log(f"Metadata written to {metadata_file}")

    # Record override usage
    if result.usage_counter:
        try:
            from abogen.normalization_settings import record_override_usage

            record_override_usage(result.usage_counter)
        except Exception as exc:
            events.log(f"Failed to record override usage: {exc}", level="debug")



