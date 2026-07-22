"""Unified conversion executor.

Takes a ConversionPlan and ports, executes the TTS conversion,
and returns a ConversionResult. No UI imports allowed.

This is Stage 6 of the conversion flow unification plan.
"""

from __future__ import annotations

import time
from contextlib import ExitStack
from typing import Any, Callable, Dict, List, Optional, Tuple

from abogen.application.conversion_models import (
    ChapterPlan,
    ConversionPlan,
    IntroOutroSpec,
    SegmentPlan,
)
from abogen.application.conversion_ports import (
    AudioSink,
    ConversionEvents,
    PipelineProvider,
    SubtitleWriter,
    VoiceResolver,
)
from abogen.application.conversion_result import ConversionResult
from abogen.domain.audio_sink import open_audio_sink
from abogen.domain.conversion_engine import (
    SegmentStats,
    SynthParams,
    process_and_write_subtitles,
    synthesize_text,
)
from abogen.domain.enums import OutputFormat, SubtitleMode
from abogen.domain.normalization import TTSContext
from abogen.domain.output_paths import sanitize_filename_for_chapter
from abogen.infrastructure.subtitle_writer import make_subtitle_writer


def execute_conversion(
    plan: ConversionPlan,
    events: ConversionEvents,
    pipeline_provider: PipelineProvider,
    voice_resolver: VoiceResolver,
    tts_context: TTSContext,
    *,
    check_cancelled: Optional[Callable[[], None]] = None,
) -> ConversionResult:
    """Execute a conversion plan and return the result.

    Args:
        plan: The conversion plan from build_conversion_plan()
        events: UI-specific callbacks (log, progress, check_cancelled)
        pipeline_provider: Provides TTS backends
        voice_resolver: Resolves voice specs into loaded voices
        tts_context: Normalization context for text processing
        check_cancelled: Optional cancellation checker (overrides events.check_cancelled)

    Returns:
        ConversionResult with paths and markers

    Raises:
        ConversionCancelled: If conversion is cancelled
    """
    request = plan.request
    result = ConversionResult(metadata=plan.metadata)

    # Determine cancellation checker
    if check_cancelled is None:
        check_cancelled = lambda: events.check_cancelled()

    # Stats for progress tracking
    total_characters = sum(
        len(ch.body_text) for ch in plan.chapters
    )
    if plan.intro and plan.intro.enabled:
        total_characters += len(plan.intro.text)
    if plan.outro and plan.outro.enabled:
        total_characters += len(plan.outro.text)

    stats = SegmentStats(
        processed_chars=0,
        current_time=0.0,
        etr_start_time=time.time(),
        total_characters=total_characters,
    )

    # Compute subtitle flag once (used in every synthesize_text call)
    use_spacy = request.subtitle_mode not in (SubtitleMode.DISABLED, SubtitleMode.LINE)

    # Output paths
    output_layout = plan.output_layout
    if not output_layout:
        raise ValueError("ConversionPlan must have an output_layout")

    # Determine if merged output is needed
    merge_chapters = request.merge_chapters_at_end or not request.save_chapters_separately
    if request.output_format == OutputFormat.M4B:
        merge_chapters = True

    # Resolve voices
    base_voice_spec = request.voice or "M1"
    base_provider, base_voice_choice, base_speed, base_steps = _resolve_voice(
        voice_resolver, base_voice_spec, request
    )

    # Use ExitStack for resource management
    with ExitStack() as stack:
        # Open merged audio sink
        audio_sink: Optional[AudioSink] = None
        audio_path = None
        if merge_chapters:
            audio_path = output_layout.audio_dir / f"{_base_name(request)}.{request.output_format}"
            meta = plan.metadata if plan.metadata else None
            audio_sink = stack.enter_context(
                open_audio_sink(
                    audio_path,
                    request.output_format,
                    metadata=meta,
                    cancel_check=check_cancelled,
                )
            )
            result.audio_path = audio_path

        # Open subtitle writer if needed
        subtitle_writer: Optional[SubtitleWriter] = None
        if request.subtitle_mode != SubtitleMode.DISABLED and audio_sink:
            subtitle_writer = make_subtitle_writer(
                audio_path,
                request.subtitle_format,
                request.subtitle_mode,
                max_words=request.max_subtitle_words,
            )
            if subtitle_writer:
                subtitle_writer.open()
                stack.callback(subtitle_writer.close)
                result.subtitle_paths.append(subtitle_writer.path)

        effective_subtitle_mode = request.subtitle_mode if subtitle_writer else SubtitleMode.DISABLED

        synth = SynthParams(
            tts_context=tts_context,
            stats=stats,
            check_cancel=check_cancelled,
            on_progress=lambda pct, etr: events.progress(pct, etr),
            audio_sink=audio_sink,
            subtitle_mode=effective_subtitle_mode,
            max_subtitle_words=request.max_subtitle_words,
            lang_code=request.language,
            use_spacy_segmentation=use_spacy,
        )

        # Chapter directory
        chapter_dir = None
        if request.save_chapters_separately and len(plan.chapters) > 1:
            chapter_dir = output_layout.audio_dir / "chapters"
            chapter_dir.mkdir(parents=True, exist_ok=True)

        # Process intro
        intro_emitted = False
        if plan.intro and plan.intro.enabled and merge_chapters:
            events.log(f"Title intro: {plan.intro.text[:80]}")
            intro_provider, intro_voice, intro_speed, intro_steps = _resolve_voice(
                voice_resolver, plan.intro.voice_spec, request
            )
            intro_backend = pipeline_provider.get(intro_provider, request.language, request.use_gpu)
            synthesize_text(
                text=plan.intro.text,
                params=synth,
                backend=intro_backend,
                voice=intro_voice,
                speed=intro_speed or request.speed,
                chapter_sink=None,
                preview_callback=lambda text: events.log(f"  {text[:80]}"),
            )
            intro_emitted = True
            events.log("Intro synthesized.")

        # Chapter loop
        for chapter_idx, chapter in enumerate(plan.chapters, 1):
            check_cancelled()

            chapter_display = f"Chapter {chapter_idx}/{len(plan.chapters)}: {chapter.title}"
            events.log(f"Processing {chapter_display}")

            # Resolve chapter voice
            chapter_provider, chapter_voice, chapter_speed, chapter_steps = _resolve_voice(
                voice_resolver, chapter.voice_spec, request
            )
            chapter_backend = pipeline_provider.get(chapter_provider, request.language, request.use_gpu)

            # Per-chapter sink
            chapter_sink: Optional[AudioSink] = None
            chapter_path = None
            if chapter_dir:
                chapter_filename = sanitize_filename_for_chapter(chapter.title, chapter_idx)
                chapter_path = chapter_dir / f"{chapter_filename}.{request.separate_chapters_format}"
                chapter_sink = stack.enter_context(
                    open_audio_sink(
                        chapter_path,
                        request.separate_chapters_format,
                        cancel_check=check_cancelled,
                    )
                )
                result.chapter_paths.append(chapter_path)

            # Intro delay before first chapter
            if not intro_emitted and plan.intro and plan.intro.enabled:
                # Intro will be emitted with first chapter
                intro_provider, intro_voice, intro_speed, intro_steps = _resolve_voice(
                    voice_resolver, plan.intro.voice_spec, request
                )
                intro_backend = pipeline_provider.get(intro_provider, request.language, request.use_gpu)
                synthesize_text(
                    text=plan.intro.text,
                    params=synth,
                    backend=intro_backend,
                    voice=intro_voice,
                    speed=intro_speed or request.speed,
                    chapter_sink=chapter_sink,
                    preview_callback=lambda text: events.log(f"  Intro: {text[:80]}"),
                )
                intro_emitted = True
                if request.chapter_intro_delay > 0:
                    _append_silence(
                        request.chapter_intro_delay,
                        chapter_sink=chapter_sink,
                        audio_sink=audio_sink,
                        stats=stats,
                    )

            # Process heading
            if chapter.title:
                heading_text = _format_heading(chapter.title, chapter_idx, request)
                if heading_text:
                    synthesize_text(
                        text=heading_text,
                        params=synth,
                        backend=chapter_backend,
                        voice=chapter_voice,
                        speed=chapter_speed or request.speed,
                        chapter_sink=chapter_sink,
                        preview_callback=lambda text: events.log(f"  Title: {text[:80]}"),
                    )
                    if request.chapter_intro_delay > 0:
                        _append_silence(
                            request.chapter_intro_delay,
                            chapter_sink=chapter_sink,
                            audio_sink=audio_sink,
                            stats=stats,
                        )

            # Process body segments
            chapter_chunk_markers: List[Dict[str, Any]] = []
            for seg_idx, segment in enumerate(chapter.segments):
                check_cancelled()

                # Resolve segment voice (may differ from chapter voice)
                if segment.voice_spec != chapter.voice_spec:
                    seg_provider, seg_voice, seg_speed, seg_steps = _resolve_voice(
                        voice_resolver, segment.voice_spec, request
                    )
                    seg_backend = pipeline_provider.get(seg_provider, request.language, request.use_gpu)
                else:
                    seg_provider = chapter_provider
                    seg_voice = chapter_voice
                    seg_speed = chapter_speed
                    seg_backend = chapter_backend

                seg_start_time = stats.current_time
                local_segments, accumulated_tokens = synthesize_text(
                    text=segment.text,
                    params=synth,
                    backend=seg_backend,
                    voice=seg_voice,
                    speed=seg_speed or request.speed,
                    chapter_sink=chapter_sink,
                    preview_callback=lambda text: events.log(f"  {text[:80]}"),
                )

                # Process subtitles
                if subtitle_writer and audio_sink and accumulated_tokens:
                    process_and_write_subtitles(
                        accumulated_tokens,
                        subtitle_writer,
                        subtitle_mode=request.subtitle_mode,
                        max_subtitle_words=request.max_subtitle_words,
                        lang_code=request.language,
                        use_spacy_segmentation=use_spacy,
                        fallback_end_time=stats.current_time,
                    )

                # Record chunk marker
                if segment.source in ("chunk", "voice_marker"):
                    chapter_chunk_markers.append({
                        "id": segment.chunk_id,
                        "chapter_index": chapter_idx - 1,
                        "chunk_index": segment.chunk_index or seg_idx,
                        "start": seg_start_time,
                        "end": stats.current_time,
                        "speaker_id": segment.speaker_id,
                        "voice": segment.voice_spec,
                        "level": segment.level or request.chunk_level,
                        "characters": len(segment.text),
                    })

            # Silence between chapters
            if chapter_idx < len(plan.chapters) and request.silence_between_chapters > 0:
                _append_silence(
                    request.silence_between_chapters,
                    chapter_sink=chapter_sink,
                    audio_sink=audio_sink,
                    stats=stats,
                )

            # Close chapter sink
            if chapter_sink:
                chapter_sink.close()

            # Add chapter marker
            result.chapter_markers.append({
                "chapter_index": chapter_idx - 1,
                "title": chapter.title,
                "start": stats.current_time - (stats.current_time - seg_start_time) if chapter.segments else stats.current_time,
                "end": stats.current_time,
            })

            result.chunk_markers.extend(chapter_chunk_markers)

        # Process outro
        if plan.outro and plan.outro.enabled and merge_chapters:
            events.log(f"Closing outro: {plan.outro.text[:80]}")
            outro_provider, outro_voice, outro_speed, outro_steps = _resolve_voice(
                voice_resolver, plan.outro.voice_spec, request
            )
            outro_backend = pipeline_provider.get(outro_provider, request.language, request.use_gpu)

            # Silence before outro
            if request.silence_between_chapters > 0:
                _append_silence(
                    request.silence_between_chapters,
                    chapter_sink=None,
                    audio_sink=audio_sink,
                    stats=stats,
                )

            synthesize_text(
                text=plan.outro.text,
                params=synth,
                backend=outro_backend,
                voice=outro_voice,
                speed=outro_speed or request.speed,
                chapter_sink=None,
                preview_callback=lambda text: events.log(f"  {text[:80]}"),
            )
            events.log("Outro synthesized.")

    # Set result metadata
    result.total_chapters = len(plan.chapters)
    result.total_segments = sum(len(ch.segments) for ch in plan.chapters)
    result.total_characters = total_characters

    if output_layout.project_root:
        result.project_root = output_layout.project_root

    return result


