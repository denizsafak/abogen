"""
Queue management view.

Displays the current conversion queue, allowing the user to reorder,
remove, and inspect queued items before starting batch processing.
"""
from __future__ import annotations
from typing import Optional

import flet as ft

from ..state import AppState, ConversionJob
from ..utils.theme import get_palette, RADIUS_SM, SPACE_SM, SPACE_MD, SPACE_LG
from ..utils.helpers import safe_basename, output_format_label, format_number
from ..components import (
    build_card, build_section_header, build_primary_button,
    build_secondary_button, show_snack, build_divider,
    resolve_icon,
)


class QueueView:
    """Queue manager view."""

    def __init__(self, page: ft.Page, state: AppState) -> None:
        self._page = page
        self._state = state
        self._list_col: Optional[ft.Column] = None

    def build(self) -> ft.Column:
        p = self._page
        s = self._state
        pal = get_palette(p)
        dark = p.theme_mode == ft.ThemeMode.DARK

        self._list_col = ft.Column(spacing=SPACE_SM)
        self._refresh_list()

        header = build_section_header("Conversion Queue",
                                      icon="list_alt", page=p)

        action_row = ft.Row([
            build_primary_button(
                "Start Queue",
                icon="play_arrow",
                on_click=self._on_start_queue,
                page=p,
                disabled=not s.queued_items,
            ),
            build_secondary_button(
                "Clear All",
                icon="delete_sweep",
                on_click=self._on_clear_queue,
                page=p,
            ),
        ], spacing=SPACE_SM, wrap=True)

        queue_card = build_card(ft.Column([
            header,
            ft.Divider(height=1, color=pal.divider),
            self._list_col,
            ft.Container(height=SPACE_SM),
            action_row,
        ], spacing=SPACE_MD), page=p)

        return ft.Column([queue_card], scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        if self._list_col is None:
            return
        self._list_col.controls.clear()
        s = self._state
        pal = get_palette(self._page)
        dark = self._page.theme_mode == ft.ThemeMode.DARK

        if not s.queued_items:
            self._list_col.controls.append(
                ft.Text("No items in the queue.", size=13,
                        color=pal.text_secondary,
                        text_align=ft.TextAlign.CENTER)
            )
            return

        for idx, job in enumerate(s.queued_items):
            tile = self._build_job_tile(idx, job, dark, pal)
            self._list_col.controls.append(tile)

        try:
            self._page.update()
        except Exception:
            pass

    def _build_job_tile(self, idx: int, job: ConversionJob, dark: bool, pal) -> ft.Container:
        """Build a single queue-item tile."""
        bg = pal.bg_elevated
        border_clr = pal.border
        accent = "#5b8af5" if dark else "#3a5fc4"
        text_primary = pal.text_primary
        text_secondary = pal.text_secondary

        def _remove(_):
            self._state.queued_items.pop(idx)
            self._refresh_list()

        name = safe_basename(job.display_name or job.file_path)
        details = (
            f"Voice: {job.voice}  ·  Format: {output_format_label(job.output_format)}"
            f"  ·  Speed: {job.speed:.2f}x  ·  Chars: {format_number(job.char_count)}"
        )

        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(str(idx + 1), size=12, weight=ft.FontWeight.W_700,
                                    color=accent),
                    width=32,
                ),
                ft.Column([
                    ft.Text(name, size=13, weight=ft.FontWeight.W_600, color=text_primary,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(details, size=11, color=text_secondary),
                ], expand=True, tight=True, spacing=2),
                ft.IconButton(
                    icon=resolve_icon("delete_outline"),
                    icon_color=pal.error if hasattr(pal, "error") else "#e84e3c",
                    icon_size=18,
                    tooltip="Remove",
                    on_click=_remove,
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=SPACE_SM),
            bgcolor=bg,
            border=ft.Border.all(1, border_clr),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        )

    # ------------------------------------------------------------------

    def _on_start_queue(self, _: ft.ControlEvent) -> None:
        if not self._state.queued_items:
            show_snack(self._page, "Queue is empty.", error=True)
            return
        # Navigate to dashboard and trigger queue start
        # This is wired in main.py via the nav controller
        self._page.pubsub.send_all("start_queue")

    def _on_clear_queue(self, _: ft.ControlEvent) -> None:
        if not self._state.queued_items:
            return
        self._state.queued_items.clear()
        self._refresh_list()
        show_snack(self._page, "Queue cleared.")
