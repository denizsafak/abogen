from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    import spacy  # type: ignore
except Exception:  # pragma: no cover - spaCy may be unavailable in minimal environments
    spacy = None


@dataclass(frozen=True)
class HeteronymVariant:
    key: str
    label: str
    replacement_token: str
    example_sentence: str


@dataclass(frozen=True)
class HeteronymSpec:
    token: str
    variants: Tuple[HeteronymVariant, HeteronymVariant]

    def default_choice_for_token(self, spacy_token: Any) -> str:
        """Return the most likely variant key for this token."""
        pos = (getattr(spacy_token, "pos_", "") or "").upper()
        tag = (getattr(spacy_token, "tag_", "") or "").upper()

        token_lower = self.token.casefold()
        if token_lower == "wind":
            # VERB => /waɪnd/, NOUN => /wɪnd/
            return "verb" if pos == "VERB" else "noun"
        if token_lower == "read":
            # VBD/VBN => /rɛd/
            return "past" if tag in {"VBD", "VBN"} else "present"
        if token_lower == "tear":
            return "verb" if pos == "VERB" else "noun"
        if token_lower == "close":
            return "verb" if pos == "VERB" else "adj"
        if token_lower == "lead":
            # Default to verb unless POS suggests noun.
            return "metal" if pos == "NOUN" else "verb"
        return self.variants[0].key


# Minimal, high-confidence starter set.
# NOTE: These replacements intentionally prioritize speech output.
# Some replacements may not be appropriate for subtitles/text exports.
_HETERONYM_SPECS: Dict[str, HeteronymSpec] = {
    "wind": HeteronymSpec(
        token="wind",
        variants=(
            HeteronymVariant(
                key="noun",
                label="Noun (the wind)",
                replacement_token="wind",
                example_sentence="Listen to the wind.",
            ),
            HeteronymVariant(
                key="verb",
                label="Verb (to wind)",
                replacement_token="wynd",
                example_sentence="I need to wind the watch.",
            ),
        ),
    ),
    "read": HeteronymSpec(
        token="read",
        variants=(
            HeteronymVariant(
                key="present",
                label="Present (I read every day)",
                replacement_token="read",
                example_sentence="I read every day.",
            ),
            HeteronymVariant(
                key="past",
                label="Past (I read it yesterday)",
                replacement_token="red",
                example_sentence="I read it yesterday.",
            ),
        ),
    ),
    "tear": HeteronymSpec(
        token="tear",
        variants=(
            HeteronymVariant(
                key="noun",
                label="Noun (a tear /crying/)",
                replacement_token="tier",
                example_sentence="A tear rolled down her cheek.",
            ),
            HeteronymVariant(
                key="verb",
                label="Verb (to tear /rip/)",
                replacement_token="tear",
                example_sentence="Please don't tear the page.",
            ),
        ),
    ),
    "close": HeteronymSpec(
        token="close",
        variants=(
            HeteronymVariant(
                key="adj",
                label="Adjective (close /near/)",
                replacement_token="close",
                example_sentence="We are close to the station.",
            ),
            HeteronymVariant(
                key="verb",
                label="Verb (close /klohz/)",
                replacement_token="cloze",
                example_sentence="Please close the door.",
            ),
        ),
    ),
    "lead": HeteronymSpec(
        token="lead",
        variants=(
            HeteronymVariant(
                key="verb",
                label="Verb (to lead)",
                replacement_token="lead",
                example_sentence="They will lead the way.",
            ),
            HeteronymVariant(
                key="metal",
                label="Noun (lead /metal/)",
                replacement_token="led",
                example_sentence="The pipe was made of lead.",
            ),
        ),
    ),
}


def _hash_id(*parts: str) -> str:
    digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


_WORD_BOUNDARY_CACHE: Dict[str, re.Pattern[str]] = {}


def _word_boundary_pattern(token: str) -> re.Pattern[str]:
    key = token.casefold()
    cached = _WORD_BOUNDARY_CACHE.get(key)
    if cached is not None:
        return cached
    escaped = re.escape(token)
    pattern = re.compile(rf"(?i)(?<!\w){escaped}(?P<possessive>'s|\u2019s|\u2019)?(?!\w)")
    _WORD_BOUNDARY_CACHE[key] = pattern
    return pattern


def _preserve_case(replacement: str, original: str) -> str:
    if not replacement:
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _build_replacement_sentence(sentence: str, token: str, replacement_token: str) -> str:
    pattern = _word_boundary_pattern(token)

    def _repl(match: re.Match[str]) -> str:
        matched = match.group(0) or ""
        suffix = match.group("possessive") or ""
        base = matched[: len(matched) - len(suffix)] if suffix else matched
        return _preserve_case(replacement_token, base) + suffix

    return pattern.sub(_repl, sentence)


def _load_spacy(language: str) -> Any:
    if spacy is None:
        return None

    # English only for now.
    # Use installed small model; keep it simple.
    lang = (language or "en").lower()
    if lang.startswith("en"):
        try:
            return spacy.load("en_core_web_sm")
        except Exception:
            return spacy.blank("en")
    return spacy.blank("xx")


def extract_heteronym_overrides(
    chapters: Sequence[Mapping[str, Any]],
    *,
    language: str,
    existing: Optional[Iterable[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Extract distinct heteronym-containing sentences from chapters.

    Returns entries shaped for persistence + UI.

    Each entry contains:
    - id
    - token
    - sentence
    - options: [{key,label,replacement_token,replacement_sentence,example_sentence}]
    - default_choice
    - choice
    """

    lang = (language or "en").lower()
    if not lang.startswith("en"):
        return []

    if spacy is None:
        return []

    nlp = _load_spacy(lang)
    if nlp is None:
        return []

    previous_choices: Dict[str, str] = {}
    if existing:
        for item in existing:
            if not isinstance(item, Mapping):
                continue
            entry_id = str(item.get("id") or "").strip()
            choice = str(item.get("choice") or "").strip()
            if entry_id and choice:
                previous_choices[entry_id] = choice

    results: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            continue
        text = str(chapter.get("text") or "")
        if not text.strip():
            continue

        doc = nlp(text)
        for sent in getattr(doc, "sents", []):
            sentence = str(getattr(sent, "text", "") or "").strip()
            if not sentence:
                continue

            for token in sent:
                token_text = str(getattr(token, "text", "") or "")
                if not token_text:
                    continue
                token_key = token_text.casefold()
                spec = _HETERONYM_SPECS.get(token_key)
                if not spec:
                    continue

                dedupe_key = (token_key, sentence)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                entry_id = _hash_id(token_key, sentence)
                default_choice = spec.default_choice_for_token(token)
                choice = previous_choices.get(entry_id, default_choice)

                options: List[Dict[str, Any]] = []
                for variant in spec.variants:
                    replacement_sentence = _build_replacement_sentence(
                        sentence, token=spec.token, replacement_token=variant.replacement_token
                    )
                    options.append(
                        {
                            "key": variant.key,
                            "label": variant.label,
                            "replacement_token": variant.replacement_token,
                            "replacement_sentence": replacement_sentence,
                            "example_sentence": variant.example_sentence,
                        }
                    )

                results.append(
                    {
                        "id": entry_id,
                        "token": token_text,
                        "token_lower": token_key,
                        "sentence": sentence,
                        "options": options,
                        "default_choice": default_choice,
                        "choice": choice,
                    }
                )

    return results
