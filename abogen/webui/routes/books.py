from typing import Any, Dict

from flask import Blueprint, render_template
from flask.typing import ResponseReturnValue

from abogen.webui.routes.utils.settings import (
    load_settings,
    load_integration_settings,
)
from abogen.webui.routes.utils.voice import template_options

books_bp = Blueprint("books", __name__)

def _calibre_integration_enabled(integrations: Dict[str, Any]) -> bool:
    calibre = integrations.get("calibre_opds", {})
    return bool(calibre.get("enabled") and calibre.get("base_url"))

@books_bp.get("/")
def find_books_page() -> ResponseReturnValue:
    settings = load_settings()
    integrations = load_integration_settings()
    return render_template(
        "find_books.html",
        integrations=integrations,
        opds_available=_calibre_integration_enabled(integrations),
        options=template_options(),
        settings=settings,
    )

@books_bp.get("/search")
def search_books() -> ResponseReturnValue:
    return find_books_page()


