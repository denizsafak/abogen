from __future__ import annotations

import json
import re
import unicodedata
import os
import locale
from fractions import Fraction
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency guard
    from num2words import num2words
except ImportError:
    num2words = None
    logger.warning(
        "num2words library not found. Number normalization will be disabled."
    )
except Exception as e:  # pragma: no cover - graceful degradation
    num2words = None
    logger.error(f"Failed to import num2words: {e}")

HAS_NUM2WORDS = num2words is not None

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from abogen.llm_client import LLMCompletion

from abogen.spacy_contraction_resolver import resolve_ambiguous_contractions

# ---------- Contraction Category Defaults ----------

CONTRACTION_CATEGORY_DEFAULTS: Dict[str, bool] = {
    "contraction_aux_be": True,
    "contraction_aux_have": True,
    "contraction_modal_will": True,
    "contraction_modal_would": True,
    "contraction_negation_not": True,
    "contraction_let_us": True,
}

# ---------- Configuration Dataclass ----------


@dataclass
class ApostropheConfig:
    contraction_mode: str = "expand"  # expand|collapse|keep
    possessive_mode: str = "keep"  # keep|collapse
    plural_possessive_mode: str = "collapse"  # keep|collapse
    irregular_possessive_mode: str = (
        "keep"  # keep|expand (expand just means keep or add hints; modify if needed)
    )
    sibilant_possessive_mode: str = "mark"  # keep|mark|approx
    fantasy_mode: str = "keep"  # keep|mark|collapse_internal
    acronym_possessive_mode: str = "keep"  # keep|collapse_add_s
    decades_mode: str = "expand"  # keep|expand
    leading_elision_mode: str = "expand"  # keep|expand
    ambiguous_past_modal_mode: str = (
        "contextual"  # keep|expand_prefer_would|expand_prefer_had|contextual
    )
    add_phoneme_hints: bool = True  # Whether to emit markers like ‹IZ›
    fantasy_marker: str = "‹FAP›"  # Marker inserted if fantasy_mode == mark
    sibilant_iz_marker: str = "‹IZ›"  # Marker for /ɪz/ insertion
    joiner: str = ""  # Replacement used when collapsing internal apostrophes
    lowercase_for_matching: bool = (
        True  # Normalize to lower for rule matching (not output)
    )
    protect_cultural_names: bool = True  # Always keep O'Brien, D'Angelo, etc.
    convert_numbers: bool = True  # Convert grouped numbers such as 12,500 to words
    convert_currency: bool = True  # Convert currency symbols to words
    remove_footnotes: bool = True  # Remove footnote indicators
    number_lang: str = "en"  # num2words language code
    year_pronunciation_mode: str = "american"  # off|american (extend if needed)
    contraction_categories: Dict[str, bool] = field(
        default_factory=lambda: dict(CONTRACTION_CATEGORY_DEFAULTS)
    )

    def is_contraction_enabled(self, category: str) -> bool:
        return self.contraction_categories.get(category, True)


# ---------- Dictionaries / Patterns ----------

# Common contraction expansions (type + expansion words)
CONTRACTION_LEXICON: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "let's": ("contraction_let_us", ("let", "us")),
    "can't": ("contraction_negation_not", ("can", "not")),
    "won't": ("contraction_negation_not", ("will", "not")),
    "don't": ("contraction_negation_not", ("do", "not")),
    "doesn't": ("contraction_negation_not", ("does", "not")),
    "didn't": ("contraction_negation_not", ("did", "not")),
    "isn't": ("contraction_negation_not", ("is", "not")),
    "aren't": ("contraction_negation_not", ("are", "not")),
    "wasn't": ("contraction_negation_not", ("was", "not")),
    "weren't": ("contraction_negation_not", ("were", "not")),
    "haven't": ("contraction_negation_not", ("have", "not")),
    "hasn't": ("contraction_negation_not", ("has", "not")),
    "hadn't": ("contraction_negation_not", ("had", "not")),
    "couldn't": ("contraction_negation_not", ("could", "not")),
    "shouldn't": ("contraction_negation_not", ("should", "not")),
    "wouldn't": ("contraction_negation_not", ("would", "not")),
    "mustn't": ("contraction_negation_not", ("must", "not")),
    "mightn't": ("contraction_negation_not", ("might", "not")),
    "shan't": ("contraction_negation_not", ("shall", "not")),
}

SUFFIX_CONTRACTION_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("'ll", "will", "contraction_modal_will"),
    ("'re", "are", "contraction_aux_be"),
    ("'ve", "have", "contraction_aux_have"),
)

SUFFIX_CONTRACTION_BASES: Dict[str, Tuple[str, ...]] = {
    "'m": ("i",),
}

# For ambiguous 'd and 's we handle separately
_NUMBER_WITH_GROUP_RE = re.compile(r"(?<![\w\d])(-?\d{1,3}(?:,\d{3})+)(?![\w\d])")
_NUMBER_RANGE_SEPARATORS = "-‐‑–—−"
_NUMBER_RANGE_CLASS = re.escape(_NUMBER_RANGE_SEPARATORS)
_NUMBER_CORE_PATTERN = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)"
_WIDE_RANGE_SEPARATORS = {"–", "—"}
_NUMBER_RANGE_RE = re.compile(
    rf"(?<!\w)(?P<left>{_NUMBER_CORE_PATTERN})(?P<sep>\s*[{_NUMBER_RANGE_CLASS}]\s*)(?P<right>{_NUMBER_CORE_PATTERN})(?![\w{_NUMBER_RANGE_CLASS}/])"
)
_NUMBER_SPACE_RANGE_RE = re.compile(
    rf"(?<![\w{_NUMBER_RANGE_CLASS}/])(?P<left>{_NUMBER_CORE_PATTERN})(?P<gap>\s+)(?P<right>{_NUMBER_CORE_PATTERN})(?![\w{_NUMBER_RANGE_CLASS}/])"
)
_FRACTION_SLASHES = "/⁄"
_FRACTION_SLASH_CLASS = re.escape(_FRACTION_SLASHES)
_FRACTION_RE = re.compile(
    rf"(?<!\w)(?P<numerator>-?\d+)\s*[{_FRACTION_SLASH_CLASS}]\s*(?P<denominator>-?\d+)(?![\w{_FRACTION_SLASH_CLASS}])"
)

_CURRENCY_RE = re.compile(
    r"(?P<symbol>[$£€¥])\s*(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d+)?)(?:\s+(?P<magnitude>hundred|thousand|million|billion|trillion|quadrillion))?(?!\d)",
    re.IGNORECASE,
)

_URL_RE = re.compile(
    r"(https?://)?(www\.)?(?P<domain>[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+)(/[^\s]*)?"
)
_FOOTNOTE_RE = re.compile(r"([a-zA-Z]+)(\d+)")
_BRACKET_FOOTNOTE_RE = re.compile(r"\[\d+\]")

_ISO_DATE_RE = re.compile(
    r"\b(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})\b"
)
_MDY_DATE_RE = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*,\s*(?P<year>\d{4})\b",
    re.IGNORECASE,
)

_TIME_RE = re.compile(
    r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridian>a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)

_ADDRESS_ABBR_RE = re.compile(
    r"(?P<prefix>\b\w+\s+)(?P<abbr>St|Rd|Ave|Blvd|Ln|Dr)\.(?=\s*(?:,|\.|!|\?|$))"
)

_MONTH_MAP = {
    "jan": "January",
    "january": "January",
    "feb": "February",
    "february": "February",
    "mar": "March",
    "march": "March",
    "apr": "April",
    "april": "April",
    "may": "May",
    "jun": "June",
    "june": "June",
    "jul": "July",
    "july": "July",
    "aug": "August",
    "august": "August",
    "sep": "September",
    "sept": "September",
    "september": "September",
    "oct": "October",
    "october": "October",
    "nov": "November",
    "november": "November",
    "dec": "December",
    "december": "December",
}


def _is_us_locale() -> bool:
    for key in ("LC_ALL", "LC_TIME", "LANG"):
        value = os.environ.get(key)
        if value and "en_US" in value:
            return True
    try:
        loc = locale.getlocale(locale.LC_TIME)
        if loc and loc[0] and "en_US" in loc[0]:
            return True
    except Exception:
        pass
    return False


