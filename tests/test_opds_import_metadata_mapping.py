from __future__ import annotations

from abogen.webui.routes.api import _opds_metadata_overrides


def test_opds_metadata_overrides_maps_author_and_subtitle() -> None:
    overrides = _opds_metadata_overrides(
        {
            "authors": ["Alexandre Dumas"],
            "subtitle": "Unabridged",
            "series": "Example",
            "series_index": 2,
            "tags": ["Fiction", "Classic"],
            "summary": "Summary text",
        }
    )

    assert overrides["authors"] == "Alexandre Dumas"
    assert overrides["author"] == "Alexandre Dumas"
    assert overrides["subtitle"] == "Unabridged"

    # Existing behavior still present
    assert overrides["series"] == "Example"
    assert overrides["series_index"] == "2"
    assert overrides["tags"] == "Fiction, Classic"
    assert overrides["description"] == "Summary text"


def test_opds_metadata_overrides_accepts_author_string() -> None:
    overrides = _opds_metadata_overrides({"author": "Mary Shelley"})
    assert overrides["authors"] == "Mary Shelley"
    assert overrides["author"] == "Mary Shelley"
