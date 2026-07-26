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
from typing import Dict, Optional

from abogen.application.conversion_executor import execute_conversion
from abogen.application.conversion_models import ConversionPlan
from abogen.application.conversion_planner import build_conversion_plan
from abogen.application.conversion_ports import (
    ConversionEvents,
    PipelineProvider,
    VoiceResolver,
)
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_result import ConversionResult
from abogen.domain.enums import SubtitleMode
from abogen.domain.normalization import TTSContext
from abogen.domain.split_pattern import get_split_pattern


def run_conversion(
    request: ConversionRequest,
    events: ConversionEvents,
    pipeline_provider: PipelineProvider,
    voice_resolver: VoiceResolver,
) -> ConversionResult:
    """Execute a conversion request and return the result.

    This is the single entry point for both UIs. It orchestrates:
    1. TTS context preparation
    2. Conversion planning
    3. Conversion execution
    4. Resource cleanup

    Args:
        request: Normalized conversion request
        events: UI-specific callbacks (log, progress, check_cancelled)
        pipeline_provider: Provides TTS backends
        voice_resolver: Resolves voice specs into loaded voices

    Returns:
        ConversionResult with paths and markers

    Raises:
        ConversionCancelled: If conversion was cancelled
        ValueError: If request is invalid
        Exception: On TTS or I/O errors
    """
    try:
        # Stage 1: Prepare TTS context
        events.log("Preparing conversion pipeline")
        usage_counter: Dict[str, int] = defaultdict(int)
        tts_context = _prepare_tts_context(request, events, usage_counter=usage_counter)

        # Stage 2: Build conversion plan
        events.log("Building conversion plan")
        plan = build_conversion_plan(request)

        # Stage 3: Execute conversion
        events.log("Starting conversion")
        result = execute_conversion(
            plan=plan,
            events=events,
            pipeline_provider=pipeline_provider,
            voice_resolver=voice_resolver,
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
    epub3_config = request.epub3_export
    if epub3_config and plan.extraction:
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
                    book_id=epub3_config.book_id,
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


def _prepare_tts_context(
    request: ConversionRequest,
    events: ConversionEvents,
    *,
    usage_counter: Optional[Dict[str, int]] = None,
) -> TTSContext:
    """Prepare TTSContext with normalization settings.

    This compiles pronunciation/heteronym rules and creates the
    normalization context used during conversion.

    Args:
        request: Conversion request with override settings
        events: For logging warnings about missing features

    Returns:
        TTSContext ready for text normalization
    """
    from abogen.domain.normalization import (
        build_apostrophe_config,
        get_runtime_settings,
    )
    from abogen.normalization_settings import apply_overrides, build_llm_configuration
    from abogen.domain.pronunciation import (
        compile_heteronym_sentence_rules,
        compile_pronunciation_rules,
        merge_pronunciation_overrides,
    )

    # Get runtime normalization settings
    normalization_settings = get_runtime_settings()

    # Extract pronunciation config early (needed for normalization overrides)
    pronunciation = request.pronunciation

    # Apply per-job normalization overrides (same as runners)
    job_overrides = pronunciation.normalization_overrides if pronunciation else None
    if job_overrides:
        normalization_settings = apply_overrides(normalization_settings, job_overrides)

    # Build apostrophe config
    apostrophe_config = build_apostrophe_config(
        settings=normalization_settings,
    )

    # Validate LLM apostrophe mode
    apostrophe_mode = str(normalization_settings.get("normalization_apostrophe_mode", "spacy")).lower()
    if apostrophe_mode == "llm":
        llm_config = build_llm_configuration(normalization_settings)
        if not llm_config.is_configured():
            raise RuntimeError(
                "LLM-based apostrophe normalization is selected, but the LLM configuration is incomplete."
            )

    # Check for num2words availability
    if apostrophe_config.convert_numbers:
        try:
            import num2words  # noqa: F401
        except ImportError:
            events.log(
                "Number normalization is enabled but 'num2words' library is not available. "
                "Numbers will NOT be converted to words.",
                level="warning",
            )

    # Compute split pattern
    split_pattern = get_split_pattern(
        request.language or Language.EN_US,
        request.subtitle_mode or SubtitleMode.DISABLED,
    )

    # Merge pronunciation overrides (manual + pronunciation)

    class _MockJob:
        def __init__(self, pron):
            self.pronunciation_overrides = pron.pronunciation_overrides if pron else []
            self.manual_overrides = pron.manual_overrides if pron else []
            self.heteronym_overrides = pron.heteronym_overrides if pron else []

    merged_overrides = merge_pronunciation_overrides(_MockJob(pronunciation))

    # Compile rules
    pronunciation_rules = compile_pronunciation_rules(merged_overrides)
    heteronym_overrides = pronunciation.heteronym_overrides if pronunciation else []
    heteronym_rules = compile_heteronym_sentence_rules(heteronym_overrides)

    if heteronym_rules:
        events.log(
            f"Applying {len(heteronym_rules)} heteronym override(s) during conversion.",
            level="debug",
        )
    if pronunciation_rules:
        events.log(
            f"Applying {len(pronunciation_rules)} pronunciation override(s) during conversion.",
            level="debug",
        )

    return TTSContext(
        split_pattern=split_pattern,
        pronunciation_rules=pronunciation_rules,
        heteronym_rules=heteronym_rules,
        normalization_overrides=pronunciation.normalization_overrides if pronunciation else None,
        usage_counter=usage_counter or {},
    )