def _year_to_words_american(value: int, language: str) -> str:
    if language.lower().startswith("en") and 2000 <= value <= 2099:
        if value == 2000:
            return "two thousand"
        if 2001 <= value <= 2009:
            tail = _DIGIT_WORDS[value % 10]
            return f"two thousand {tail}"

        first_two = value // 100
        last_two = value % 100
        first_words = _int_to_words(first_two, language) or "twenty"
        if last_two == 0:
            return f"{first_words} hundred"
        if last_two < 10:
            return f"{first_words} oh {_DIGIT_WORDS[last_two]}"
        last_words = _int_to_words(last_two, language)
        return f"{first_words} {last_words or last_two}"

    words = _int_to_words(value, language)
    return words or str(value)


def _normalize_dates(text: str, language: str) -> str:
    us = _is_us_locale()

    def _format_iso(match: re.Match[str]) -> str:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        month_name = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ][month - 1]
        ordinal = _int_to_ordinal_words(day, language) or str(day)
        year_words = _year_to_words_american(year, language)
        return (
            f"{month_name} {ordinal}, {year_words}"
            if us
            else f"{ordinal} {month_name} {year_words}"
        )

    def _format_mdy(match: re.Match[str]) -> str:
        month_raw = str(match.group("month") or "").strip().lower().rstrip(".")
        month_name = _MONTH_MAP.get(month_raw)
        if not month_name:
            return match.group(0)
        day = int(match.group("day"))
        year = int(match.group("year"))
        ordinal = _int_to_ordinal_words(day, language) or str(day)
        year_words = _year_to_words_american(year, language)
        return (
            f"{month_name} {ordinal}, {year_words}"
            if us
            else f"{ordinal} {month_name} {year_words}"
        )

    out = _ISO_DATE_RE.sub(_format_iso, text)
    out = _MDY_DATE_RE.sub(_format_mdy, out)
    return out


def _normalize_times(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        hour = match.group("hour")
        minute = match.group("minute")
        meridian = match.group("meridian").lower().replace(".", "")
        if minute:
            return f"{hour}:{minute} {meridian}"
        return f"{hour} {meridian}"

    return _TIME_RE.sub(_replace, text)


def _normalize_address_abbreviations(text: str) -> str:
    mapping = {
        "st": "street",
        "rd": "road",
        "ave": "avenue",
        "blvd": "boulevard",
        "ln": "lane",
        "dr": "drive",
    }

    def _replace(match: re.Match[str]) -> str:
        abbr = match.group("abbr")
        full = mapping.get(abbr.lower())
        if not full:
            return match.group(0)
        return match.group("prefix") + _match_casing(abbr, full)

    return _ADDRESS_ABBR_RE.sub(_replace, text)


def _normalize_internet_slang(text: str) -> str:
    mapping = {
        "pls": "please",
        "plz": "please",
    }

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = mapping.get(token.lower())
        if not replacement:
            return token
        return _match_casing(token, replacement)

    return re.sub(r"\b(?:pls|plz)\b", _replace, text, flags=re.IGNORECASE)


_DECIMAL_NUMBER_RE = re.compile(
    rf"(?<![\w{_NUMBER_RANGE_CLASS}/])(?P<number>-?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)\.(?P<fraction>\d+))(?![\w{_NUMBER_RANGE_CLASS}/])"
)
_PLAIN_NUMBER_RE = re.compile(
    rf"(?<![\w{_NUMBER_RANGE_CLASS}/])(?P<number>{_NUMBER_CORE_PATTERN})(?![\w{_NUMBER_RANGE_CLASS}/])"
)

_DIGIT_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)


def _int_to_words(value: int, language: str) -> Optional[str]:
    """Convert integer to spelled-out words using configured language."""
    if num2words is None:
        return None

    try:
        words = num2words(abs(value), lang=language)
    except Exception:  # pragma: no cover - unsupported locale
        return None

    if value < 0:
        return f"minus {words}"
    return words


def _int_to_ordinal_words(value: int, language: str) -> Optional[str]:
    if num2words is not None:
        try:
            return num2words(value, lang=language, ordinal=True)
        except Exception:  # pragma: no cover - unsupported locale
            return None

    if language.lower().startswith("en"):
        ordinals = {
            1: "first",
            2: "second",
            3: "third",
            4: "fourth",
            5: "fifth",
            6: "sixth",
            7: "seventh",
            8: "eighth",
            9: "ninth",
            10: "tenth",
            11: "eleventh",
            12: "twelfth",
            13: "thirteenth",
            14: "fourteenth",
            15: "fifteenth",
            16: "sixteenth",
            17: "seventeenth",
            18: "eighteenth",
            19: "nineteenth",
            20: "twentieth",
            21: "twenty-first",
            22: "twenty-second",
            23: "twenty-third",
            24: "twenty-fourth",
            25: "twenty-fifth",
            26: "twenty-sixth",
            27: "twenty-seventh",
            28: "twenty-eighth",
            29: "twenty-ninth",
            30: "thirtieth",
            31: "thirty-first",
        }
        return ordinals.get(int(value))

    return None


def _pluralize_fraction_word(base: str) -> str:
    if base == "half":
        return "halves"
    if base == "calf":  # defensive; unlikely but keeps pattern predictable
        return "calves"
    if base.endswith("f"):
        return base[:-1] + "ves"
    if base.endswith("fe"):
        return base[:-2] + "ves"
    return base + "s"


def _fraction_denominator_word(
    denominator: int, numerator: int, language: str
) -> Optional[str]:
    """Return spoken form for fraction denominator respecting plurality."""
    if denominator == 0:
        return None

    numerator_abs = abs(numerator)
    if denominator == 1:
        return ""
    if denominator == 2:
        return "half" if numerator_abs == 1 else "halves"
    if denominator == 4:
        return "quarter" if numerator_abs == 1 else "quarters"

    base = _int_to_ordinal_words(denominator, language)
    if base is None:
        return None
    if numerator_abs == 1:
        return base
    return _pluralize_fraction_word(base)


def _format_fraction_words(
    numerator: int, denominator: int, language: str
) -> Optional[str]:
    """Return spoken representation of a simple fraction."""
    if denominator == 0:
        return None

    fraction = Fraction(numerator, denominator)
    num = fraction.numerator
    den = fraction.denominator

    if abs(den) > 100:
        return None

    numerator_words = _int_to_words(abs(num), language)
    if numerator_words is None:
        return None

    denom_word = _fraction_denominator_word(den, num, language)
    if denom_word is None:
        return None

    if denom_word:
        if num < 0:
            numerator_words = f"minus {numerator_words}"
        return f"{numerator_words} {denom_word}".strip()

    # If denominator collapses to 1, just speak the integer value.
    spoken = _int_to_words(num, language)
    return spoken


def _replace_number_range(match: re.Match[str], language: str) -> str:
    left_raw = match.group("left")
    right_raw = match.group("right")
    left = _coerce_int_token(left_raw)
    right = _coerce_int_token(right_raw)
    if left is None or right is None:
        return match.group(0)

    left_words = _int_to_words(left, language)
    right_words = _int_to_words(right, language)
    if not left_words or not right_words:
        return match.group(0)

    return f"{left_words} to {right_words}"


def _replace_space_separated_range(match: re.Match[str], language: str) -> str:
    left_raw = match.group("left")
    right_raw = match.group("right")
    left = _coerce_int_token(left_raw)
    right = _coerce_int_token(right_raw)
    if left is None or right is None:
        return match.group(0)

    left_words = _int_to_words(left, language)
    right_words = _int_to_words(right, language)
    if not left_words or not right_words:
        return match.group(0)

    return f"{left_words} to {right_words}"


def _replace_fraction(match: re.Match[str], language: str) -> str:
    numerator_raw = match.group("numerator")
    denominator_raw = match.group("denominator")
    try:
        numerator = int(numerator_raw)
        denominator = int(denominator_raw)
    except ValueError:
        return match.group(0)

    spoken = _format_fraction_words(numerator, denominator, language)
    if not spoken:
        return match.group(0)
    return spoken


def _coerce_int_token(token: str) -> Optional[int]:
    if token is None:
        return None
    cleaned = token.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "+"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


AMBIGUOUS_D_BASES = {"i", "you", "he", "she", "we", "they"}
AMBIGUOUS_S_BASES = {
    "it",
    "that",
    "what",
    "where",
    "who",
    "when",
    "how",
    "there",
    "here",
    "he",
    "she",
    "we",
    "they",
    "you",
}


