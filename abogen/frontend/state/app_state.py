"""
Centralized, per-session application state for the Abogen Flet frontend.

Each Flet page (session) gets its own instance of AppState, which guarantees
complete isolation between simultaneous web-browser clients and the desktop
window. The class carries every configuration variable, file buffer reference,
and generation progress field that the rest of the UI reads or writes.

This module intentionally has no Flet imports so it can be unit-tested without
a running Flet server.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from abogen.utils import load_config, save_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_config() -> Dict[str, Any]:
    """Load the persisted user config dict, returning an empty dict on failure."""
    try:
        return load_config() or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Per-session state
# ---------------------------------------------------------------------------


@dataclass
class ConversionJob:
    """Lightweight descriptor of a single queued conversion job."""

    file_path: str
    """Absolute path to the text/epub/pdf/txt input file."""

    display_name: str
    """User-visible filename (may be the original epub/pdf path)."""

    voice: str
    """Voice formula string (e.g. 'af_heart' or 'af_heart*0.5+am_adam*0.5')."""

    lang_code: str
    """Single-char language prefix used by Kokoro (e.g. 'a', 'b', 'e')."""

    speed: float = 1.0
    """Playback speed multiplier, range 0.1 – 2.0."""

    output_format: str = "mp3"
    """Output audio container format."""

    subtitle_mode: str = "Disabled"
    """Subtitle generation mode."""

    save_option: str = "Save next to input file"
    """Save location strategy."""

    output_folder: Optional[str] = None
    """Absolute path when save_option is 'Choose output folder'."""

    char_count: int = 0
    """Pre-computed character count for ETR estimation."""

    replace_single_newlines: bool = True
    save_chapters_separately: Optional[bool] = None
    merge_chapters_at_end: Optional[bool] = None


@dataclass
class AppState:
    """
    Single source of truth for one Flet session.

    Instantiated once per ``ft.app()`` call on desktop, and once per browser
    tab on web.  All UI components receive a reference to this object and
    read/write it to keep themselves in sync.

    Thread-safety: mutation from background threads should be done via the
    provided ``_lock``.  The UI update callbacks (``on_log``,
    ``on_progress``, etc.) are always invoked on the Flet event loop via
    ``page.run_task()`` and must be set by the view layer.
    """

    # -----------------------------------------------------------------------
    # Runtime identity
    # -----------------------------------------------------------------------
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # -----------------------------------------------------------------------
    # Persisted user config (loaded once, written on every change)
    # -----------------------------------------------------------------------
    config: Dict[str, Any] = field(default_factory=_default_config)

    # -----------------------------------------------------------------------
    # File / input state
    # -----------------------------------------------------------------------
    selected_file: Optional[str] = None
    """Path to the processed text file (may be a temp cache copy for epub/pdf)."""

    selected_file_type: Optional[str] = None
    """'txt' | 'epub' | 'pdf' | 'markdown' | None"""

    selected_book_path: Optional[str] = None
    """Original epub/pdf path before being converted to txt."""

    displayed_file_path: Optional[str] = None
    """Path shown in the UI drop-zone (original book or txt file)."""

    selected_chapters: List[str] = field(default_factory=list)
    """Ordered list of selected chapter href tokens (or page numbers for PDFs)."""

    save_chapters_separately: Optional[bool] = None
    merge_chapters_at_end: Optional[bool] = None
    save_as_project: bool = False
    char_count: int = 0

    # -----------------------------------------------------------------------
    # Voice / language
    # -----------------------------------------------------------------------
    selected_voice: str = "af_heart"
    selected_lang: str = "a"
    selected_profile_name: Optional[str] = None
    mixed_voice_state: Optional[List[Any]] = None
    """List of [voice_id, weight] pairs when the formula mixer is in use."""

    # -----------------------------------------------------------------------
    # Conversion parameters
    # -----------------------------------------------------------------------
    speed: float = 1.0
    use_gpu: bool = True
    selected_format: str = "wav"
    subtitle_mode: str = "Sentence"
    subtitle_format: str = "ass_centered_narrow"
    replace_single_newlines: bool = True
    save_option: str = "Save next to input file"
    selected_output_folder: Optional[str] = None
    silence_duration: float = 2.0
    max_subtitle_words: int = 50
    separate_chapters_format: str = "wav"
    use_silent_gaps: bool = True
    subtitle_speed_method: str = "tts"
    use_spacy_segmentation: bool = True
    chunk_level: str = "paragraph"
    generate_epub3: bool = False

    # TTS provider
    tts_provider: str = "kokoro"
    supertonic_total_steps: int = 5

    # Chapter options
    chapter_intro_delay: float = 0.5
    read_title_intro: bool = False
    read_closing_outro: bool = True
    auto_prefix_chapter_titles: bool = True
    normalize_chapter_opening_caps: bool = True

    # Speaker analysis
    speaker_analysis_threshold: int = 3

    # Word substitutions
    word_substitutions_enabled: bool = False
    word_substitutions_list: str = ""
    case_sensitive_substitutions: bool = False
    replace_all_caps: bool = False
    replace_numerals: bool = False
    fix_nonstandard_punctuation: bool = False

    # -----------------------------------------------------------------------
    # Conversion runtime state
    # -----------------------------------------------------------------------
    is_converting: bool = False
    is_cancelled: bool = False
    progress: float = 0.0
    """Fractional progress 0.0 – 1.0."""
    etr_seconds: Optional[float] = None
    """Estimated seconds remaining, or None if unknown."""
    last_output_path: Optional[str] = None
    log_lines: List[str] = field(default_factory=list)
    """Buffered log messages, capped at LOG_MAX_LINES."""

    LOG_MAX_LINES: int = 2000

    # -----------------------------------------------------------------------
    # Queue
    # -----------------------------------------------------------------------
    queued_items: List[ConversionJob] = field(default_factory=list)
    current_queue_index: int = 0

    # -----------------------------------------------------------------------
    # Callbacks (set by the view layer, not serialised)
    # -----------------------------------------------------------------------
    on_log: Optional[Callable[[str, str], None]] = field(default=None, repr=False, compare=False)
    """Called from any thread: ``on_log(message, level)``."""

    on_progress: Optional[Callable[[float, Optional[float]], None]] = field(
        default=None, repr=False, compare=False
    )
    """Called from any thread: ``on_progress(fraction, etr_seconds)``."""

    on_conversion_finished: Optional[Callable[[str, Optional[str]], None]] = field(
        default=None, repr=False, compare=False
    )
    """Called from any thread: ``on_conversion_finished(message, output_path)``."""

    # -----------------------------------------------------------------------
    # Integrations
    # -----------------------------------------------------------------------
    audiobookshelf_enabled: bool = False
    audiobookshelf_base_url: str = ""
    audiobookshelf_api_token: str = ""
    audiobookshelf_library_id: str = ""
    audiobookshelf_folder_id: str = ""
    audiobookshelf_verify_ssl: bool = True
    audiobookshelf_auto_send: bool = False
    audiobookshelf_send_cover: bool = True
    audiobookshelf_send_chapters: bool = True
    audiobookshelf_send_subtitles: bool = False
    audiobookshelf_timeout: float = 30.0

    calibre_opds_enabled: bool = False
    calibre_opds_base_url: str = ""
    calibre_opds_username: str = ""
    calibre_opds_password: str = ""
    calibre_opds_verify_ssl: bool = True

    # -----------------------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------------------

    def load_from_config(self) -> None:
        """
        Populate all fields from the persisted JSON config file.

        Called once at startup and whenever the settings page is saved.
        Thread-safe.
        """
        with self._lock:
            cfg = _default_config()
            self.config = cfg

            self.selected_voice = cfg.get("selected_voice", "af_heart")
            self.selected_lang = self.selected_voice[0] if self.selected_voice else "a"
            self.selected_profile_name = cfg.get("selected_profile_name")
            self.speed = cfg.get("speed", 1.0)
            self.use_gpu = cfg.get("use_gpu", True)
            self.selected_format = cfg.get("selected_format", "wav")
            self.subtitle_mode = cfg.get("subtitle_mode", "Sentence")
            self.subtitle_format = cfg.get("subtitle_format", "ass_centered_narrow")
            self.replace_single_newlines = cfg.get("replace_single_newlines", True)
            self.save_option = cfg.get("save_option", "Save next to input file")
            self.selected_output_folder = cfg.get("selected_output_folder")
            self.silence_duration = cfg.get("silence_duration", 2.0)
            self.max_subtitle_words = cfg.get("max_subtitle_words", 50)
            self.separate_chapters_format = cfg.get("separate_chapters_format", "wav")
            self.use_silent_gaps = cfg.get("use_silent_gaps", True)
            self.subtitle_speed_method = cfg.get("subtitle_speed_method", "tts")
            self.use_spacy_segmentation = cfg.get("use_spacy_segmentation", True)
            self.chunk_level = cfg.get("chunk_level", "paragraph")
            self.generate_epub3 = cfg.get("generate_epub3", False)
            self.tts_provider = cfg.get("tts_provider", "kokoro")
            self.supertonic_total_steps = cfg.get("supertonic_total_steps", 5)
            self.chapter_intro_delay = cfg.get("chapter_intro_delay", 0.5)
            self.read_title_intro = cfg.get("read_title_intro", False)
            self.read_closing_outro = cfg.get("read_closing_outro", True)
            self.auto_prefix_chapter_titles = cfg.get("auto_prefix_chapter_titles", True)
            self.normalize_chapter_opening_caps = cfg.get("normalize_chapter_opening_caps", True)
            self.speaker_analysis_threshold = cfg.get("speaker_analysis_threshold", 3)
            self.word_substitutions_enabled = cfg.get("word_substitutions_enabled", False)
            self.word_substitutions_list = cfg.get("word_substitutions_list", "")
            self.case_sensitive_substitutions = cfg.get("case_sensitive_substitutions", False)
            self.replace_all_caps = cfg.get("replace_all_caps", False)
            self.replace_numerals = cfg.get("replace_numerals", False)
            self.fix_nonstandard_punctuation = cfg.get("fix_nonstandard_punctuation", False)

            # Integrations
            integrations: Dict[str, Any] = cfg.get("integrations", {})
            abs_cfg = integrations.get("audiobookshelf", {})
            self.audiobookshelf_enabled = bool(abs_cfg.get("enabled", False))
            self.audiobookshelf_base_url = str(abs_cfg.get("base_url", ""))
            self.audiobookshelf_api_token = str(abs_cfg.get("api_token", ""))
            self.audiobookshelf_library_id = str(abs_cfg.get("library_id", ""))
            self.audiobookshelf_folder_id = str(abs_cfg.get("folder_id", ""))
            self.audiobookshelf_verify_ssl = bool(abs_cfg.get("verify_ssl", True))
            self.audiobookshelf_auto_send = bool(abs_cfg.get("auto_send", False))
            self.audiobookshelf_send_cover = bool(abs_cfg.get("send_cover", True))
            self.audiobookshelf_send_chapters = bool(abs_cfg.get("send_chapters", True))
            self.audiobookshelf_send_subtitles = bool(abs_cfg.get("send_subtitles", False))
            self.audiobookshelf_timeout = float(abs_cfg.get("timeout", 30.0))

            cal_cfg = integrations.get("calibre_opds", {})
            self.calibre_opds_enabled = bool(cal_cfg.get("enabled", False))
            self.calibre_opds_base_url = str(cal_cfg.get("base_url", ""))
            self.calibre_opds_username = str(cal_cfg.get("username", ""))
            self.calibre_opds_password = str(cal_cfg.get("password", ""))
            self.calibre_opds_verify_ssl = bool(cal_cfg.get("verify_ssl", True))

    def persist_config(self) -> None:
        """
        Write the current config snapshot back to disk.

        Only the fields that map to the JSON config are written; runtime state
        (progress, log_lines, callbacks) is not persisted.
        Thread-safe.
        """
        with self._lock:
            cfg = self.config.copy()
            cfg["selected_voice"] = self.selected_voice
            cfg["selected_profile_name"] = self.selected_profile_name
            cfg["speed"] = self.speed
            cfg["use_gpu"] = self.use_gpu
            cfg["selected_format"] = self.selected_format
            cfg["subtitle_mode"] = self.subtitle_mode
            cfg["subtitle_format"] = self.subtitle_format
            cfg["replace_single_newlines"] = self.replace_single_newlines
            cfg["save_option"] = self.save_option
            cfg["selected_output_folder"] = self.selected_output_folder
            cfg["silence_duration"] = self.silence_duration
            cfg["max_subtitle_words"] = self.max_subtitle_words
            cfg["separate_chapters_format"] = self.separate_chapters_format
            cfg["use_silent_gaps"] = self.use_silent_gaps
            cfg["subtitle_speed_method"] = self.subtitle_speed_method
            cfg["use_spacy_segmentation"] = self.use_spacy_segmentation
            cfg["chunk_level"] = self.chunk_level
            cfg["generate_epub3"] = self.generate_epub3
            cfg["tts_provider"] = self.tts_provider
            cfg["supertonic_total_steps"] = self.supertonic_total_steps
            cfg["chapter_intro_delay"] = self.chapter_intro_delay
            cfg["read_title_intro"] = self.read_title_intro
            cfg["read_closing_outro"] = self.read_closing_outro
            cfg["auto_prefix_chapter_titles"] = self.auto_prefix_chapter_titles
            cfg["normalize_chapter_opening_caps"] = self.normalize_chapter_opening_caps
            cfg["speaker_analysis_threshold"] = self.speaker_analysis_threshold
            cfg["word_substitutions_enabled"] = self.word_substitutions_enabled
            cfg["word_substitutions_list"] = self.word_substitutions_list
            cfg["case_sensitive_substitutions"] = self.case_sensitive_substitutions
            cfg["replace_all_caps"] = self.replace_all_caps
            cfg["replace_numerals"] = self.replace_numerals
            cfg["fix_nonstandard_punctuation"] = self.fix_nonstandard_punctuation
            # Integrations
            cfg.setdefault("integrations", {})
            cfg["integrations"]["audiobookshelf"] = {
                "enabled": self.audiobookshelf_enabled,
                "base_url": self.audiobookshelf_base_url,
                "api_token": self.audiobookshelf_api_token,
                "library_id": self.audiobookshelf_library_id,
                "folder_id": self.audiobookshelf_folder_id,
                "verify_ssl": self.audiobookshelf_verify_ssl,
                "auto_send": self.audiobookshelf_auto_send,
                "send_cover": self.audiobookshelf_send_cover,
                "send_chapters": self.audiobookshelf_send_chapters,
                "send_subtitles": self.audiobookshelf_send_subtitles,
                "timeout": self.audiobookshelf_timeout,
            }
            cfg["integrations"]["calibre_opds"] = {
                "enabled": self.calibre_opds_enabled,
                "base_url": self.calibre_opds_base_url,
                "username": self.calibre_opds_username,
                "password": self.calibre_opds_password,
                "verify_ssl": self.calibre_opds_verify_ssl,
            }
            self.config = cfg
            try:
                save_config(cfg)
            except Exception:
                pass

    def append_log(self, message: str, level: str = "info") -> None:
        """
        Thread-safely append a log line and trigger the UI callback.

        Caps the internal buffer at ``LOG_MAX_LINES`` to prevent unbounded
        memory growth during very long conversion tasks.
        """
        with self._lock:
            self.log_lines.append(f"[{level.upper()}] {message}")
            if len(self.log_lines) > self.LOG_MAX_LINES:
                # Trim oldest 10 % to amortise the cost of trimming
                trim = self.LOG_MAX_LINES // 10
                self.log_lines = self.log_lines[trim:]

        cb = self.on_log
        if cb is not None:
            try:
                cb(message, level)
            except Exception:
                pass

    def update_progress(self, fraction: float, etr: Optional[float] = None) -> None:
        """
        Update fractional progress and ETR, then notify the UI callback.

        Args:
            fraction: Value in [0.0, 1.0].
            etr: Estimated seconds remaining, or None.
        """
        with self._lock:
            self.progress = max(0.0, min(1.0, fraction))
            self.etr_seconds = etr

        cb = self.on_progress
        if cb is not None:
            try:
                cb(fraction, etr)
            except Exception:
                pass

    def get_voice_formula(self) -> str:
        """
        Return the effective voice formula string.

        Uses the mixed_voice_state if the formula mixer is active, otherwise
        returns the raw selected_voice.
        """
        if self.mixed_voice_state:
            parts = [f"{name}*{weight}" for name, weight in self.mixed_voice_state]
            return " + ".join(filter(None, parts))
        return self.selected_voice or "af_heart"

    def reset_file_state(self) -> None:
        """Clear all file-related fields without touching voice/settings."""
        with self._lock:
            self.selected_file = None
            self.selected_file_type = None
            self.selected_book_path = None
            self.displayed_file_path = None
            self.selected_chapters = []
            self.save_chapters_separately = None
            self.merge_chapters_at_end = None
            self.save_as_project = False
            self.char_count = 0

    def reset_conversion_state(self) -> None:
        """Clear all runtime conversion fields to start fresh."""
        with self._lock:
            self.is_converting = False
            self.is_cancelled = False
            self.progress = 0.0
            self.etr_seconds = None
            self.last_output_path = None
            self.log_lines = []
