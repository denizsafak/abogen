from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

try:  # pragma: no cover - optional dependency
    import spacy
except Exception:  # pragma: no cover - spaCy unavailable at runtime
    spacy = None

# Lazy spaCy type hints to avoid a hard dependency at import time.
Language = Any  # type: ignore[assignment]
Token = Any  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractionResolution:
    start: int
    end: int
    surface: str
    expansion: str
    category: str
    lemma: str

    @property
    def span(self) -> Tuple[int, int]:
        return self.start, self.end


_DEFAULT_MODEL = os.environ.get("ABOGEN_SPACY_MODEL", "en_core_web_sm")


@lru_cache(maxsize=1)
def _load_spacy_model(model: str = _DEFAULT_MODEL) -> Optional[Language]:
    if spacy is None:
        logger.debug("spaCy is not installed; skipping contraction disambiguation")
        return None

    try:
        nlp = spacy.load(model)
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.warning("Failed to load spaCy model '%s': %s", model, exc)
        return None
    return nlp


def resolve_ambiguous_contractions(
    text: str, *, model: Optional[str] = None
) -> Dict[Tuple[int, int], ContractionResolution]:
    """Use spaCy to disambiguate ambiguous contractions in *text*.

    Returns a mapping from (start, end) spans to their resolved expansion.
    Only ambiguous `'s` and `'d` contractions are considered.
    """
    if not text:
        return {}

    nlp = _load_spacy_model(model or _DEFAULT_MODEL)
    if nlp is None:
        return {}

    doc = nlp(text)
    resolutions: Dict[Tuple[int, int], ContractionResolution] = {}
    for token in doc:
        if token.text == "'s":
            resolution = _resolve_apostrophe_s(token)
        elif token.text == "'d":
            resolution = _resolve_apostrophe_d(token)
        else:
            resolution = None

        if resolution is None:
            continue

        if resolution.span not in resolutions:
            resolutions[resolution.span] = resolution
    return resolutions


def _resolution(
    prev: Token, token: Token, expansion_word: str, category: str, lemma_hint: str
) -> Optional[ContractionResolution]:
    if token is None or prev is None:
        return None

    if prev.idx + len(prev.text) != token.idx:
        # Not a contiguous contraction (whitespace or punctuation in between)
        return None

    surface_start = prev.idx
    surface_end = token.idx + len(token.text)
    surface_text = token.doc.text[surface_start:surface_end]

    expansion = _assemble_expansion(prev.text, surface_text, expansion_word)
    return ContractionResolution(
        start=surface_start,
        end=surface_end,
        surface=surface_text,
        expansion=expansion,
        category=category,
        lemma=lemma_hint,
    )


def _assemble_expansion(base_text: str, surface_text: str, expansion_word: str) -> str:
    """Combine *base_text* with *expansion_word*, preserving coarse casing."""
    if not expansion_word:
        return base_text

    if surface_text.isupper() and expansion_word.isalpha():
        adjusted = expansion_word.upper()
    elif len(surface_text) > 2 and surface_text[:-2].istitle() and expansion_word:
        # Surface like "It's" -> keep appended word lowercase
        adjusted = expansion_word.lower()
    else:
        adjusted = expansion_word

    return f"{base_text} {adjusted}".strip()


def _resolve_apostrophe_s(token: Token) -> Optional[ContractionResolution]:
    prev = token.nbor(-1) if token.i > 0 else None
    if prev is None:
        return None

    # Possessive marker e.g., dog's
    if token.tag_ == "POS" or token.lemma_ == "'s":
        return None

    prev_lower = prev.lemma_.lower()
    surface = token.doc.text[prev.idx : token.idx + len(token.text)]

    if prev_lower == "let":
        return _resolution(prev, token, "us", "contraction_let_us", "us")

    # Special check for 's been -> has been, overriding lemma
    next_content = _next_content_token(token)
    if next_content and next_content.text.lower() == "been":
        return _resolution(prev, token, "has", "contraction_aux_have", "have")

    lemma = token.lemma_.lower()
    if not lemma:
        lemma = "be" if _favors_be(token) else "have" if _favors_have(token) else "be"

    if lemma == "be":
        return _resolution(prev, token, "is", "contraction_aux_be", "be")
    if lemma == "have":
        return _resolution(prev, token, "has", "contraction_aux_have", "have")

    if _favors_have(token):
        return _resolution(prev, token, "has", "contraction_aux_have", "have")

    if _favors_be(token):
        return _resolution(prev, token, "is", "contraction_aux_be", "be")

    # Default to copula expansion.
    return _resolution(prev, token, "is", "contraction_aux_be", lemma or "be")


def _resolve_apostrophe_d(token: Token) -> Optional[ContractionResolution]:
    prev = token.nbor(-1) if token.i > 0 else None
    if prev is None:
        return None

    if token.morph.get("VerbForm") == ["Part"]:
        # spaCy sometimes tags possessives oddly; guard anyway
        return None

    lemma = token.lemma_.lower()
    tense = set(token.morph.get("Tense"))
    next_content = _next_content_token(token)
    prefers_had = _context_prefers_had(token)

    if prefers_had:
        return _resolution(prev, token, "had", "contraction_aux_have", "have")

    if "Past" in tense and lemma in {"have", "had"}:
        return _resolution(prev, token, "had", "contraction_aux_have", "have")

    if next_content is not None:
        next_tag = next_content.tag_
        next_lemma = next_content.lemma_.lower()
    else:
        next_tag = ""
        next_lemma = ""

    if next_tag == "VB":
        return _resolution(
            prev, token, "would", "contraction_modal_would", lemma or "will"
        )

    if token.tag_ == "MD" or lemma in {"will", "would", "shall"}:
        return _resolution(
            prev, token, "would", "contraction_modal_would", lemma or "will"
        )

    if next_lemma in {"been", "gone", "had", "better"} or next_tag in {"VBN", "VBD"}:
        return _resolution(prev, token, "had", "contraction_aux_have", "have")

    if lemma in {"have", "had"}:
        return _resolution(prev, token, "had", "contraction_aux_have", lemma)

    return _resolution(prev, token, "would", "contraction_modal_would", lemma or "will")


def _next_content_token(token: Token) -> Optional[Token]:
    doc = token.doc
    for candidate in doc[token.i + 1 :]:
        if candidate.is_space:
            continue
        if candidate.is_punct and candidate.text not in {"-"}:
            break
        if candidate.text in {"'", ""}:
            continue
        return candidate
    return None


def _favors_have(token: Token) -> bool:
    next_content = _next_content_token(token)
    if next_content is None:
        return False
    if next_content.tag_ in {"VBN"}:
        return True
    if next_content.lemma_.lower() in {"been", "gone", "had"}:
        return True
    return False


def _favors_be(token: Token) -> bool:
    next_content = _next_content_token(token)
    if next_content is None:
        return True
    if next_content.tag_ in {"VBG", "JJ", "RB", "DT", "IN"}:
        return True
    return False


def _context_prefers_had(token: Token) -> bool:
    head = token.head if token.head is not None else None
    if head is not None and head.i > token.i:
        head_tag = head.tag_
        head_lemma = head.lemma_.lower()
        if head_tag in {"VBN", "VBD"} or head_lemma in {"gone", "been", "had"}:
            return True
        if head_lemma == "better":
            return True

    next_content = _next_content_token(token)
    if next_content is None:
        return False
    next_tag = next_content.tag_
    next_lemma = next_content.lemma_.lower()
    if next_tag in {"VBN", "VBD"}:
        return True
    if next_lemma in {"been", "gone", "had"}:
        return True
    if next_lemma == "better":
        return True
    return False
