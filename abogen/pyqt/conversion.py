import os
import re
import time
import hashlib  # For generating unique cache filenames
from platformdirs import user_desktop_dir
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QVBoxLayout, QDialog, QLabel, QDialogButtonBox
from contextlib import ExitStack, contextmanager
import numpy as np
import soundfile as sf
from abogen.utils import (
    create_process,
    get_user_cache_path,
    detect_encoding,
)
from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    COLORS,
    CHAPTER_OPTIONS_COUNTDOWN,
    SUBTITLE_FORMATS,
    SUPPORTED_SOUND_FORMATS,
    SUPPORTED_SUBTITLE_FORMATS,
)
from abogen.infrastructure.subtitle_writer import make_subtitle_writer, resolve_subtitle_format
from abogen.domain.split_pattern import get_split_pattern
from abogen.domain.subtitle_processor import (
    parse_subtitle_file,
    process_subtitle_entries,
)
from abogen.domain.output_paths import (
    resolve_output_directory,
    build_output_path,
    sanitize_output_stem,
    sanitize_filename_for_chapter,
    resolve_unique_path,
)
from abogen.domain.audio_helpers import build_ffmpeg_command, to_float32
from abogen.domain.audio_sink import AudioSink, open_audio_sink
from abogen.domain.conversion_engine import synthesize_text, SegmentStats, SegmentInfo
from abogen.domain.intro_outro import resolve_intro, resolve_outro
from abogen.domain.audio_buffer import (
    create_silence,
    mix_audio,
    normalize_audio,
    SAMPLE_RATE,
)
from abogen.domain.subtitle_generation import process_subtitle_tokens
from abogen.domain.voice_loader import VoiceCache, load_voice_cached, resolve_voice
from abogen.domain.progress import calc_etr_str
from abogen.domain.normalization import TTSContext
from abogen.domain.pronunciation import (
    compile_pronunciation_rules,
    compile_heteronym_sentence_rules,
    merge_pronunciation_overrides,
)
from abogen.domain.metadata_extraction import (
    extract_metadata_and_build_args,
    extract_metadata_from_text,
    read_text_for_metadata,
)
from abogen.domain.text_chapters import parse_chapters_from_text
from abogen.infrastructure.exporters import ExportService
import abogen.hf_tracker as hf_tracker
import static_ffmpeg
import threading  # for efficient waiting
import subprocess



def _extract_metadata_dict(file_name: str, is_direct_text: bool) -> dict:
    """Extract metadata dict from file for intro/outro text building."""
    try:
        from abogen.domain.metadata_extraction import read_text_for_metadata, extract_metadata_from_text
        text = read_text_for_metadata(
            file_path=file_name,
            is_direct_text=is_direct_text,
            direct_text=file_name if is_direct_text else None,
        )
        if text:
            return extract_metadata_from_text(text) or {}
    except Exception:
        pass
    return {}


# Configuration constants
_USER_RESPONSE_TIMEOUT = (
    0.1  # Timeout in seconds for checking user response/cancellation
)

from abogen.subtitle_utils import (
    clean_text,
    detect_timestamps_in_text,
    get_sample_voice_text,
    sanitize_name_for_os,
    split_text_by_voice_markers
)

class CountdownDialog(QDialog):
    """Base dialog with auto-accept countdown functionality"""

    def __init__(self, title, countdown_seconds, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowCloseButtonHint
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self.countdown_seconds = countdown_seconds
        self.layout = QVBoxLayout(self)
        self._timer = None
        self._button_box = None

    def add_countdown_and_buttons(self):
        """Add countdown label and OK button - call this after adding custom content"""
        self.countdown_label = QLabel(
            f"Auto-accepting in {self.countdown_seconds} seconds..."
        )
        self.countdown_label.setStyleSheet(f"color: {COLORS['GREEN']};")
        self.layout.addWidget(self.countdown_label)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self._button_box.accepted.connect(self.accept)
        self.layout.addWidget(self._button_box)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(1000)

    def _on_timer_tick(self):
        self.countdown_seconds -= 1
        if self.countdown_seconds > 0:
            self.countdown_label.setText(
                f"Auto-accepting in {self.countdown_seconds} seconds..."
            )
        else:
            self._timer.stop()
            self._button_box.accepted.emit()

    def closeEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)


class ChapterOptionsDialog(CountdownDialog):
    def __init__(self, chapter_count, parent=None):
        super().__init__("Chapter Options", CHAPTER_OPTIONS_COUNTDOWN, parent)

        self.layout.addWidget(
            QLabel(f"Detected {chapter_count} chapters in the text file.")
        )
        self.layout.addWidget(QLabel("How would you like to process these chapters?"))

        self.save_separately_checkbox = QCheckBox("Save each chapter separately")
        self.merge_at_end_checkbox = QCheckBox("Create a merged version at the end")

        self.save_separately_checkbox.setChecked(False)
        self.merge_at_end_checkbox.setChecked(True)

        self.save_separately_checkbox.stateChanged.connect(
            self.update_merge_checkbox_state
        )

        self.layout.addWidget(self.save_separately_checkbox)
        self.layout.addWidget(self.merge_at_end_checkbox)

        self.add_countdown_and_buttons()
        self.update_merge_checkbox_state()

    def update_merge_checkbox_state(self):
        self.merge_at_end_checkbox.setEnabled(self.save_separately_checkbox.isChecked())

    def get_options(self):
        return {
            "save_chapters_separately": self.save_separately_checkbox.isChecked(),
            "merge_chapters_at_end": self.merge_at_end_checkbox.isChecked()
            and self.merge_at_end_checkbox.isEnabled(),
        }


class TimestampDetectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Timestamps Detected")
        self.setMinimumWidth(350)
        self.use_timestamps_result = True
        self.countdown_seconds = CHAPTER_OPTIONS_COUNTDOWN

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("This file contains timestamps in HH:MM:SS format."))
        layout.addWidget(
            QLabel("Do you want to use these timestamps for precise audio timing?")
        )

        yes_label = QLabel(
            "• Yes: Generate audio that matches each timestamp (subtitle mode will be ignored)"
        )
        yes_label.setStyleSheet(f"color: {COLORS['BLUE_BORDER_HOVER']};")
        layout.addWidget(yes_label)

        no_label = QLabel("• No: Ignore timestamps and process as regular text")
        no_label.setStyleSheet(f"color: {COLORS['ORANGE']};")
        layout.addWidget(no_label)

        # Countdown label
        self.countdown_label = QLabel(
            f"Auto-accepting in {self.countdown_seconds} seconds..."
        )
        self.countdown_label.setStyleSheet(f"color: {COLORS['GREEN']};")
        layout.addWidget(self.countdown_label)

        button_box = QDialogButtonBox()
        yes_button = button_box.addButton("Yes", QDialogButtonBox.ButtonRole.AcceptRole)
        no_button = button_box.addButton("No", QDialogButtonBox.ButtonRole.RejectRole)

        yes_button.clicked.connect(lambda: self._set_result(True))
        no_button.clicked.connect(lambda: self._set_result(False))

        layout.addWidget(button_box)

        # Timer for countdown
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(1000)

    def _on_timer_tick(self):
        self.countdown_seconds -= 1
        if self.countdown_seconds > 0:
            self.countdown_label.setText(
                f"Auto-accepting in {self.countdown_seconds} seconds..."
            )
        else:
            self._timer.stop()
            self._set_result(True)

    def _set_result(self, use_timestamps):
        if self._timer:
            self._timer.stop()
        self.use_timestamps_result = use_timestamps
        self.accept()

    def use_timestamps(self):
        return self.use_timestamps_result