def _is_ambiguous_d(token: str) -> bool:
    low = token.lower()
    return low.endswith("'d") and low[:-2] in AMBIGUOUS_D_BASES


def _is_ambiguous_s(token: str) -> bool:
    low = token.lower()
    return low.endswith("'s") and low[:-2] in AMBIGUOUS_S_BASES


# Irregular possessives that are not formed by simple + 's logic
IRREGULAR_POSSESSIVES = {
    "children's": "children's",
    "men's": "men's",
    "women's": "women's",
    "people's": "people's",
    "geese's": "geese's",
    "mouse's": "mouse's",  # singular irregular
}

SIBILANT_END_RE = re.compile(r"(?:[sxz]|(?:ch|sh))$", re.IGNORECASE)

DECADE_RE = re.compile(r"^'\d0s$", re.IGNORECASE)  # '90s, '80s
LEADING_ELISION = {
    "'tis": "it is",
    "'twas": "it was",
    "'cause": "because",
    "'em": "them",
    "'round": "around",
    "'til": "until",
}

CULTURAL_NAME_PATTERNS = [
    re.compile(r"^O'[A-Z][a-z]+$"),
    re.compile(r"^D'[A-Z][a-z]+$"),
    re.compile(r"^L'[A-Za-z].*$"),
    re.compile(r"^Mc[A-Z].*$"),  # not apostrophe, but often relevant (kept anyway)
]

ACRONYM_POSSESSIVE_RE = re.compile(r"^[A-Z]{2,}'s$")

INTERNAL_APOSTROPHE_RE = re.compile(r"[A-Za-z]'.+[A-Za-z]")  # apostrophe not at edge

# Capture contiguous runs of Unicode letters/digits/apostrophes/hyphens, otherwise fall back to
# single-character tokens (punctuation, symbols, etc.).
WORD_TOKEN_RE = re.compile(
    r"[0-9A-Za-z'’\u00C0-\u1FFF\u2C00-\uD7FF\-]+|[^0-9A-Za-z\s]",
    re.UNICODE,
)

APOSTROPHE_CHARS = "’`´ꞌʼ"

TERMINAL_PUNCTUATION = {".", "?", "!", "…", ";", ":"}
CLOSING_PUNCTUATION = "\"'”’)]}»›"
ELLIPSIS_SUFFIXES = ("...", "…")
_LINE_SPLIT_RE = re.compile(r"(\n+)")

TITLE_ABBREVIATIONS = {
    "mr": "mister",
    "mrs": "missus",
    "ms": "miz",
    "dr": "doctor",
    "prof": "professor",
    "rev": "reverend",
    "gen": "general",
    "sgt": "sergeant",
}

SUFFIX_ABBREVIATIONS = {
    "jr": "junior",
    "sr": "senior",
}

_TITLE_PATTERN = re.compile(
    r"\b(?P<abbr>"
    + "|".join(sorted(TITLE_ABBREVIATIONS.keys(), key=len, reverse=True))
    + r")\.",
    re.IGNORECASE,
)
_SUFFIX_PATTERN = re.compile(
    r"\b(?P<abbr>"
    + "|".join(sorted(SUFFIX_ABBREVIATIONS.keys(), key=len, reverse=True))
    + r")\.",
    re.IGNORECASE,
)

# ---------- Utility Functions ----------


def normalize_unicode_apostrophes(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for ch in APOSTROPHE_CHARS:
        text = text.replace(ch, "'")
    return text


def tokenize(text: str) -> List[str]:
    # Simple tokenization preserving punctuation tokens
    return WORD_TOKEN_RE.findall(text)


def tokenize_with_spans(text: str) -> List[Tuple[str, int, int]]:
    return [
        (match.group(0), match.start(), match.end())
        for match in WORD_TOKEN_RE.finditer(text)
    ]


def _cleanup_spacing(text: str) -> str:
    if not text:
        return text

    for marker in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"):
        text = text.replace(marker, "")

    # Collapse spaces before closing punctuation.
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"\s+([’\"”»›)\]\}])", r"\1", text)

    # Remove spaces directly after opening punctuation/quotes.
    text = re.sub(r"([«‹“‘\"'(\[\{])\s+", r"\1", text)

    # Ensure spaces exist after sentence punctuation when followed by a word/quote.
    text = re.sub(r"([,.;:!?%])(?![\s”'\"’»›)])", r"\1 ", text)
    text = re.sub(r"([”\"’])(?![\s.,;:!?\"”’»›)])", r"\1 ", text)

    # Tighten hyphen/em dash spacing between word characters.
    text = re.sub(r"(?<=\w)\s*([-–—])\s*(?=\w)", r"\1", text)

    # Normalize multiple spaces.
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


_ROMAN_VALUE_MAP = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

_ROMAN_COMPOSE_ORDER = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]

_ROMAN_PREFIX_RE = re.compile(
    r"^(?P<roman>[IVXLCDM]+)(?P<sep>[\s\.:,;\-–—]*)", re.IGNORECASE
)

_ROMAN_TOKEN_RE = re.compile(r"^[IVXLCDM]+$")
_ROMAN_CARDINAL_CONTEXTS = {
    "act",
    "appendix",
    "article",
    "battle",
    "book",
    "campaign",
    "chapter",
    "episode",
    "film",
    "final",
    "fantasy",
    "game",
    "installment",
    "lesson",
    "level",
    "mission",
    "movement",
    "opus",
    "operation",
    "page",
    "part",
    "phase",
    "psalm",
    "round",
    "scene",
    "season",
    "section",
    "series",
    "song",
    "super",
    "bowl",
    "stage",
    "step",
    "track",
    "volume",
    "war",
    "world",
    "world war",
}
_ROMAN_NAME_TITLES = {
    "baron",
    "baroness",
    "captain",
    "cardinal",
    "count",
    "countess",
    "duchess",
    "duke",
    "emperor",
    "empress",
    "general",
    "governor",
    "king",
    "lord",
    "lady",
    "major",
    "pope",
    "president",
    "prince",
    "princess",
    "queen",
    "saint",
    "sir",
}
_ROMAN_NAME_CONNECTORS = {
    "de",
    "del",
    "della",
    "der",
    "di",
    "dos",
    "la",
    "le",
    "of",
    "the",
    "van",
    "von",
}
_ROMAN_BREAK_TOKENS = {
    ",",
    ".",
    "!",
    "?",
    ";",
    ":",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "—",
    "–",
    "-",
    "'",
    '"',
}

_ROMAN_CONTEXT_PASSTHROUGH = {"-", "–", "—", ":"}
_ROMAN_CONTEXT_COMPOUND_RE = re.compile(
    r"^(?P<context>[A-Za-z]+)(?P<sep>[-–—:])(?P<roman>[IVXLCDM]+)$",
    re.IGNORECASE,
)


def _roman_to_int(token: str) -> Optional[int]:
    if not token:
        return None
    total = 0
    prev = 0
    token_upper = token.upper()
    for char in reversed(token_upper):
        value = _ROMAN_VALUE_MAP.get(char)
        if value is None:
            return None
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    if total <= 0:
        return None
    if _int_to_roman(total) != token_upper:
        return None
    return total


def _int_to_roman(value: int) -> str:
    parts: List[str] = []
    remaining = value
    for amount, symbol in _ROMAN_COMPOSE_ORDER:
        while remaining >= amount:
            parts.append(symbol)
            remaining -= amount
    return "".join(parts)


def _is_titlecase_token(token: str) -> bool:
    cleaned = token.replace("'", "").replace("-", "")
    if not cleaned:
        return False
    if not cleaned[0].isalpha() or not cleaned[0].isupper():
        return False
    tail = cleaned[1:]
    return not tail or tail.islower()


def _token_is_cardinal_context(token: str) -> bool:
    return token.lower() in _ROMAN_CARDINAL_CONTEXTS


def _has_cardinal_leading_context(
    tokens: Sequence[Tuple[str, int, int]], index: int
) -> bool:
    j = index - 1
    while j >= 0:
        token, *_ = tokens[j]
        stripped = token.strip()
        if not stripped:
            j -= 1
            continue
        lowered = stripped.lower()
        if lowered in _ROMAN_CONTEXT_PASSTHROUGH:
            j -= 1
            continue
        if lowered in _ROMAN_BREAK_TOKENS:
            return False
        cleaned = lowered.strip("()[]{}\"'.,;!?")
        if cleaned in _ROMAN_CARDINAL_CONTEXTS:
            return True
        if cleaned:
            return False
        j -= 1
    return False


