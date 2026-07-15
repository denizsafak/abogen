from __future__ import annotations

import re
from typing import List, Tuple


_HEADING_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
_HEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?P<number>(?:\d+|[ivxlcdm]+))(?P<suffix>(?:[\s.:;-].*)?)$",
    re.IGNORECASE,
)
_ACRONYM_ALLOWLIST = {
    "AI", "API", "CPU", "DIY", "GPU", "HTML", "HTTP", "HTTPS", "ID",
    "JSON", "MP3", "MP4", "M4B", "NASA", "OCR", "PDF", "SQL", "TV",
    "TTS", "UK", "UN", "UFO", "OK", "URL", "USA", "US", "VR",
}
_ROMAN_NUMERAL_CHARS = frozenset("IVXLCDM")
_CAPS_WORD_RE = re.compile(r"[A-Z][A-Z0-9'\u2019-]*")


def simplify_heading_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    simplified = _HEADING_SANITIZE_RE.sub("", raw)
    if simplified.startswith("chapter"):
        simplified = simplified[7:]
    return simplified


def headings_equivalent(left: str, right: str) -> bool:
    simple_left = simplify_heading_text(left)
    simple_right = simplify_heading_text(right)
    if not simple_left or not simple_right:
        return False
    if simple_left == simple_right:
        return True
    if simple_right.startswith(simple_left):
        return True
    if simple_left.startswith(simple_right):
        return True
    if len(simple_left) > 5 and simple_left in simple_right:
        return True
    return False


def strip_duplicate_heading_line(text: str, heading: str) -> Tuple[str, bool]:
    source_text = str(text or "")
    if not source_text:
        return source_text, False
    normalized_heading = simplify_heading_text(heading)
    if not normalized_heading:
        return source_text, False
    lines = source_text.splitlines()
    new_lines: List[str] = []
    removed = False
    for line in lines:
        stripped = line.strip()
        if not removed and stripped:
            if headings_equivalent(stripped, heading):
                removed = True
                continue
        new_lines.append(line)
    if not removed:
        return source_text, False
    while new_lines and not new_lines[0].strip():
        new_lines.pop(0)
    return "\n".join(new_lines), True


def normalize_caps_word(word: str) -> str:
    upper = word.upper()
    letters = [char for char in upper if char.isalpha()]
    if not letters:
        return word
    if upper in _ACRONYM_ALLOWLIST:
        return word
    if len(letters) <= 1:
        return word
    if all(char in _ROMAN_NUMERAL_CHARS for char in letters) and len(letters) <= 7:
        return word

    parts = re.split(r"(['\-\u2019])", word)
    normalized_parts: List[str] = []
    for part in parts:
        if part in {"'", "-", "\u2019"}:
            normalized_parts.append(part)
            continue
        if not part:
            continue
        normalized_parts.append(part[0].upper() + part[1:].lower())
    return "".join(normalized_parts) or word


def normalize_chapter_opening_caps(text: str) -> Tuple[str, bool]:
    if not text:
        return text, False

    leading_len = len(text) - len(text.lstrip())
    leading = text[:leading_len]
    working = text[leading_len:]
    if not working:
        return text, False

    builder: List[str] = []
    pos = 0
    changed = False

    while pos < len(working):
        char = working[pos]
        if char in "\r\n":
            builder.append(working[pos:])
            pos = len(working)
            break
        if char.isspace():
            builder.append(char)
            pos += 1
            continue
        if char.islower():
            builder.append(working[pos:])
            pos = len(working)
            break
        if not char.isalpha():
            builder.append(char)
            pos += 1
            continue

        match = _CAPS_WORD_RE.match(working, pos)
        if not match:
            builder.append(char)
            pos += 1
            continue

        word = match.group(0)
        if any(ch.islower() for ch in word):
            builder.append(working[pos:])
            pos = len(working)
            break

        normalized = normalize_caps_word(word)
        if normalized != word:
            changed = True
        builder.append(normalized)
        pos = match.end()

    if pos < len(working):
        builder.append(working[pos:])

    if not changed:
        return text, False

    return leading + "".join(builder), True


def format_spoken_chapter_title(title: str, index: int, apply_prefix: bool) -> str:
    base = str(title or "").strip()
    if not base:
        return f"Chapter {index}" if apply_prefix else ""
    if not apply_prefix:
        return base
    lowered = base.lower()
    if lowered.startswith("chapter") and (len(lowered) == 7 or not lowered[7].isalpha()):
        return base
    match = _HEADING_NUMBER_PREFIX_RE.match(base)
    if match:
        number = match.group("number") or ""
        suffix = match.group("suffix") or ""
        cleaned_suffix = suffix.lstrip(" .,:;-_ \t\u2013\u2014\u00b7\u2022")
        if cleaned_suffix:
            return f"Chapter {number}. {cleaned_suffix}"
        return f"Chapter {number}"
    return base


def apply_chapter_text_transforms(
    text: str,
    *,
    heading_text: str,
    raw_title: str,
    strip_heading: bool,
    normalize_caps: bool,
) -> Tuple[str, bool, bool]:
    """Strip duplicate heading and normalize opening caps.

    Returns ``(text, heading_removed, caps_changed)``.
    The caller is responsible for state updates (pending flags, logging,
    dict mutation, ``continue``).
    """
    heading_removed = False
    caps_changed = False

    if strip_heading and heading_text:
        text, heading_removed = strip_duplicate_heading_line(text, heading_text)
        if not heading_removed and raw_title:
            match = _HEADING_NUMBER_PREFIX_RE.match(raw_title)
            if match:
                number = match.group("number")
                if number:
                    text, heading_removed = strip_duplicate_heading_line(text, number)

    if normalize_caps and text:
        text, caps_changed = normalize_chapter_opening_caps(text)

    return text, heading_removed, caps_changed