class ConversionThread(QThread):
    progress_updated = pyqtSignal(int, str)  # Add str for ETR
    conversion_finished = pyqtSignal(object, object)  # Pass output path as second arg
    log_updated = pyqtSignal(object)  # Updated signal for log updates
    chapters_detected = pyqtSignal(int)  # Signal for chapter detection

    # Punctuation constants for unified handling across languages
    PUNCTUATION_SENTENCE = ".!?।。！？"
    PUNCTUATION_SENTENCE_COMMA = ".!?,।。！？、，"
    PUNCTUATION_COMMAS = ",，、"

    def __init__(
        self,
        file_name,
        lang_code,
        speed,
        voice,
        save_option,
        output_folder,
        subtitle_mode,
        output_format,
        backend,
        start_time,
        total_char_count,
        use_gpu=True,
        from_queue=False,
        save_base_path=None,
    ):  # Add use_gpu parameter
        super().__init__()
        self._chapter_options_event = threading.Event()
        self._timestamp_response_event = threading.Event()
        self.backend = backend
        self.file_name = file_name
        self.lang_code = lang_code
        self.speed = speed
        self.voice = voice
        self.save_option = save_option
        self.output_folder = output_folder
        self.subtitle_mode = subtitle_mode
        self.cancel_requested = False
        self.should_cancel = False
        self.process = None
        self.output_format = output_format
        self.from_queue = from_queue
        self.start_time = start_time  # Store start_time
        self.total_char_count = total_char_count  # Use passed total character count
        self.processed_char_count = 0  # Initialize processed character count
        self.display_path = None  # Add variable for display path
        self.save_base_path = save_base_path  # Store the save base path
        self.is_direct_text = (
            False  # Flag to indicate if input is from textbox rather than file
        )
        self.chapter_options_set = False
        self.waiting_for_user_input = False
        self.use_gpu = use_gpu  # Store the GPU setting
        self.max_subtitle_words = 50  # Default value, will be overridden from GUI
        self.silence_duration = 2.0  # Default value, will be overridden from GUI
        self.use_spacy_segmentation = True  # Default, will be overridden from GUI
        self.read_title_intro = False  # Will be overridden from GUI
        self.read_closing_outro = True  # Will be overridden from GUI
        # Set split pattern based on language and subtitle mode
        self.split_pattern = get_split_pattern(lang_code, subtitle_mode)
        self.voice_cache = VoiceCache()  # Cache for loaded voices

    def load_voice_cached(self, voice_name, tts):
        """Load voice with caching to avoid reloading same voice.

        Args:
            voice_name: Voice name or formula string
            tts: TTS pipeline instance

        Returns:
            Loaded voice tensor or voice name string
        """
        return load_voice_cached(
            voice_name=voice_name,
            pipeline=tts,
            use_gpu=self.use_gpu,
            cache=self.voice_cache,
        )

    def _stream_audio_in_chunks(
        self, segments, process_func, progress_prefix="Processing"
    ):
        """
        Process audio segments in memory-efficient chunks

        Args:
            segments: List of audio segments to process
            process_func: Function that takes (segment_bytes, is_last) and processes a chunk
            progress_prefix: Prefix for progress messages

        Returns:
            Total samples processed
        """
        # Calculate total size for progress reporting
        total_samples = sum(len(segment) for segment in segments)
        samples_processed = 0

        self.log_updated.emit((f"\n{progress_prefix} segments...", "grey"))

        # Stream each segment individually
        for i, segment in enumerate(segments):
            try:
                segment_bytes = to_float32(segment).tobytes()
                is_last = i == len(segments) - 1

                # Update progress periodically - skip if there's only one segment
                if (i % 20 == 0 or is_last) and len(segments) > 1:
                    progress_percent = int((samples_processed / total_samples) * 100)
                    self.log_updated.emit(
                        f"{progress_prefix} segment {i+1}/{len(segments)} ({progress_percent}% complete)"
                    )

                # Process this segment
                process_func(segment_bytes, is_last)

                # Update samples processed
                samples_processed += len(segment)

                # Clear segment bytes from memory
                del segment_bytes
            except Exception as e:
                self.log_updated.emit(
                    (f"Error processing segment {i}: {str(e)}", "red")
                )
                raise

        return samples_processed

    def run(self):
        print(
            f"\nVoice: {self.voice}\nLanguage: {self.lang_code}\nSpeed: {self.speed}\nGPU: {self.use_gpu}\nFile: {self.file_name}\nSubtitle mode: {self.subtitle_mode}\nOutput format: {self.output_format}\nSave option: {self.save_option}\n"
        )
        try:
            hf_tracker.set_log_callback(lambda msg: self.log_updated.emit(msg))
            sink_stack = ExitStack()
            # Show configuration
            self.log_updated.emit("Configuration:")

            # Determine input file and processing file
            if getattr(self, "from_queue", False):
                input_file = self.save_base_path or self.file_name
                processing_file = self.file_name
            else:
                input_file = self.display_path if self.display_path else self.file_name
                processing_file = self.file_name

            # Normalize paths for consistent display (fixes Windows path separator issues)
            input_file = os.path.normpath(input_file) if input_file else input_file
            processing_file = (
                os.path.normpath(processing_file)
                if processing_file
                else processing_file
            )

            self.log_updated.emit(f"- Input File: {input_file}")
            if input_file != processing_file:
                self.log_updated.emit(f"- Processing File: {processing_file}")

            # Use file_name for logs if from_queue, otherwise use display_path if available
            if getattr(self, "from_queue", False):
                base_path = (
                    self.save_base_path or self.file_name
                )  # Use save_base_path if available
            else:
                base_path = self.display_path if self.display_path else self.file_name

            # Use file size string passed from GUI
            if hasattr(self, "file_size_str"):
                self.log_updated.emit(f"- File size: {self.file_size_str}")

            self.log_updated.emit(f"- Total characters: {int(self.total_char_count):,}")

            self.log_updated.emit(
                f"- Language: {self.lang_code} ({LANGUAGE_DESCRIPTIONS.get(self.lang_code, 'Unknown')})"
            )
            self.log_updated.emit(f"- Voice: {self.voice}")
            self.log_updated.emit(f"- Speed: {self.speed}")
            self.log_updated.emit(f"- Subtitle mode: {self.subtitle_mode}")
            self.log_updated.emit(f"- Output format: {self.output_format}")
            self.log_updated.emit(
                f"- Subtitle format: {next((label for value, label in SUBTITLE_FORMATS if value == getattr(self, 'subtitle_format', 'srt')), getattr(self, 'subtitle_format', 'srt'))}"
            )
            self.log_updated.emit(
                f"- Use spaCy for sentence segmentation: {'Yes' if getattr(self, 'use_spacy_segmentation', False) else 'No'}"
            )
            self.log_updated.emit(f"- Save option: {self.save_option}")
            if self.replace_single_newlines:
                self.log_updated.emit(f"- Replace single newlines: Yes")

            # Check if input is a subtitle file for additional configuration
            is_subtitle_input = False
            if not self.is_direct_text and self.file_name:
                file_ext = os.path.splitext(self.file_name)[1].lower()
                if file_ext in [".srt", ".ass", ".vtt"]:
                    is_subtitle_input = True

            # Display subtitle-specific options if processing subtitle file
            if is_subtitle_input:
                if getattr(self, "use_silent_gaps", False):
                    self.log_updated.emit("- Use silent gaps: Yes")
                speed_method = getattr(self, "subtitle_speed_method", "tts")
                method_label = (
                    "TTS Regeneration"
                    if speed_method == "tts"
                    else "FFmpeg Time-stretch"
                )
                self.log_updated.emit(f"- Speed adjustment method: {method_label}")

            # Display save_chapters_separately flag if it's set
            if hasattr(self, "save_chapters_separately"):
                self.log_updated.emit(
                    (
                        f"- Save chapters separately: {'Yes' if self.save_chapters_separately else 'No'}"
                    )
                )
                # Display merge_chapters_at_end flag if save_chapters_separately is True
                if self.save_chapters_separately:
                    merge_at_end = getattr(self, "merge_chapters_at_end", True)
                    self.log_updated.emit(
                        f"- Merge chapters at the end: {'Yes' if merge_at_end else 'No'}"
                    )
                    # Display the separate chapters format if it's set
                    separate_format = getattr(self, "separate_chapters_format", "wav")
                    self.log_updated.emit(
                        f"- Separate chapters format: {separate_format}"
                    )

            # If merge_at_end is True, display the silence duration
            if getattr(self, "merge_chapters_at_end", True):
                self.log_updated.emit(
                    f"- Silence between chapters: {self.silence_duration} seconds"
                )

            if self.save_option == "Choose output folder":
                self.log_updated.emit(
                    f"- Output folder: {self.output_folder or os.getcwd()}"
                )

            self.log_updated.emit(("\nInitializing TTS pipeline...", "grey"))

            # Check if the input is a subtitle file or timestamp text file
            is_subtitle_file = False
            is_timestamp_text = False
            if not self.is_direct_text and self.file_name:
                file_ext = os.path.splitext(self.file_name)[1].lower()
                if file_ext in [".srt", ".ass", ".vtt"]:
                    is_subtitle_file = True
                    self.log_updated.emit(
                        f"\nDetected subtitle file format: {file_ext}"
                    )
                elif file_ext == ".txt" and detect_timestamps_in_text(self.file_name):
                    is_timestamp_text = True
                    self.log_updated.emit(
                        ("\nDetected timestamps in text file", "grey")
                    )
                    # Signal to ask user (-1 indicates timestamp detection)
                    self.chapters_detected.emit(-1)
                    # Wait for user response using event with timeout for responsive cancellation
                    while not self._timestamp_response_event.wait(
                        timeout=_USER_RESPONSE_TIMEOUT
                    ):
                        if self.cancel_requested:
                            self.conversion_finished.emit("Cancelled", None)
                            return
                    # Check cancellation one more time after event is set
                    if self.cancel_requested:
                        self.conversion_finished.emit("Cancelled", None)
                        return
                    if not self._timestamp_response:
                        is_timestamp_text = False
                    delattr(self, "_timestamp_response")
                    self._timestamp_response_event.clear()

            # Process subtitle files separately
            if is_subtitle_file or is_timestamp_text:
                self._process_subtitle_file(self.backend, base_path, is_timestamp_text)
                return

            if self.is_direct_text:
                text = self.file_name  # Treat file_name as direct text input
            else:
                encoding = detect_encoding(self.file_name)
                with open(
                    self.file_name, "r", encoding=encoding, errors="replace"
                ) as file:
                    text = file.read()

            # Clean up text using utility function
            text = clean_text(text)

            # Apply word substitutions if enabled
            if getattr(self, "word_substitutions_enabled", False):
                from abogen.word_substitution import apply_word_substitutions

                self.log_updated.emit("Applying word substitutions...")

                substitutions_list = getattr(self, "word_substitutions_list", "")
                case_sensitive = getattr(self, "case_sensitive_substitutions", False)
                replace_caps = getattr(self, "replace_all_caps", False)
                replace_nums = getattr(self, "replace_numerals", False)
                fix_punct = getattr(self, "fix_nonstandard_punctuation", False)

                text = apply_word_substitutions(
                    text,
                    substitutions_list,
                    case_sensitive,
                    replace_caps,
                    replace_nums,
                    fix_punct,
                )

            # --- Compile normalization rules (heteronym + pronunciation) ---
            from abogen.domain.normalization import TTSContext
            pronunciation_overrides = merge_pronunciation_overrides(
                getattr(self, "pronunciation_overrides", None),
                getattr(self, "manual_overrides", None),
            )
            self._tts_context = TTSContext(
                split_pattern=self.split_pattern,
                pronunciation_rules=compile_pronunciation_rules(pronunciation_overrides),
                heteronym_rules=compile_heteronym_sentence_rules(
                    getattr(self, "heteronym_overrides", None)
                ),
                normalization_overrides=getattr(self, "normalization_overrides", None),
            )

            # --- Chapter splitting logic ---
            chapters = parse_chapters_from_text(text, clean=False)
            total_chapters = len(chapters)

            # --- Voice marker splitting logic ---
            # Split each chapter by voice markers, preserving voice state across chapters
            chapters_with_voices = []
            current_voice = self.voice  # Start with default voice
            total_valid_markers = 0
            total_invalid_markers = 0

            for chapter_name, chapter_text in chapters:
                # Use current_voice as the starting voice for this chapter
                voice_segments, last_voice, valid_count, invalid_count = split_text_by_voice_markers(chapter_text, current_voice)
                chapters_with_voices.append((chapter_name, voice_segments))

                # Update current_voice so next chapter continues with this voice
                current_voice = last_voice

                # Track total valid/invalid markers
                total_valid_markers += valid_count
                total_invalid_markers += invalid_count

            # Log voice marker information with accurate counts
            total_markers = total_valid_markers + total_invalid_markers
            if total_markers > 0:
                if total_invalid_markers == 0:
                    # All markers were valid
                    self.log_updated.emit(
                        (f"\nDetected {total_markers} voice marker(s) - all valid", "grey")
                    )
                else:
                    # Some markers were invalid
                    self.log_updated.emit(
                        (f"\nDetected {total_markers} voice marker(s) - {total_valid_markers} valid, {total_invalid_markers} invalid (using previous voice)", "orange")
                    )

            # Replace chapters with the new structure
            chapters = chapters_with_voices

            # For text files with chapters, prompt user for options if not already set
            is_txt_file = not self.is_direct_text and (
                self.file_name.lower().endswith(".txt")
                or (self.display_path and self.display_path.lower().endswith(".txt"))
            )

            if (
                is_txt_file
                and total_chapters > 1
                and (
                    not hasattr(self, "save_chapters_separately")
                    or not hasattr(self, "merge_chapters_at_end")
                )
                and not self.chapter_options_set
            ):

                # Emit signal to main thread and wait
                self.chapters_detected.emit(total_chapters)
                self._chapter_options_event.wait()
                if self.cancel_requested:
                    self.conversion_finished.emit("Cancelled", None)
                    return
                self.chapter_options_set = True

            # Log all detected chapters at the beginning
            if total_chapters > 1:
                chapter_list = "\n".join(
                    [f"{i+1}) {c[0]}" for i, c in enumerate(chapters)]
                )
                self.log_updated.emit(
                    (f"\nDetected chapters ({total_chapters}):\n" + chapter_list)
                )
            else:
                self.log_updated.emit((f"\nProcessing {chapters[0][0]}...", "grey"))

            # If save_chapters_separately is enabled, find a unique suffix ONCE and use for both folder and merged file
            save_chapters_separately = getattr(self, "save_chapters_separately", False)
            merge_chapters_at_end = getattr(self, "merge_chapters_at_end", True)

            # Ensure merge_chapters_at_end is True if not saving chapters separately
            if not save_chapters_separately:
                merge_chapters_at_end = True

            chapters_out_dir = None
            suffix = ""

            # Use file_name for logs if from_queue, otherwise use display_path if available
            if getattr(self, "from_queue", False):
                base_path = (
                    self.save_base_path or self.file_name
                )  # Use save_base_path if available
            else:
                base_path = self.display_path if self.display_path else self.file_name

            base_name = os.path.splitext(os.path.basename(base_path))[0]
            sanitized_base_name = sanitize_name_for_os(base_name, is_folder=True)

            parent_dir = resolve_output_directory(
                save_mode=self.save_option,
                stored_path=Path(base_path),
                output_folder=getattr(self, "output_folder", None),
                desktop_dir=Path(user_desktop_dir()),
                user_output_path=None,
                user_cache_outputs=Path(os.getcwd()),
            )
            parent_dir = str(parent_dir)
            # Ensure the output folder exists, error if it doesn't
            if not os.path.exists(parent_dir):
                self.log_updated.emit(
                    (
                        f"Output folder does not exist: {parent_dir}",
                        "red",
                    )
                )
            # Find a unique suffix for both folder and merged file, always
            counter = 1
            allowed_exts = set(SUPPORTED_SOUND_FORMATS + SUPPORTED_SUBTITLE_FORMATS)
            while True:
                suffix = f"_{counter}" if counter > 1 else ""
                chapters_out_dir_candidate = os.path.join(
                    parent_dir, f"{sanitized_base_name}{suffix}_chapters"
                )
                # Only check for files with allowed extensions (extension without dot, case-insensitive)
                # Use generator expression to avoid processing all files upfront
                file_parts = (
                    os.path.splitext(fname) for fname in os.listdir(parent_dir)
                )
                clash = any(
                    name == f"{sanitized_base_name}{suffix}"
                    and ext[1:].lower() in allowed_exts
                    for name, ext in file_parts
                )
                if not os.path.exists(chapters_out_dir_candidate) and not clash:
                    break
                counter += 1
            if save_chapters_separately and total_chapters > 1:
                separate_chapters_format = getattr(
                    self, "separate_chapters_format", "wav"
                )
                chapters_out_dir = chapters_out_dir_candidate
                os.makedirs(chapters_out_dir, exist_ok=True)
                self.log_updated.emit(
                    (f"\nChapters output folder: {chapters_out_dir}", "grey")
                )

            # Prepare merged output file for incremental writing ONLY if merge_chapters_at_end is True
            if merge_chapters_at_end:
                out_dir = parent_dir
                base_filepath_no_ext = os.path.join(
                    out_dir, f"{sanitized_base_name}{suffix}"
                )
                merged_out_path = f"{base_filepath_no_ext}.{self.output_format}"
                subtitle_entries = []
                current_time = 0.0
                rate = 24000
                subtitle_mode = self.subtitle_mode
                self.etr_start_time = time.time()
                self.processed_char_count = 0
                current_segment = 0
                chapters_time = [
                    {"chapter": chapter[0], "start": 0.0, "end": 0.0}
                    for chapter in chapters
                ]
                # Prepare output file/ffmpeg process for merged output
                merged_sink = sink_stack.enter_context(
                    self._open_merged_sink(
                        merged_out_path,
                        cancel_check=lambda: self.cancel_requested,
                    )
                )
                # Open merged subtitle file for incremental writing if needed
                merged_subtitle_writer = None
                merged_subtitle_path = None
                if self.subtitle_mode != "Disabled":
                    subtitle_format = getattr(self, "subtitle_format", "srt")
                    extension, _ = resolve_subtitle_format(subtitle_format, self.subtitle_mode)
                    merged_subtitle_path = (
                        os.path.splitext(merged_out_path)[0] + f".{extension}"
                    )
                    merged_subtitle_writer = make_subtitle_writer(
                        Path(merged_subtitle_path),
                        subtitle_format,
                        self.subtitle_mode,
                        max_words=self.max_subtitle_words,
                    )
                    if merged_subtitle_writer:
                        merged_subtitle_writer.open()
                else:
                    merged_subtitle_path = None
                    merged_subtitle_writer = None
            else:
                # If not merging, set merged_sink and related variables to None
                merged_sink = None
                merged_out_path = None
                subtitle_entries = []
                current_time = 0.0
                rate = 24000
                subtitle_mode = self.subtitle_mode
                self.etr_start_time = time.time()
                self.processed_char_count = 0
                current_segment = 0
                chapters_time = [
                    {"chapter": chapter[0], "start": 0.0, "end": 0.0}
                    for chapter in chapters
                ]

            # --- Intro synthesis ---
            intro_emitted = False
            if merge_chapters_at_end:
                intro_spec = resolve_intro(
                    _extract_metadata_dict(self.file_name, self.is_direct_text),
                    os.path.basename(self.file_name) if self.file_name else "",
                    getattr(self, "read_title_intro", False),
                    self.voice, self.voice, list(self.voice_cache._cache.keys()),
                )
                if intro_spec.enabled:
                    self.log_updated.emit((f"Title intro: {intro_spec.text[:80]}", "grey"))
                    loaded_intro_voice = self.load_voice_cached(intro_spec.voice_spec, self.backend)
                    intro_stats = SegmentStats(
                        processed_chars=self.processed_char_count,
                        current_time=current_time,
                        etr_start_time=self.etr_start_time,
                        total_characters=self.total_char_count,
                    )
                    run_tts_segment_loop(
                        text=intro_spec.text,
                        backend=self.backend,
                        voice=loaded_intro_voice,
                        speed=self.speed,
                        split_pattern=self.split_pattern,
                        stats=intro_stats,
                        check_cancel=lambda: self.cancel_requested,
                        on_progress=lambda pct, etr: self.progress_updated.emit(pct, etr),
                        chapter_sink=None,
                        audio_sink=merged_sink,
                    )
                    self.processed_char_count = intro_stats.processed_chars
                    current_time = intro_stats.current_time
                    intro_emitted = True
                    self.log_updated.emit(("Intro synthesized.", "grey"))

            # Instead of processing the whole text, process by chapter
            for chapter_idx, (chapter_name, voice_segments) in enumerate(chapters, 1):
                chapter_out_path = None
                chapter_sink = None
                chapter_subtitle_writer = None
                chapter_subtitle_path = None
                if total_chapters > 1:
                    self.log_updated.emit(
                        (
                            f"\nChapter {chapter_idx}/{total_chapters}: {chapter_name}",
                            "blue",
                        )
                    )
                chapter_subtitle_entries = []
                chapter_current_time = 0.0
                # Set chapter start time before processing
                chapter_time = chapters_time[chapter_idx - 1]
                if merge_chapters_at_end:
                    chapter_time["start"] = current_time

                # Prepare per-chapter output file if needed
                if save_chapters_separately and total_chapters > 1:
                    chapter_filename = sanitize_filename_for_chapter(chapter_name, chapter_idx)
                    chapter_out_path = os.path.join(
                        chapters_out_dir,
                        f"{chapter_filename}.{separate_chapters_format}",
                    )
                    if separate_chapters_format in ("wav", "flac", "mp3", "opus"):
                        chapter_sink = sink_stack.enter_context(open_audio_sink(
                            Path(chapter_out_path),
                            separate_chapters_format,
                            cancel_check=lambda: self.cancel_requested,
                        ))
                    else:
                        self.log_updated.emit(
                            (
                                f"Unsupported chapter format: {separate_chapters_format}",
                                "red",
                            )
                        )
                        continue
                    if self.subtitle_mode != "Disabled":
                        subtitle_format = getattr(self, "subtitle_format", "srt")
                        extension, _ = resolve_subtitle_format(subtitle_format, self.subtitle_mode)
                        chapter_subtitle_path = os.path.join(
                            chapters_out_dir, f"{chapter_filename}.{extension}"
                        )
                        chapter_subtitle_writer = make_subtitle_writer(
                            Path(chapter_subtitle_path),
                            subtitle_format,
                            self.subtitle_mode,
                            max_words=self.max_subtitle_words,
                        )
                        if chapter_subtitle_writer:
                            chapter_subtitle_writer.open()
                    else:
                        chapter_subtitle_writer = None
                else:
                    chapter_subtitle_path = None
                    chapter_subtitle_writer = None


                # Process each voice segment within the chapter
                for segment_idx, (voice_name, segment_text) in enumerate(voice_segments):
                    # Load voice for this segment (with caching)
                    try:
                        loaded_voice = self.load_voice_cached(voice_name, self.backend)
                        if segment_idx > 0:
                            voice_display = voice_name if len(voice_name) < 50 else voice_name[:47] + "..."
                            self.log_updated.emit((f"  → Voice: {voice_display}", "grey"))
                    except Exception:
                        self.log_updated.emit(
                            (f"⚠ Voice loading error for '{voice_name}', continuing with previous", "orange")
                        )
                        if segment_idx == 0:
                            loaded_voice = self.load_voice_cached(self.voice, self.backend)

                    # Determine if spaCy segmentation should be used for PRE-TTS segmentation
                    # Only non-English languages use spaCy for pre-segmentation
                    # English uses spaCy only for subtitle generation (post-TTS)
                    # spaCy is disabled when subtitle mode is "Disabled" or "Line"
                    # spaCy is also disabled when input is a subtitle file
                    is_subtitle_input = (
                        not self.is_direct_text
                        and self.file_name
                        and os.path.splitext(self.file_name)[1].lower()
                        in [".srt", ".ass", ".vtt"]
                    )
                    use_spacy = (
                        getattr(self, "use_spacy_segmentation", False)
                        and self.subtitle_mode not in ["Disabled", "Line"]
                        and not is_subtitle_input
                    )
                    spacy_sentences = None
                    active_split_pattern = self.split_pattern
                    spacing_pattern = r"\s*" if self.lang_code in ["z", "j"] else r"\s+"

                    # Pre-load spaCy model for English if it will be needed for subtitle generation
                    if (
                        use_spacy
                        and self.lang_code in ["a", "b"]
                        and self.subtitle_mode in ["Sentence", "Sentence + Comma"]
                    ):
                        from abogen.spacy_utils import get_spacy_model

                        nlp = get_spacy_model(
                            self.lang_code,
                            log_callback=lambda msg: self.log_updated.emit(msg),
                        )
                        if nlp:
                            self.log_updated.emit(
                                (
                                    "\nUsing spaCy for sentence segmentation (only for subtitles)...",
                                    "grey",
                                )
                            )

                    if use_spacy and self.lang_code not in ["a", "b"]:
                        # Non-English: use spaCy for pre-TTS segmentation
                        self.log_updated.emit(
                            ("\nUsing spaCy for sentence segmentation (pre-TTS)...", "grey")
                        )
                        from abogen.spacy_utils import segment_sentences

                        spacy_sentences = segment_sentences(
                            segment_text,
                            self.lang_code,
                            log_callback=lambda msg: self.log_updated.emit(msg),
                        )
                        if spacy_sentences:
                            self.log_updated.emit(
                                (
                                    f"\nspaCy: Text segmented into {len(spacy_sentences)} sentences...",
                                    "grey",
                                )
                            )
                            # For Sentence + Comma mode, still split on commas within spaCy sentences
                            if self.subtitle_mode == "Sentence + Comma":
                                active_split_pattern = r"(?<=[{}]){}|\n+".format(
                                    self.PUNCTUATION_COMMAS, spacing_pattern
                                )
                            else:
                                active_split_pattern = (
                                    "\n"  # Use newline splitting for Sentence mode
                                )
                        else:
                            self.log_updated.emit(
                                ("\nspaCy: Fallback to default segmentation...", "grey")
                            )

                    # Process text - either as spaCy sentences or as single text
                    text_segments = spacy_sentences if spacy_sentences else [segment_text]

                    # Print active split pattern used by the TTS engine once for this batch
                    try:
                        print(f"Using split pattern: {active_split_pattern!r}")
                    except Exception:
                        # Print must never break processing
                        print("Using split pattern: (unprintable)")

                    for text_segment in text_segments:
                        def _qt_check_cancel() -> bool:
                            if self.cancel_requested:
                                sink_stack.close()
                                self.conversion_finished.emit("Cancelled", None)
                                return True
                            return False

                        def _qt_on_progress(pct: int, etr: str) -> None:
                            self.processed_char_count = stats.processed_chars
                            self.progress_updated.emit(pct, etr)

                        def _qt_on_segment(info: SegmentInfo) -> None:
                            nonlocal chapter_current_time
                            self.log_updated.emit(
                                f"\n{stats.processed_chars:,}/{self.total_char_count:,}: {info.graphemes}"
                            )
                            if self.subtitle_mode != "Disabled" and info.tokens:
                                tokens_with_timestamps = list(info.tokens)
                                chapter_tokens_with_timestamps = [
                                    {
                                        "start": chapter_current_time + (t["start"] - info.chunk_start),
                                        "end": chapter_current_time + (t["end"] - info.chunk_start),
                                        "text": t["text"],
                                        "whitespace": t["whitespace"],
                                    }
                                    for t in info.tokens
                                ]
                                if merge_chapters_at_end:
                                    new_entries = []
                                    process_subtitle_tokens(
                                        tokens_with_timestamps,
                                        new_entries,
                                        self.max_subtitle_words,
                                        self.subtitle_mode,
                                        self.lang_code,
                                        use_spacy_segmentation=getattr(self, "use_spacy_segmentation", False),
                                        fallback_end_time=info.chunk_start + info.duration,
                                    )
                                    if merged_subtitle_writer:
                                        for start, end, text in new_entries:
                                            merged_subtitle_writer.write_entry(start, end, text)
                                if chapter_sink:
                                    new_chapter_entries = []
                                    process_subtitle_tokens(
                                        chapter_tokens_with_timestamps,
                                        new_chapter_entries,
                                        self.max_subtitle_words,
                                        self.subtitle_mode,
                                        self.lang_code,
                                        use_spacy_segmentation=getattr(self, "use_spacy_segmentation", False),
                                        fallback_end_time=chapter_current_time + info.duration,
                                    )
                                    if chapter_subtitle_writer:
                                        for start, end, text in new_chapter_entries:
                                            chapter_subtitle_writer.write_entry(start, end, text)
                            if chapter_sink:
                                chapter_current_time += info.duration

                        stats = SegmentStats(
                            processed_chars=self.processed_char_count,
                            current_time=current_time,
                            etr_start_time=self.etr_start_time,
                            total_characters=self.total_char_count,
                        )

                        try:
                            synthesize_text(
                                text=text_segment,
                                tts_context=self._tts_context,
                                backend=self.backend,
                                voice=loaded_voice,
                                speed=self.speed,
                                stats=stats,
                                check_cancel=_qt_check_cancel,
                                on_progress=_qt_on_progress,
                                chapter_sink=chapter_sink,
                                audio_sink=merged_sink if merge_chapters_at_end else None,
                                on_segment=_qt_on_segment,
                                split_pattern_override=active_split_pattern,
                            )
                        except Exception as exc:
                            self.log_updated.emit(
                                (f"Warning: TTS failed: {exc}", "orange")
                            )

                        self.processed_char_count = stats.processed_chars
                        current_time = stats.current_time

                # Add silence between chapters for merged output (except after the last chapter)
                if merge_chapters_at_end and chapter_idx < total_chapters:
                    silence_audio = create_silence(self.silence_duration)

                    if merged_sink:
                        merged_sink.write(silence_audio)
                    

                    # Update timing for the silence
                    current_time += self.silence_duration
                    if chapter_sink:
                        chapter_current_time += self.silence_duration

                # Set chapter end time after processing
                if merge_chapters_at_end:
                    chapter_time["end"] = current_time
                # Finalize chapter file for ffmpeg formats
                if chapter_sink:
                    self.log_updated.emit(("\nProcessing chapter audio...", "grey"))
                # Close chapter subtitle writer if open
                if chapter_subtitle_writer:
                    chapter_subtitle_writer.close()
                if (
                    save_chapters_separately
                    and total_chapters > 1
                    and self.subtitle_mode != "Disabled"
                    and chapter_subtitle_path
                ):
                    self.log_updated.emit(
                        (
                            f"\nChapter {chapter_idx} saved to: {chapter_out_path}\n\nChapter subtitle saved to: {chapter_subtitle_path}",
                            "green",
                        )
                    )
                elif chapter_out_path:
                    self.log_updated.emit(
                        (
                            f"\nChapter {chapter_idx} saved to: {chapter_out_path}",
                            "green",
                        )
                    )

            # --- Outro synthesis ---
            if merge_chapters_at_end:
                outro_spec = resolve_outro(
                    _extract_metadata_dict(self.file_name, self.is_direct_text),
                    os.path.basename(self.file_name) if self.file_name else "",
                    getattr(self, "read_closing_outro", True),
                    self.voice, self.voice, list(self.voice_cache._cache.keys()),
                )
                if outro_spec.enabled:
                    self.log_updated.emit((f"Closing outro: {outro_spec.text[:80]}", "grey"))
                    loaded_outro_voice = self.load_voice_cached(outro_spec.voice_spec, self.backend)
                    outro_stats = SegmentStats(
                        processed_chars=self.processed_char_count,
                        current_time=current_time,
                        etr_start_time=self.etr_start_time,
                        total_characters=self.total_char_count,
                    )
                    run_tts_segment_loop(
                        text=outro_spec.text,
                        backend=self.backend,
                        voice=loaded_outro_voice,
                        speed=self.speed,
                        split_pattern=self.split_pattern,
                        stats=outro_stats,
                        check_cancel=lambda: self.cancel_requested,
                        on_progress=lambda pct, etr: self.progress_updated.emit(pct, etr),
                        chapter_sink=None,
                        audio_sink=merged_sink,
                    )
                    self.processed_char_count = outro_stats.processed_chars
                    current_time = outro_stats.current_time
                    self.log_updated.emit(("Outro synthesized.", "grey"))

            # Finalize merged output file ONLY if merging
            if merge_chapters_at_end:
                self.log_updated.emit(("\nFinalizing audio. Please wait...", "grey"))
                merged_sink.close()
                if self.output_format == "m4b":
                    # Add chapters via ExportService (unified with WebUI)
                    if total_chapters > 1:
                        export_svc = ExportService()
                        metadata_text = read_text_for_metadata(
                            file_path=self.file_name,
                            is_direct_text=self.is_direct_text,
                            direct_text=self.file_name if self.is_direct_text else None,
                        )
                        metadata = extract_metadata_from_text(metadata_text) if metadata_text else {}
                        # Convert cover_path from metadata to Path if present
                        cover_path_raw = metadata.pop("cover_path", None)
                        cover_path = Path(cover_path_raw) if cover_path_raw and os.path.exists(cover_path_raw) else None
                        # Build chapters list for ExportService
                        chapters_for_export = [
                            {"title": ch["chapter"], "start": ch["start"], "end": ch["end"]}
                            for ch in chapters_time
                        ]
                        export_svc.embed_m4b_metadata(
                            audio_path=Path(merged_out_path),
                            metadata=metadata,
                            chapters=chapters_for_export,
                            cover_path=cover_path,
                            log_callback=lambda msg, level="info": self.log_updated.emit((msg, "grey" if level == "info" else "orange")),
                        )
                elif self.output_format in ["opus"]:
                    merged_sink.close()
                self.progress_updated.emit(100, "00:00:00")
                # Close merged subtitle writer if open
                if merged_subtitle_writer:
                    merged_subtitle_writer.close()
            # Subtitle and final message logic
            if merge_chapters_at_end:
                if self.subtitle_mode != "Disabled":
                    self.conversion_finished.emit(
                        (
                            f"\nAudio saved to: {merged_out_path}\n\nSubtitle saved to: {merged_subtitle_path}",
                            "green",
                        ),
                        merged_out_path,
                    )
                else:
                    self.conversion_finished.emit(
                        (f"\nAudio saved to: {merged_out_path}", "green"),
                        merged_out_path,
                    )
            else:
                # If not merging, report the folder that holds the chapter files
                self.progress_updated.emit(100, "00:00:00")
                chapters_dir = os.path.abspath(chapters_out_dir or parent_dir)
                self.conversion_finished.emit(
                    (f"\nAll chapters saved to: {chapters_dir}", "green"),
                    chapters_dir,
                )
        except Exception as e:
            # Cleanup all sinks on error
            try:
                sink_stack.close()
            except Exception:
                pass
            self.log_updated.emit((f"Error occurred: {str(e)}", "red"))
            self.conversion_finished.emit(("Audio generation failed.", "red"), None)
        finally:
            sink_stack.close()

    def _process_subtitle_file(self, tts, base_path, is_timestamp_text=False):
        """Process subtitle files with precise timing and generate output subtitles."""
        try:
            # Parse subtitle file
            subtitles = parse_subtitle_file(self.file_name, is_timestamp_text)

            if not subtitles:
                self.log_updated.emit(("No valid subtitle entries found.", "red"))
                self.conversion_finished.emit(
                    ("No subtitle entries to process.", "red"), None
                )
                return

            self.log_updated.emit(
                (f"\nFound {len(subtitles)} subtitle entries", "grey")
            )

            # Setup output paths
            base_name = os.path.splitext(os.path.basename(base_path))[0]
            parent_dir = (
                user_desktop_dir()
                if self.save_option == "Save to Desktop"
                else (
                    os.path.dirname(base_path)
                    if self.save_option == "Save next to input file"
                    else self.output_folder or os.getcwd()
                )
            )

            if not os.path.exists(parent_dir):
                self.log_updated.emit(
                    (f"Output folder does not exist: {parent_dir}", "red")
                )
                return

            allowed_exts = set(SUPPORTED_SOUND_FORMATS + SUPPORTED_SUBTITLE_FORMATS)
            sanitized_base_path = resolve_unique_path(
                parent_dir, base_name, self.output_format, allowed_exts
            )
            base_filepath_no_ext = sanitized_base_path
            merged_out_path = f"{base_filepath_no_ext}.{self.output_format}"
            rate = 24000

            # Setup audio output
            merged_sink = self._open_merged_sink(
                merged_out_path,
                cancel_check=lambda: self.cancel_requested,
            ).__enter__()

            # Always generate subtitles for subtitle input files
            subtitle_writer = None
            subtitle_path = None
            subtitle_format = getattr(self, "subtitle_format", "srt")
            extension, _ = resolve_subtitle_format(subtitle_format, self.subtitle_mode)
            subtitle_path = f"{base_filepath_no_ext}.{extension}"
            subtitle_writer = make_subtitle_writer(
                Path(subtitle_path),
                subtitle_format,
                self.subtitle_mode,
                max_words=self.max_subtitle_words,
            )
            if subtitle_writer:
                subtitle_writer.open()

            # Load voice
            loaded_voice = resolve_voice(self.voice, tts, self.use_gpu)

            # Process all subtitles via domain
            audio_buffer = process_subtitle_entries(
                subtitles,
                backend=self.backend,
                voice=loaded_voice,
                speed=self.speed,
                cancel_check=lambda: self.cancel_requested,
                log_callback=lambda msg: self.log_updated.emit((msg, "grey")),
                progress_callback=self.progress_updated.emit,
                replace_newlines=getattr(self, "replace_single_newlines", True),
                use_gaps=getattr(self, "use_silent_gaps", False),
                is_timestamp_text=is_timestamp_text,
                subtitle_speed_method=getattr(self, "subtitle_speed_method", "tts"),
            )

            if self.cancel_requested:
                if subtitle_writer:
                    subtitle_writer.close()
                self.conversion_finished.emit("Cancelled", None)
                return

            # Write subtitle entries (post-loop)
            for start_time, end_time, text in subtitles:
                processed_text = text.replace("\n", " ") if getattr(self, "replace_single_newlines", True) else text
                display_text = (
                    processed_text
                    if "ass" in subtitle_format
                    else processed_text.replace("\n", "\\N")
                )
                subtitle_writer.write_entry(start_time, end_time, display_text)

            # Write the complete audio buffer
            self.log_updated.emit(("\nFinalizing audio. Please wait...", "grey"))
            if merged_sink:
                merged_sink.write(to_float32(audio_buffer))
                merged_sink.close()

            if subtitle_writer:
                subtitle_writer.close()

            self.progress_updated.emit(100, "00:00:00")
            result_msg = f"\nAudio saved to: {merged_out_path}" + (
                f"\n\nSubtitle saved to: {subtitle_path}" if subtitle_path else ""
            )
            self.conversion_finished.emit((result_msg, "green"), merged_out_path)

        except Exception as e:
            try:
                if "merged_sink" in locals() and merged_sink:
                    merged_sink.close()
                if "subtitle_writer" in locals() and subtitle_writer:
                    subtitle_writer.close()
            except:
                pass
            self.log_updated.emit((f"Error processing subtitle file: {str(e)}", "red"))
            self.conversion_finished.emit(("Audio generation failed.", "red"), None)

    def set_chapter_options(self, options):
        """Set chapter options from the dialog and resume processing"""
        self.save_chapters_separately = options["save_chapters_separately"]
        self.merge_chapters_at_end = options["merge_chapters_at_end"]
        self.waiting_for_user_input = False
        self._chapter_options_event.set()

    def set_timestamp_response(self, treat_as_subtitle):
        """Set whether to treat timestamp text file as subtitle."""
        self._timestamp_response = treat_as_subtitle
        self._timestamp_response_event.set()

    @contextmanager
    def _open_merged_sink(self, path, cancel_check=None):
        """Open audio sink for the merged output, handling m4b cover art."""
        if self.output_format in ("wav", "flac", "mp3", "opus"):
            with open_audio_sink(
                Path(path),
                self.output_format,
                cancel_check=cancel_check,
            ) as sink:
                yield sink
        elif self.output_format == "m4b":
            static_ffmpeg.add_paths()
            metadata_options, cover_path = (
                self._extract_and_add_metadata_tags_to_ffmpeg_cmd()
            )
            cmd = build_ffmpeg_command(
                Path(path),
                self.output_format,
            )
            cmd.insert(2, "-thread_queue_size")
            cmd.insert(3, "32768")
            if cover_path and os.path.exists(cover_path):
                output_path = cmd.pop()
                cmd.extend([
                    "-i", cover_path,
                    "-map", "0:a",
                    "-map", "1",
                    "-c:v", "copy",
                    "-disposition:v", "attached_pic",
                ])
                cmd.extend(metadata_options)
                cmd.append(output_path)
            else:
                output_path = cmd.pop()
                cmd.extend(metadata_options)
                cmd.append(output_path)
            with open_audio_sink(
                Path(path),
                self.output_format,
                ffmpeg_cmd=cmd,
                cancel_check=cancel_check,
            ) as sink:
                yield sink
        else:
            raise ValueError(f"Unsupported output format: {self.output_format}")

    def _extract_and_add_metadata_tags_to_ffmpeg_cmd(self):
        """Extract metadata tags from text content and add them to ffmpeg command"""
        # Read text for metadata extraction
        text = read_text_for_metadata(
            file_path=self.file_name,
            is_direct_text=self.is_direct_text,
            direct_text=self.file_name if self.is_direct_text else None,
        )
        
        if not text:
            self.log_updated.emit(
                ("Warning: Could not read file for metadata extraction", "orange")
            )
            return [], None
        
        # Extract metadata and build ffmpeg args
        filename = self.file_name if self.is_direct_text else (
            self.display_path if self.display_path else self.file_name
        )
        
        try:
            metadata_options, cover_path = extract_metadata_and_build_args(
                text=text,
                filename=filename,
                display_path=getattr(self, "display_path", None),
                from_queue=getattr(self, "from_queue", False),
            )
            return metadata_options, cover_path
        except Exception as e:
            self.log_updated.emit(
                (f"Warning: Metadata extraction error: {e}", "orange")
            )
            return [], None

    def cancel(self):
        self.cancel_requested = True
        self.should_cancel = True
        self.waiting_for_user_input = False
        # Clear voice cache (instance and module-level)
        self.voice_cache.clear()
        from abogen.voice_cache import clear_voice_cache
        clear_voice_cache()
        # Terminate subprocess if running
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


class VoicePreviewThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        backend,
        lang_code,
        voice,
        speed,
        use_gpu=False,
        parent=None,
    ):
        super().__init__(parent)
        self.backend = backend
        self.lang_code = lang_code
        self.voice = voice
        self.speed = speed
        self.use_gpu = use_gpu

        # Cache location for preview audio
        self.cache_dir = get_user_cache_path("preview_cache")

        # Calculate cache path
        self.cache_path = self._get_cache_path()

    def _get_cache_path(self):
        """Generate a unique filename for the voice with its parameters"""
        # For a voice formula, use a hash of the formula
        if "*" in self.voice:
            voice_id = (
                f"voice_formula_{hashlib.md5(self.voice.encode()).hexdigest()[:8]}"
            )
        else:
            voice_id = self.voice

        # Create a unique filename based on voice_id, language, and speed
        filename = f"{voice_id}_{self.lang_code}_{self.speed:.2f}.wav"
        return os.path.join(self.cache_dir, filename)

    def run(self):
        print(
            f"\nVoice: {self.voice}\nLanguage: {self.lang_code}\nSpeed: {self.speed}\nGPU: {self.use_gpu}\n"
        )

        # Generate the preview and save to cache
        try:

            # Enable voice formula support for preview
            loaded_voice = resolve_voice(self.voice, self.backend, self.use_gpu)
            sample_text = get_sample_voice_text(self.lang_code)
            audio_segments = []
            for result in self.backend(
                sample_text, voice=loaded_voice, speed=self.speed, split_pattern=None
            ):
                audio_segments.append(result.audio)
            if audio_segments:
                audio = np.concatenate(audio_segments)
                # Save directly to the cache path
                sf.write(self.cache_path, audio, 24000)
                self.temp_wav = self.cache_path
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Voice preview error: {str(e)}")


class PlayAudioThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, wav_path, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.is_canceled = False

    def run(self):
        try:
            import pygame
            import time as _time

            pygame.mixer.init()
            pygame.mixer.music.load(self.wav_path)
            pygame.mixer.music.play()
            # Wait until playback is finished or canceled
            while pygame.mixer.music.get_busy() and not self.is_canceled:
                _time.sleep(0.2)

            # Make sure to clean up regardless of how we exited the loop
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.quit()  # Quit the mixer
            except Exception:
                # Ignore any errors during cleanup
                pass

            self.finished.emit()
        except Exception as e:
            # Handle initialization errors separately to give better error messages
            if "mixer not initialized" in str(e):
                self.error.emit(
                    "Audio playback error: The audio system was not properly initialized"
                )
            else:
                self.error.emit(f"Audio playback error: {str(e)}")

    def stop(self):
        """Safely stop playback"""
        self.is_canceled = True
        # Try to stop pygame if it's running, but catch all exceptions
        try:
            import pygame

            if pygame.mixer.get_init():
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception:
            # Ignore all errors when stopping since mixer might not be initialized
            pass
