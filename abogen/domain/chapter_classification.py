"""Heuristics for classifying chapters as content vs. supplements.

A 'supplement' is any non-story material that a listener would typically
skip: title page, copyright, table of contents, acknowledgements, etc.
The scoring functions return a float; higher ⇒ more likely to be a
supplement.  ``should_preselect_chapter`` turns that score into a
boolean suitable for a web form default.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Compiled once at module load – these are immutable.

_SUPPLEMENT_TITLE_PATTERNS: List[Tuple[re.Pattern[str], float]] = [
    (re.compile(r"\btitle\s+page\b"), 3.0),
    (re.compile(r"\bcopyright\b"), 2.4),
    (re.compile(r"\btable\s+of\s+contents\b"), 2.8),
    (re.compile(r"\bcontents\b"), 2.0),
    (re.compile(r"\backnowledg(e)?ments?\b"), 2.0),
    (re.compile(r"\bdedication\b"), 2.0),
    (re.compile(r"\babout\s+the\s+author(s)?\b"), 2.4),
    (re.compile(r"\balso\s+by\b"), 2.0),
    (re.compile(r"\bpraise\s+for\b"), 2.0),
    (re.compile(r"\bcolophon\b"), 2.2),
    (re.compile(r"\bpublication\s+data\b"), 2.2),
    (re.compile(r"\btranscriber'?s?\s+note\b"), 2.2),
    (re.compile(r"\bglossary\b"), 2.2),
    (re.compile(r"\bindex\b"), 2.0),
    (re.compile(r"\bbibliograph(y|ies)\b"), 2.0),
    (re.compile(r"\breferences\b"), 1.8),
    (re.compile(r"\bappendix\b"), 1.9),
]

_CONTENT_TITLE_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bchapter\b"),
    re.compile(r"\bbook\b"),
    re.compile(r"\bpart\b"),
    re.compile(r"\bsection\b"),
    re.compile(r"\bscene\b"),
    re.compile(r"\bprologue\b"),
    re.compile(r"\bepilogue\b"),
    re.compile(r"\bintroduction\b"),
    re.compile(r"\bstory\b"),
]

_SUPPLEMENT_TEXT_KEYWORDS: List[Tuple[str, float]] = [
    ("copyright", 1.2),
    ("all rights reserved", 1.1),
    ("isbn", 0.9),
    ("library of congress", 1.0),
    ("table of contents", 1.0),
    ("dedicated to", 0.8),
    ("acknowledg", 0.8),
    ("printed in", 0.6),
    ("permission", 0.6),
    ("publisher", 0.5),
    ("praise for", 0.9),
    ("also by", 0.9),
    ("glossary", 0.8),
    ("index", 0.8),
    ("newsletter", 3.2),
    ("mailing list", 2.6),
    ("sign-up", 2.2),
]


def supplement_score(title: str, text: str, index: int) -> float:
    """Return a score indicating how likely *title*/*text* is a supplement.

    Higher values ⇒ more likely to be non-story material (title page,
    copyright, acknowledgements, etc.).
    """
    normalized_title = (title or "").lower()
    score = 0.0

    for pattern, weight in _SUPPLEMENT_TITLE_PATTERNS:
        if pattern.search(normalized_title):
            score += weight

    for pattern in _CONTENT_TITLE_PATTERNS:
        if pattern.search(normalized_title):
            score -= 2.0

    stripped_text = (text or "").strip()
    length = len(stripped_text)
    if length <= 150:
        score += 0.9
    elif length <= 400:
        score += 0.6
    elif length <= 800:
        score += 0.35

    lowercase_text = stripped_text.lower()
    for keyword, weight in _SUPPLEMENT_TEXT_KEYWORDS:
        if keyword in lowercase_text:
            score += weight

    if index == 0 and score > 0:
        score += 0.25

    return score


def should_preselect_chapter(
    title: str,
    text: str,
    index: int,
    total_count: int,
) -> bool:
    """Return True if the chapter should be *enabled* by default in the form.

    A single chapter is always preselected.  For multi-chapter books, the
    chapter is preselected when its supplement score is below 1.9.
    """
    if total_count <= 1:
        return True
    score = supplement_score(title, text, index)
    return score < 1.9


def ensure_at_least_one_chapter_enabled(chapters: List[Dict[str, Any]]) -> None:
    """Mutate *chapters* in-place so that at least one has ``enabled=True``."""
    if not chapters:
        return
    if any(chapter.get("enabled") for chapter in chapters):
        return
    best_index = max(range(len(chapters)), key=lambda idx: chapters[idx].get("characters", 0))
    chapters[best_index]["enabled"] = True
