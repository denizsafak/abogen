"""Text utility functions for the domain layer."""

from __future__ import annotations

import re
from typing import Any

# Pre-compiled patterns for calculate_text_length
_METADATA_TAG_PATTERN = re.compile(r"<<METADATA_[^:]+:[^>]*>>")
_CHAPTER_MARKER_PATTERN = re.compile(r"<<CHAPTER_MARKER:[^>]*>>")
_VOICE_MARKER_PATTERN = re.compile(r"<<VOICE:[^>]*>>")


def calculate_text_length(text: str) -> int:
    """Calculate character count, ignoring internal markers and newlines.

    Strips chapter markers, voice markers, and metadata tags before counting.
    """
    text = _CHAPTER_MARKER_PATTERN.sub("", text)
    text = _VOICE_MARKER_PATTERN.sub("", text)
    text = _METADATA_TAG_PATTERN.sub("", text)
    text = text.replace("\n", "").strip()
    return len(text)


# Block-level HTML tags that must be separated by a paragraph break when
# converting EPUB/XHTML to plain text. The original list only covered
# p/div/h1-h6/li/blockquote, so boundaries marked up with <section>,
# <article>, table cells, etc. — and crucially <br> — were concatenated
# with ZERO characters (e.g. 'it."Test'), which also broke subtitles.
HTML_BLOCK_TAGS = (
    "p",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "blockquote",
    "section",
    "article",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
    "figure",
    "figcaption",
    "pre",
    "address",
    "table",
    "tr",
    "td",
    "th",
    "dl",
    "dt",
    "dd",
    "ul",
    "ol",
)


def prepare_soup_block_breaks(soup: Any) -> Any:
    """Insert explicit break markers into a BeautifulSoup tree.

    - Every <br> becomes a single newline (line break; two in a row
      naturally form a paragraph break that survives ``clean_text``).
    - Every <hr> becomes a paragraph break.
    - Every block-level tag gets a trailing paragraph break so
      ``soup.get_text()`` never concatenates two blocks with zero
      characters. ``clean_text`` later collapses runs of 3+ newlines
      to exactly two, so nested blocks are safe.

    Returns the same soup for chaining. Operates in place.
    """
    from bs4 import NavigableString  # type: ignore[import]

    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for hr in soup.find_all("hr"):
        hr.replace_with(NavigableString("\n\n"))
    for tag in soup.find_all(list(HTML_BLOCK_TAGS)):
        tag.append(NavigableString("\n\n"))
    return soup
