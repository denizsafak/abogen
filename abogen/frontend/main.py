"""
Abogen Flet Frontend – main entry point.

Run as desktop app:
    python -m abogen.frontend.main

Run as web app (binds to port 8080 by default):
    python -m abogen.frontend.main --web --port 8080

Architecture
------------
One ``ft.app()`` call launches the server.  For every new browser tab (or the
desktop window) Flet invokes ``_app_entry(page)`` in its own coroutine, which
creates a fresh ``AppState`` and wires together the navigation rail and views.
This guarantees complete per-session isolation in multi-user web deployments.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import flet as ft

from .state import AppState
from .components import resolve_icon
from .views.dashboard import DashboardView
from .views.settings import SettingsView
from .views.queue_view import QueueView
from .utils.theme import make_theme, DARK, LIGHT, SPACE_SM, SPACE_MD, SPACE_LG, RADIUS_MD
from abogen.constants import PROGRAM_NAME as APP_NAME


# ---------------------------------------------------------------------------
# Navigation destinations
# ---------------------------------------------------------------------------

_NAV_ITEMS = [
    ("Convert", "swap_horiz", "swap_horiz"),
    ("Queue",   "list_alt",   "list_alt"),
    ("Settings", "settings",  "settings"),
]

_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


def _build_sidebar_item(
    *,
    label: str,
    icon: str,
    selected: bool,
    palette,
    on_click,
) -> ft.Container:
    accent = palette.accent if selected else palette.text_secondary
    bg = palette.sidebar_selected_bg if selected else palette.sidebar_bg
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(resolve_icon(icon), size=20, color=accent),
                ft.Text(
                    label,
                    size=13,
                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                    color=accent,
                ),
            ],
            spacing=SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=bg,
        border_radius=RADIUS_MD,
        padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=10),
        ink=True,
        on_click=on_click,
    )


# ---------------------------------------------------------------------------
# Per-session entry point
# ---------------------------------------------------------------------------

def _app_entry(page: ft.Page) -> None:
    try:
        # ── State ────────────────────────────────────────────────────────────
        state = AppState()
        state.load_from_config()

        # ── Page basics ──────────────────────────────────────────────────────
        page.title = APP_NAME
        page.padding = 0
        page.spacing = 0
        page.bgcolor = DARK.bg_base
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = make_theme(dark=True)
        page.dark_theme = make_theme(dark=True)
        page.fonts = {}
        page.window.min_width = 520
        page.window.min_height = 600
        page.update()

        # ── Content area ref ─────────────────────────────────────────────────
        content_area = ft.Column(expand=True, spacing=0)
        sidebar_body = ft.Column(spacing=SPACE_SM)
        theme_button_host = ft.Container()
        brand_title = ft.Text(
            APP_NAME,
            size=18,
            weight=ft.FontWeight.W_700,
            color=DARK.text_primary,
        )
        brand_fallback_icon = ft.Icon(resolve_icon("speaker_notes"), size=32, color=DARK.accent)
        divider = ft.VerticalDivider(width=1, color=DARK.border)

        # ── Views ────────────────────────────────────────────────────────────
        dashboard_view = DashboardView(page, state)
        settings_view = SettingsView(page, state)
        queue_view = QueueView(page, state)

        views = [
            dashboard_view.build,
            queue_view.build,
            settings_view.build,
        ]
        _selected_index = [0]

        def _refresh_sidebar() -> None:
            dark = page.theme_mode == ft.ThemeMode.DARK
            pal = DARK if dark else LIGHT
            sidebar_body.controls = [
                _build_sidebar_item(
                    label=label,
                    icon=icon,
                    selected=index == _selected_index[0],
                    palette=pal,
                    on_click=lambda _, i=index: _navigate(i),
                )
                for index, (label, icon, _) in enumerate(_NAV_ITEMS)
            ]
            sidebar.bgcolor = pal.sidebar_bg
            divider.color = pal.border
            brand_title.color = pal.text_primary
            brand_fallback_icon.color = pal.accent
            theme_button_host.content = ft.Container(
                content=ft.Icon(
                    resolve_icon("dark_mode" if dark else "light_mode"),
                    size=20,
                    color=pal.text_secondary,
                ),
                tooltip="Toggle theme",
                border_radius=RADIUS_MD,
                padding=8,
                ink=True,
                on_click=lambda _: _toggle_theme(page, _refresh_sidebar),
            )

        def _navigate(index: int) -> None:
            _selected_index[0] = index
            content_area.controls.clear()
            built = views[index]()
            content_area.controls.append(
                ft.Container(
                    content=built,
                    expand=True,
                    padding=ft.Padding.symmetric(horizontal=SPACE_LG, vertical=SPACE_LG),
                )
            )
            _refresh_sidebar()
            page.update()

        # ── Sidebar ──────────────────────────────────────────────────────────
        pal = DARK
        sidebar = ft.Container(
            width=220,
            bgcolor=pal.sidebar_bg,
            padding=ft.Padding.all(SPACE_MD),
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Image(
                                    src="icon.png",
                                    width=36,
                                    height=36,
                                    fit=ft.BoxFit.CONTAIN,
                                    error_content=brand_fallback_icon,
                                ),
                                brand_title,
                            ],
                            spacing=SPACE_MD,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.only(top=SPACE_SM, bottom=SPACE_LG),
                    ),
                    sidebar_body,
                    ft.Container(expand=True),
                    ft.Row([theme_button_host], alignment=ft.MainAxisAlignment.END),
                ],
                expand=True,
                spacing=SPACE_SM,
            ),
        )
        _refresh_sidebar()

        # ── Page handle for pubsub (queue → dashboard) ───────────────────────
        def _handle_pubsub(topic: str) -> None:
            if topic == "start_queue":
                _navigate(0)

        page.pubsub.subscribe(_handle_pubsub)

        # ── Layout ────────────────────────────────────────────────────────────
        page.add(
            ft.Row(
                [
                    sidebar,
                    divider,
                    ft.Container(content=content_area, expand=True),
                ],
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

        # Show dashboard by default
        _navigate(0)
        page.update()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR IN _app_entry: {e}")
        raise


def _toggle_theme(page: ft.Page, refresh_sidebar) -> None:
    """Switch between dark and light theme modes."""
    if page.theme_mode == ft.ThemeMode.DARK:
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = LIGHT.bg_base
    else:
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = DARK.bg_base

    page.theme = make_theme(page.theme_mode == ft.ThemeMode.DARK)
    refresh_sidebar()
    page.update()


# ---------------------------------------------------------------------------
# CLI helpers & entry point
# ---------------------------------------------------------------------------

def _is_port_free(host: str, port: int) -> bool:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def _find_free_port(host: str, start_port: int) -> int:
    import socket
    port = start_port
    while port < 65535:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError:
            port += 1
    return start_port


def main() -> None:
    """
    Start the Abogen Flet frontend.

    Parses ``--web`` and ``--port`` CLI arguments to choose desktop vs. web
    mode, then hands control to ``ft.app()``.
    """
    import logging
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("flet").setLevel(logging.INFO)

    parser = argparse.ArgumentParser(description=f"{APP_NAME} – Flet frontend")
    parser.add_argument(
        "--web", action="store_true",
        help="Run as a web server instead of a desktop window.",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Port for the web server (default: 8080). Ignored in desktop mode.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for the web server (default: 127.0.0.1). Use 0.0.0.0 to expose publicly.",
    )
    args = parser.parse_args()

    if args.web:
        port_specified = "--port" in sys.argv
        target_port = args.port

        if not port_specified:
            target_port = _find_free_port(args.host, 8080)
            if target_port != 8080:
                print(f"Port 8080 is in use. Automatically routed to free port: {target_port}")
        else:
            if not _is_port_free(args.host, target_port):
                print(f"Error: Port {target_port} is already in use on {args.host}.", file=sys.stderr)
                print("Please select a different port or omit the --port flag to find one automatically.", file=sys.stderr)
                sys.exit(1)

        print(f"Starting Abogen WebUI on http://{args.host}:{target_port} ...")
        ft.app(
            target=_app_entry,
            view=ft.AppView.WEB_BROWSER,
            port=target_port,
            host=args.host,
            assets_dir=str(_ASSETS_DIR) if _ASSETS_DIR.exists() else None,
            no_cdn=True,
            web_renderer="canvaskit",
        )
    else:
        try:
            ft.app(
                target=_app_entry,
                view=ft.AppView.FLET_APP,
                assets_dir=str(_ASSETS_DIR) if _ASSETS_DIR.exists() else None,
            )
        except Exception as e:
            print(f"Warning: Failed to launch native desktop window: {e}", file=sys.stderr)
            print("Falling back to running as a web application in your default browser...", file=sys.stderr)
            target_port = _find_free_port("127.0.0.1", 8080)
            print(f"Starting Abogen WebUI on http://127.0.0.1:{target_port} ...")
            ft.app(
                target=_app_entry,
                view=ft.AppView.WEB_BROWSER,
                port=target_port,
                host="127.0.0.1",
                assets_dir=str(_ASSETS_DIR) if _ASSETS_DIR.exists() else None,
                no_cdn=True,
                web_renderer="canvaskit",
            )


def main_web() -> None:
    """
    Start the Abogen Flet frontend as a web server.
    """
    import sys
    if "--web" not in sys.argv:
        sys.argv.insert(1, "--web")
    main()


if __name__ == "__main__":
    main()
