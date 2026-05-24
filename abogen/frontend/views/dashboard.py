"""
Dashboard view – the primary conversion screen.

Hosts the file drop-zone, voice/speed/format controls, real-time log
terminal, progress bar, and the Start/Cancel/Finish action row.

All heavy work is delegated to ConversionBridge which runs on daemon
threads and schedules UI updates back onto the Flet event loop.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import flet as ft

from ..state import AppState
from ..utils.helpers import (
    detect_file_type, human_readable_size, format_number,
    format_etr, grouped_voices, output_format_label,
    subtitle_format_label, is_book_type, voice_lang_code, SUPPORTED_EXTENSIONS
)
from ..utils.theme import get_palette, RADIUS_MD, RADIUS_SM, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL
from ..utils.conversion_bridge import ConversionBridge
from ..components import (
    build_drop_zone, build_log_terminal, log_entry,
    build_primary_button, build_secondary_button,
    build_card, build_section_header, labelled_row, show_snack,
)
from abogen.constants import (
    SUBTITLE_FORMATS, SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
    LANGUAGE_DESCRIPTIONS, VOICES_INTERNAL,
)
from abogen.utils import get_gpu_acceleration, get_user_cache_path, calculate_text_length, clean_text


class DashboardView:
    """
    The main conversion dashboard.

    Instantiated once per Flet session and mounted as a ``ft.Column``
    inside the page's content area.
    """

    def __init__(self, page: ft.Page, state: AppState) -> None:
        self._page = page
        self._state = state
        self._bridge = ConversionBridge(page, state)

        # Internal refs
        self._log_list: Optional[ft.ListView] = None
        self._progress_bar: Optional[ft.ProgressBar] = None
        self._etr_label: Optional[ft.Text] = None
        self._drop_zone_ref: Optional[ft.GestureDetector] = None
        self._drop_zone_container: Optional[ft.Container] = None
        self._file_picker: Optional[ft.FilePicker] = None

        # Wire state callbacks
        state.on_log = self._on_log
        state.on_progress = self._on_progress
        state.on_conversion_finished = self._on_finished

        # Build UI refs
        self._voice_dd: Optional[ft.Dropdown] = None
        self._speed_slider: Optional[ft.Slider] = None
        self._speed_label: Optional[ft.Text] = None
        self._format_dd: Optional[ft.Dropdown] = None
        self._subtitle_dd: Optional[ft.Dropdown] = None
        self._subtitle_fmt_dd: Optional[ft.Dropdown] = None
        self._gpu_switch: Optional[ft.Switch] = None
        self._start_btn: Optional[ft.ElevatedButton] = None
        self._cancel_btn: Optional[ft.OutlinedButton] = None
        self._finish_col: Optional[ft.Column] = None
        self._controls_col: Optional[ft.Column] = None
        self._log_section: Optional[ft.Container] = None
        self._progress_col: Optional[ft.Column] = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> ft.Column:
        """Return the complete dashboard column."""
        p = self._page
        dark = p.theme_mode == ft.ThemeMode.DARK
        pal = get_palette(p)
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()

        # --- Drop zone ---
        self._drop_zone_container = ft.Container()
        self._refresh_drop_zone()

        # --- Voice selector ---
        voice_items = []
        for lang_label, voices in grouped_voices():
            voice_items.append(ft.dropdown.Option(key=f"__hdr_{lang_label}", text=f"── {lang_label} ──", disabled=True))
            for v in voices:
                voice_items.append(ft.dropdown.Option(key=v, text=v))

        self._voice_dd = ft.Dropdown(
            options=voice_items,
            value=self._state.selected_voice,
            on_select=self._on_voice_changed,
            dense=True,
            expand=True,
            border_radius=RADIUS_SM,
        )

        # --- Speed slider ---
        self._speed_label = ft.Text(f"{self._state.speed:.2f}", size=13, width=40)
        self._speed_slider = ft.Slider(
            min=0.1, max=2.0, value=self._state.speed,
            divisions=190, label="{value}",
            on_change=self._on_speed_changed,
            expand=True,
        )

        # --- Format ---
        self._format_dd = ft.Dropdown(
            options=[ft.dropdown.Option(key=k, text=output_format_label(k))
                     for k in ("wav", "flac", "mp3", "opus", "m4b")],
            value=self._state.selected_format,
            on_select=lambda e: self._set_field("selected_format", e.control.value),
            dense=True, expand=True, border_radius=RADIUS_SM,
        )

        # --- Subtitle mode ---
        sub_modes = ["Disabled", "Line", "Sentence", "Sentence + Comma",
                     "Sentence + Highlighting"] + [f"{i} word{'s' if i > 1 else ''}" for i in range(1, 11)]
        self._subtitle_dd = ft.Dropdown(
            options=[ft.dropdown.Option(m) for m in sub_modes],
            value=self._state.subtitle_mode,
            on_select=lambda e: self._set_field("subtitle_mode", e.control.value),
            dense=True, expand=True, border_radius=RADIUS_SM,
        )

        # --- Subtitle format ---
        self._subtitle_fmt_dd = ft.Dropdown(
            options=[ft.dropdown.Option(key=k, text=lbl) for k, lbl in SUBTITLE_FORMATS],
            value=self._state.subtitle_format,
            on_select=lambda e: self._set_field("subtitle_format", e.control.value),
            dense=True, expand=True, border_radius=RADIUS_SM,
        )

        # --- GPU ---
        self._gpu_switch = ft.Switch(
            value=self._state.use_gpu, label="",
            on_change=lambda e: self._set_field("use_gpu", e.control.value),
            active_color="#5b8af5" if dark else "#3a5fc4",
        )

        # --- Log ---
        log_lv = ft.ListView(expand=True, auto_scroll=True, spacing=1, padding=ft.Padding.all(8))
        self._log_list = log_lv
        bg_log = "#0d1117" if dark else "#f8f9fc"
        bd_log = "#252a38" if dark else "#dce0ea"
        self._log_section = ft.Container(
            content=log_lv, bgcolor=bg_log,
            border=ft.Border.all(1, bd_log),
            border_radius=RADIUS_SM, height=220,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            visible=False,
        )

        # --- Progress ---
        fill = "#5b8af5" if dark else "#3a5fc4"
        bg_p = "#1e2230" if dark else "#e4e8f0"
        self._progress_bar = ft.ProgressBar(
            value=0, color=fill, bgcolor=bg_p, height=8,
            border_radius=ft.BorderRadius.all(4), expand=True,
        )
        self._etr_label = ft.Text("", size=11, color=pal.text_secondary, text_align=ft.TextAlign.CENTER)
        self._progress_col = ft.Column([
            ft.Row([self._progress_bar], spacing=0),
            self._etr_label,
        ], spacing=SPACE_SM, horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False)

        # --- Buttons ---
        self._start_btn = build_primary_button(
            "Start Conversion",
            icon="play_arrow",
            on_click=self._on_start,
            page=p,
        )
        self._cancel_btn = build_secondary_button(
            "Cancel", icon="stop",
            on_click=self._on_cancel, page=p,
        )
        self._cancel_btn.visible = False

        # --- Finish row ---
        self._finish_col = ft.Column([
            ft.Row([
                build_secondary_button("Open File", icon="open_in_new",
                                       on_click=self._on_open_file, page=p),
                build_secondary_button("Go to Folder", icon="folder_open",
                                       on_click=self._on_go_folder, page=p),
                build_secondary_button("New Conversion", icon="refresh",
                                       on_click=self._on_reset, page=p),
            ], wrap=True, spacing=SPACE_SM, run_spacing=SPACE_SM),
        ], visible=False)

        # --- Controls column ---
        self._controls_col = ft.Column([
            build_section_header("Voice & Speed", icon="record_voice_over", page=p),
            labelled_row("Voice", self._voice_dd, page=p),
            labelled_row("Speed", ft.Row([self._speed_slider, self._speed_label], expand=True, spacing=SPACE_SM), page=p),
            ft.Divider(height=1, color=pal.divider),
            build_section_header("Output", icon="audio_file", page=p),
            labelled_row("Format", self._format_dd, page=p),
            labelled_row("Subtitles", self._subtitle_dd, page=p),
            labelled_row("Subtitle Format", self._subtitle_fmt_dd, page=p),
            ft.Divider(height=1, color=pal.divider),
            build_section_header("Processing", icon="memory", page=p),
            labelled_row("GPU Acceleration", self._gpu_switch, page=p),
        ], spacing=SPACE_MD)

        outer = ft.Column([
            self._drop_zone_container,
            ft.Container(height=SPACE_MD),
            build_card(self._controls_col, page=p),
            ft.Container(height=SPACE_SM),
            self._log_section,
            self._progress_col,
            ft.Row([self._start_btn, self._cancel_btn], spacing=SPACE_SM, wrap=True),
            self._finish_col,
        ], spacing=SPACE_MD, expand=True, scroll=ft.ScrollMode.AUTO)

        return outer

    # ------------------------------------------------------------------
    # Drop-zone management
    # ------------------------------------------------------------------

    def _refresh_drop_zone(self, *, accent: bool = False, error: bool = False, err_msg: str = "") -> None:
        """Rebuild the drop-zone widget and update its container."""
        p = self._page
        s = self._state
        fname = None; fsize = None; fchars = None
        if s.selected_file and os.path.exists(s.selected_file):
            disp = s.displayed_file_path or s.selected_file
            fname = os.path.basename(disp)
            try:
                fsize = human_readable_size(os.path.getsize(s.selected_file))
            except Exception:
                fsize = ""
            if s.char_count:
                fchars = format_number(s.char_count)

        label = err_msg if error else "Drag & drop your file here or click to browse"
        sub = "Supports .txt · .epub · .pdf · .md · .srt · .ass · .vtt"

        dz = build_drop_zone(
            on_pick=self._open_file_picker,
            label=label, sub_label=sub,
            accent=accent, error=error,
            filename=fname, file_size=fsize, char_count=fchars,
            page=p,
        )
        if self._drop_zone_container is not None:
            self._drop_zone_container.content = dz
        self._drop_zone_ref = dz

    # ------------------------------------------------------------------
    # File picking
    # ------------------------------------------------------------------

    def _open_file_picker(self) -> None:
        """Open the native file picker dialog."""
        self._page.run_task(self._pick_files_async)

    async def _pick_files_async(self) -> None:
        """Run the file picker using Flet's async service API."""
        picker = self._file_picker
        if picker is None:
            picker = ft.FilePicker()
            self._file_picker = picker

        try:
            files = await picker.pick_files(
                dialog_title="Select Input File",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["txt", "epub", "pdf", "md", "markdown", "srt", "ass", "vtt"],
                allow_multiple=False,
            )
        except Exception as ex:
            self._refresh_drop_zone(error=True, err_msg="Could not open file picker.")
            show_snack(self._page, f"File picker error: {ex}", error=True)
            self._page.update()
            return
        if not files:
            return
        file_path = files[0].path
        if not file_path or not os.path.exists(file_path):
            return
        self._load_file(file_path)

    def _load_file(self, file_path: str) -> None:
        """Validate and load a file into the session state."""
        from pathlib import Path as _Path
        ext = _Path(file_path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            self._state.reset_file_state()
            self._refresh_drop_zone(error=True, err_msg=f"Unsupported file type: {ext}")
            self._page.update()
            return

        ftype = detect_file_type(file_path)
        s = self._state

        if ftype in ("epub", "pdf", "markdown"):
            # For book types: extract text to temp cache
            self._handle_book_file(file_path, ftype)
        else:
            # Plain text / subtitle files
            s.selected_file = file_path
            s.selected_file_type = ftype
            s.displayed_file_path = file_path
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                s.char_count = calculate_text_length(clean_text(text))
            except Exception:
                s.char_count = 0
            self._refresh_drop_zone(accent=True)
            self._update_subtitle_availability()
            self._page.update()

    def _handle_book_file(self, book_path: str, ftype: str) -> None:
        """Extract text from epub/pdf/markdown and store as temp txt."""
        import threading as _t
        s = self._state

        def _extract():
            try:
                from abogen.text_extractor import extract_from_path
                chapters = extract_from_path(book_path, file_type=ftype)
                combined = "\n\n".join(ch.text for ch in chapters if ch.text.strip())
                cache_dir = get_user_cache_path()
                base = os.path.splitext(os.path.basename(book_path))[0]
                fd, tmp = tempfile.mkstemp(prefix=f"{base}_", suffix=".txt", dir=cache_dir)
                os.close(fd)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(combined)

                s.selected_file = tmp
                s.selected_file_type = ftype
                s.selected_book_path = book_path
                s.displayed_file_path = book_path
                s.char_count = calculate_text_length(clean_text(combined))
                s.selected_chapters = [f"ch_{i}" for i in range(len(chapters))]

                self._refresh_drop_zone(accent=True)
                self._update_subtitle_availability()
                self._page.update()
            except Exception as ex:
                s.reset_file_state()
                self._refresh_drop_zone(error=True, err_msg=f"Could not parse file: {ex}")
                self._page.update()

        _t.Thread(target=_extract, daemon=True).start()

    # ------------------------------------------------------------------
    # Control event handlers
    # ------------------------------------------------------------------

    def _set_field(self, attr: str, value) -> None:
        setattr(self._state, attr, value)
        self._state.persist_config()

    def _on_voice_changed(self, e: ft.ControlEvent) -> None:
        v = e.control.value or "af_heart"
        self._state.selected_voice = v
        self._state.selected_lang = voice_lang_code(v)
        self._state.persist_config()
        self._update_subtitle_availability()
        self._page.update()

    def _on_speed_changed(self, e: ft.ControlEvent) -> None:
        val = round(float(e.control.value), 2)
        self._state.speed = val
        if self._speed_label:
            self._speed_label.value = f"{val:.2f}"
        self._state.persist_config()
        self._page.update()

    def _update_subtitle_availability(self) -> None:
        """Enable or disable subtitle controls based on selected language."""
        lang = self._state.selected_lang
        enabled = lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        if self._subtitle_dd:
            self._subtitle_dd.disabled = not enabled
        if self._subtitle_fmt_dd:
            self._subtitle_fmt_dd.disabled = not enabled

    # ------------------------------------------------------------------
    # Conversion control
    # ------------------------------------------------------------------

    def _on_start(self, _: ft.ControlEvent) -> None:
        """Validate inputs and kick off conversion."""
        s = self._state
        if not s.selected_file or not os.path.exists(s.selected_file):
            self._refresh_drop_zone(error=True, err_msg="Please select an input file first.")
            self._page.update()
            return

        # Transition UI to converting state
        self._set_converting_ui(True)

        self._bridge.start(
            input_file=s.selected_file,
            voice=s.get_voice_formula(),
            lang_code=s.selected_lang,
            speed=s.speed,
            output_format=s.selected_format,
            subtitle_mode=s.subtitle_mode,
            subtitle_format=s.subtitle_format,
            use_gpu=s.use_gpu,
            save_option=s.save_option,
            output_folder=s.selected_output_folder,
            replace_single_newlines=s.replace_single_newlines,
            char_count=s.char_count,
            save_chapters_separately=s.save_chapters_separately or False,
            merge_chapters_at_end=True if s.merge_chapters_at_end is None else s.merge_chapters_at_end,
            separate_chapters_format=s.separate_chapters_format,
            silence_between_chapters=s.silence_duration,
            max_subtitle_words=s.max_subtitle_words,
            chapter_intro_delay=s.chapter_intro_delay,
            read_title_intro=s.read_title_intro,
            read_closing_outro=s.read_closing_outro,
            auto_prefix_chapter_titles=s.auto_prefix_chapter_titles,
            normalize_chapter_opening_caps=s.normalize_chapter_opening_caps,
            tts_provider=s.tts_provider,
            supertonic_total_steps=s.supertonic_total_steps,
            chunk_level=s.chunk_level,
            generate_epub3=s.generate_epub3,
            word_substitutions_enabled=s.word_substitutions_enabled,
            word_substitutions_list=s.word_substitutions_list,
            case_sensitive_substitutions=s.case_sensitive_substitutions,
            replace_all_caps=s.replace_all_caps,
            replace_numerals=s.replace_numerals,
            fix_nonstandard_punctuation=s.fix_nonstandard_punctuation,
        )

    def _on_cancel(self, _: ft.ControlEvent) -> None:
        self._bridge.cancel()

    def _set_converting_ui(self, converting: bool) -> None:
        """Toggle UI between idle and converting states."""
        if self._start_btn:
            self._start_btn.visible = not converting
        if self._cancel_btn:
            self._cancel_btn.visible = converting
        if self._controls_col:
            self._controls_col.visible = not converting
        if self._log_section:
            self._log_section.visible = converting
            if self._log_list:
                self._log_list.controls.clear()
        if self._progress_col:
            self._progress_col.visible = converting
            if self._progress_bar:
                self._progress_bar.value = 0
            if self._etr_label:
                self._etr_label.value = "Estimating…"
        if self._finish_col:
            self._finish_col.visible = False
        self._page.update()

    # ------------------------------------------------------------------
    # State callbacks (called from background thread via page.run_task)
    # ------------------------------------------------------------------

    def _on_log(self, message: str, level: str) -> None:
        if self._log_list is None:
            return
        entry = log_entry(message, level, self._page)
        self._log_list.controls.append(entry)
        # Cap log lines
        if len(self._log_list.controls) > 2000:
            self._log_list.controls = self._log_list.controls[-1800:]
        try:
            self._page.update()
        except Exception:
            pass

    def _on_progress(self, fraction: float, etr: Optional[float]) -> None:
        if self._progress_bar:
            self._progress_bar.value = min(fraction, 0.99)
        if self._etr_label:
            self._etr_label.value = format_etr(etr)
        try:
            self._page.update()
        except Exception:
            pass

    def _on_finished(self, message: str, output_path: Optional[str]) -> None:
        if self._progress_bar:
            self._progress_bar.value = 1.0
        if self._cancel_btn:
            self._cancel_btn.visible = False

        if message == "Cancelled":
            # Restore idle state
            self._set_converting_ui(False)
            show_snack(self._page, "Conversion cancelled.", error=True)
            return

        if "failed" in message.lower() or "error" in message.lower():
            self._log_on_log(message, "error")
            self._set_converting_ui(False)
            show_snack(self._page, f"Error: {message}", error=True)
            return

        # Success
        if self._log_section:
            self._log_section.visible = True
        if self._progress_col:
            self._progress_col.visible = False
        if self._controls_col:
            self._controls_col.visible = False
        if self._finish_col:
            self._finish_col.visible = True
        if self._start_btn:
            self._start_btn.visible = False
        show_snack(self._page, "Conversion completed!")
        try:
            self._page.update()
        except Exception:
            pass

    def _log_on_log(self, message: str, level: str) -> None:
        self._on_log(message, level)

    # ------------------------------------------------------------------
    # Finish actions
    # ------------------------------------------------------------------

    def _on_open_file(self, _: ft.ControlEvent) -> None:
        path = self._state.last_output_path
        if path and os.path.exists(path):
            import subprocess, platform
            try:
                if platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
                elif platform.system() == "Windows":
                    os.startfile(path)
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as ex:
                show_snack(self._page, f"Cannot open file: {ex}", error=True)
        else:
            show_snack(self._page, "Output file not found.", error=True)

    def _on_go_folder(self, _: ft.ControlEvent) -> None:
        path = self._state.last_output_path
        folder = os.path.dirname(path) if path and os.path.isfile(path) else path
        if folder and os.path.isdir(folder):
            import subprocess, platform
            try:
                if platform.system() == "Darwin":
                    subprocess.Popen(["open", folder])
                elif platform.system() == "Windows":
                    subprocess.Popen(["explorer", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as ex:
                show_snack(self._page, f"Cannot open folder: {ex}", error=True)
        else:
            show_snack(self._page, "Output folder not found.", error=True)

    def _on_reset(self, _: ft.ControlEvent) -> None:
        self._state.reset_file_state()
        self._state.reset_conversion_state()
        self._refresh_drop_zone()
        self._set_converting_ui(False)
        if self._finish_col:
            self._finish_col.visible = False
        if self._controls_col:
            self._controls_col.visible = True
        if self._start_btn:
            self._start_btn.visible = True
        self._page.update()
