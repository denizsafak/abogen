from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import unicodedata

_DIALOGUE_VERBS = (
    "said",
    "asked",
    "replied",
    "whispered",
    "shouted",
    "cried",
    "muttered",
    "answered",
    "hissed",
    "called",
    "added",
    "continued",
    "insisted",
    "remarked",
    "yelled",
    "breathed",
    "murmured",
    "exclaimed",
    "explained",
    "noted",
)

_VERB_PATTERN = "(?:" + "|".join(_DIALOGUE_VERBS) + ")"
_NAME_FRAGMENT = r"[A-ZÀ-ÖØ-Þ][\w'’\-]*"
_NAME_PATTERN = rf"{_NAME_FRAGMENT}(?:\s+{_NAME_FRAGMENT})*"

_COLON_PATTERN = re.compile(rf"^\s*({_NAME_PATTERN})\s*:\s*(.+)$")
_NAME_BEFORE_VERB = re.compile(rf"({_NAME_PATTERN})\s+{_VERB_PATTERN}\b", re.IGNORECASE)
_VERB_BEFORE_NAME = re.compile(rf"{_VERB_PATTERN}\s+({_NAME_PATTERN})", re.IGNORECASE)
_PRONOUN_PATTERN = re.compile(r"\b(?:he|she|they)\b", re.IGNORECASE)
_QUOTE_PATTERN = re.compile(r'["“”]([^"“”\\]*(?:\\.[^"“”\\]*)*)["”]')
_MALE_PRONOUN_PATTERN = re.compile(r"\b(?:he|him|his|himself)\b", re.IGNORECASE)
_FEMALE_PRONOUN_PATTERN = re.compile(r"\b(?:she|her|hers|herself)\b", re.IGNORECASE)
_PRONOUN_LABELS = {
    "he",
    "she",
    "they",
    "them",
    "theirs",
    "their",
    "themselves",
    "him",
    "his",
    "himself",
    "her",
    "hers",
    "herself",
    "we",
    "us",
    "our",
    "ours",
    "ourselves",
    "i",
    "me",
    "my",
    "mine",
    "myself",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}

_FEMALE_TITLE_HINTS = (
    "madame",
    "mme",
    "madam",
    "mrs",
    "miss",
    "ms",
    "lady",
    "countess",
    "baroness",
    "princess",
    "queen",
    "mademoiselle",
)

_MALE_TITLE_HINTS = (
    "monsieur",
    "m.",
    "mr",
    "sir",
    "lord",
    "count",
    "baron",
    "prince",
    "king",
    "abbé",
    "abbe",
)

_MALE_TOKEN_WEIGHTS = {
    "he": 1.0,
    "him": 0.6,
    "his": 0.75,
    "himself": 1.0,
}

_FEMALE_TOKEN_WEIGHTS = {
    "she": 1.0,
    "her": 0.4,
    "hers": 0.75,
    "herself": 1.0,
}

_STOP_LABELS = {
    "and",
    "but",
    "then",
    "though",
    "meanwhile",
    "therefore",
    "after",
    "before",
    "when",
    "while",
    "because",
    "as",
    "yet",
    "nor",
    "so",
    "thus",
    "suddenly",
    "eventually",
    "finally",
    "until",
    "unless",
}


@dataclass(slots=True)
class SpeakerGuess:
    speaker_id: str
    label: str
    count: int = 0
    confidence: str = "low"
    sample_quotes: List[Dict[str, str]] = field(default_factory=list)
    suppressed: bool = False
    gender: str = "unknown"
    detected_gender: str = "unknown"
    male_votes: int = 0
    female_votes: int = 0

    def register_occurrence(
        self,
        confidence: str,
        text: str,
        quote: Optional[str],
        male_votes: int,
        female_votes: int,
        sample_excerpt: Optional[str] = None,
    ) -> None:
        self.count += 1
        if _CONFIDENCE_RANK.get(confidence, 0) > _CONFIDENCE_RANK.get(self.confidence, 0):
            self.confidence = confidence

        excerpt = sample_excerpt if sample_excerpt is not None else _build_excerpt(text, quote)
        gender_hint = _format_gender_hint(male_votes, female_votes)
        if excerpt:
            payload = {"excerpt": excerpt, "gender_hint": gender_hint}
            if payload not in self.sample_quotes:
                self.sample_quotes.append(payload)
                if len(self.sample_quotes) > 3:
                    self.sample_quotes = self.sample_quotes[:3]

        if male_votes:
            self.male_votes += male_votes
        if female_votes:
            self.female_votes += female_votes
        self.detected_gender = _derive_gender(self.male_votes, self.female_votes, self.detected_gender)
        if self.gender in {"unknown", "male", "female"}:
            self.gender = _derive_gender(self.male_votes, self.female_votes, self.gender)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.speaker_id,
            "label": self.label,
            "count": self.count,
            "confidence": self.confidence,
            "sample_quotes": [dict(sample) for sample in self.sample_quotes],
            "suppressed": self.suppressed,
            "gender": self.gender,
            "detected_gender": self.detected_gender,
        }


