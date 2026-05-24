"""
Settings view – a categorised, scrollable settings page.

Groups settings into collapsible cards:
  - Output (format, save location, chapters)
  - Text processing (newlines, caps, substitutions, numerals)
  - Subtitle options
  - TTS pipeline (provider, GPU, chunking)
  - Integrations (Audiobookshelf, Calibre OPDS)
"""
from __future__ import annotations
from typing import Optional

import flet as ft

from ..state import AppState
from ..utils.theme import get_palette, RADIUS_MD, RADIUS_SM, SPACE_SM, SPACE_MD, SPACE_LG
from ..utils.helpers import output_format_label, subtitle_format_label, SUPPORTED_EXTENSIONS
from ..components import (
    build_card, build_section_header, labelled_row, show_snack, build_divider,
    build_primary_button,
)
from abogen.constants import SUBTITLE_FORMATS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dd(options, value, on_change, **kw):
    """Compact dropdown factory."""
    return ft.Dropdown(
        options=[ft.dropdown.Option(key=k, text=v) for k, v in options],
        value=value, on_select=on_change, dense=True,
        border_radius=RADIUS_SM, expand=True, **kw
    )


def _sw(value, on_change, label=""):
    return ft.Switch(value=value, on_change=on_change, label=label)


class SettingsView:
    """The full settings panel."""

    def __init__(self, page: ft.Page, state: AppState) -> None:
        self._page = page
        self._state = state

    def build(self) -> ft.Column:
        p = self._page
        s = self._state
        pal = get_palette(p)

        # ── Output card ──────────────────────────────────────────────
        format_dd = _dd(
            [(k, output_format_label(k)) for k in ("wav", "flac", "mp3", "opus", "m4b")],
            s.selected_format,
            lambda e: self._save("selected_format", e.control.value),
        )
        save_dd = _dd(
            [
                ("Save next to input file", "Save next to input file"),
                ("Save to Desktop", "Save to Desktop"),
                ("Choose output folder", "Choose output folder"),
            ],
            s.save_option,
            lambda e: self._save("save_option", e.control.value),
        )
        chapters_sw = _sw(s.save_chapters_separately or False,
                          lambda e: self._save("save_chapters_separately", e.control.value))
        merge_sw = _sw(True if s.merge_chapters_at_end is None else s.merge_chapters_at_end,
                       lambda e: self._save("merge_chapters_at_end", e.control.value))
        sep_fmt_dd = _dd(
            [(k, output_format_label(k)) for k in ("wav", "flac", "mp3", "opus")],
            s.separate_chapters_format,
            lambda e: self._save("separate_chapters_format", e.control.value),
        )
        epub3_sw = _sw(s.generate_epub3, lambda e: self._save("generate_epub3", e.control.value))

        output_card = build_card(ft.Column([
            build_section_header("Output", icon="audio_file", page=p),
            labelled_row("Audio Format", format_dd, page=p),
            labelled_row("Save Location", save_dd, page=p),
            build_divider(p),
            labelled_row("Save Chapters Separately", chapters_sw, page=p),
            labelled_row("Merge at End", merge_sw, page=p),
            labelled_row("Chapter Format", sep_fmt_dd, page=p),
            labelled_row("Generate EPUB3", epub3_sw, page=p),
        ], spacing=SPACE_MD), page=p)

        # ── Text processing card ─────────────────────────────────────
        newlines_sw = _sw(s.replace_single_newlines,
                          lambda e: self._save("replace_single_newlines", e.control.value))
        caps_sw = _sw(s.replace_all_caps, lambda e: self._save("replace_all_caps", e.control.value))
        norm_sw = _sw(s.normalize_chapter_opening_caps,
                      lambda e: self._save("normalize_chapter_opening_caps", e.control.value))
        numerals_sw = _sw(s.replace_numerals, lambda e: self._save("replace_numerals", e.control.value))
        punct_sw = _sw(s.fix_nonstandard_punctuation,
                       lambda e: self._save("fix_nonstandard_punctuation", e.control.value))
        wordsub_sw = _sw(s.word_substitutions_enabled,
                         lambda e: self._save("word_substitutions_enabled", e.control.value))
        wordsub_tf = ft.TextField(
            value=s.word_substitutions_list,
            multiline=True, min_lines=3, max_lines=6,
            hint_text="word|replacement  (one per line)",
            on_change=lambda e: self._save("word_substitutions_list", e.control.value),
            expand=True, border_radius=RADIUS_SM, text_size=12,
        )
        case_sw = _sw(s.case_sensitive_substitutions,
                      lambda e: self._save("case_sensitive_substitutions", e.control.value))
        spacy_sw = _sw(s.use_spacy_segmentation,
                       lambda e: self._save("use_spacy_segmentation", e.control.value))
        chunk_dd = _dd(
            [("paragraph", "Paragraph"), ("sentence", "Sentence")],
            s.chunk_level,
            lambda e: self._save("chunk_level", e.control.value),
        )
        title_intro_sw = _sw(s.read_title_intro, lambda e: self._save("read_title_intro", e.control.value))
        outro_sw = _sw(s.read_closing_outro, lambda e: self._save("read_closing_outro", e.control.value))
        prefix_sw = _sw(s.auto_prefix_chapter_titles,
                        lambda e: self._save("auto_prefix_chapter_titles", e.control.value))

        text_card = build_card(ft.Column([
            build_section_header("Text Processing", icon="text_fields", page=p),
            labelled_row("Replace Single Newlines", newlines_sw,
                         tooltip="Replace single newlines with spaces before processing.", page=p),
            labelled_row("Replace ALL CAPS Words", caps_sw, page=p),
            labelled_row("Normalize Opening CAPS", norm_sw, page=p),
            labelled_row("Replace Numerals (spoken)", numerals_sw, page=p),
            labelled_row("Fix Non-standard Punctuation", punct_sw, page=p),
            build_divider(p),
            labelled_row("Word Substitutions", wordsub_sw, page=p),
            labelled_row("Case Sensitive", case_sw, page=p),
            ft.Text("Substitution rules  (word|replacement, one per line):",
                    size=12, color=pal.text_secondary),
            wordsub_tf,
            build_divider(p),
            build_section_header("Chapter Options", icon="library_books", page=p),
            labelled_row("Announce Book Title (intro)", title_intro_sw, page=p),
            labelled_row("Announce Book Title (outro)", outro_sw, page=p),
            labelled_row("Auto-prefix Chapter Titles", prefix_sw, page=p),
            labelled_row("Chunk Level", chunk_dd, page=p),
            labelled_row("Use spaCy Segmentation", spacy_sw, page=p),
        ], spacing=SPACE_MD), page=p)

        # ── Subtitle card ─────────────────────────────────────────────
        sub_modes = ["Disabled", "Line", "Sentence", "Sentence + Comma",
                     "Sentence + Highlighting"] + [f"{i} word{'s' if i > 1 else ''}" for i in range(1, 11)]
        sub_mode_dd = _dd(
            [(m, m) for m in sub_modes],
            s.subtitle_mode,
            lambda e: self._save("subtitle_mode", e.control.value),
        )
        sub_fmt_dd = _dd(
            [(k, lbl) for k, lbl in SUBTITLE_FORMATS],
            s.subtitle_format,
            lambda e: self._save("subtitle_format", e.control.value),
        )

        def _mk_mw_slider():
            lbl = ft.Text(str(s.max_subtitle_words), size=12, width=36)
            sl = ft.Slider(
                min=1, max=200, value=s.max_subtitle_words, divisions=199, label="{value}",
                expand=True,
                on_change=lambda e: (self._save("max_subtitle_words", int(e.control.value)),
                                     setattr(lbl, "value", str(int(e.control.value))),
                                     self._page.update()),
            )
            return ft.Row([sl, lbl], expand=True, spacing=SPACE_SM)

        sub_speed_dd = _dd(
            [("tts", "TTS duration"), ("silence", "Silence detection")],
            s.subtitle_speed_method,
            lambda e: self._save("subtitle_speed_method", e.control.value),
        )
        silent_gaps_sw = _sw(s.use_silent_gaps,
                             lambda e: self._save("use_silent_gaps", e.control.value))

        subtitle_card = build_card(ft.Column([
            build_section_header("Subtitles", icon="subtitles", page=p),
            labelled_row("Mode", sub_mode_dd, page=p),
            labelled_row("Format", sub_fmt_dd, page=p),
            labelled_row("Max Words / Block", _mk_mw_slider(), page=p),
            labelled_row("Speed Method", sub_speed_dd, page=p),
            labelled_row("Silent Gaps", silent_gaps_sw, page=p),
        ], spacing=SPACE_MD), page=p)

        # ── Pipeline card ─────────────────────────────────────────────
        provider_dd = _dd(
            [("kokoro", "Kokoro (default)"), ("supertonic", "Supertonic")],
            s.tts_provider,
            lambda e: self._save("tts_provider", e.control.value),
        )
        gpu_sw = _sw(s.use_gpu, lambda e: self._save("use_gpu", e.control.value),
                     label="GPU acceleration (if available)")

        def _mk_steps_slider():
            lbl = ft.Text(str(s.supertonic_total_steps), size=12, width=28)
            sl = ft.Slider(
                min=2, max=15, value=s.supertonic_total_steps, divisions=13,
                label="{value}", expand=True,
                on_change=lambda e: (self._save("supertonic_total_steps", int(e.control.value)),
                                     setattr(lbl, "value", str(int(e.control.value))),
                                     self._page.update()),
            )
            return ft.Row([sl, lbl], expand=True, spacing=SPACE_SM)

        thresh_tf = ft.TextField(
            value=str(s.speaker_analysis_threshold), width=80,
            keyboard_type=ft.KeyboardType.NUMBER, border_radius=RADIUS_SM,
            on_change=lambda e: self._save_int("speaker_analysis_threshold", e.control.value, 1, 25),
        )
        silence_tf = ft.TextField(
            value=str(s.silence_duration), width=80,
            keyboard_type=ft.KeyboardType.NUMBER, border_radius=RADIUS_SM,
            on_change=lambda e: self._save_float("silence_duration", e.control.value, 0.0),
        )
        intro_tf = ft.TextField(
            value=str(s.chapter_intro_delay), width=80,
            keyboard_type=ft.KeyboardType.NUMBER, border_radius=RADIUS_SM,
            on_change=lambda e: self._save_float("chapter_intro_delay", e.control.value, 0.0),
        )

        pipeline_card = build_card(ft.Column([
            build_section_header("TTS Pipeline", icon="settings", page=p),
            labelled_row("Provider", provider_dd, page=p),
            labelled_row("GPU Acceleration", gpu_sw, page=p),
            labelled_row("Supertonic Steps", _mk_steps_slider(), page=p),
            build_divider(p),
            labelled_row("Speaker Analysis Threshold", thresh_tf, page=p),
            labelled_row("Silence Between Chapters (s)", silence_tf, page=p),
            labelled_row("Chapter Intro Delay (s)", intro_tf, page=p),
        ], spacing=SPACE_MD), page=p)

        # ── Integration card (Audiobookshelf) ─────────────────────────
        abs_enabled_sw = _sw(s.audiobookshelf_enabled,
                             lambda e: self._save("audiobookshelf_enabled", e.control.value))
        abs_url_tf = ft.TextField(value=s.audiobookshelf_base_url, hint_text="http://abs-server:13378",
                                  expand=True, border_radius=RADIUS_SM, text_size=12,
                                  on_change=lambda e: self._save("audiobookshelf_base_url", e.control.value))
        abs_token_tf = ft.TextField(value=s.audiobookshelf_api_token, password=True,
                                    can_reveal_password=True, expand=True,
                                    border_radius=RADIUS_SM, text_size=12,
                                    on_change=lambda e: self._save("audiobookshelf_api_token", e.control.value))
        abs_lib_tf = ft.TextField(value=s.audiobookshelf_library_id, hint_text="Library ID",
                                  expand=True, border_radius=RADIUS_SM, text_size=12,
                                  on_change=lambda e: self._save("audiobookshelf_library_id", e.control.value))
        abs_auto_sw = _sw(s.audiobookshelf_auto_send,
                          lambda e: self._save("audiobookshelf_auto_send", e.control.value))

        integ_card = build_card(ft.Column([
            build_section_header("Audiobookshelf Integration",
                                 icon="cloud_upload", page=p),
            labelled_row("Enabled", abs_enabled_sw, page=p),
            labelled_row("Server URL", abs_url_tf, page=p),
            labelled_row("API Token", abs_token_tf, page=p),
            labelled_row("Library ID", abs_lib_tf, page=p),
            labelled_row("Auto-upload on finish", abs_auto_sw, page=p),
        ], spacing=SPACE_MD), page=p)

        save_btn = build_primary_button(
            "Save Settings", icon="save",
            on_click=self._on_save, page=p,
        )

        return ft.Column([
            output_card,
            ft.Container(height=SPACE_MD),
            text_card,
            ft.Container(height=SPACE_MD),
            subtitle_card,
            ft.Container(height=SPACE_MD),
            pipeline_card,
            ft.Container(height=SPACE_MD),
            integ_card,
            ft.Container(height=SPACE_LG),
            save_btn,
            ft.Container(height=SPACE_LG),
        ], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save(self, attr: str, value) -> None:
        setattr(self._state, attr, value)

    def _save_int(self, attr: str, raw: str, lo: int, hi: int) -> None:
        try:
            v = max(lo, min(hi, int(raw)))
            setattr(self._state, attr, v)
        except ValueError:
            pass

    def _save_float(self, attr: str, raw: str, lo: float) -> None:
        try:
            v = max(lo, float(raw))
            setattr(self._state, attr, v)
        except ValueError:
            pass

    def _on_save(self, _: ft.ControlEvent) -> None:
        self._state.persist_config()
        show_snack(self._page, "Settings saved.")
