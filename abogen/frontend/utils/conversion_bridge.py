"""
Background conversion bridge for the Abogen Flet frontend.

This module wraps the existing ``abogen.webui.conversion_runner`` (and its
``ConversionService`` / ``Job`` machinery) in an async-friendly interface that
can push real-time progress and log updates back to the Flet event loop without
blocking the UI thread.

Key design decisions
--------------------
* All heavy work is offloaded to daemon threads. The Flet page event loop
  is never blocked.
* Progress and log callbacks are scheduled back onto the Flet page via
  ``page.run_task()`` so Flet's session isolation remains intact.
* Cancellation is cooperative: the underlying job's ``cancel_requested``
  flag is set, and the runner checks it at chunk boundaries.
* The module is a pure adapter – it does NOT duplicate any processing logic
  from the core pipeline.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft

from abogen.utils import (
    get_gpu_acceleration,
    get_user_cache_path,
    get_user_output_path,
    load_numpy_kpipeline,
    prevent_sleep_end,
    prevent_sleep_start,
)
from abogen.webui.service import (
    ConversionService,
    Job,
    JobStatus,
    PendingJob,
    build_service,
)
from abogen.webui.conversion_runner import run_conversion_job

from ..state import AppState

# ---------------------------------------------------------------------------
# Module-level singleton ConversionService (shared across sessions, as in the
# web UI – but each job carries its own output folder keyed by session).
# ---------------------------------------------------------------------------

_SERVICE_LOCK = threading.Lock()
_SERVICE: Optional[ConversionService] = None


def _get_service() -> ConversionService:
    """
    Return (creating if necessary) the module-level ConversionService.

    The service manages the background worker thread and persistent job state.
    Thread-safe via a module-level lock.
    """
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            output_root = Path(get_user_output_path("frontend"))
            uploads_root = Path(get_user_cache_path("frontend/uploads"))
            _SERVICE = build_service(
                runner=run_conversion_job,
                output_root=output_root,
                uploads_root=uploads_root,
            )
    return _SERVICE


# ---------------------------------------------------------------------------
# Public conversion bridge
# ---------------------------------------------------------------------------


class ConversionBridge:
    """
    Thin adapter between the Flet UI session and the core conversion pipeline.

    One ``ConversionBridge`` instance is created per Flet page (session) and
    is responsible for:
    1. Accepting a conversion request from the UI.
    2. Writing the input text to a temp file if needed.
    3. Submitting the job to ``ConversionService``.
    4. Polling the job from a daemon thread and forwarding progress/logs to
       the Flet page via ``page.run_task()``.
    5. Providing a ``cancel()`` method that sets the cooperative flag.
    """

    def __init__(self, page: ft.Page, state: AppState) -> None:
        """
        Initialise the bridge.

        Args:
            page: The Flet ``Page`` for this session. Used to schedule
                  UI callbacks on the correct event loop.
            state: The session's ``AppState`` instance.
        """
        self._page = page
        self._state = state
        self._current_job: Optional[Job] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_poll = threading.Event()
        self._seen_log_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        input_file: str,
        voice: str,
        lang_code: str,
        speed: float,
        output_format: str,
        subtitle_mode: str,
        subtitle_format: str,
        use_gpu: bool,
        save_option: str,
        output_folder: Optional[str],
        replace_single_newlines: bool,
        char_count: int,
        chapters: Optional[List[Dict[str, Any]]] = None,
        save_chapters_separately: bool = False,
        merge_chapters_at_end: bool = True,
        separate_chapters_format: str = "wav",
        silence_between_chapters: float = 2.0,
        max_subtitle_words: int = 50,
        chapter_intro_delay: float = 0.5,
        read_title_intro: bool = False,
        read_closing_outro: bool = True,
        auto_prefix_chapter_titles: bool = True,
        normalize_chapter_opening_caps: bool = True,
        tts_provider: str = "kokoro",
        supertonic_total_steps: int = 5,
        chunk_level: str = "paragraph",
        generate_epub3: bool = False,
        word_substitutions_enabled: bool = False,
        word_substitutions_list: str = "",
        case_sensitive_substitutions: bool = False,
        replace_all_caps: bool = False,
        replace_numerals: bool = False,
        fix_nonstandard_punctuation: bool = False,
    ) -> None:
        """
        Submit a conversion job and begin the progress-polling loop.

        This method returns immediately; all heavy work runs on daemon threads.
        UI callbacks (``state.on_log``, ``state.on_progress``,
        ``state.on_conversion_finished``) are scheduled on the Flet event loop.

        Args:
            input_file: Absolute path to the text/epub/pdf input file.
            voice: Kokoro voice formula string.
            lang_code: Single-char language code.
            speed: Playback speed multiplier (0.1 – 2.0).
            output_format: Audio container key (``'wav'``, ``'mp3'``, …).
            subtitle_mode: Subtitle generation mode string.
            subtitle_format: Subtitle container key (``'srt'``, ``'ass_wide'``, …).
            use_gpu: Whether to request GPU acceleration.
            save_option: Save-location strategy string.
            output_folder: Explicit output folder or None.
            replace_single_newlines: Pre-processing flag.
            char_count: Pre-computed character count for ETR estimation.
            chapters: Optional list of chapter dicts for epub/pdf.
            save_chapters_separately: Split chapters into separate files.
            merge_chapters_at_end: Merge chapter files into one after generation.
            separate_chapters_format: Format for individual chapter files.
            silence_between_chapters: Silence gap (seconds) between chapters.
            max_subtitle_words: Maximum words per subtitle block.
            chapter_intro_delay: Silence before chapter title announcement (s).
            read_title_intro: Announce book title at the start.
            read_closing_outro: Announce book title at the end.
            auto_prefix_chapter_titles: Prepend "Chapter N." to titles.
            normalize_chapter_opening_caps: Fix ALL-CAPS opening lines.
            tts_provider: ``'kokoro'`` or ``'supertonic'``.
            supertonic_total_steps: Quality steps for the Supertonic pipeline.
            chunk_level: ``'paragraph'`` or ``'sentence'`` chunking granularity.
            generate_epub3: Also produce an EPUB3 audiobook package.
            word_substitutions_enabled: Toggle word-substitution pre-processing.
            word_substitutions_list: Newline-delimited ``word|replacement`` rules.
            case_sensitive_substitutions: Case-sensitive matching for substitutions.
            replace_all_caps: Lowercase ALL-CAPS words.
            replace_numerals: Convert digits to spoken words.
            fix_nonstandard_punctuation: Normalise curly quotes etc.
        """
        if self._state.is_converting:
            return

        # Resolve the effective output folder
        resolved_output: Optional[Path] = self._resolve_output_folder(
            save_option=save_option,
            output_folder=output_folder,
            input_file=input_file,
        )

        # Store the input file as a Path
        stored_path = Path(input_file)
        original_filename = stored_path.name

        # Block signals until the job is submitted
        prevent_sleep_start()
        self._state.is_converting = True
        self._state.is_cancelled = False
        self._state.progress = 0.0
        self._state.etr_seconds = None
        self._state.log_lines = []
        self._seen_log_count = 0

        # Enqueue the job on the service
        service = _get_service()
        job = service.enqueue(
            original_filename=original_filename,
            stored_path=stored_path,
            language=lang_code,
            voice=voice,
            speed=speed,
            tts_provider=tts_provider,
            supertonic_total_steps=supertonic_total_steps,
            use_gpu=use_gpu,
            subtitle_mode=subtitle_mode,
            output_format=output_format,
            save_mode=self._save_mode_key(save_option),
            output_folder=resolved_output,
            replace_single_newlines=replace_single_newlines,
            subtitle_format=subtitle_format,
            total_characters=char_count,
            chapters=chapters or [],
            save_chapters_separately=save_chapters_separately,
            merge_chapters_at_end=merge_chapters_at_end,
            separate_chapters_format=separate_chapters_format,
            silence_between_chapters=silence_between_chapters,
            max_subtitle_words=max_subtitle_words,
            chapter_intro_delay=chapter_intro_delay,
            read_title_intro=read_title_intro,
            read_closing_outro=read_closing_outro,
            auto_prefix_chapter_titles=auto_prefix_chapter_titles,
            normalize_chapter_opening_caps=normalize_chapter_opening_caps,
            chunk_level=chunk_level,
            generate_epub3=generate_epub3,
        )
        self._current_job = job

        # Persist word-substitution settings to config so the runner picks them up
        self._state.word_substitutions_enabled = word_substitutions_enabled
        self._state.word_substitutions_list = word_substitutions_list
        self._state.case_sensitive_substitutions = case_sensitive_substitutions
        self._state.replace_all_caps = replace_all_caps
        self._state.replace_numerals = replace_numerals
        self._state.fix_nonstandard_punctuation = fix_nonstandard_punctuation
        self._state.persist_config()

        # Start the poll thread
        self._stop_poll.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_job_loop, daemon=True, name="abogen-poll"
        )
        self._poll_thread.start()

    def cancel(self) -> None:
        """
        Request cancellation of the currently running job.

        Sets the cooperative flag on the underlying ``Job`` object; the runner
        will stop after completing the current text chunk.
        """
        if self._current_job is not None:
            self._state.is_cancelled = True
            try:
                _get_service().cancel(self._current_job.id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _save_mode_key(option: str) -> str:
        """
        Convert the human-readable save option to the service's internal key.

        Args:
            option: UI-facing string (``'Save next to input file'``, …).

        Returns:
            Service key string.
        """
        mapping = {
            "Save next to input file": "save_next_to_input",
            "Save to Desktop": "save_to_desktop",
            "Choose output folder": "custom",
        }
        return mapping.get(option, "save_next_to_input")

    @staticmethod
    def _resolve_output_folder(
        save_option: str,
        output_folder: Optional[str],
        input_file: str,
    ) -> Optional[Path]:
        """
        Return the output ``Path`` based on the save option, or None for
        the "next to input" strategy (the runner handles that internally).

        Args:
            save_option: UI-facing save strategy string.
            output_folder: Explicit path when ``save_option`` is ``'Choose output folder'``.
            input_file: Path to the source file for the ``'Save to Desktop'`` strategy.

        Returns:
            Resolved ``Path`` or ``None``.
        """
        if save_option == "Choose output folder" and output_folder:
            p = Path(output_folder)
            p.mkdir(parents=True, exist_ok=True)
            return p
        if save_option == "Save to Desktop":
            desktop = Path.home() / "Desktop"
            desktop.mkdir(exist_ok=True)
            return desktop
        # "Save next to input file" – let the runner decide
        return None

    def _poll_job_loop(self) -> None:
        """
        Background daemon loop that polls the current Job for updates.

        Runs until the job enters a terminal state or until ``_stop_poll``
        is set.  Uses ``page.run_task()`` to schedule UI updates on the Flet
        event loop without triggering thread-safety violations.
        """
        job = self._current_job
        if job is None:
            return

        service = _get_service()
        POLL_INTERVAL = 0.25  # seconds

        while not self._stop_poll.is_set():
            # Re-fetch the current job state (it's mutated in-place by the runner)
            current = service.get_job(job.id)
            if current is None:
                break

            # Forward new log lines
            new_logs = current.logs[self._seen_log_count:]
            self._seen_log_count += len(new_logs)
            for log_entry in new_logs:
                level = getattr(log_entry, "level", "info")
                message = getattr(log_entry, "message", str(log_entry))
                self._schedule_log(message, level)

            # Forward progress
            if current.progress is not None:
                etr = getattr(current, "estimated_time_remaining", None)
                self._schedule_progress(float(current.progress), etr)

            # Check for terminal states
            status = current.status
            if status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                output_path: Optional[str] = None
                if current.result and current.result.audio_path:
                    output_path = str(current.result.audio_path)
                if status == JobStatus.COMPLETED:
                    finish_msg = "Conversion completed successfully."
                elif status == JobStatus.CANCELLED:
                    finish_msg = "Cancelled"
                else:
                    finish_msg = f"Conversion failed: {current.error or 'Unknown error'}"

                self._schedule_finished(finish_msg, output_path)
                break

            time.sleep(POLL_INTERVAL)

        prevent_sleep_end()
        self._state.is_converting = False

    def _schedule_log(self, message: str, level: str) -> None:
        """Schedule a log update on the Flet event loop."""
        state = self._state
        page = self._page
        state.append_log(message, level)

        async def _update() -> None:
            cb = state.on_log
            if cb:
                cb(message, level)
            try:
                page.update()
            except Exception:
                pass

        try:
            page.run_task(_update)
        except Exception:
            pass

    def _schedule_progress(self, fraction: float, etr: Optional[float]) -> None:
        """Schedule a progress update on the Flet event loop."""
        state = self._state
        page = self._page
        state.progress = max(0.0, min(1.0, fraction))
        state.etr_seconds = etr

        async def _update() -> None:
            cb = state.on_progress
            if cb:
                cb(fraction, etr)
            try:
                page.update()
            except Exception:
                pass

        try:
            page.run_task(_update)
        except Exception:
            pass

    def _schedule_finished(
        self, message: str, output_path: Optional[str]
    ) -> None:
        """Schedule a completion notification on the Flet event loop."""
        state = self._state
        page = self._page
        state.last_output_path = output_path
        self._stop_poll.set()

        async def _update() -> None:
            state.is_converting = False
            state.progress = 1.0
            state.last_output_path = output_path
            cb = state.on_conversion_finished
            if cb:
                cb(message, output_path)
            try:
                page.update()
            except Exception:
                pass

        try:
            page.run_task(_update)
        except Exception:
            pass