@dataclass(slots=True)
class SpeakerAnalysis:
    assignments: Dict[str, str]
    speakers: Dict[str, SpeakerGuess]
    suppressed: List[str]
    narrator: str = "narrator"
    version: str = "1.0"
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "narrator": self.narrator,
            "assignments": dict(self.assignments),
            "speakers": {speaker_id: guess.as_dict() for speaker_id, guess in self.speakers.items()},
            "suppressed": list(self.suppressed),
            "stats": dict(self.stats),
        }


def analyze_speakers(
    chapters: Sequence[Dict[str, Any]] | Iterable[Dict[str, Any]],
    chunks: Sequence[Dict[str, Any]] | Iterable[Dict[str, Any]],
    *,
    threshold: int = 3,
    max_speakers: int = 8,
) -> SpeakerAnalysis:
    narrator_id = "narrator"
    speaker_guesses: Dict[str, SpeakerGuess] = {
        narrator_id: SpeakerGuess(speaker_id=narrator_id, label="Narrator", confidence="low")
    }
    label_index: Dict[str, str] = {"Narrator": narrator_id}
    assignments: Dict[str, str] = {}
    suppressed: List[str] = []

    ordered_chunks = sorted(
        (dict(chunk) for chunk in chunks),
        key=lambda entry: (
            _safe_int(entry.get("chapter_index")),
            _safe_int(entry.get("chunk_index")),
        ),
    )
    last_explicit: Optional[str] = None
    explicit_assignments = 0
    unique_speakers: set[str] = set()

    for index, chunk in enumerate(ordered_chunks):
        chunk_id = str(chunk.get("id") or "")
        text = _get_chunk_text(chunk)
        speaker_id, confidence, quote = _infer_chunk_speaker(text, last_explicit)
        if speaker_id is None:
            speaker_id = last_explicit or narrator_id
            confidence = "medium" if last_explicit else "low"
            quote = quote or _extract_quote(text)
        if speaker_id != narrator_id:
            last_explicit = speaker_id
            explicit_assignments += 1

        if speaker_id in speaker_guesses:
            record_id = speaker_id
            guess = speaker_guesses[record_id]
            label = guess.label
        else:
            label = _normalize_label(speaker_id)
            record_id = label_index.get(label)
            if record_id is None:
                record_id = _dedupe_slug(_slugify(label), speaker_guesses)
                label_index[label] = record_id
                speaker_guesses[record_id] = SpeakerGuess(speaker_id=record_id, label=label)
            guess = speaker_guesses[record_id]
        assignments[chunk_id] = record_id
        unique_speakers.add(record_id)

        if record_id != narrator_id and record_id != speaker_id and speaker_id == last_explicit:
            last_explicit = record_id

        sample_excerpt = None
        if record_id != narrator_id:
            sample_excerpt = _select_sample_excerpt(ordered_chunks, index, guess.label, quote, confidence)

        male_votes, female_votes = _count_gender_votes(text, guess.label)

        guess.register_occurrence(confidence, text, quote, male_votes, female_votes, sample_excerpt)

    active_speakers = [sid for sid in speaker_guesses if sid != narrator_id]
    # Apply minimum occurrence threshold.
    for speaker_id in list(active_speakers):
        guess = speaker_guesses[speaker_id]
        if guess.count < max(1, threshold):
            guess.suppressed = True
            suppressed.append(speaker_id)
            _reassign(assignments, speaker_id, narrator_id)
            active_speakers.remove(speaker_id)

    # Apply maximum active speaker cap.
    if max_speakers and len(active_speakers) > max_speakers:
        active_speakers.sort(key=lambda sid: (-speaker_guesses[sid].count, sid))
        for speaker_id in active_speakers[max_speakers:]:
            guess = speaker_guesses[speaker_id]
            guess.suppressed = True
            suppressed.append(speaker_id)
            _reassign(assignments, speaker_id, narrator_id)
        active_speakers = active_speakers[:max_speakers]

    narrator_guess = speaker_guesses[narrator_id]
    narrator_guess.count = sum(1 for value in assignments.values() if value == narrator_id)
    narrator_guess.confidence = "low"

    stats = {
        "total_chunks": len(ordered_chunks),
        "explicit_chunks": explicit_assignments,
        "active_speakers": len(active_speakers),
        "unique_speakers": len(unique_speakers),
        "suppressed": len(suppressed),
    }

    return SpeakerAnalysis(
        assignments=assignments,
        speakers=speaker_guesses,
        suppressed=suppressed,
        narrator=narrator_id,
        stats=stats,
    )


