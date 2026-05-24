"""
Reusable UI components for the Abogen Flet frontend.

Each function in this module returns a standalone Flet control or small
widget tree.  Components read the current palette from the page's theme
mode and should not hold any mutable state themselves – state lives in the
session's ``AppState`` object.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import flet as ft

from ..utils.theme import get_palette, RADIUS_MD, RADIUS_SM, SPACE_SM, SPACE_MD, SPACE_LG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_icon(icon: Any) -> Any:
    """Convert a snake_case icon name to Flet IconData when possible."""
    if isinstance(icon, str):
        return getattr(ft.Icons, icon.upper(), icon)
    return icon


# ---------------------------------------------------------------------------
# Drop-zone (file input area)
# ---------------------------------------------------------------------------


def build_drop_zone(
    *,
    on_pick: Callable[[], None],
    label: str = "Drag & drop your file here or click to browse",
    sub_label: str = "Supports: .txt · .epub · .pdf · .md · .srt · .ass · .vtt",
    accent: bool = False,
    error: bool = False,
    filename: Optional[str] = None,
    file_size: Optional[str] = None,
    char_count: Optional[str] = None,
    page: Optional[ft.Page] = None,
) -> ft.GestureDetector:
    """
    Build an interactive file drop-zone widget.

    The zone shows a dashed border and centred instructions by default,
    switching to an 'active' green style when a file is loaded and a red
    style when an error has occurred.

    Args:
        on_pick: Callback invoked when the user clicks or activates the zone.
        label: Primary instruction text.
        sub_label: Secondary hint text shown beneath the label.
        accent: When True, renders the 'active/success' green style.
        error: When True, renders the 'error/red' style.
        filename: When provided, replaces the instruction text with file info.
        file_size: Human-readable file size to display alongside the filename.
        char_count: Character count to display alongside file info.
        page: The current Flet ``Page``; used to derive the active palette.

    Returns:
        A ``ft.GestureDetector`` wrapping the visual drop-zone container.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    p = get_palette(page) if page else None

    # Colour scheme
    if error:
        border_color = "#e84e3c" if dark else "#c0392b"
        bg_color = "#1a0a08" if dark else "#fff5f5"
        text_color = "#e84e3c" if dark else "#c0392b"
        icon_name = "error_outline"
    elif accent:
        border_color = "#42ad4a" if dark else "#2e9437"
        bg_color = "#091810" if dark else "#f0fff1"
        text_color = "#42ad4a" if dark else "#2e9437"
        icon_name = "check_circle_outline"
    else:
        border_color = "#3a4466" if dark else "#a8b4d0"
        bg_color = "#151928" if dark else "#f7f8fd"
        text_color = "#9ba3b8" if dark else "#5a6172"
        icon_name = "upload_file"

    if filename:
        # Compact file-info display
        info_rows: List[ft.Control] = [
            ft.Row(
                [
                    ft.Icon(resolve_icon("insert_drive_file"), color=text_color, size=28),
                    ft.Column(
                        [
                            ft.Text(
                                filename,
                                weight=ft.FontWeight.W_600,
                                size=13,
                                color=text_color,
                                no_wrap=False,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        tight=True,
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=SPACE_SM,
            )
        ]
        if file_size or char_count:
            chips: List[ft.Control] = []
            if file_size:
                chips.append(
                    ft.Text(f"📄 {file_size}", size=11, color=text_color, italic=True)
                )
            if char_count:
                chips.append(
                    ft.Text(f"🔤 {char_count} chars", size=11, color=text_color, italic=True)
                )
            info_rows.append(
                ft.Row(chips, alignment=ft.MainAxisAlignment.CENTER, spacing=SPACE_MD)
            )
        content = ft.Column(
            info_rows,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=SPACE_SM,
        )
    else:
        content = ft.Column(
            [
                ft.Icon(resolve_icon(icon_name), size=48, color=border_color, opacity=0.8),
                ft.Text(
                    label,
                    size=14,
                    weight=ft.FontWeight.W_500,
                    color=text_color,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    sub_label,
                    size=11,
                    color=text_color,
                    opacity=0.6,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=SPACE_SM,
        )

    inner = ft.Container(
        content=content,
        border=ft.Border.all(2, border_color),
        border_radius=RADIUS_MD,
        bgcolor=bg_color,
        padding=ft.Padding.all(SPACE_LG),
        height=160,
        alignment=ft.Alignment.CENTER,
        expand=True,
    )

    return ft.GestureDetector(
        content=ft.Row([inner], spacing=0),
        on_tap=lambda _: on_pick(),
        mouse_cursor=ft.MouseCursor.CLICK,
    )


# ---------------------------------------------------------------------------
# Log terminal
# ---------------------------------------------------------------------------


def build_log_terminal(
    *,
    ref: Optional[ft.Ref] = None,
    max_height: int = 260,
    page: Optional[ft.Page] = None,
) -> ft.Container:
    """
    Build a scrollable, read-only log terminal widget.

    Args:
        ref: Optional ``ft.Ref[ft.ListView]`` to bind the inner list-view so
             callers can append entries programmatically.
        max_height: Maximum pixel height before vertical scrolling activates.
        page: Current Flet ``Page`` for palette derivation.

    Returns:
        A styled ``ft.Container`` wrapping a ``ft.ListView``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    bg = "#0d1117" if dark else "#f8f9fc"
    text_color = "#b0b8cc" if dark else "#3d4358"
    border_color = "#252a38" if dark else "#dce0ea"

    list_view = ft.ListView(
        expand=True,
        auto_scroll=True,
        spacing=1,
        padding=ft.Padding.all(SPACE_SM),
    )
    if ref is not None:
        ref.current = list_view

    return ft.Container(
        content=list_view,
        bgcolor=bg,
        border=ft.Border.all(1, border_color),
        border_radius=RADIUS_SM,
        height=max_height,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def log_entry(message: str, level: str = "info", page: Optional[ft.Page] = None) -> ft.Text:
    """
    Create a single log-line ``ft.Text`` widget with appropriate colour coding.

    Args:
        message: The log message string.
        level: Severity string: ``'info'``, ``'success'``, ``'error'``,
               ``'warning'``, ``'debug'``, ``'critical'``.
        page: Current Flet ``Page`` for dark/light mode detection.

    Returns:
        A styled ``ft.Text`` control.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    palette: dict[str, str] = {
        "info": "#9ba3b8" if dark else "#5a6172",
        "success": "#42ad4a" if dark else "#2e9437",
        "error": "#e84e3c" if dark else "#c0392b",
        "warning": "#f5a623" if dark else "#d4870a",
        "debug": "#5a6172" if dark else "#9ba3b8",
        "critical": "#ff5722",
        "trace": "#4e5568" if dark else "#b0b8cc",
    }
    color = palette.get(level.lower(), palette["info"])
    return ft.Text(message, size=12, color=color, selectable=True, no_wrap=False)


# ---------------------------------------------------------------------------
# Progress row
# ---------------------------------------------------------------------------


def build_progress_row(
    *,
    progress_value: float = 0.0,
    etr_text: str = "",
    page: Optional[ft.Page] = None,
) -> ft.Column:
    """
    Build a progress-bar + ETR-label column.

    Args:
        progress_value: Float in [0.0, 1.0].
        etr_text: Pre-formatted estimated-time-remaining string.
        page: Current ``Page`` for palette derivation.

    Returns:
        A ``ft.Column`` containing the progress bar and label.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    fill = "#5b8af5" if dark else "#3a5fc4"
    bg = "#1e2230" if dark else "#e4e8f0"

    bar = ft.ProgressBar(
        value=progress_value,
        color=fill,
        bgcolor=bg,
        height=8,
        border_radius=ft.BorderRadius.all(4),
        expand=True,
    )
    label = ft.Text(
        etr_text,
        size=11,
        color="#9ba3b8" if dark else "#5a6172",
        text_align=ft.TextAlign.CENTER,
    )
    return ft.Column(
        [bar, label],
        spacing=SPACE_SM,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Primary action button
# ---------------------------------------------------------------------------


def build_primary_button(
    text: str,
    *,
    icon: Optional[str] = None,
    on_click: Optional[Callable] = None,
    disabled: bool = False,
    width: Optional[int] = None,
    page: Optional[ft.Page] = None,
) -> ft.ElevatedButton:
    """
    Build a prominent, styled primary action button.

    Args:
        text: Button label.
        icon: Optional Flet icon name (e.g. ``'play_arrow'``).
        on_click: Click callback.
        disabled: Whether the button is non-interactive.
        width: Optional fixed pixel width.
        page: Current ``Page`` for accent colour derivation.

    Returns:
        A styled ``ft.ElevatedButton``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    bg = "#5b8af5" if dark else "#3a5fc4"
    on_bg = "#ffffff"

    style = ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: bg,
            ft.ControlState.HOVERED: "#3a5fc4" if dark else "#2a4fae",
            ft.ControlState.DISABLED: "#2a2f3f" if dark else "#c0c8d8",
        },
        color={
            ft.ControlState.DEFAULT: on_bg,
            ft.ControlState.DISABLED: "#4e5568" if dark else "#9ba3b8",
        },
        elevation={"default": 2, "hovered": 4},
        padding=ft.Padding.symmetric(horizontal=SPACE_LG, vertical=SPACE_MD),
        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
        animation_duration=150,
    )

    return ft.ElevatedButton(
        content=text,
        icon=resolve_icon(icon),
        on_click=on_click,
        disabled=disabled,
        width=width,
        style=style,
        height=48,
    )


# ---------------------------------------------------------------------------
# Secondary / ghost button
# ---------------------------------------------------------------------------


def build_secondary_button(
    text: str,
    *,
    icon: Optional[str] = None,
    on_click: Optional[Callable] = None,
    disabled: bool = False,
    page: Optional[ft.Page] = None,
) -> ft.OutlinedButton:
    """
    Build a secondary outlined button.

    Args:
        text: Button label.
        icon: Optional Flet icon name.
        on_click: Click callback.
        disabled: Whether the button is non-interactive.
        page: Current ``Page`` for border colour derivation.

    Returns:
        A styled ``ft.OutlinedButton``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    border_clr = "#3a4466" if dark else "#a8b4d0"
    text_clr = "#e8eaf0" if dark else "#1a1d27"

    style = ft.ButtonStyle(
        side={
            ft.ControlState.DEFAULT: ft.BorderSide(1.5, border_clr),
            ft.ControlState.HOVERED: ft.BorderSide(1.5, "#5b8af5" if dark else "#3a5fc4"),
        },
        color={
            ft.ControlState.DEFAULT: text_clr,
            ft.ControlState.HOVERED: "#5b8af5" if dark else "#3a5fc4",
            ft.ControlState.DISABLED: "#4e5568" if dark else "#9ba3b8",
        },
        padding=ft.Padding.symmetric(horizontal=SPACE_LG, vertical=SPACE_MD),
        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
        animation_duration=150,
    )

    return ft.OutlinedButton(
        content=text,
        icon=resolve_icon(icon),
        on_click=on_click,
        disabled=disabled,
        style=style,
        height=44,
    )


# ---------------------------------------------------------------------------
# Section card
# ---------------------------------------------------------------------------


def build_card(
    content: ft.Control,
    *,
    padding: int = SPACE_LG,
    page: Optional[ft.Page] = None,
) -> ft.Container:
    """
    Wrap a control in a styled card container.

    Args:
        content: The child control to embed.
        padding: Internal padding in pixels.
        page: Current ``Page`` for palette derivation.

    Returns:
        A styled ``ft.Container``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    bg = "#181b23" if dark else "#ffffff"
    border_clr = "#2c3147" if dark else "#dce0ea"

    return ft.Container(
        content=content,
        bgcolor=bg,
        border=ft.Border.all(1, border_clr),
        border_radius=RADIUS_MD,
        padding=ft.Padding.all(padding),
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=12,
            color=ft.Colors.with_opacity(0.12 if dark else 0.06, ft.Colors.BLACK),
            offset=ft.Offset(0, 2),
        ),
    )


# ---------------------------------------------------------------------------
# Section header
# ---------------------------------------------------------------------------


def build_section_header(
    title: str,
    *,
    subtitle: Optional[str] = None,
    icon: Optional[str] = None,
    page: Optional[ft.Page] = None,
) -> ft.Row:
    """
    Build a consistent section header row with an optional icon.

    Args:
        title: Section heading text.
        subtitle: Optional explanatory sub-text.
        icon: Optional Flet icon name.
        page: Current ``Page`` for palette derivation.

    Returns:
        A ``ft.Row`` containing the icon and text column.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    title_color = "#e8eaf0" if dark else "#1a1d27"
    sub_color = "#9ba3b8" if dark else "#5a6172"
    accent = "#5b8af5" if dark else "#3a5fc4"

    children: List[ft.Control] = []
    if icon:
        children.append(ft.Icon(resolve_icon(icon), size=20, color=accent))

    text_parts: List[ft.Control] = [
        ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=title_color)
    ]
    if subtitle:
        text_parts.append(ft.Text(subtitle, size=11, color=sub_color))

    children.append(
        ft.Column(text_parts, spacing=1, tight=True, expand=True)
    )

    return ft.Row(children, spacing=SPACE_SM, vertical_alignment=ft.CrossAxisAlignment.START)


# ---------------------------------------------------------------------------
# Status badge
# ---------------------------------------------------------------------------


def build_status_badge(
    label: str,
    *,
    variant: str = "info",
    page: Optional[ft.Page] = None,
) -> ft.Container:
    """
    Build a small status badge chip.

    Args:
        label: Badge text.
        variant: Colour variant: ``'info'``, ``'success'``, ``'error'``,
                 ``'warning'``, ``'neutral'``.
        page: Current ``Page`` for theme derivation.

    Returns:
        A pill-shaped ``ft.Container``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    palette = {
        "info":    ("#1a2a5e" if dark else "#dde8ff", "#5b8af5" if dark else "#3a5fc4"),
        "success": ("#0d2010" if dark else "#d4f4d7", "#42ad4a" if dark else "#2e9437"),
        "error":   ("#2a0a08" if dark else "#ffe0dc", "#e84e3c" if dark else "#c0392b"),
        "warning": ("#2a1a00" if dark else "#fff4d8", "#f5a623" if dark else "#d4870a"),
        "neutral": ("#1e2230" if dark else "#edf0f5", "#9ba3b8" if dark else "#5a6172"),
    }
    bg, fg = palette.get(variant, palette["info"])

    return ft.Container(
        content=ft.Text(label, size=10, weight=ft.FontWeight.W_600, color=fg),
        bgcolor=bg,
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
    )


# ---------------------------------------------------------------------------
# Labelled control row
# ---------------------------------------------------------------------------


def labelled_row(
    label: str,
    control: ft.Control,
    *,
    label_width: int = 200,
    tooltip: Optional[str] = None,
    page: Optional[ft.Page] = None,
) -> ft.Row:
    """
    Lay a label and a control side-by-side in a consistent row.

    Args:
        label: Human-readable label text.
        control: The UI control placed to the right of the label.
        label_width: Fixed pixel width of the label column.
        tooltip: Optional tooltip text on the label.
        page: Current ``Page`` for palette derivation.

    Returns:
        A ``ft.Row`` with the label pinned to a fixed width.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    lbl_color = "#9ba3b8" if dark else "#5a6172"

    lbl = ft.Text(label, size=13, color=lbl_color, weight=ft.FontWeight.W_500, width=label_width)
    if tooltip:
        lbl.tooltip = tooltip

    return ft.Row(
        [lbl, ft.Container(content=control, expand=True)],
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=SPACE_MD,
    )


# ---------------------------------------------------------------------------
# Snack-bar helper
# ---------------------------------------------------------------------------


def show_snack(
    page: ft.Page,
    message: str,
    *,
    error: bool = False,
    duration: int = 3000,
) -> None:
    """
    Display a brief snack-bar notification.

    Args:
        page: The Flet ``Page`` instance.
        message: Text to display.
        error: When True, colours the bar red instead of the default accent.
        duration: Visible duration in milliseconds.
    """
    dark = page.theme_mode == ft.ThemeMode.DARK
    bg = "#e84e3c" if error else ("#5b8af5" if dark else "#3a5fc4")
    page.snack_bar = ft.SnackBar(
        content=ft.Text(message, color="#ffffff", size=13),
        bgcolor=bg,
        duration=duration,
        show_close_icon=True,
        close_icon_color="#ffffff",
    )
    page.snack_bar.open = True
    page.update()


# ---------------------------------------------------------------------------
# Divider helper
# ---------------------------------------------------------------------------


def build_divider(page: Optional[ft.Page] = None) -> ft.Divider:
    """
    Build a styled horizontal rule divider.

    Args:
        page: Current ``Page`` for palette derivation.

    Returns:
        A ``ft.Divider``.
    """
    dark = page is not None and page.theme_mode == ft.ThemeMode.DARK
    return ft.Divider(color="#252a38" if dark else "#e8ebf2", height=1, thickness=1)
