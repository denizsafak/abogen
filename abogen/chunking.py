from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Literal, Optional, Tuple
from typing import Pattern

import re

from abogen.kokoro_text_normalization import ApostropheConfig, normalize_for_pipeline
from abogen.normalization_settings import build_apostrophe_config, get_runtime_settings

ChunkLevel = Literal["paragraph", "sentence"]

_SENTENCE_SPLIT_REGEX = re.compile(r"(?<!\b[A-Z])[.!?][\s\n]+")
_WHITESPACE_REGEX = re.compile(r"\s+")
_PARAGRAPH_SPLIT_REGEX = re.compile(r"(?:\r?\n){2,}")
_ABBREVIATION_END_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Rev|Sr|Jr|St|Gen|Lt|Col|Sgt|Capt|Adm|Cmdr|vs|etc)\.$",
    re.IGNORECASE,
)

_PIPELINE_APOSTROPHE_CONFIG = ApostropheConfig()


@dataclass(frozen=True)
class Chunk:
    id: str
    chapter_index: int
    chunk_index: int
    level: ChunkLevel
    text: str
    speaker_id: str = "narrator"
    voice: Optional[str] = None
    voice_profile: Optional[str] = None
    voice_formula: Optional[str] = None
    display_text: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "chapter_index": self.chapter_index,
            "chunk_index": self.chunk_index,
            "level": self.level,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "voice": self.voice,
            "voice_profile": self.voice_profile,
            "voice_formula": self.voice_formula,
            "display_text": self.display_text,
        }


def _iter_paragraphs(text: str) -> Iterator[str]:
    for raw_segment in _PARAGRAPH_SPLIT_REGEX.split(text.strip()):
        normalized = raw_segment.strip()
        if normalized:
            yield normalized


def _iter_sentences(paragraph: str) -> Iterator[Tuple[str, str]]:
    if not paragraph:
        return
    start = 0
    for match in _SENTENCE_SPLIT_REGEX.finditer(paragraph):
        end = match.end()
        raw_segment = paragraph[start:end]
        candidate = raw_segment.strip()
        if candidate:
            yield candidate, raw_segment
        start = match.end()
    tail_raw = paragraph[start:]
    tail = tail_raw.strip()
    if tail:
        yield tail, tail_raw


def _normalize_whitespace(value: str) -> str:
    return _WHITESPACE_REGEX.sub(" ", value).strip()


def _normalize_chunk_text(value: str) -> str:
    settings = get_runtime_settings()
    config = build_apostrophe_config(settings=settings, base=_PIPELINE_APOSTROPHE_CONFIG)
    normalized = normalize_for_pipeline(value, config=config, settings=settings)
    return _normalize_whitespace(normalized)


def _split_sentences(paragraph: str) -> List[Tuple[str, str]]:
    sentences = list(_iter_sentences(paragraph))
    if not sentences:
        return []

    merged: List[Tuple[str, str]] = []
    buffer_norm: List[str] = []
    buffer_raw: List[str] = []

    for normalized_sentence, raw_sentence in sentences:
        if buffer_norm:
            buffer_norm.append(normalized_sentence)
            buffer_raw.append(raw_sentence)
        else:
            buffer_norm = [normalized_sentence]
            buffer_raw = [raw_sentence]

        if _ABBREVIATION_END_RE.search(normalized_sentence.rstrip()):
            continue

        merged.append((" ".join(buffer_norm), "".join(buffer_raw)))
        buffer_norm = []
        buffer_raw = []

    if buffer_norm:
        merged.append((" ".join(buffer_norm), "".join(buffer_raw)))

    return merged