def _infer_chunk_speaker(text: str, last_explicit: Optional[str]) -> Tuple[Optional[str], str, Optional[str]]:
    normalized = text.strip()
    if not normalized:
        return None, "low", None

    colon_match = _COLON_PATTERN.match(normalized)
    if colon_match:
        raw_label = colon_match.group(1)
        cleaned = _normalize_candidate_name(raw_label)
        if cleaned is None:
            return None, "low", colon_match.group(2).strip()
        quote = colon_match.group(2).strip()
        return cleaned, "high", quote

    quote = _extract_quote(normalized)
    if not quote:
        return None, "low", None

    before, after = _split_around_quote(normalized, quote)

    candidate = _match_name_near_quote(before, after)
    if candidate:
        cleaned = _normalize_candidate_name(candidate)
        if cleaned:
            return cleaned, "high", quote

    if last_explicit:
        pronoun_after = _PRONOUN_PATTERN.search(after)
        pronoun_before = _PRONOUN_PATTERN.search(before)
        if pronoun_after or pronoun_before:
            return last_explicit, "medium", quote

    return None, "low", quote


def _split_around_quote(text: str, quote: str) -> Tuple[str, str]:
    quote_index = text.find(quote)
    if quote_index == -1:
        return text, ""
    before = text[:quote_index]
    after = text[quote_index + len(quote) :]
    return before, after


def _match_name_near_quote(before: str, after: str) -> Optional[str]:
    trailing = before[-120:]
    leading = after[:120]

    match = _NAME_BEFORE_VERB.search(trailing)
    if match:
        name = match.group(1)
        if _looks_like_name(name):
            return name

    match = re.search(rf"({_NAME_PATTERN})\s*,?\s*{_VERB_PATTERN}", leading, flags=re.IGNORECASE)
    if match:
        name = match.group(1)
        if _looks_like_name(name):
            return name

    match = _VERB_BEFORE_NAME.search(leading)
    if match:
        name = match.group(1)
        if _looks_like_name(name):
            return name

    return None


def _looks_like_name(value: str) -> bool:
    normalized = _normalize_candidate_name(value)
    if not normalized:
        return False
    parts = normalized.split()
    if not parts:
        return False
    return all(part and part[0].isupper() for part in parts)


def _extract_quote(text: str) -> Optional[str]:
    match = _QUOTE_PATTERN.search(text)
    if not match:
        return None
    return match.group(0)


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return slug or "speaker"


def _dedupe_slug(slug: str, existing: Dict[str, SpeakerGuess]) -> str:
    candidate = slug
    index = 2
    while candidate in existing:
        candidate = f"{slug}_{index}"
        index += 1
    return candidate


def _normalize_label(label: str) -> str:
    words = re.split(r"\s+", label.strip())
    return " ".join(word.capitalize() for word in words if word)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _reassign(assignments: Dict[str, str], old: str, new: str) -> None:
    for key, value in list(assignments.items()):
        if value == old:
            assignments[key] = new