def _should_render_ordinal(
    tokens: Sequence[Tuple[str, int, int]],
    index: int,
    value: int,
) -> bool:
    # Treat trailing roman numerals in name-like sequences as ordinals while
    # leaving enumerated headings or series labels as cardinals.
    if value <= 0:
        return False
    if index <= 0:
        return False

    uppercase_count = 0
    title_count = 0
    j = index - 1
    while j >= 0:
        token, *_ = tokens[j]
        lowered = token.lower()

        if lowered in _ROMAN_CARDINAL_CONTEXTS:
            return False
        if lowered in _ROMAN_BREAK_TOKENS or token.isdigit():
            break
        if lowered in _ROMAN_NAME_CONNECTORS:
            j -= 1
            continue
        if _is_titlecase_token(token):
            uppercase_count += 1
            if lowered in _ROMAN_NAME_TITLES:
                title_count += 1
            j -= 1
            continue
        break

    if not uppercase_count:
        return False

    if title_count:
        return value <= 50

    if uppercase_count >= 2:
        return value <= 20

    return False


def _normalize_roman_numerals(text: str, language: str) -> str:
    if not text:
        return text

    tokens = tokenize_with_spans(text)
    if not tokens:
        return text

    parts: List[str] = []
    cursor = 0

    for index, (token, start, end) in enumerate(tokens):
        parts.append(text[cursor:start])
        replacement = token

        compound_match = _ROMAN_CONTEXT_COMPOUND_RE.match(token)
        if compound_match:
            context_word = compound_match.group("context")
            separator = compound_match.group("sep")
            roman_part = compound_match.group("roman")
            numeric_value = _roman_to_int(roman_part.upper())
            if (
                numeric_value is not None
                and numeric_value <= 200
                and context_word.lower() in _ROMAN_CARDINAL_CONTEXTS
            ):
                words = _int_to_words(numeric_value, language)
                if words:
                    if separator == ":":
                        replacement = f"{context_word}: {words}"
                    else:
                        replacement = f"{context_word} {words}"
        else:
            candidate = token.upper()
            is_roman = _ROMAN_TOKEN_RE.match(candidate)
            if is_roman:
                numeric_value = _roman_to_int(candidate)
                if numeric_value is not None:
                    convert = False
                    if len(token) >= 2:
                        if token.isupper():
                            convert = True
                        elif numeric_value <= 200 and _has_cardinal_leading_context(
                            tokens, index
                        ):
                            convert = True
                    elif len(token) == 1:
                        # Only convert single letters if context is strong
                        if _has_cardinal_leading_context(tokens, index):
                            convert = True

                    if convert:
                        if _should_render_ordinal(tokens, index, numeric_value):
                            ordinal = _int_to_ordinal_words(numeric_value, language)
                            if ordinal:
                                replacement = f"the {ordinal}"
                        else:
                            words = _int_to_words(numeric_value, language)
                            if words:
                                replacement = words

        parts.append(replacement)
        cursor = end

    parts.append(text[cursor:])
    return "".join(parts)


_ACRONYM_ALLOWLIST = {
    "AI",
    "API",
    "CPU",
    "DIY",
    "GPU",
    "HTML",
    "HTTP",
    "HTTPS",
    "ID",
    "JSON",
    "MP3",
    "MP4",
    "M4B",
    "NASA",
    "OCR",
    "PDF",
    "SQL",
    "TV",
    "TTS",
    "UK",
    "UN",
    "UFO",
    "OK",
    "URL",
    "USA",
    "US",
    "VR",
}
_ROMAN_NUMERAL_LETTERS = frozenset("IVXLCDM")
_CAPS_WORD_PATTERN = re.compile(r"[A-Z][A-Z0-9'\u2019-]*")
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'\u2019-]*")
_QUOTE_PAIRS = {
    '"': '"',
    "“": "”",
    "„": "“",
    "«": "»",
    "‹": "›",
}


def _should_preserve_caps_word(word: str) -> bool:
    letters = "".join(ch for ch in word if ch.isalpha())
    if not letters:
        return False
    base = letters
    if word.endswith(("'S", "’S")) and len(letters) > 1:
        base = letters[:-1]
    upper_base = base.upper()
    if upper_base in _ACRONYM_ALLOWLIST:
        return True
    if (
        all(ch in _ROMAN_NUMERAL_LETTERS for ch in letters.upper())
        and len(letters) <= 7
    ):
        return True
    return False


def _should_normalize_caps_segment(segment: str) -> bool:
    letters = [ch for ch in segment if ch.isalpha()]
    if not letters:
        return False
    if any(ch.islower() for ch in letters):
        return False
    if len(letters) <= 1:
        return False
    if not any(ch.isspace() for ch in segment) and len(letters) <= 4:
        return False
    return True


def _normalize_caps_segment(segment: str) -> str:
    if not segment:
        return segment

    preserve: Dict[str, str] = {}
    for match in _CAPS_WORD_PATTERN.finditer(segment):
        word = match.group(0)
        if _should_preserve_caps_word(word):
            preserve[word.lower()] = word

    lowered = segment.lower()
    result_chars: List[str] = []
    capitalize_next = True
    for char in lowered:
        if capitalize_next and char.isalpha():
            result_chars.append(char.upper())
            capitalize_next = False
        else:
            result_chars.append(char)
            if char.isalpha():
                capitalize_next = False
        if char in ".!?":
            capitalize_next = True
        elif char in "\n":
            capitalize_next = True

    def _restore(match: re.Match[str]) -> str:
        token = match.group(0)
        lookup = preserve.get(token.lower())
        if lookup:
            return lookup
        lower = token.lower()
        if lower == "i":
            return "I"
        if lower.startswith("i'") or lower.startswith("i\u2019"):
            return "I" + token[1:]
        return token

    return _WORD_PATTERN.sub(_restore, "".join(result_chars))


