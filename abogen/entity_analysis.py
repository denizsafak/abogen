from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

try:  # pragma: no cover - fallback when spaCy not available during tests
    import spacy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - spaCy optional during runtime bootstrap
    spacy = None

_Language = Any  # type: ignore[misc,assignment]
Doc = Any  # type: ignore[misc,assignment]
Span = Any  # type: ignore[misc,assignment]


_TITLE_PREFIXES = (
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "prof",
    "sir",
    "madam",
    "lady",
    "lord",
    "capt",
    "captain",
    "col",
    "colonel",
    "maj",
    "major",
    "sgt",
    "sergeant",
    "rev",
    "father",
    "mother",
    "brother",
    "sister",
)

_STOP_LABELS = {
    "the",
    "that",
    "this",
    "those",
    "these",
    "there",
    "here",
    "then",
    "and",
    "but",
    "or",
    "nor",
    "so",
    "yet",
    "dr",
    "mr",
    "mrs",
    "ms",
    "miss",
    "sir",
    "madam",
    "lady",
    "lord",
}

_EXCLUDED_NER_LABELS = {
    "CARDINAL",
    "DATE",
    "ORDINAL",
    "PERCENT",
    "TIME",
    "LAW",
    "MONEY",
    "QUANTITY",
}

_TITLE_PATTERN = re.compile(r"^(?:" + "|".join(re.escape(prefix) for prefix in _TITLE_PREFIXES) + r")\.?\s+", re.IGNORECASE)
_POSSESSIVE_PATTERN = re.compile(r"(?:'s|’s|\u2019s)$", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[^\w\s'-]+")
_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_SUFFIX_PATTERN = re.compile(
    r",?\s+(?:jr|sr|ii|iii|iv|v|vi|md|phd|esq|esquire|dds|dvm)\.?$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class EntityRecord:
    key: Tuple[str, str]
    label: str
    kind: str
    category: str
    count: int = 0
    samples: List[Dict[str, Any]] = field(default_factory=list)
    chapter_indices: set[int] = field(default_factory=set)
    forms: Counter = field(default_factory=Counter)
    first_position: Optional[Tuple[int, int]] = None

    def register(self, *, chapter_index: int, position: int, text: str, sentence: Optional[str]) -> None:
        self.count += 1
        self.chapter_indices.add(chapter_index)
        self.forms[text] += 1
        if self.first_position is None:
            self.first_position = (chapter_index, position)
        if sentence and len(self.samples) < 5:
            payload = {
                "excerpt": sentence.strip(),
                "chapter_index": chapter_index,
            }
            if payload not in self.samples:
                self.samples.append(payload)

    def as_dict(self, ordinal: int) -> Dict[str, Any]:
        chapter_indices = sorted(self.chapter_indices)
        first_chapter = chapter_indices[0] if chapter_indices else None
        return {
            "id": f"{self.category}_{ordinal}",
            "label": self.label,
            "normalized": self.key[1],
            "category": self.category,
            "kind": self.kind,
            "count": self.count,
            "samples": list(self.samples),
            "chapter_indices": chapter_indices,
            "first_chapter": first_chapter,
            "forms": self.forms.most_common(6),
        }


@dataclass(slots=True)
class EntityExtractionResult:
    summary: Dict[str, Any]
    cache_key: str
    elapsed: float
    errors: List[str]


class EntityModelError(RuntimeError):
    pass


_MODEL_CACHE: Dict[str, Any] = {}
_MODEL_LOCK = threading.RLock()


def _resolve_model_name(language: str) -> str:
    override = os.environ.get("ABOGEN_SPACY_MODEL")
    if override:
        return override.strip()
    lowered = language.strip().lower()
    if lowered.startswith("en"):
        return "en_core_web_sm"
    return "en_core_web_sm"


def _load_model(language: str) -> Any:
    if spacy is None:
        raise EntityModelError("spaCy is not available. Install spaCy to enable entity extraction.")

    model_name = _resolve_model_name(language)
    cache_key = model_name.lower()
    with _MODEL_LOCK:
        if cache_key in _MODEL_CACHE:
            return _MODEL_CACHE[cache_key]
        try:
            nlp = spacy.load(model_name)  # type: ignore[arg-type]
        except OSError as exc:  # pragma: no cover - external dependency failure
            raise EntityModelError(
                f"spaCy model '{model_name}' is not installed. Download it with "
                "`python -m spacy download en_core_web_sm`."
            ) from exc
        nlp.max_length = max(nlp.max_length, 2_000_000)
        _MODEL_CACHE[cache_key] = nlp
        return nlp


def _normalize_label(text: str) -> str:
    if not text:
        return ""
    stripped = text.strip().strip("\"'`“”’")
    if not stripped:
        return ""
    stripped = _TITLE_PATTERN.sub("", stripped)
    stripped = _SUFFIX_PATTERN.sub("", stripped)
    stripped = _POSSESSIVE_PATTERN.sub("", stripped)
    stripped = _NON_WORD_PATTERN.sub(" ", stripped)
    stripped = _MULTI_SPACE_PATTERN.sub(" ", stripped)
    stripped = stripped.strip()
    if not stripped or stripped.lower() in _STOP_LABELS:
        return ""
    parts = stripped.split()
    if not parts:
        return ""
    if len(parts) == 1 and len(parts[0]) <= 1:
        return ""
    # Normalise casing: preserve uppercase abbreviations, otherwise title case.
    normalized_parts = []
    for index, part in enumerate(parts):
        if part.isupper():
            normalized_parts.append(part)
        elif part[:1].isupper():
            normalized_parts.append(part[:1].upper() + part[1:])
        elif index == 0:
            normalized_parts.append(part[:1].upper() + part[1:])
        else:
            normalized_parts.append(part)
    normalized = " ".join(normalized_parts).strip()
    if normalized.lower() in _STOP_LABELS:
        return ""
    return normalized


def _token_key(value: str) -> str:
    return _MULTI_SPACE_PATTERN.sub(" ", value.lower().strip()).strip()


def _iter_named_entities(doc: Any) -> Iterable[Any]:  # type: ignore[override]
    for ent in getattr(doc, "ents", ()):
        if ent.label_ == "":
            continue
        yield ent


def _extract_propn_tokens(doc: Any) -> Iterable[Any]:  # type: ignore[override]
    seen: set[Tuple[int, int]] = set()
    for ent in getattr(doc, "ents", ()):  # guard multi-token spans
        seen.add((ent.start, ent.end))
    for token in doc:
        if token.pos_ != "PROPN":
            continue
        span_key = (token.i, token.i + 1)
        if span_key in seen:
            continue
        if token.is_stop:
            continue
        text = token.text.strip()
        if not text:
            continue
        if token.ent_type_:
            continue
        yield doc[token.i : token.i + 1]


def _empty_result(cache_key: str, error: Optional[str] = None) -> EntityExtractionResult:
    payload = {
        "people": [],
        "entities": [],
        "index": {"tokens": []},
        "stats": {
            "tokens": 0,
            "chapters": 0,
            "processed": False,
        },
        "model": None,
    }
    errors = [error] if error else []
    return EntityExtractionResult(summary=payload, cache_key=cache_key, elapsed=0.0, errors=errors)


def extract_entities(
    chapters: Iterable[Mapping[str, Any]],
    *,
    language: str = "en",
) -> EntityExtractionResult:
    start = time.perf_counter()
    normalized_language = language or "en"
    combined_hasher = hashlib.sha1()
    chapter_texts: List[Tuple[int, str]] = []
    for idx, chapter in enumerate(chapters):
        text = chapter.get("text") if isinstance(chapter, Mapping) else None
        text_value = str(text or "")
        original_index = idx
        if isinstance(chapter, Mapping):
            try:
                original_index = int(chapter.get("index", idx))
            except (TypeError, ValueError):
                original_index = idx
        chapter_texts.append((original_index, text_value))
        if text_value:
            combined_hasher.update(text_value.encode("utf-8", "ignore"))
            combined_hasher.update(str(original_index).encode("utf-8", "ignore"))
    cache_key = combined_hasher.hexdigest()

    if not chapter_texts:
        return _empty_result(cache_key)

    try:
        nlp = _load_model(normalized_language)
    except EntityModelError as exc:
        return _empty_result(cache_key, str(exc))

    records: Dict[Tuple[str, str], EntityRecord] = {}
    tokens_for_index: Dict[str, Dict[str, Any]] = {}
    processed_tokens = 0

    for chapter_index, text in chapter_texts:
        trimmed = text.strip()
        if not trimmed:
            continue
        if len(trimmed) + 1024 > nlp.max_length:
            nlp.max_length = len(trimmed) + 1024
        doc = nlp(trimmed)

        def _register_span(span: Any, category_hint: Optional[str] = None) -> None:
            nonlocal processed_tokens
            if category_hint is None and span.label_ in _EXCLUDED_NER_LABELS:
                return
            cleaned = _normalize_label(span.text)
            if not cleaned:
                return
            key = _token_key(cleaned)
            if not key:
                return
            category = category_hint or ("people" if span.label_ == "PERSON" else "entities")
            record_key = (category, key)
            record = records.get(record_key)
            if record is None:
                record = EntityRecord(
                    key=record_key,
                    label=cleaned,
                    kind=span.label_ or ("PROPN" if category == "entities" else "PERSON"),
                    category=category,
                )
                records[record_key] = record
            sentence = span.sent.text if hasattr(span, "sent") and span.sent is not None else None
            record.register(
                chapter_index=chapter_index,
                position=span.start,
                text=span.text,
                sentence=sentence,
            )
            processed_tokens += 1
            index_entry = tokens_for_index.get(key)
            if index_entry is None:
                index_entry = {
                    "token": record.label,
                    "normalized": key,
                    "category": category,
                    "count": 0,
                    "samples": [],
                }
                tokens_for_index[key] = index_entry
            index_entry["count"] += 1
            if sentence and len(index_entry["samples"]) < 3:
                if sentence not in index_entry["samples"]:
                    index_entry["samples"].append(sentence)

        for ent in _iter_named_entities(doc):
            _register_span(ent)

        for span in _extract_propn_tokens(doc):
            _register_span(span, category_hint="entities")

    elapsed = time.perf_counter() - start

    people_records = [record for record in records.values() if record.category == "people"]
    people_keys = {record.key[1] for record in people_records}
    entity_records = [
        record
        for record in records.values()
        if record.category == "entities"
        and record.key[1] not in people_keys
        and record.kind != "PERSON"
    ]

    people_records.sort(key=lambda rec: (-rec.count, rec.label))
    entity_records.sort(key=lambda rec: (-rec.count, rec.label))

    people_payload = [record.as_dict(index + 1) for index, record in enumerate(people_records)]
    entity_payload = [record.as_dict(index + 1) for index, record in enumerate(entity_records)]

    index_payload = sorted(tokens_for_index.values(), key=lambda item: (-item["count"], item["token"]))

    summary = {
        "people": people_payload,
        "entities": entity_payload,
        "index": {"tokens": index_payload},
        "stats": {
            "tokens": processed_tokens,
            "chapters": len(chapter_texts),
            "processed": True,
            "people": len(people_payload),
            "entities": len(entity_payload),
        },
        "model": {
            "name": getattr(nlp, "meta", {}).get("name", "unknown"),
            "version": getattr(nlp, "meta", {}).get("version", "unknown"),
            "lang": getattr(nlp, "meta", {}).get("lang", normalized_language),
        },
    }

    return EntityExtractionResult(summary=summary, cache_key=cache_key, elapsed=elapsed, errors=[])


def search_tokens(index: Mapping[str, Any], query: str, *, limit: int = 15) -> List[Dict[str, Any]]:
    tokens = index.get("tokens") if isinstance(index, Mapping) else None
    if not isinstance(tokens, list) or not query:
        return []
    normalized = query.strip().lower()
    if not normalized:
        return tokens[:limit]
    results: List[Dict[str, Any]] = []
    for entry in tokens:
        token_label = str(entry.get("token", ""))
        normalized_label = token_label.lower()
        if normalized in normalized_label or normalized in str(entry.get("normalized", "")):
            results.append(entry)
        if len(results) >= limit:
            break
    return results


def merge_override(summary: Mapping[str, Any], overrides: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(summary, Mapping):
        return {"people": [], "entities": []}
    merged_summary: Dict[str, Any] = dict(summary)
    for key in ("people", "entities"):
        items = summary.get(key)
        if not isinstance(items, list):
            continue
        merged_items: List[Dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, Mapping):
                continue
            normalized = _token_key(str(entry.get("normalized") or entry.get("label") or ""))
            merged = dict(entry)
            if normalized and normalized in overrides:
                merged_override = dict(overrides[normalized])
                merged["override"] = merged_override
            merged_items.append(merged)
        merged_summary[key] = merged_items
    return merged_summary


def normalize_token(token: str) -> str:
    return _token_key(_normalize_label(token))


def normalize_manual_override_token(token: str) -> str:
    if not token:
        return ""
    stripped = token.strip().strip("\"'`“”’")
    if not stripped:
        return ""
    return _MULTI_SPACE_PATTERN.sub(" ", stripped.lower()).strip()