def chunk_text(
    *,
    chapter_index: int,
    chapter_title: str,
    text: str,
    level: ChunkLevel,
    speaker_id: str = "narrator",
    voice: Optional[str] = None,
    voice_profile: Optional[str] = None,
    voice_formula: Optional[str] = None,
    chunk_prefix: Optional[str] = None,
) -> List[Dict[str, object]]:
    """Split text into ordered chunk dictionaries."""

    prefix = chunk_prefix or f"chap{chapter_index:04d}"
    chunks: List[Dict[str, object]] = []

    if level == "paragraph":
        paragraphs = list(_iter_paragraphs(text)) or [text.strip()]
        for para_index, paragraph in enumerate(paragraphs):
            normalized = _normalize_whitespace(paragraph)
            if not normalized:
                continue
            chunk_id = f"{prefix}_p{para_index:04d}"
            payload = Chunk(
                id=chunk_id,
                chapter_index=chapter_index,
                chunk_index=len(chunks),
                level=level,
                text=normalized,
                speaker_id=speaker_id,
                voice=voice,
                voice_profile=voice_profile,
                voice_formula=voice_formula,
            ).as_dict()
            payload["normalized_text"] = _normalize_chunk_text(paragraph)
            payload["original_text"] = paragraph
            chunks.append(payload)
        _attach_display_text(text, chunks)
        return chunks

    # Sentence level – flatten paragraphs into individual sentences
    sentence_index = 0
    for para_index, paragraph in enumerate(list(_iter_paragraphs(text)) or [text.strip()]):
        normalized_para = _normalize_whitespace(paragraph)
        if not normalized_para:
            continue
        sentence_pairs = _split_sentences(paragraph) or [(normalized_para, paragraph)]
        for sent_local_index, (normalized_sentence, raw_sentence) in enumerate(sentence_pairs):
            normalized_sentence = _normalize_whitespace(normalized_sentence)
            if not normalized_sentence:
                continue
            chunk_id = f"{prefix}_p{para_index:04d}_s{sent_local_index:04d}"
            payload = Chunk(
                id=chunk_id,
                chapter_index=chapter_index,
                chunk_index=sentence_index,
                level=level,
                text=normalized_sentence,
                speaker_id=speaker_id,
                voice=voice,
                voice_profile=voice_profile,
                voice_formula=voice_formula,
            ).as_dict()
            payload["normalized_text"] = _normalize_chunk_text(raw_sentence)
            payload["display_text"] = raw_sentence
            payload["original_text"] = raw_sentence
            chunks.append(payload)
            sentence_index += 1

    _attach_display_text(text, chunks)
    return chunks


_DISPLAY_PATTERN_CACHE: Dict[str, Pattern[str]] = {}


def _build_display_pattern(text: str) -> Pattern[str]:
    cached = _DISPLAY_PATTERN_CACHE.get(text)
    if cached is not None:
        return cached
    escaped = re.escape(text)
    escaped = escaped.replace(r"\ ", r"\s+")
    pattern = re.compile(r"(\s*" + escaped + r"\s*)", re.DOTALL)
    _DISPLAY_PATTERN_CACHE[text] = pattern
    return pattern


def _search_source_span(source: str, normalized: str, start: int) -> Optional[Tuple[int, int]]:
    if not normalized:
        return None
    pattern = _build_display_pattern(normalized)
    match = pattern.search(source, start)
    if not match:
        return None
    return match.start(1), match.end(1)


def _attach_display_text(source: str, chunks: List[Dict[str, object]]) -> None:
    if not source or not chunks:
        return
    cursor = 0
    for chunk in chunks:
        candidate = str(chunk.get("display_text") or chunk.get("text") or "")
        if not candidate:
            continue
        match = _search_source_span(source, candidate, cursor)
        if match is None and cursor:
            match = _search_source_span(source, candidate, 0)
        if match is None:
            chunk.setdefault("display_text", candidate)
            chunk.setdefault("original_text", chunk.get("display_text") or candidate)
            continue
        start, end = match
        chunk["display_text"] = source[start:end]
        chunk["original_text"] = source[start:end]
        cursor = end


def build_chunks_for_chapters(
    chapters: Iterable[Dict[str, object]],
    *,
    level: ChunkLevel,
    speaker_id: str = "narrator",
) -> List[Dict[str, object]]:
    """Generate chunk dictionaries for a sequence of chapter payloads."""
    all_chunks: List[Dict[str, object]] = []
    for chapter_index, entry in enumerate(chapters):
        if not isinstance(entry, dict):  # defensive
            continue
        text = str(entry.get("text", "") or "").strip()
        if not text:
            continue
        voice = entry.get("voice")
        voice_profile = entry.get("voice_profile")
        voice_formula = entry.get("voice_formula")
        prefix = entry.get("id") or f"chap{chapter_index:04d}"
        chapter_chunks = chunk_text(
            chapter_index=chapter_index,
            chapter_title=str(entry.get("title") or f"Chapter {chapter_index + 1}"),
            text=text,
            level=level,
            speaker_id=speaker_id,
            voice=str(voice) if voice else None,
            voice_profile=str(voice_profile) if voice_profile else None,
            voice_formula=str(voice_formula) if voice_formula else None,
            chunk_prefix=str(prefix),
        )
        all_chunks.extend(chapter_chunks)
    return all_chunks