def _normalize_all_caps_quotes(text: str) -> str:
    if not text:
        return text

    builder: List[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        closing = _QUOTE_PAIRS.get(char)
        if not closing:
            builder.append(char)
            index += 1
            continue

        cursor = index + 1
        while cursor < length and text[cursor] != closing:
            cursor += 1

        if cursor >= length:
            builder.append(text[index:])
            break

        body = text[index + 1 : cursor]
        if _should_normalize_caps_segment(body):
            normalized = _normalize_caps_segment(body)
            builder.append(char + normalized + closing)
        else:
            builder.append(text[index : cursor + 1])

        index = cursor + 1

    if index < length:
        builder.append(text[index:])

    return "".join(builder)


def normalize_roman_numeral_titles(
    titles: Sequence[str],
    *,
    threshold: float = 0.5,
) -> List[str]:
    if not titles:
        return []

    normalized: List[str] = []
    matches: List[Tuple[int, str, int, str, str]] = []
    non_empty = 0

    for index, raw in enumerate(titles):
        title = "" if raw is None else str(raw)
        stripped = title.lstrip()
        leading_ws = title[: len(title) - len(stripped)]
        if not stripped:
            normalized.append(title)
            continue

        non_empty += 1
        match = _ROMAN_PREFIX_RE.match(stripped)
        if not match:
            normalized.append(title)
            continue

        roman_token = match.group("roman")
        separator = match.group("sep") or ""
        rest = stripped[match.end() :]

        if not separator and rest and rest[:1].isalnum():
            normalized.append(title)
            continue

        numeric_value = _roman_to_int(roman_token)
        if numeric_value is None:
            normalized.append(title)
            continue

        matches.append((index, leading_ws, numeric_value, separator, rest))
        normalized.append(title)

    if not matches or non_empty == 0:
        return list(normalized)

    if len(matches) <= non_empty * threshold:
        return list(normalized)

    output = list(normalized)
    for idx, leading_ws, value, separator, rest in matches:
        new_title = f"{leading_ws}{value}"
        if separator:
            new_title += separator
        elif rest and not rest[0].isspace() and rest[0] not in ".-–—:;,":
            new_title += " "
        new_title += rest
        output[idx] = new_title

    return output


def _match_casing(template: str, replacement: str) -> str:
    if template.isupper():
        return replacement.upper()
    if template[:1].isupper() and template[1:].islower():
        return replacement.capitalize()
    if template[:1].isupper():
        # Mixed case (e.g., Mc), fall back to title case
        return replacement.capitalize()
    return replacement


def expand_titles_and_suffixes(text: str) -> str:
    def _replace(match: re.Match[str], mapping: dict[str, str]) -> str:
        abbr = match.group("abbr")
        lookup = mapping.get(abbr.lower())
        if not lookup:
            return match.group(0)
        return _match_casing(abbr, lookup)

    text = _TITLE_PATTERN.sub(lambda m: _replace(m, TITLE_ABBREVIATIONS), text)
    text = _SUFFIX_PATTERN.sub(lambda m: _replace(m, SUFFIX_ABBREVIATIONS), text)
    return text


def ensure_terminal_punctuation(text: str) -> str:
    def _amend(segment: str) -> str:
        if not segment or not segment.strip():
            return segment

        stripped = segment.rstrip()
        trailing_ws = segment[len(stripped) :]

        match = re.match(rf"^(.*?)([{re.escape(CLOSING_PUNCTUATION)}]*)$", stripped)
        if not match:
            return segment

        body, closers = match.groups()
        if not body:
            return segment

        normalized_body = body.rstrip()
        trailing_body_ws = body[len(normalized_body) :]

        if normalized_body.endswith(ELLIPSIS_SUFFIXES):
            return normalized_body + trailing_body_ws + closers + trailing_ws

        last_char = normalized_body[-1]
        if last_char in TERMINAL_PUNCTUATION:
            return normalized_body + trailing_body_ws + closers + trailing_ws

        return normalized_body + "." + trailing_body_ws + closers + trailing_ws

    parts = _LINE_SPLIT_RE.split(text)
    amended: List[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("\n"):
            amended.append(part)
        else:
            amended.append(_amend(part))
    if not parts:
        return _amend(text)
    return "".join(amended)


def is_cultural_name(token: str, cfg: ApostropheConfig) -> bool:
    if not cfg.protect_cultural_names:
        return False
    for pat in CULTURAL_NAME_PATTERNS:
        if pat.match(token):
            return True
    return False


def _case_preserving_words(original: str, words: Sequence[str]) -> str:
    if not words:
        return ""
    if original.isupper():
        return " ".join(word.upper() for word in words)

    if original[:1].isupper():
        adjusted = [words[0].capitalize()]
        if len(words) > 1:
            adjusted.extend(words[1:])
        return " ".join(adjusted)

    return " ".join(words)


def _apply_contraction_policy(
    token: str,
    *,
    category: str,
    cfg: ApostropheConfig,
    expand: Callable[[], str],
    collapse: Optional[str] = None,
) -> str:
    mode = cfg.contraction_mode
    if mode == "collapse":
        return collapse if collapse is not None else token.replace("'", "")
    if mode != "expand":
        return token
    if not cfg.is_contraction_enabled(category):
        return token
    return expand()


def _assemble_contraction_expansion(
    base_text: str, surface_text: str, expansion_word: str
) -> str:
    if not expansion_word:
        return base_text

    if surface_text.isupper() and expansion_word.isalpha():
        adjusted = expansion_word.upper()
    elif len(surface_text) > 2 and surface_text[:-2].istitle() and expansion_word:
        adjusted = expansion_word.lower()
    else:
        adjusted = expansion_word

    return f"{base_text} {adjusted}".strip()


def _classify_ambiguous_d(token: str, cfg: ApostropheConfig) -> Tuple[str, str]:
    base = token[:-2]
    collapse_value = base + "d"

    if cfg.contraction_mode == "collapse":
        return "contraction_modal_would", collapse_value
    if cfg.contraction_mode != "expand":
        return "contraction_modal_would", token

    mode = cfg.ambiguous_past_modal_mode
    if mode == "expand_prefer_had":
        candidates = [
            ("contraction_aux_have", "had"),
            ("contraction_modal_would", "would"),
        ]
    elif mode == "expand_prefer_would":
        candidates = [
            ("contraction_modal_would", "would"),
            ("contraction_aux_have", "had"),
        ]
    else:  # contextual
        candidates = [
            ("contraction_modal_would", "would"),
            ("contraction_aux_have", "had"),
        ]

    for category, word in candidates:
        if not cfg.is_contraction_enabled(category):
            continue
        expanded = _assemble_contraction_expansion(base, token, word)
        return category, expanded

    # If every category is disabled, leave the token as-is but report default category
    return candidates[0][0], token


def _classify_ambiguous_s(token: str, cfg: ApostropheConfig) -> Tuple[str, str]:
    base = token[:-2]

    if cfg.contraction_mode == "collapse":
        return "contraction_aux_be", base + "s"
    if cfg.contraction_mode != "expand":
        return "contraction_aux_be", token

    candidates = [
        ("contraction_aux_be", "is"),
        ("contraction_aux_have", "has"),
    ]

    for category, word in candidates:
        if not cfg.is_contraction_enabled(category):
            continue
        expanded = _assemble_contraction_expansion(base, token, word)
        return category, expanded

    return candidates[0][0], token


def classify_token(token: str, cfg: ApostropheConfig) -> Tuple[str, str]:
    """
    Classify apostrophe usage and propose normalized form.
    Returns (category, normalized_token_or_same).
    Categories include: contraction_* variants, plural_possessive, irregular_possessive,
    sibilant_possessive, singular_possessive, acronym_possessive, decade, leading_elision,
    fantasy_internal, cultural_name, other.
    """
    if "'" not in token:
        return "other", token

    low = token.lower()

    # 1. Decades
    if DECADE_RE.match(token):
        if cfg.decades_mode == "expand":
            decade_digit = token[1]
            decade_map = {
                "0": "two thousands",
                "1": "tens",
                "2": "twenties",
                "3": "thirties",
                "4": "forties",
                "5": "fifties",
                "6": "sixties",
                "7": "seventies",
                "8": "eighties",
                "9": "nineties",
            }
            spoken = decade_map.get(decade_digit)
            if spoken:
                return "decade", spoken
            return "decade", token
        return "decade", token

    # 2. Leading elision
    if low in LEADING_ELISION:
        if cfg.leading_elision_mode == "expand":
            return "leading_elision", LEADING_ELISION[low]
        return "leading_elision", token

    # 3. Ambiguous 'd contractions
    if _is_ambiguous_d(token):
        return _classify_ambiguous_d(token, cfg)

    # 4. Ambiguous 's contractions
    if _is_ambiguous_s(token):
        return _classify_ambiguous_s(token, cfg)

    # 5. Lexicon-based contractions
    lex_entry = CONTRACTION_LEXICON.get(low)
    if lex_entry is not None:
        category, words = lex_entry

        def _expand() -> str:
            return _case_preserving_words(token, words)

        collapse_value = token.replace("'", "")
        normalized = _apply_contraction_policy(
            token, category=category, cfg=cfg, expand=_expand, collapse=collapse_value
        )
        return category, normalized

    # 6. Suffix contractions ('m handled separately)
    if low.endswith("'m") and low[:-2] in SUFFIX_CONTRACTION_BASES.get(
        "'m", ()
    ):  # pronoun I'm

        def _expand_m() -> str:
            base = token[:-2]
            return _assemble_contraction_expansion(base, token, "am")

        normalized = _apply_contraction_policy(
            token,
            category="contraction_aux_be",
            cfg=cfg,
            expand=_expand_m,
            collapse=token.replace("'", ""),
        )
        return "contraction_aux_be", normalized

    for suffix, append_word, category in SUFFIX_CONTRACTION_RULES:
        if low.endswith(suffix) and len(token) > len(suffix):
            base = token[: -len(suffix)]

            def _expand_suffix() -> str:
                return _assemble_contraction_expansion(base, token, append_word)

            normalized = _apply_contraction_policy(
                token,
                category=category,
                cfg=cfg,
                expand=_expand_suffix,
                collapse=token.replace("'", ""),
            )
            return category, normalized

    # 7. Irregular possessives (keep or expand logic)
    if low in IRREGULAR_POSSESSIVES:
        if cfg.irregular_possessive_mode == "keep":
            return "irregular_possessive", token
        return "irregular_possessive", token

    # 8. Plural possessive pattern dogs'
    if re.match(r"^[A-Za-z0-9]+s'$", token):
        if cfg.plural_possessive_mode == "collapse":
            return "plural_possessive", token[:-1]
        return "plural_possessive", token

    # 9. Acronym possessive NASA's
    if ACRONYM_POSSESSIVE_RE.match(token):
        if cfg.acronym_possessive_mode == "collapse_add_s":
            return "acronym_possessive", token.replace("'", "")
        return "acronym_possessive", token

    # 10. Sibilant singular possessive boss's, church's
    if low.endswith("'s"):
        base = token[:-2]
        if SIBILANT_END_RE.search(base):
            if cfg.sibilant_possessive_mode == "keep":
                return "sibilant_possessive", token
            if cfg.sibilant_possessive_mode == "approx":
                return "sibilant_possessive", base + "es"
            if cfg.sibilant_possessive_mode == "mark":
                normalized = base
                normalized += cfg.sibilant_iz_marker if cfg.add_phoneme_hints else "es"
                return "sibilant_possessive", normalized

    # 11. Generic singular possessive (\w+'s)
    if re.match(r"^[A-Za-z0-9]+'s$", token):
        if cfg.possessive_mode == "collapse":
            return "singular_possessive", token.replace("'", "")
        return "singular_possessive", token

    # 12. Cultural names or fantasy internal
    if is_cultural_name(token, cfg):
        return "cultural_name", token

    if INTERNAL_APOSTROPHE_RE.search(token):
        if cfg.fantasy_mode == "keep":
            return "fantasy_internal", token
        if cfg.fantasy_mode == "mark":
            out = token + (cfg.fantasy_marker if cfg.add_phoneme_hints else "")
            return "fantasy_internal", out
        if cfg.fantasy_mode == "collapse_internal":
            inner = re.sub(r"(?<=\w)'+(?=\w)", cfg.joiner, token)
            return "fantasy_internal", inner

    if cfg.fantasy_mode == "collapse_internal":
        return "other", token.replace("'", cfg.joiner)
    return "other", token


def normalize_apostrophes(
    text: str, cfg: ApostropheConfig | None = None
) -> Tuple[str, List[Tuple[str, str, str]]]:
    """
    Normalize apostrophes per config.
    Returns normalized text AND a list of (original_token, category, normalized_token)
    so you can debug or post-process (e.g., apply phoneme replacement for ‹IZ›).
    """
    if cfg is None:
        cfg = ApostropheConfig()

    text = normalize_unicode_apostrophes(text)
    text = _normalize_grouped_numbers(text, cfg)
    token_entries = tokenize_with_spans(text)

    use_contextual_s = cfg.contraction_mode == "expand"
    use_contextual_d = (
        cfg.contraction_mode == "expand"
        and cfg.ambiguous_past_modal_mode == "contextual"
    )

    need_contextual = False
    if (use_contextual_s or use_contextual_d) and token_entries:
        for token_value, _, _ in token_entries:
            if use_contextual_s and _is_ambiguous_s(token_value):
                need_contextual = True
                break
            if use_contextual_d and _is_ambiguous_d(token_value):
                need_contextual = True
                break

    contextual_resolutions = (
        resolve_ambiguous_contractions(text) if need_contextual else {}
    )

    results: List[Tuple[str, str, str]] = []
    normalized_tokens: List[str] = []

    for tok, start, end in token_entries:
        category, norm = classify_token(tok, cfg)

        resolution = (
            contextual_resolutions.get((start, end)) if contextual_resolutions else None
        )
        if resolution is not None and cfg.contraction_mode == "expand":
            if cfg.is_contraction_enabled(resolution.category):
                category = resolution.category
                norm = resolution.expansion
            else:
                norm = tok

        results.append((tok, category, norm))
        normalized_tokens.append(norm)

    filtered = [token for token in normalized_tokens if token]
    normalized_text = _cleanup_spacing(" ".join(filtered))
    return normalized_text, results


def _normalize_grouped_numbers(text: str, cfg: ApostropheConfig) -> str:
    if not text:
        return text

    language = (cfg.number_lang or "en").strip() or "en"

    def _year_mode() -> str:
        mode = (cfg.year_pronunciation_mode or "").strip().lower()
        if mode in {"", "none", "off", "disabled"}:
            return "off"
        if mode not in {"american"}:
            return "off"
        return mode

    year_mode = _year_mode()

    def _format_year_tail(value: int, *, allow_oh: bool = True) -> Optional[str]:
        if value == 0:
            return ""
        if value < 10:
            if allow_oh:
                return f"oh {_DIGIT_WORDS[value]}"
            return _DIGIT_WORDS[value]
        words = _int_to_words(value, language)
        if not words:
            return None
        return words

    def _format_year_like(token: str, value: int) -> Optional[str]:
        if year_mode == "off" or num2words is None:
            return None
        if len(token) != 4 or not token.isdigit():
            return None
        if value < 1000 or value > 9999:
            return None
        style = year_mode

        def _words(value_to_convert: int) -> Optional[str]:
            words = _int_to_words(value_to_convert, language)
            return words

        if style == "american":
            # Special handling for 2000-2009 to use "two thousand X"
            if 2000 <= value <= 2009:
                words = _words(value)
                if words:
                    return words.replace(" and ", " ")
                return None

            # US-style: 1100-1999 are often spoken as "X hundred Y".
            if 1100 <= value <= 1999:
                hundreds = value // 100
                remainder = value % 100
                prefix = _words(hundreds)
                if not prefix:
                    return None
                if remainder == 0:
                    return f"{prefix} hundred"
                tail = _format_year_tail(remainder, allow_oh=True)
                if tail is None:
                    return None
                return f"{prefix} hundred {tail}".strip()

            if value % 1000 == 0:
                thousands = value // 1000
                thousands_words = _words(thousands)
                if thousands_words:
                    return f"{thousands_words} thousand"
                return None

            first_two = value // 100
            last_two = value % 100

            prefix = _words(first_two)
            if not prefix:
                return None

            if last_two == 0:
                return f"{prefix} hundred"

            if last_two < 10:
                # Use "oh X" format (e.g. "nineteen oh five")
                return f"{prefix} oh {_DIGIT_WORDS[last_two]}"

            tail = _format_year_tail(last_two)
            if tail:
                return f"{prefix} {tail}"
            return prefix

        return None

    def _replace_grouped(match: re.Match[str]) -> str:
        token = match.group(1)
        value = _coerce_int_token(token)
        if value is None:
            cleaned = token.replace(",", "")
            return cleaned
        if num2words is None:
            return str(value)
        words = _int_to_words(value, language)
        return words or str(value)

    def _replace_plain(match: re.Match[str]) -> str:
        token = match.group("number")
        if "," in token:
            return token.replace(",", "")

        start, end = match.span()
        source = match.string
        before = source[start - 1] if start > 0 else ""
        after = source[end] if end < len(source) else ""

        if before == "/" or after == "/":
            return token

        if after == ".":
            next_char = source[end + 1] if end + 1 < len(source) else ""
            if next_char.isdigit():
                return token

        if before == ".":
            prev_char = source[start - 2] if start >= 2 else ""
            if prev_char.isdigit() or start == 1:
                return token

        value = _coerce_int_token(token)
        if value is None:
            return token

        # Check context for "address" vs year markers to avoid converting house numbers to years
        window_start = max(0, start - 60)
        window_end = min(len(source), end + 60)
        context = source[window_start:window_end].lower()

        # Check for "address" or "addresses" as a whole word
        has_address = bool(re.search(r"\baddress(es)?\b", context))

        # Check for year markers as whole words
        has_year_marker = bool(
            re.search(r"\b(bc|ad|bce|ce|b\.c\.|a\.d\.|b\.c\.e\.|c\.e\.)\b", context)
        )

        should_try_year = True
        if has_address and not has_year_marker:
            should_try_year = False

        if should_try_year:
            year_like = _format_year_like(token, value)
            if year_like:
                return year_like

        if num2words is None:
            return str(value)
        words = _int_to_words(value, language)
        return words or str(value)

    def _replace_decimal(match: re.Match[str]) -> str:
        token = match.group("number")
        fraction_part = match.group("fraction")
        start, end = match.span()
        source = match.string

        if end < len(source) and source[end] == ".":
            next_char = source[end + 1] if end + 1 < len(source) else ""
            if next_char.isdigit():
                return token

        is_negative = token.startswith("-")
        core = token[1:] if is_negative else token
        if "." not in core:
            return token

        integer_part, _, _ = core.partition(".")
        if not integer_part or not fraction_part:
            return token

        integer_value = _coerce_int_token(integer_part.replace(",", ""))
        if integer_value is None:
            return token

        trimmed_fraction = fraction_part.rstrip("0")
        integer_words = _int_to_words(integer_value, language)

        if not trimmed_fraction:
            if integer_words is None:
                return token
            spoken = integer_words
            return f"minus {spoken}" if is_negative else spoken

        if integer_words is None:
            fallback_core = core.replace(".", " point ")
            return f"minus {fallback_core}" if is_negative else fallback_core

        digit_words: List[str] = []
        for digit in trimmed_fraction:
            if not digit.isdigit():
                return token
            digit_words.append(_DIGIT_WORDS[int(digit)])

        spoken = f"{integer_words} point {' '.join(digit_words)}"
        return f"minus {spoken}" if is_negative else spoken

    def _replace_currency(match: re.Match[str]) -> str:
        if num2words is None:
            return match.group(0)

        symbol = match.group("symbol")
        amount_str = match.group("amount").replace(",", "")
        magnitude = match.group("magnitude")

        try:
            amount = float(amount_str)
        except ValueError:
            return match.group(0)

        if magnitude:
            # Magnitude case: $2.5 million -> two point five million dollars
            if "." in amount_str:
                integer_part, fraction_part = amount_str.split(".", 1)
                integer_val = int(integer_part)
                integer_words = _int_to_words(integer_val, language)

                # Spell out fraction digits
                digit_words = []
                for digit in fraction_part:
                    if digit.isdigit():
                        digit_words.append(_DIGIT_WORDS[int(digit)])

                amount_spoken = f"{integer_words} point {' '.join(digit_words)}"
            else:
                amount_spoken = _int_to_words(int(amount), language)

            currency_names = {
                "$": "dollars",
                "£": "pounds",
                "€": "euros",
                "¥": "yen",
            }
            currency_name = currency_names.get(symbol, "dollars")

            return f"{amount_spoken} {magnitude} {currency_name}"

        # Handle $0.99 -> ninety-nine cents (avoid "zero dollars and...").
        if amount_str.startswith("0") and amount < 1.0:
            dollars_part, dot, fraction = amount_str.partition(".")
            if dot and fraction:
                cents_str = (fraction + "00")[:2]
                try:
                    cents_value = int(cents_str)
                except ValueError:
                    cents_value = 0
                if cents_value > 0:
                    cents_words = _int_to_words(cents_value, language) or str(
                        cents_value
                    )
                    subunit = {
                        "$": "cent",
                        "€": "cent",
                        "£": "penny",
                        "¥": "yen",
                    }.get(symbol, "cent")
                    if symbol == "£":
                        subunit = "pence" if cents_value != 1 else "penny"
                    else:
                        subunit = (
                            (subunit + "s")
                            if cents_value != 1 and subunit not in {"pence", "yen"}
                            else subunit
                        )
                    return f"{cents_words} {subunit}".strip()

        currency_map = {
            "$": "USD",
            "£": "GBP",
            "€": "EUR",
            "¥": "JPY",
        }
        currency_code = currency_map.get(symbol, "USD")

        try:
            # Always use float to avoid num2words treating int as cents (if that's what it does)
            # or to ensure consistent behavior.
            words = num2words(
                amount, to="currency", currency=currency_code, lang=language
            )

            # Remove "zero cents" if present
            # Patterns: ", zero cents", " and zero cents"
            words = words.replace(", zero cents", "").replace(" and zero cents", "")
            return words
        except Exception:
            return match.group(0)

    def _replace_url(match: re.Match[str]) -> str:
        domain = match.group("domain")

        # Avoid matching dotted abbreviations/acronyms without an explicit URL prefix.
        has_prefix = match.group(1) or match.group(2)
        if not has_prefix:
            parts = [p for p in domain.split(".") if p]
            if parts and all(p.isalpha() and len(p) <= 2 for p in parts):
                return match.group(0)

        # Avoid matching numbers like 1.05 or 12.34.56
        # If the domain consists only of digits and dots, ignore it (unless it has http/www prefix)
        has_prefix = match.group(1) or match.group(2)
        if not has_prefix and all(c.isdigit() or c == "." or c == "-" for c in domain):
            # Check if it really looks like a number (e.g. 1.05)
            # If it has multiple dots like 1.2.3.4 it might be an IP, which we might want to speak as dot?
            # But 1.05 is definitely a number.
            # Let's be safe: if it looks like a float, skip.
            try:
                float(domain)
                return match.group(0)
            except ValueError:
                pass

        if domain.startswith("www."):
            domain = domain[4:]
        spoken = domain.replace(".", " dot ")
        return spoken

    def _remove_footnote(match: re.Match[str]) -> str:
        return match.group(1)

    normalized = text

    # Apply URL replacement first (independent of number conversion).
    normalized = _URL_RE.sub(_replace_url, normalized)

    if getattr(cfg, "remove_footnotes", False):
        normalized = _FOOTNOTE_RE.sub(_remove_footnote, normalized)
        normalized = _BRACKET_FOOTNOTE_RE.sub("", normalized)

    if cfg.convert_currency:
        normalized = _CURRENCY_RE.sub(_replace_currency, normalized)

    if cfg.convert_numbers:
        normalized = _NUMBER_RANGE_RE.sub(
            lambda m: _replace_number_range(m, language), normalized
        )
        normalized = _NUMBER_SPACE_RANGE_RE.sub(
            lambda m: _replace_space_separated_range(m, language), normalized
        )
        normalized = _FRACTION_RE.sub(
            lambda m: _replace_fraction(m, language), normalized
        )
        normalized = _DECIMAL_NUMBER_RE.sub(_replace_decimal, normalized)
        normalized = _NUMBER_WITH_GROUP_RE.sub(_replace_grouped, normalized)
        normalized = _PLAIN_NUMBER_RE.sub(_replace_plain, normalized)
        normalized = _normalize_roman_numerals(normalized, language)

    return normalized


def _normalize_dotted_acronyms(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        value = match.group(0)
        compact = value.replace(".", "")
        return compact

    return re.sub(r"\b(?:[A-Z]\.){1,}[A-Z]\.?(?=\W|$)", _replace, text)


# ---------- Optional phoneme hint post-processing ----------


def apply_phoneme_hints(text: str, iz_marker="‹IZ›") -> str:
    """
    Replace markers with an orthographic sequence that
    your phonemizer will reliably convert to /ɪz/.
    """
    return text.replace(iz_marker, " iz")


DEFAULT_APOSTROPHE_CONFIG = ApostropheConfig()


_MUSTACHE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
_LLM_SYSTEM_PROMPT = (
    "You assist with audiobook preparation. Review the sentence, identify any apostrophes or "
    "contractions that should be expanded for clarity, and respond by calling the "
    "apply_regex_replacements tool. Each replacement must target a single token, include a precise "
    "regex pattern, and provide the exact replacement text. If no changes are required, call the tool "
    "with an empty replacements list. Do not rewrite the sentence directly."
)

_LLM_REGEX_TOOL_NAME = "apply_regex_replacements"
_LLM_REGEX_TOOL = {
    "type": "function",
    "function": {
        "name": _LLM_REGEX_TOOL_NAME,
        "description": (
            "Return regex substitutions to normalize apostrophes or contractions in the provided sentence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "replacements": {
                    "description": "Ordered substitutions to apply to the sentence.",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Regular expression that matches the token to replace.",
                            },
                            "replacement": {
                                "type": "string",
                                "description": "Replacement text for the match.",
                            },
                            "flags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional re flags such as IGNORECASE.",
                            },
                            "count": {
                                "type": "integer",
                                "description": "Optional maximum number of replacements (default all).",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Short explanation of why the replacement is needed.",
                            },
                        },
                        "required": ["pattern", "replacement"],
                    },
                }
            },
            "required": ["replacements"],
        },
    },
}
_LLM_REGEX_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": _LLM_REGEX_TOOL_NAME},
}
_LLM_ALLOWED_REGEX_FLAGS = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
}


