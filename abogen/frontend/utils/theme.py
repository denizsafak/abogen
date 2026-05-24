"""
Design tokens and theme configuration for the Abogen Flet frontend.

This module defines the application's complete colour palette, typography
scale, spacing constants, and border radii in one canonical place.
All component modules import from here; changing a value here propagates
instantly across the entire UI.

Flet's ``ft.Theme`` uses ``ColorScheme``, but for custom widgets we paint
directly with hex colours drawn from ``LIGHT`` and ``DARK`` palettes.
"""

from __future__ import annotations

import flet as ft
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Palette:
    """A complete colour palette for one theme mode."""

    # Backgrounds
    bg_base: str        # Deepest background (window / page)
    bg_surface: str     # Cards, panels, dialogs
    bg_elevated: str    # Slightly raised elements (toolbar, sidebar)
    bg_input: str       # Text-field / dropdown backgrounds

    # Brand accent
    accent: str         # Primary interactive colour (buttons, links)
    accent_muted: str   # Hover tint over accents
    accent_on: str      # Text drawn on top of accent fills

    # Semantic
    success: str
    error: str
    warning: str
    info: str

    # Text hierarchy
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str

    # Borders / dividers
    border: str
    border_focused: str
    divider: str

    # Specific UI atoms
    drop_zone_border: str
    drop_zone_bg: str
    drop_zone_active_border: str
    drop_zone_active_bg: str
    log_bg: str
    log_text: str
    progress_bar_bg: str
    progress_bar_fill: str
    sidebar_bg: str
    sidebar_selected_bg: str
    sidebar_selected_text: str
    nav_indicator: str


DARK = _Palette(
    bg_base="#0f1117",
    bg_surface="#181b23",
    bg_elevated="#1e2230",
    bg_input="#252a38",

    accent="#5b8af5",
    accent_muted="#3a5fc4",
    accent_on="#ffffff",

    success="#42ad4a",
    error="#e84e3c",
    warning="#f5a623",
    info="#5b8af5",

    text_primary="#e8eaf0",
    text_secondary="#9ba3b8",
    text_disabled="#4e5568",
    text_on_accent="#ffffff",

    border="#2c3147",
    border_focused="#5b8af5",
    divider="#252a38",

    drop_zone_border="#3a4466",
    drop_zone_bg="#151928",
    drop_zone_active_border="#42ad4a",
    drop_zone_active_bg="#0d1f10",
    log_bg="#0d1117",
    log_text="#b0b8cc",
    progress_bar_bg="#1e2230",
    progress_bar_fill="#5b8af5",
    sidebar_bg="#13161f",
    sidebar_selected_bg="#252a38",
    sidebar_selected_text="#5b8af5",
    nav_indicator="#5b8af5",
)

LIGHT = _Palette(
    bg_base="#f4f5f8",
    bg_surface="#ffffff",
    bg_elevated="#edf0f5",
    bg_input="#f0f2f7",

    accent="#3a5fc4",
    accent_muted="#2a4fae",
    accent_on="#ffffff",

    success="#2e9437",
    error="#c0392b",
    warning="#d4870a",
    info="#3a5fc4",

    text_primary="#1a1d27",
    text_secondary="#5a6172",
    text_disabled="#9ba3b8",
    text_on_accent="#ffffff",

    border="#dce0ea",
    border_focused="#3a5fc4",
    divider="#e8ebf2",

    drop_zone_border="#a8b4d0",
    drop_zone_bg="#f7f8fd",
    drop_zone_active_border="#2e9437",
    drop_zone_active_bg="#f0fff1",
    log_bg="#f8f9fc",
    log_text="#3d4358",
    progress_bar_bg="#e4e8f0",
    progress_bar_fill="#3a5fc4",
    sidebar_bg="#eff1f5",
    sidebar_selected_bg="#dde3f2",
    sidebar_selected_text="#3a5fc4",
    nav_indicator="#3a5fc4",
)


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

FONT_FAMILY = "Inter, Segoe UI, Roboto, system-ui, sans-serif"
FONT_SIZE_XS = 11
FONT_SIZE_SM = 12
FONT_SIZE_BASE = 14
FONT_SIZE_MD = 16
FONT_SIZE_LG = 20
FONT_SIZE_XL = 26
FONT_SIZE_DISPLAY = 34


# ---------------------------------------------------------------------------
# Spacing scale (pixels)
# ---------------------------------------------------------------------------

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32
SPACE_3XL = 48


# ---------------------------------------------------------------------------
# Border radii
# ---------------------------------------------------------------------------

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 16
RADIUS_FULL = 999  # Pill-shaped


# ---------------------------------------------------------------------------
# Flet ColorScheme builders
# ---------------------------------------------------------------------------


def build_color_scheme(palette: _Palette) -> ft.ColorScheme:
    """
    Construct a ``ft.ColorScheme`` from a ``_Palette`` object.

    Args:
        palette: The ``DARK`` or ``LIGHT`` palette.

    Returns:
        A fully-populated Flet ``ColorScheme``.
    """
    return ft.ColorScheme(
        primary=palette.accent,
        on_primary=palette.accent_on,
        primary_container=palette.accent_muted,
        secondary=palette.accent,
        on_secondary=palette.text_on_accent,
        surface=palette.bg_surface,
        on_surface=palette.text_primary,
        on_surface_variant=palette.text_secondary,
        error=palette.error,
        on_error=palette.text_on_accent,
        outline=palette.border,
    )


def build_text_theme() -> ft.TextTheme:
    """
    Construct a ``ft.TextTheme`` using the application's type scale.

    Returns:
        A Flet ``TextTheme`` with consistent font-size assignments.
    """
    return ft.TextTheme(
        display_large=ft.TextStyle(size=FONT_SIZE_DISPLAY, weight=ft.FontWeight.W_700),
        headline_large=ft.TextStyle(size=FONT_SIZE_XL, weight=ft.FontWeight.W_700),
        headline_medium=ft.TextStyle(size=FONT_SIZE_LG, weight=ft.FontWeight.W_600),
        title_large=ft.TextStyle(size=FONT_SIZE_MD, weight=ft.FontWeight.W_600),
        title_medium=ft.TextStyle(size=FONT_SIZE_BASE, weight=ft.FontWeight.W_500),
        body_large=ft.TextStyle(size=FONT_SIZE_BASE),
        body_medium=ft.TextStyle(size=FONT_SIZE_SM),
        label_large=ft.TextStyle(size=FONT_SIZE_SM, weight=ft.FontWeight.W_500),
        label_medium=ft.TextStyle(size=FONT_SIZE_XS),
    )


def make_theme(dark: bool) -> ft.Theme:
    """
    Build a complete Flet ``Theme`` for the requested mode.

    Args:
        dark: True for dark-mode theme, False for light-mode theme.

    Returns:
        A configured ``ft.Theme`` instance.
    """
    palette = DARK if dark else LIGHT
    return ft.Theme(
        color_scheme=build_color_scheme(palette),
        text_theme=build_text_theme(),
        color_scheme_seed=palette.accent,
        use_material3=True,
    )


def get_palette(page: ft.Page) -> _Palette:
    """
    Return the active colour palette for the given page.

    Args:
        page: The Flet ``Page`` instance.

    Returns:
        ``DARK`` or ``LIGHT`` depending on the page's theme mode.
    """
    return DARK if page.theme_mode == ft.ThemeMode.DARK else LIGHT