def _strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _count_gender_votes(text: str, label: Optional[str]) -> Tuple[int, int]:
    if not text:
        return 0, 0

    search_text = text
    windows: List[Tuple[int, int]] = []
    degrade_factor = 1.0

    if label:
        pattern = re.compile(re.escape(label), re.IGNORECASE)
        matches = list(pattern.finditer(search_text))
        if not matches:
            alt_label = _strip_diacritics(label)
            if alt_label and alt_label != label:
                ascii_text = _strip_diacritics(search_text)
                pattern_alt = re.compile(re.escape(alt_label), re.IGNORECASE)
                windows = [match.span() for match in pattern_alt.finditer(ascii_text)]
                # Map spans back roughly using proportional index
                if windows:
                    mapped: List[Tuple[int, int]] = []
                    for start, end in windows:
                        start_idx = min(len(search_text) - 1, int(start * len(search_text) / max(len(ascii_text), 1)))
                        end_idx = min(len(search_text), int(end * len(search_text) / max(len(ascii_text), 1)))
                        mapped.append((start_idx, end_idx))
                    windows = mapped
        else:
            windows = [match.span() for match in matches]

    if not windows:
        windows = [(0, len(search_text))]
        degrade_factor = 0.25

    radius = 60
    quote_spans: List[Tuple[int, int, str]] = []
    for match in _QUOTE_PATTERN.finditer(search_text):
        try:
            content_start, content_end = match.span(1)
        except IndexError:
            content_start, content_end = match.span()
        if content_start < content_end:
            quote_spans.append((content_start, content_end, search_text[content_start:content_end]))

    normalized_label = _normalize_candidate_name(label) if label else None
    normalized_label_lower = normalized_label.lower() if normalized_label else None

    def _window_weight(position: int) -> float:
        for start, end in windows:
            if position < start - radius or position > end + radius:
                continue
            if position >= end:
                return 1.0
            if position <= start:
                return 0.2
            return 1.0
        return 0.0

    def _quote_weight(position: int) -> float:
        for start, end, content in quote_spans:
            if position < start or position >= end:
                continue
            local_index = position - start
            prefix = content[:local_index]
            tail = prefix[-80:]
            name_matches = list(re.finditer(_NAME_PATTERN, tail))
            if name_matches:
                last_name = _normalize_candidate_name(name_matches[-1].group(0))
                if normalized_label_lower and last_name and last_name.lower() == normalized_label_lower:
                    return 0.6
                return 0.05
            if re.search(r"[.!?]\s", prefix):
                return 0.2
            if prefix.strip():
                return 0.15
            return 0.1
        return 1.0

    male_score = 0.0
    for match in _MALE_PRONOUN_PATTERN.finditer(search_text):
        base_weight = _window_weight(match.start())
        if not base_weight:
            continue
        quote_modifier = _quote_weight(match.start())
        weight = base_weight * quote_modifier
        if not weight:
            continue
        token = match.group(0).lower()
        male_score += _MALE_TOKEN_WEIGHTS.get(token, 0.6) * weight

    female_score = 0.0
    for match in _FEMALE_PRONOUN_PATTERN.finditer(search_text):
        base_weight = _window_weight(match.start())
        if not base_weight:
            continue
        quote_modifier = _quote_weight(match.start())
        weight = base_weight * quote_modifier
        if not weight:
            continue
        if quote_modifier >= 0.95:
            weight = max(weight, 0.4)
        token = match.group(0).lower()
        female_score += _FEMALE_TOKEN_WEIGHTS.get(token, 0.4) * weight

    for start, end in windows:
        span_start = max(0, start - 40)
        span_end = min(len(search_text), end + 40)
        span_text = search_text[span_start:span_end].lower()
        if any(title in span_text for title in _FEMALE_TITLE_HINTS):
            female_score += 2.5
        if any(title in span_text for title in _MALE_TITLE_HINTS):
            male_score += 2.5

    male_votes = int(round(male_score * degrade_factor))
    female_votes = int(round(female_score * degrade_factor))
    return male_votes, female_votes