def _render_mustache(template: str, context: Mapping[str, str]) -> str:
    if not template:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return context.get(key, "")

    return _MUSTACHE_PATTERN.sub(_replace, template)


_SENTENCE_CAPTURE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$", re.MULTILINE)


def _split_sentences_for_llm(text: str) -> List[str]:
    sentences = [
        segment.strip() for segment in _SENTENCE_CAPTURE_RE.findall(text or "")
    ]
    return [segment for segment in sentences if segment]


def _normalize_with_llm(
    text: str,
    *,
    settings: Mapping[str, Any],
    config: ApostropheConfig,
) -> str:
    from abogen.normalization_settings import (
        build_llm_configuration,
        DEFAULT_LLM_PROMPT,
    )
    from abogen.llm_client import generate_completion, LLMClientError

    llm_config = build_llm_configuration(settings)
    if not llm_config.is_configured():
        raise LLMClientError("LLM configuration is incomplete")

    prompt_template = str(settings.get("llm_prompt") or DEFAULT_LLM_PROMPT)
    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    normalized_lines: List[str] = []
    for raw_line in lines:
        newline = ""
        if raw_line.endswith(("\r", "\n")):
            stripped_newline = raw_line.rstrip("\r\n")
            newline = raw_line[len(stripped_newline) :]
            line_body = stripped_newline
        else:
            line_body = raw_line

        if not line_body.strip():
            normalized_lines.append(line_body + newline)
            continue

        leading_ws = line_body[: len(line_body) - len(line_body.lstrip())]
        trailing_ws = line_body[len(line_body.rstrip()) :]
        core = line_body[len(leading_ws) : len(line_body) - len(trailing_ws)]

        sentences = _split_sentences_for_llm(core)
        if not sentences:
            normalized_lines.append(line_body + newline)
            continue

        paragraph_context = core
        rewritten_sentences: List[str] = []
        for sentence in sentences:
            prompt_context = {
                "text": sentence,
                "sentence": sentence,
                "paragraph": paragraph_context,
            }
            prompt = _render_mustache(prompt_template, prompt_context)
            completion = generate_completion(
                llm_config,
                system_message=_LLM_SYSTEM_PROMPT,
                user_message=prompt,
                tools=[_LLM_REGEX_TOOL],
                tool_choice=_LLM_REGEX_TOOL_CHOICE,
            )
            rewritten_sentences.append(
                _apply_llm_regex_replacements(sentence, completion)
            )

        normalized_core = " ".join(filter(None, rewritten_sentences)) or core

        rebuilt = f"{leading_ws}{normalized_core}{trailing_ws}{newline}"
        normalized_lines.append(rebuilt)

    result = "".join(normalized_lines)
    return result if result else text


