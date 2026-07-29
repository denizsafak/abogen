"""Unified conversion executor.

Takes a ConversionPlan and ports, executes the TTS conversion,
and returns a ConversionResult. No UI imports allowed.

This is Stage 6 of the conversion flow unification plan.
"""

from __future__ import annotations

import logging
import time
from contextlib import ExitStack
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from abogen.application.conversion_models import (
    ConversionPlan,
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
from abogen.domain.chapter_titles import (
    apply_chapter_text_transforms,
    headings_equivalent as _headings_equivalent,
)
from abogen.domain.output_paths import sanitize_filename_for_chapter
from abogen.infrastructure.subtitle_writer import make_subtitle_writer


# ─── MarkerCollector ───


class MarkerCollector:
    """Observes execution events and accumulates chapter/chunk markers.

    Separates marker collection from synthesis logic.
    """

    def __init__(self) -> None:
        self._chapter_markers: List[Dict[str, Any]] = []
        self._chunk_markers: List[Dict[str, Any]] = []
        self._current_chapter_voices: Set[Tuple[str, str]] = set()
        self._current_chapter_index: int = 0
        self._current_chapter_title: str = ""
        self._current_chapter_start: float = 0.0

    def on_chapter_start(
        self, index: int, title: str, start_time: float
    ) -> None:
        """Record chapter start."""
        self._current_chapter_index = index
        self._current_chapter_title = title
        self._current_chapter_start = start_time
        self._current_chapter_voices.clear()

    def on_segment(
        self,
        provider: str,
        voice: Any,
        voice_spec: str,
        speaker_id: str = "narrator",
    ) -> None:
        """Record a voice used in this chapter (for multi-speaker tracking)."""
        self._current_chapter_voices.add((provider, voice_spec))

    def on_chunk(
        self,
        chunk_id: str,
        chapter_index: int,
        chunk_index: int,
        start: float,
        end: float,
        speaker_id: str,
        provider: str,
        voice_spec: str,
        level: str,
        characters: int,
    ) -> None:
        """Record a chunk marker."""
        self._chunk_markers.append({
            "id": chunk_id,
            "chapter_index": chapter_index,
            "chunk_index": chunk_index,
            "start": start,
            "end": end,
            "speaker_id": speaker_id,
            "voice": {"provider": provider, "voice": voice_spec},
            "level": level,
            "characters": characters,
        })

    def on_chapter_end(self, end_time: float) -> None:
        """Record chapter end and build chapter marker."""
        voices = [
            {"provider": p, "voice": v}
            for p, v in sorted(self._current_chapter_voices)
        ]
        self._chapter_markers.append({
            "chapter_index": self._current_chapter_index,
            "index": self._current_chapter_index + 1,
            "title": self._current_chapter_title,
            "start": self._current_chapter_start,
            "end": end_time,
            "voices": voices,
        })

    def on_outro(
        self,
        start_time: float,
        end_time: float,
        provider: str,
        voice_spec: str,
    ) -> None:
        """Record outro chapter marker."""
        self._chapter_markers.append({
            "chapter_index": len(self._chapter_markers),
            "index": len(self._chapter_markers) + 1,
            "title": "Outro",
            "start": start_time,
            "end": end_time,
            "voices": [{"provider": provider, "voice": voice_spec}],
        })

    @property
    def chapter_markers(self) -> List[Dict[str, Any]]:
        return self._chapter_markers

    @property
    def chunk_markers(self) -> List[Dict[str, Any]]:
        return self._chunk_markers


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
    collector = MarkerCollector()

    logging.info(
        "[executor] Starting: chapters=%d intro=%s outro=%s merge=%s",
        len(plan.chapters),
        bool(plan.intro and plan.intro.enabled),
        bool(plan.outro and plan.outro.enabled),
        request.save.merge_chapters_at_end,
    )

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
    use_spacy = request.subtitle.mode not in (SubtitleMode.DISABLED, SubtitleMode.LINE)

    # Output paths
    output_layout = plan.output_layout
    if not output_layout:
        raise ValueError("ConversionPlan must have an output_layout")

    # Determine if merged output is needed
    merge_chapters = request.save.merge_chapters_at_end or not request.save.save_chapters_separately
    if request.output_format == OutputFormat.M4B:
        merge_chapters = True

    # Resolve voices
    base_voice_spec = request.voice or "M1"
    logging.info("[executor] Resolving base voice: spec=%s", base_voice_spec)
    base_provider, base_voice_choice, base_speed, base_steps = _resolve_voice(
        voice_resolver, base_voice_spec, request,
        log_callback=lambda msg: events.log(msg, level="warning"),
    )
    logging.info("[executor] Base voice resolved: provider=%s voice=%s speed=%.2f", base_provider, base_voice_choice, base_speed)

    # Use ExitStack for resource management
    with ExitStack() as stack:
        # Open merged audio sink
        audio_sink: Optional[AudioSink] = None
        audio_path = None
        if merge_chapters:
            audio_path = output_layout.audio_dir / f"{_base_name(request)}{request.output_format.dot_ext}"
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
        if request.subtitle.mode != SubtitleMode.DISABLED and audio_sink:
            subtitle_writer = make_subtitle_writer(
                audio_path,
                request.subtitle,
            )
            if subtitle_writer:
                subtitle_writer.open()
                stack.callback(subtitle_writer.close)
                result.subtitle_paths.append(subtitle_writer.path)

        effective_subtitle_mode = request.subtitle.mode if subtitle_writer else SubtitleMode.DISABLED

        synth = SynthParams(
            tts_context=tts_context,
            stats=stats,
            check_cancel=check_cancelled,
            on_progress=lambda pct, etr: events.progress(pct, etr),
            audio_sink=audio_sink,
            subtitle_mode=effective_subtitle_mode,
            max_subtitle_words=request.subtitle.max_words,
            language=request.language,
            use_spacy_segmentation=use_spacy,
        )

        # Chapter directory
        chapter_dir = None
        if request.save.save_chapters_separately and len(plan.chapters) > 1:
            chapter_dir = output_layout.audio_dir / "chapters"
            chapter_dir.mkdir(parents=True, exist_ok=True)

        # Process intro
        intro_emitted = False
        if plan.intro and plan.intro.enabled and merge_chapters:
            events.log(f"Title intro: {plan.intro.text[:80]}")
            intro_provider, intro_voice, intro_speed, intro_steps = _resolve_voice(
                voice_resolver, plan.intro.voice_spec, request,
                log_callback=lambda msg: events.log(msg, level="warning"),
            )
            intro_backend = pipeline_provider.get(intro_provider, request.language, request.use_gpu)
            synthesize_text(
                text=plan.intro.text,
                params=synth,
                backend=intro_backend,
                voice=intro_voice,
                speed=intro_speed or request.speed,
                total_steps=intro_steps,
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
            logging.info("[executor] Chapter %d/%d: %s", chapter_idx, len(plan.chapters), chapter.title)

            # Resolve chapter voice
            chapter_provider, chapter_voice, chapter_speed, chapter_steps = _resolve_voice(
                voice_resolver, chapter.voice_spec, request,
                log_callback=lambda msg: events.log(msg, level="warning"),
            )
            logging.info("[executor] Chapter %d voice: provider=%s voice=%s speed=%.2f", chapter_idx, chapter_provider, chapter_voice, chapter_speed)
            chapter_backend = pipeline_provider.get(chapter_provider, request.language, request.use_gpu)

            # Record chapter start for markers
            collector.on_chapter_start(chapter_idx - 1, chapter.title, stats.current_time)

            # Per-chapter sink
            chapter_sink: Optional[AudioSink] = None
            chapter_path = None
            if chapter_dir:
                chapter_filename = sanitize_filename_for_chapter(chapter.title, chapter_idx)
                chapter_path = chapter_dir / f"{chapter_filename}.{request.save.separate_chapters_format}"
                chapter_sink = stack.enter_context(
                    open_audio_sink(
                        chapter_path,
                        request.save.separate_chapters_format,
                        cancel_check=check_cancelled,
                    )
                )
                result.chapter_paths.append(chapter_path)

            # Per-chapter subtitle writer
            chapter_subtitle_writer: Optional[SubtitleWriter] = None
            if chapter_dir and request.subtitle.mode != SubtitleMode.DISABLED and chapter_sink:
                from abogen.infrastructure.subtitle_writer import resolve_subtitle_format

                chapter_filename = sanitize_filename_for_chapter(chapter.title, chapter_idx)
                subtitle_ext, _ = resolve_subtitle_format(
                    request.subtitle
                )
                chapter_subtitle_path = chapter_dir / f"{chapter_filename}.{subtitle_ext}"
                chapter_subtitle_writer = make_subtitle_writer(
                    chapter_subtitle_path,
                    request.subtitle,
                )
                if chapter_subtitle_writer:
                    chapter_subtitle_writer.open()
                    result.subtitle_paths.append(chapter_subtitle_writer.path)

            # Intro delay before first chapter
            if not intro_emitted and plan.intro and plan.intro.enabled:
                # Intro will be emitted with first chapter
                intro_provider, intro_voice, intro_speed, intro_steps = _resolve_voice(
                    voice_resolver, plan.intro.voice_spec, request,
                    log_callback=lambda msg: events.log(msg, level="warning"),
                )
                intro_backend = pipeline_provider.get(intro_provider, request.language, request.use_gpu)
                synthesize_text(
                    text=plan.intro.text,
                    params=synth,
                    backend=intro_backend,
                    voice=intro_voice,
                    speed=intro_speed or request.speed,
                    total_steps=intro_steps,
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
            heading_text = ""
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

            # Heading dedup: check if first line of body matches heading
            pending_heading_strip = False
            if heading_text and chapter.body_text:
                first_line = next(
                    (line.strip() for line in chapter.body_text.splitlines() if line.strip()),
                    "",
                )
                if first_line and _headings_equivalent(first_line, heading_text):
                    pending_heading_strip = True

            # Process body segments
            for seg_idx, segment in enumerate(chapter.segments):
                check_cancelled()

                # Apply heading dedup to first segment (consume-once)
                seg_text = segment.text
                if pending_heading_strip and seg_text.strip():
                    seg_text, heading_removed, _ = apply_chapter_text_transforms(
                        seg_text,
                        heading_text=heading_text,
                        raw_title=chapter.title,
                        strip_heading=True,
                        normalize_caps=False,
                    )
                    if heading_removed:
                        pending_heading_strip = False
                    if not seg_text.strip():
                        continue

                # Resolve segment voice (may differ from chapter voice)
                if segment.voice_spec != chapter.voice_spec:
                    seg_provider, seg_voice, seg_speed, seg_steps = _resolve_voice(
                        voice_resolver, segment.voice_spec, request,
                        log_callback=lambda msg: events.log(msg, level="warning"),
                    )
                    seg_backend = pipeline_provider.get(seg_provider, request.language, request.use_gpu)
                else:
                    seg_provider = chapter_provider
                    seg_voice = chapter_voice
                    seg_speed = chapter_speed
                    seg_steps = chapter_steps
                    seg_backend = chapter_backend

                # Track voice for chapter marker
                collector.on_segment(seg_provider, seg_voice, segment.voice_spec)

                # spaCy pre-TTS segmentation
                from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation

                is_subtitle_input = bool(
                    request.subtitle_input
                )
                spacy_segments, active_split = spacy_pre_tts_segmentation(
                    seg_text,
                    request.language,
                    request.subtitle.mode,
                    is_subtitle_input=is_subtitle_input,
                    use_spacy_segmentation=use_spacy,
                    log_callback=lambda msg: events.log(msg),
                )

                seg_start_time = stats.current_time
                accumulated_tokens: List[Dict[str, Any]] = []
                for spacy_seg in spacy_segments:
                    if not spacy_seg.strip():
                        continue
                    _, seg_tokens = synthesize_text(
                        text=spacy_seg,
                        params=synth,
                        backend=seg_backend,
                        voice=seg_voice,
                        speed=seg_speed or request.speed,
                        total_steps=seg_steps,
                        chapter_sink=chapter_sink,
                        preview_callback=lambda text: events.log(f"  {text[:80]}"),
                        split_pattern_override=active_split,
                    )
                    accumulated_tokens.extend(seg_tokens)

                # Process subtitles
                if audio_sink and accumulated_tokens:
                    if subtitle_writer:
                        process_and_write_subtitles(
                            accumulated_tokens,
                            subtitle_writer,
                            subtitle=request.subtitle,
                            language=request.language,
                            use_spacy_segmentation=use_spacy,
                            fallback_end_time=stats.current_time,
                        )
                    if chapter_subtitle_writer:
                        process_and_write_subtitles(
                            accumulated_tokens,
                            chapter_subtitle_writer,
                            subtitle=request.subtitle,
                            language=request.language,
                            use_spacy_segmentation=use_spacy,
                            fallback_end_time=stats.current_time,
                        )

                # Record chunk marker
                if segment.source in ("chunk", "voice_marker"):
                    collector.on_chunk(
                        chunk_id=segment.chunk_id or "",
                        chapter_index=chapter_idx - 1,
                        chunk_index=segment.chunk_index or seg_idx,
                        start=seg_start_time,
                        end=stats.current_time,
                        speaker_id=segment.speaker_id or "narrator",
                        provider=seg_provider,
                        voice_spec=segment.voice_spec,
                        level=segment.level or (request.chapter_chunk.chunk_level if request.chapter_chunk else "paragraph"),
                        characters=len(segment.text),
                    )

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

            # Close chapter subtitle writer
            if chapter_subtitle_writer:
                chapter_subtitle_writer.close()

            # Record chapter end for markers
            collector.on_chapter_end(stats.current_time)
            logging.info("[executor] Chapter %d/%d done: time=%.1fs", chapter_idx, len(plan.chapters), stats.current_time)

        logging.info("[executor] All chapters done: total=%.1fs", stats.current_time)

        # Process outro
        if plan.outro and plan.outro.enabled and merge_chapters:
            events.log(f"Closing outro: {plan.outro.text[:80]}")
            outro_provider, outro_voice, outro_speed, outro_steps = _resolve_voice(
                voice_resolver, plan.outro.voice_spec, request,
                log_callback=lambda msg: events.log(msg, level="warning"),
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

            outro_start = stats.current_time
            synthesize_text(
                text=plan.outro.text,
                params=synth,
                backend=outro_backend,
                voice=outro_voice,
                speed=outro_speed or request.speed,
                total_steps=outro_steps,
                chapter_sink=None,
                preview_callback=lambda text: events.log(f"  {text[:80]}"),
            )
            # Record outro marker
            collector.on_outro(outro_start, stats.current_time, outro_provider, plan.outro.voice_spec)
            events.log("Outro synthesized.")

    # Set result metadata
    result.chapter_markers = collector.chapter_markers
    result.chunk_markers = collector.chunk_markers
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
    *,
    log_callback: Optional[Callable[[str], None]] = None,
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
    except Exception as exc:
        # Fallback to base voice
        base_spec = request.voice or "M1"
        if log_callback:
            log_callback(
                f"Voice '{voice_spec}' failed to resolve: {exc}. "
                f"Falling back to '{base_spec}'."
            )
        try:
            resolved = resolver.resolve(base_spec)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"Both voice '{voice_spec}' and fallback '{base_spec}' failed to resolve. "
                f"Primary error: {exc}; Fallback error: {fallback_exc}"
            ) from fallback_exc
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