def _derive_gender(male_votes: int, female_votes: int, current: str) -> str:
    if male_votes == 0 and female_votes == 0:
        return current if current != "unknown" else "unknown"

    male_threshold = max(2, female_votes + 1)
    female_threshold = max(2, male_votes + 1)

    if male_votes >= male_threshold:
        return "male"
    if female_votes >= female_threshold:
        return "female"

    if current in {"male", "female"}:
        return current
    return "unknown"


def _get_chunk_text(chunk: Dict[str, Any]) -> str:
    if not isinstance(chunk, dict):
        return ""
    value = chunk.get("normalized_text") or chunk.get("text") or ""
    return str(value)


def _trim_paragraph(paragraph: str, limit: int = 600) -> str:
    normalized = (paragraph or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _compose_context_excerpt(before: str, current: str, after: str) -> str:
    segments = []
    for value in (before, current, after):
        trimmed = _trim_paragraph(value)
        if trimmed:
            segments.append(trimmed)
    return "\n\n".join(segments)


def _contains_dialogue_attribution(label: str, text: str, quote: Optional[str]) -> bool:
    if not label or not text:
        return False
    escaped_label = re.escape(label)
    direct_pattern = re.compile(rf"\b{escaped_label}\b\s+(?:{_VERB_PATTERN})\b", re.IGNORECASE)
    reverse_pattern = re.compile(rf"(?:{_VERB_PATTERN})\s+\b{escaped_label}\b", re.IGNORECASE)
    colon_pattern = re.compile(rf"^\s*{escaped_label}\s*:\s*", re.IGNORECASE)

    if colon_pattern.search(text):
        return True
    if direct_pattern.search(text) or reverse_pattern.search(text):
        return True
    if quote:
        before, after = _split_around_quote(text, quote)
        if direct_pattern.search(before) or reverse_pattern.search(after):
            return True
    return False


def _select_sample_excerpt(
    chunks: Sequence[Dict[str, Any]],
    index: int,
    label: str,
    quote: Optional[str],
    confidence: str,
) -> Optional[str]:
    if confidence != "high" or not label:
        return None
    if index < 0 or index >= len(chunks):
        return None
    current = _get_chunk_text(chunks[index])
    if not current or not _contains_dialogue_attribution(label, current, quote):
        return None
    previous = _get_chunk_text(chunks[index - 1]) if index > 0 else ""
    following = _get_chunk_text(chunks[index + 1]) if index + 1 < len(chunks) else ""
    excerpt = _compose_context_excerpt(previous, current, following)
    return excerpt or None


def _build_excerpt(text: str, quote: Optional[str]) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    if quote:
        location = normalized.find(quote)
        if location != -1:
            start = max(0, location - 120)
            end = min(len(normalized), location + len(quote) + 120)
            snippet = normalized[start:end].strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(normalized):
                snippet = snippet + "…"
            return snippet
    if len(normalized) > 240:
        return normalized[:240].rstrip() + "…"
    return normalized


def _format_gender_hint(male_votes: int, female_votes: int) -> str:
    if male_votes and female_votes:
        return "Context mentions both male and female pronouns."
    if male_votes:
        if male_votes >= 3:
            return "Multiple male pronouns detected nearby."
        return "Some male pronouns detected in the surrounding text."
    if female_votes:
        if female_votes >= 3:
            return "Multiple female pronouns detected nearby."
        return "Some female pronouns detected in the surrounding text."
    return "No clear pronoun signal detected."


def _normalize_candidate_name(raw: str) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().strip('"“”\'’.,:;!')
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    parts = cleaned.split()
    filtered: List[str] = []
    for part in parts:
        if not part:
            continue
        if not filtered and part.lower() in _STOP_LABELS:
            continue
        filtered.append(part)
    while filtered and filtered[-1].lower() in _STOP_LABELS:
        filtered.pop()
    if not filtered:
        return None
    if all(part.lower() in _STOP_LABELS for part in filtered):
        return None
    contiguous: List[str] = []
    for part in filtered:
        if part and part[0].isupper():
            contiguous.append(part)
        else:
            break
    if contiguous:
        candidate = " ".join(contiguous)
    else:
        candidate = ""
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered in _PRONOUN_LABELS or lowered in _STOP_LABELS:
        return None
    return candidate