def _apply_llm_regex_replacements(sentence: str, completion: "LLMCompletion") -> str:
    replacements = _extract_llm_replacements(completion)
    if not replacements:
        return sentence

    updated = sentence
    for spec in replacements:
        updated = _apply_single_regex_replacement(updated, spec)
    return updated


def _extract_llm_replacements(completion: "LLMCompletion") -> List[Dict[str, Any]]:
    if completion is None:
        return []

    for call in getattr(completion, "tool_calls", ()):  # type: ignore[attr-defined]
        if getattr(call, "name", None) != _LLM_REGEX_TOOL_NAME:
            continue
        payload = _safe_load_json(getattr(call, "arguments", None))
        replacements = _coerce_replacement_list(payload)
        if replacements:
            return replacements

    if getattr(completion, "content", None):
        payload = _safe_load_json(completion.content)
        replacements = _coerce_replacement_list(payload)
        if replacements:
            return replacements

    return []


def _safe_load_json(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _coerce_replacement_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, Mapping):
        candidates = raw.get("replacements")
    else:
        candidates = raw

    if not isinstance(candidates, list):
        return []

    replacements: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        pattern = str(item.get("pattern") or "").strip()
        if not pattern:
            continue
        replacement = str(item.get("replacement") or "")
        entry: Dict[str, Any] = {"pattern": pattern, "replacement": replacement}

        flags = _normalize_flag_field(item.get("flags"))
        if flags:
            entry["flags"] = flags

        count = item.get("count")
        if isinstance(count, int) and count >= 0:
            entry["count"] = count

        replacements.append(entry)

    return replacements