# ─── Helpers ────────────────────────────────────────────────────────


def _resolve_voice(
    resolver: VoiceResolver,
    voice_spec: str,
    request: Any,
) -> Tuple[str, Any, Optional[float], Optional[int]]:
    """Resolve a voice spec and return (provider, voice, speed, steps)."""
    try:
        resolved = resolver.resolve(voice_spec)
        return (
            resolved.provider,
            resolved.voice,
            resolved.speed,
            resolved.supertonic_steps,
        )
    except Exception:
        # Fallback to base voice
        resolved = resolver.resolve(request.voice or "M1")
        return (
            resolved.provider,
            resolved.voice,
            resolved.speed,
            resolved.supertonic_steps,
        )


def _base_name(request: Any) -> str:
    """Get base name for output file."""
    from abogen.domain.output_paths import sanitize_output_stem

    if request.original_filename:
        return sanitize_output_stem(request.original_filename)
    return "output"


def _format_heading(title: str, index: int, request: Any) -> str:
    """Format chapter heading for TTS."""
    from abogen.domain.chapter_titles import format_spoken_chapter_title

    if request.auto_prefix_chapter_titles:
        return format_spoken_chapter_title(title, index, apply_prefix=True)
    return title


def _append_silence(
    duration: float,
    *,
    chapter_sink: Optional[AudioSink],
    audio_sink: Optional[AudioSink],
    stats: SegmentStats,
) -> None:
    """Append silence to sinks."""
    from abogen.domain.audio_buffer import create_silence

    silence = create_silence(duration)
    if silence.size == 0:
        return
    if chapter_sink:
        chapter_sink.write(silence)
    if audio_sink:
        audio_sink.write(silence)
        stats.current_time += duration