def _normalize_flag_field(raw: Any) -> List[str]:
    if not raw:
        return []

    if isinstance(raw, str):
        raw_iterable: Iterable[Any] = [raw]
    elif isinstance(raw, Iterable) and not isinstance(raw, (bytes, str, Mapping)):
        raw_iterable = raw
    else:
        return []

    normalized: List[str] = []
    seen: set[str] = set()
    for value in raw_iterable:
        candidate = str(value or "").strip().upper()
        if (
            not candidate
            or candidate not in _LLM_ALLOWED_REGEX_FLAGS
            or candidate in seen
        ):
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _apply_single_regex_replacement(text: str, spec: Mapping[str, Any]) -> str:
    pattern = str(spec.get("pattern") or "")
    replacement = str(spec.get("replacement") or "")
    if not pattern:
        return text

    flags_value = 0
    flag_names = spec.get("flags")
    if isinstance(flag_names, str):
        flag_iterable: Iterable[Any] = [flag_names]
    elif isinstance(flag_names, Iterable) and not isinstance(
        flag_names, (bytes, str, Mapping)
    ):
        flag_iterable = flag_names
    else:
        flag_iterable = []

    for flag_name in flag_iterable:
        lookup = str(flag_name or "").strip().upper()
        flags_value |= _LLM_ALLOWED_REGEX_FLAGS.get(lookup, 0)

    count = spec.get("count")
    count_value = count if isinstance(count, int) and count >= 0 else 0

    try:
        return re.sub(pattern, replacement, text, count=count_value, flags=flags_value)
    except re.error:
        return text


def normalize_for_pipeline(
    text: str,
    *,
    config: Optional[ApostropheConfig] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> str:
    """Normalize text for the synthesis pipeline with runtime settings."""

    from abogen.normalization_settings import (
        build_apostrophe_config,
        get_runtime_settings,
    )
    from abogen.llm_client import LLMClientError

    runtime_settings = settings or get_runtime_settings()
    base_config = config or DEFAULT_APOSTROPHE_CONFIG
    cfg = build_apostrophe_config(settings=runtime_settings, base=base_config)

    mode = str(runtime_settings.get("normalization_apostrophe_mode", "spacy")).lower()
    normalized = text

    # Pre-normalization that must happen before number/url parsing.
    if runtime_settings.get("normalization_numbers", True):
        normalized = _normalize_dates(normalized, cfg.number_lang)
        normalized = _normalize_times(normalized)
        normalized = _normalize_dotted_acronyms(normalized)
    if runtime_settings.get("normalization_titles", True):
        normalized = _normalize_address_abbreviations(normalized)
    if runtime_settings.get("normalization_internet_slang", False):
        normalized = _normalize_internet_slang(normalized)

    if mode == "off":
        normalized = normalize_unicode_apostrophes(normalized)
        if (
            cfg.convert_numbers
            or cfg.convert_currency
            or getattr(cfg, "remove_footnotes", False)
        ):
            normalized = _normalize_grouped_numbers(normalized, cfg)
        normalized = _cleanup_spacing(normalized)
    elif mode == "llm":
        try:
            normalized = _normalize_with_llm(
                normalized, settings=runtime_settings, config=cfg
            )
        except LLMClientError:
            raise
        if (
            cfg.convert_numbers
            or cfg.convert_currency
            or getattr(cfg, "remove_footnotes", False)
        ):
            normalized = _normalize_grouped_numbers(normalized, cfg)
        normalized = _cleanup_spacing(normalized)
    else:
        normalized, _ = normalize_apostrophes(normalized, cfg)

    if runtime_settings.get("normalization_titles", True):
        normalized = expand_titles_and_suffixes(normalized)
    if runtime_settings.get("normalization_terminal", True):
        normalized = ensure_terminal_punctuation(normalized)
    if runtime_settings.get("normalization_caps_quotes", True):
        normalized = _normalize_all_caps_quotes(normalized)

    if cfg.add_phoneme_hints:
        normalized = apply_phoneme_hints(normalized, iz_marker=cfg.sibilant_iz_marker)

    return normalized


# ---------- Example Usage ----------

if __name__ == "__main__":
    sample = "Bob's boss's chair. The dogs' collars. It's cold. Ta'veren and Sha'hal. O'Brien's code in the '90s. Boss's orders."
    config = ApostropheConfig()
    norm_text, details = normalize_apostrophes(sample, config)
    norm_text = apply_phoneme_hints(norm_text)
    print("Original:", sample)
    print("Normalized:", norm_text)
    for orig, cat, norm in details:
        print(f"{orig:15} -> {norm:15} [{cat}]")
