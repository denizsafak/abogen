from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import sys
import threading
import time
import uuid
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Mapping, Tuple

from abogen.utils import get_internal_cache_path, get_user_settings_dir, load_config
from abogen.voice_cache import bootstrap_voice_cache
from abogen.integrations.audiobookshelf import (
    AudiobookshelfClient,
    AudiobookshelfConfig,
    AudiobookshelfUploadError,
)


def _create_set_event() -> threading.Event:
    event = threading.Event()
    event.set()
    return event


STATE_VERSION = 8


_JOB_LOGGER = logging.getLogger("abogen.jobs")
if not _JOB_LOGGER.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    _JOB_LOGGER.addHandler(handler)
    _JOB_LOGGER.propagate = False
_JOB_LOGGER.setLevel(logging.DEBUG)

_JOB_LEVEL_MAP: Dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "success": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,
}


_PEOPLE_SPLIT_RE = re.compile(r"[;,/&]|\band\b", re.IGNORECASE)


def _emit_job_log(job_id: str, level: str, message: str) -> None:
    normalized = (level or "info").lower()
    log_level = _JOB_LEVEL_MAP.get(normalized, logging.INFO)
    try:
        _JOB_LOGGER.log(log_level, "[job %s] %s", job_id, message)
    except Exception:
        # Logging failures should never disrupt job processing, but we should know about them.
        try:
            sys.stderr.write(f"Logging failed for job {job_id}: {message}\n")
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobLog:
    timestamp: float
    message: str
    level: str = "info"


@dataclass
class JobResult:
    audio_path: Optional[Path] = None
    subtitle_paths: List[Path] = field(default_factory=list)
    artifacts: Dict[str, Path] = field(default_factory=dict)
    epub_path: Optional[Path] = None


@dataclass
class Job:
    id: str
    original_filename: str
    stored_path: Path
    language: str
    voice: str
    speed: float
    use_gpu: bool
    subtitle_mode: str
    output_format: str
    save_mode: str
    output_folder: Optional[Path]
    replace_single_newlines: bool
    subtitle_format: str
    created_at: float
    tts_provider: str = "kokoro"
    supertonic_total_steps: int = 5
    save_chapters_separately: bool = False
    merge_chapters_at_end: bool = True
    separate_chapters_format: str = "wav"
    silence_between_chapters: float = 2.0
    save_as_project: bool = False
    voice_profile: Optional[str] = None
    metadata_tags: Dict[str, str] = field(default_factory=dict)
    max_subtitle_words: int = 50
    chapter_intro_delay: float = 0.5
    read_title_intro: bool = False
    read_closing_outro: bool = True
    auto_prefix_chapter_titles: bool = True
    normalize_chapter_opening_caps: bool = True
    status: JobStatus = JobStatus.PENDING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress: float = 0.0
    total_characters: int = 0
    processed_characters: int = 0
    logs: List[JobLog] = field(default_factory=list)
    error: Optional[str] = None
    result: JobResult = field(default_factory=JobResult)
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    queue_position: Optional[int] = None
    cancel_requested: bool = False
    pause_requested: bool = False
    paused: bool = False
    resume_token: Optional[str] = None
    pause_event: threading.Event = field(default_factory=_create_set_event, repr=False, compare=False)
    cover_image_path: Optional[Path] = None
    cover_image_mime: Optional[str] = None
    chunk_level: str = "paragraph"
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    speakers: Dict[str, Any] = field(default_factory=dict)
    speaker_mode: str = "single"
    generate_epub3: bool = False
    speaker_analysis: Dict[str, Any] = field(default_factory=dict)
    speaker_analysis_threshold: int = 3
    analysis_requested: bool = False
    entity_summary: Dict[str, Any] = field(default_factory=dict)
    manual_overrides: List[Dict[str, Any]] = field(default_factory=list)
    pronunciation_overrides: List[Dict[str, Any]] = field(default_factory=list)
    heteronym_overrides: List[Dict[str, Any]] = field(default_factory=list)
    normalization_overrides: Dict[str, Any] = field(default_factory=dict)
    speaker_voice_languages: List[str] = field(default_factory=list)
    applied_speaker_config: Optional[str] = None

    @property
    def estimated_time_remaining(self) -> Optional[float]:
        """
        Returns the estimated seconds remaining based on current progress and elapsed time.
        Returns None if the job hasn't started, is finished, or progress is 0.
        """
        if self.status != JobStatus.RUNNING or not self.started_at or self.progress <= 0:
            return None
        
        elapsed = time.time() - self.started_at
        if elapsed <= 0:
            return None
            
        # Estimate total time based on current progress
        total_estimated = elapsed / self.progress
        remaining = total_estimated - elapsed
        return max(0.0, remaining)

    def add_log(self, message: str, level: str = "info") -> None:
        entry = JobLog(timestamp=time.time(), message=message, level=level)
        self.logs.append(entry)
        _emit_job_log(self.id, level, message)

    def as_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "status": self.status.value,
            "use_gpu": self.use_gpu,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "total_characters": self.total_characters,
            "processed_characters": self.processed_characters,
            "error": self.error,
            "logs": [log.__dict__ for log in self.logs],
            "result": {
                "audio": str(self.result.audio_path) if self.result.audio_path else None,
                "subtitles": [str(path) for path in self.result.subtitle_paths],
                "artifacts": {key: str(path) for key, path in self.result.artifacts.items()},
            },
            "queue_position": self.queue_position,
            "options": {
                "tts_provider": getattr(self, "tts_provider", "kokoro"),
                "supertonic_total_steps": getattr(self, "supertonic_total_steps", 5),
                "save_chapters_separately": self.save_chapters_separately,
                "merge_chapters_at_end": self.merge_chapters_at_end,
                "separate_chapters_format": self.separate_chapters_format,
                "silence_between_chapters": self.silence_between_chapters,
                "save_as_project": self.save_as_project,
                "voice_profile": self.voice_profile,
                "max_subtitle_words": self.max_subtitle_words,
                "chapter_intro_delay": self.chapter_intro_delay,
                "read_title_intro": getattr(self, "read_title_intro", False),
                "read_closing_outro": getattr(self, "read_closing_outro", True),
                "auto_prefix_chapter_titles": getattr(self, "auto_prefix_chapter_titles", True),
                "normalize_chapter_opening_caps": getattr(self, "normalize_chapter_opening_caps", True),
            },
            "metadata_tags": dict(self.metadata_tags),
            "chapters": [
                {
                    "id": entry.get("id"),
                    "index": entry.get("index"),
                    "order": entry.get("order"),
                    "title": entry.get("title"),
                    "enabled": bool(entry.get("enabled", True)),
                    "voice": entry.get("voice"),
                    "voice_profile": entry.get("voice_profile"),
                    "voice_formula": entry.get("voice_formula"),
                    "resolved_voice": entry.get("resolved_voice"),
                    "characters": len(str(entry.get("text", ""))),
                }
                for entry in self.chapters
            ],
            "chunk_level": self.chunk_level,
            "chunks": [dict(chunk) for chunk in self.chunks],
            "speakers": dict(self.speakers),
            "speaker_mode": self.speaker_mode,
            "generate_epub3": self.generate_epub3,
            "speaker_analysis": dict(self.speaker_analysis),
            "speaker_analysis_threshold": self.speaker_analysis_threshold,
            "analysis_requested": self.analysis_requested,
            "speaker_voice_languages": list(self.speaker_voice_languages),
            "applied_speaker_config": self.applied_speaker_config,
            "entity_summary": dict(self.entity_summary),
            "manual_overrides": [dict(entry) for entry in self.manual_overrides],
            "pronunciation_overrides": [dict(entry) for entry in self.pronunciation_overrides],
            "heteronym_overrides": [dict(entry) for entry in self.heteronym_overrides],
            "normalization_overrides": dict(self.normalization_overrides),
        }


def _normalize_metadata_casefold(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not values:
        return normalized
    for key, value in values.items():
        if value is None:
            continue
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        if isinstance(value, (list, tuple, set)):
            normalized[key_text] = value
        else:
            text = str(value).strip()
            if text:
                normalized[key_text] = text
    return normalized


def _split_people_field(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        results: List[str] = []
        for item in raw:
            results.extend(_split_people_field(item))
        return results
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = [_token.strip() for _token in _PEOPLE_SPLIT_RE.split(text) if _token.strip()]
    seen: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


_LIST_SPLIT_RE = re.compile(r"[;,\n]")
_SERIES_SEQUENCE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_SERIES_SEQUENCE_TAG_KEYS: Tuple[str, ...] = (
    "series_index",
    "series_position",
    "series_sequence",
    "series_number",
    "seriesnumber",
    "book_number",
    "booknumber",
)


def _split_simple_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        results: List[str] = []
        for item in raw:
            results.extend(_split_simple_list(item))
        return results
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = [_token.strip() for _token in _LIST_SPLIT_RE.split(text) if _token.strip()]
    seen: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def _first_nonempty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            if not items:
                continue
            value = items[0]
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if 0 < parsed < 3000:
        return parsed
    return None


def build_audiobookshelf_metadata(job: Job) -> Dict[str, Any]:
    tags = _normalize_metadata_casefold(job.metadata_tags)
    filename = Path(job.original_filename or "").stem or job.original_filename or "Audiobook"
    title = _first_nonempty(
        tags.get("title"),
        tags.get("book_title"),
        tags.get("name"),
        tags.get("album"),
        filename,
    )
    authors = _split_people_field(
        tags.get("authors")
        or tags.get("author")
        or tags.get("album_artist")
        or tags.get("artist")
    )
    narrators = _split_people_field(tags.get("narrators") or tags.get("narrator"))
    description = _first_nonempty(tags.get("description"), tags.get("summary"), tags.get("comment"))
    genres = _split_simple_list(tags.get("genre"))
    keywords = _split_simple_list(tags.get("tags") or tags.get("keywords"))
    language = _first_nonempty(tags.get("language"), tags.get("lang")) or job.language or ""
    series_name = _first_nonempty(
        tags.get("series"),
        tags.get("series_name"),
        tags.get("seriesname"),
        tags.get("series_title"),
        tags.get("seriestitle"),
    )
    
    series_sequence = None
    for key in _SERIES_SEQUENCE_TAG_KEYS:
        raw_value = tags.get(key)
        normalized_sequence = _normalize_series_sequence(raw_value)
        if normalized_sequence:
            series_sequence = normalized_sequence
            break
    if not series_name:
        series_sequence = None
    data: Dict[str, Any] = {
        "title": title,
        "subtitle": tags.get("subtitle"),
        "authors": authors,
        "narrators": narrators,
        "description": description,
        "publisher": tags.get("publisher"),
        "genres": genres,
        "tags": keywords,
        "language": language,
        "publishedYear": _extract_year(tags.get("published") or tags.get("publication_year") or tags.get("date") or tags.get("year")),
        "seriesName": series_name,
        "seriesSequence": series_sequence,
        "isbn": _first_nonempty(tags.get("isbn"), tags.get("asin")),
    }
    published_date = _first_nonempty(tags.get("published"), tags.get("publication_date"), tags.get("date"))
    if published_date:
        data["publishedDate"] = published_date

    rating_text = _first_nonempty(tags.get("rating"), tags.get("my_rating"))
    if rating_text:
        try:
            data["rating"] = float(str(rating_text).strip())
        except ValueError:
            pass
        rating_max_text = _first_nonempty(tags.get("rating_max"), tags.get("rating_scale"))
        if rating_max_text:
            try:
                data["ratingMax"] = float(str(rating_max_text).strip())
            except ValueError:
                pass
    # Remove empty values
    cleaned: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        cleaned[key] = value
    return cleaned


def _normalize_series_sequence(raw: Any) -> Optional[str]:
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return None
        text = str(raw)
    else:
        text = str(raw).strip()

    if not text:
        return None

    candidate = text.replace(",", ".")
    match = _SERIES_SEQUENCE_NUMBER_RE.search(candidate)
    if not match:
        return None

    normalized = match.group(0)
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
        if not normalized:
            normalized = "0"
        return normalized

    try:
        return str(int(normalized))
    except ValueError:
        cleaned = normalized.lstrip("0")
        return cleaned or "0"


def load_audiobookshelf_chapters(job: Job) -> Optional[List[Dict[str, Any]]]:
    metadata_ref = job.result.artifacts.get("metadata")
    if not metadata_ref:
        return None
    metadata_path = metadata_ref if isinstance(metadata_ref, Path) else Path(str(metadata_ref))
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        return None
    cleaned: List[Dict[str, Any]] = []
    for entry in chapters:
        if not isinstance(entry, Mapping):
            continue
        title = _first_nonempty(entry.get("title"), entry.get("original_title"))
        start = entry.get("start")
        end = entry.get("end")
        if title is None or not isinstance(start, (int, float)):
            continue
        chapter_payload: Dict[str, Any] = {
            "title": title,
            "start": float(start),
        }
        if isinstance(end, (int, float)):
            chapter_payload["end"] = float(end)
        cleaned.append(chapter_payload)
    return cleaned or None


def _existing_paths(paths: Iterable[Any]) -> List[Path]:
    resolved: List[Path] = []
    for item in paths:
        candidate = item if isinstance(item, Path) else Path(str(item))
        if candidate.exists():
            resolved.append(candidate)
    return resolved


@dataclass
class PendingJob:
    id: str
    original_filename: str
    stored_path: Path
    language: str
    voice: str
    speed: float
    use_gpu: bool
    subtitle_mode: str
    output_format: str
    save_mode: str
    output_folder: Optional[Path]
    replace_single_newlines: bool
    subtitle_format: str
    total_characters: int
    save_chapters_separately: bool
    merge_chapters_at_end: bool
    separate_chapters_format: str
    silence_between_chapters: float
    save_as_project: bool
    voice_profile: Optional[str]
    max_subtitle_words: int
    metadata_tags: Dict[str, Any]
    chapters: List[Dict[str, Any]]
    normalization_overrides: Dict[str, Any]
    created_at: float
    tts_provider: str = "kokoro"
    supertonic_total_steps: int = 5
    cover_image_path: Optional[Path] = None
    cover_image_mime: Optional[str] = None
    chapter_intro_delay: float = 0.5
    read_title_intro: bool = False
    read_closing_outro: bool = True
    auto_prefix_chapter_titles: bool = True
    normalize_chapter_opening_caps: bool = True
    chunk_level: str = "paragraph"
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    speakers: Dict[str, Any] = field(default_factory=dict)
    speaker_mode: str = "single"
    generate_epub3: bool = False
    speaker_analysis: Dict[str, Any] = field(default_factory=dict)
    speaker_analysis_threshold: int = 3
    analysis_requested: bool = False
    speaker_voice_languages: List[str] = field(default_factory=list)
    applied_speaker_config: Optional[str] = None
    entity_summary: Dict[str, Any] = field(default_factory=dict)
    manual_overrides: List[Dict[str, Any]] = field(default_factory=list)
    pronunciation_overrides: List[Dict[str, Any]] = field(default_factory=list)
    heteronym_overrides: List[Dict[str, Any]] = field(default_factory=list)
    entity_cache_key: Optional[str] = None
    wizard_max_step_index: int = 0


class ConversionService:
    def __init__(
        self,
        output_root: Path,
        runner: Callable[[Job], None],
        *,
        uploads_root: Optional[Path] = None,
        poll_interval: float = 0.5,
    ) -> None:
        self._jobs: Dict[str, Job] = {}
        self._queue: List[str] = []
        self._lock = threading.RLock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._output_root = output_root
        self._uploads_root = uploads_root or output_root / "uploads"
        self._runner = runner
        self._poll_interval = poll_interval
        self._pending_jobs: Dict[str, PendingJob] = {}
        self._state_path = self._determine_state_path()
        self._ensure_directories()
        self._bootstrap_voice_cache()
        self._load_state()

    # Public API ---------------------------------------------------------
    def list_jobs(self) -> List[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def enqueue(
        self,
        *,
        original_filename: str,
        stored_path: Path,
        language: str,
        voice: str,
        speed: float,
        tts_provider: str = "kokoro",
        supertonic_total_steps: int = 5,
        use_gpu: bool,
        subtitle_mode: str,
        output_format: str,
        save_mode: str,
        output_folder: Optional[Path],
        replace_single_newlines: bool,
        subtitle_format: str,
        total_characters: int,
        chapters: Optional[Iterable[Any]] = None,
        save_chapters_separately: bool = False,
        merge_chapters_at_end: bool = True,
        separate_chapters_format: str = "wav",
        silence_between_chapters: float = 2.0,
        save_as_project: bool = False,
        voice_profile: Optional[str] = None,
        max_subtitle_words: int = 50,
        metadata_tags: Optional[Mapping[str, Any]] = None,
        cover_image_path: Optional[Path] = None,
            cover_image_mime: Optional[str] = None,
            chapter_intro_delay: float = 0.5,
            read_title_intro: bool = False,
            read_closing_outro: bool = True,
            auto_prefix_chapter_titles: bool = True,
            normalize_chapter_opening_caps: bool = True,
        chunk_level: str = "paragraph",
        chunks: Optional[Iterable[Any]] = None,
        speakers: Optional[Mapping[str, Any]] = None,
        speaker_mode: str = "single",
        generate_epub3: bool = False,
        speaker_analysis: Optional[Mapping[str, Any]] = None,
        speaker_analysis_threshold: int = 3,
        analysis_requested: bool = False,
        entity_summary: Optional[Mapping[str, Any]] = None,
        manual_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
        pronunciation_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
        heteronym_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
        normalization_overrides: Optional[Mapping[str, Any]] = None,
    ) -> Job:
        job_id = uuid.uuid4().hex
        normalized_metadata = self._normalize_metadata_tags(metadata_tags)
        normalized_chapters = self._normalize_chapters(chapters)
        normalized_chunks = self._normalize_chunks(chunks)
        if total_characters <= 0 and normalized_chapters:
            total_characters = sum(len(str(entry.get("text", ""))) for entry in normalized_chapters)
        job = Job(
            id=job_id,
            original_filename=original_filename,
            stored_path=stored_path,
            language=language,
            voice=voice,
            speed=speed,
            tts_provider=tts_provider,
            supertonic_total_steps=int(supertonic_total_steps or 5),
            use_gpu=use_gpu,
            subtitle_mode=subtitle_mode,
            output_format=output_format,
            save_mode=save_mode,
            output_folder=output_folder,
            replace_single_newlines=replace_single_newlines,
            subtitle_format=subtitle_format,
            save_chapters_separately=save_chapters_separately,
            merge_chapters_at_end=merge_chapters_at_end,
            separate_chapters_format=separate_chapters_format,
            silence_between_chapters=silence_between_chapters,
            save_as_project=save_as_project,
            voice_profile=voice_profile,
            max_subtitle_words=max_subtitle_words,
            metadata_tags=normalized_metadata,
            created_at=time.time(),
            total_characters=total_characters,
            chapters=normalized_chapters,
            cover_image_path=cover_image_path,
            cover_image_mime=cover_image_mime,
            chapter_intro_delay=chapter_intro_delay,
            read_title_intro=bool(read_title_intro),
            read_closing_outro=bool(read_closing_outro),
            auto_prefix_chapter_titles=bool(auto_prefix_chapter_titles),
            normalize_chapter_opening_caps=bool(normalize_chapter_opening_caps),
            chunk_level=chunk_level,
            chunks=normalized_chunks,
            speakers=dict(speakers or {}),
            speaker_mode=speaker_mode,
            generate_epub3=bool(generate_epub3),
            speaker_analysis=dict(speaker_analysis or {}),
            speaker_analysis_threshold=int(speaker_analysis_threshold or 3),
            analysis_requested=bool(analysis_requested),
            entity_summary=dict(entity_summary or {}),
            manual_overrides=[dict(entry) for entry in manual_overrides] if manual_overrides else [],
            pronunciation_overrides=[dict(entry) for entry in pronunciation_overrides] if pronunciation_overrides else [],
            heteronym_overrides=[dict(entry) for entry in heteronym_overrides] if heteronym_overrides else [],
            normalization_overrides=dict(normalization_overrides or {}),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._queue.append(job_id)
            self._update_queue_positions_locked()
            self._wake_event.set()
        self._ensure_worker()
        job.add_log("Job queued")
        return job

    def store_pending_job(self, pending: PendingJob) -> None:
        with self._lock:
            self._pending_jobs[pending.id] = pending

    def get_pending_job(self, pending_id: str) -> Optional[PendingJob]:
        with self._lock:
            return self._pending_jobs.get(pending_id)

    def pop_pending_job(self, pending_id: str) -> Optional[PendingJob]:
        with self._lock:
            return self._pending_jobs.pop(pending_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return False
            job.cancel_requested = True
            job.pause_requested = False
            job.paused = False
            job.add_log("Cancellation requested", level="warning")
            job.pause_event.set()
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self._queue.remove(job_id)
                job.finished_at = time.time()
                self._update_queue_positions_locked()
            self._persist_state()
            return True

    def pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return False
            if job.pause_requested or job.paused:
                return True

            job.pause_requested = True
            job.add_log("Pause requested; finishing current chunk before stopping.", level="warning")

            if job.status == JobStatus.PENDING:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                    self._update_queue_positions_locked()
                job.status = JobStatus.PAUSED
                job.paused = True
                job.pause_event.clear()
            self._persist_state()
            return True

    def resume(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return False

            job.pause_requested = False

            if job.status == JobStatus.PAUSED and job.started_at is None:
                job.status = JobStatus.PENDING
                job.paused = False
                job.pause_event.set()
                if job_id not in self._queue:
                    self._queue.insert(0, job_id)
                self._update_queue_positions_locked()
                self._wake_event.set()
                job.add_log("Resume requested; returning job to queue.", level="info")
            else:
                job.paused = False
                job.pause_event.set()
                if job.status == JobStatus.PAUSED:
                    job.status = JobStatus.RUNNING
                job.add_log("Resume requested", level="info")

            self._persist_state()
            return True

    def retry(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                job.add_log(
                    "Retry requested while job still active; ignoring.",
                    level="warning",
                )
                return None

            stored_path = job.stored_path
            if not isinstance(stored_path, Path):
                stored_path = Path(str(stored_path))

            if not stored_path.exists():
                job.add_log(
                    f"Retry requested but source file is missing: {stored_path}",
                    level="error",
                )
                return None

            new_job = self.enqueue(
                original_filename=job.original_filename,
                stored_path=stored_path,
                language=job.language,
                voice=job.voice,
                speed=job.speed,
                use_gpu=job.use_gpu,
                subtitle_mode=job.subtitle_mode,
                output_format=job.output_format,
                save_mode=job.save_mode,
                output_folder=job.output_folder,
                replace_single_newlines=job.replace_single_newlines,
                subtitle_format=job.subtitle_format,
                total_characters=job.total_characters,
                chapters=job.chapters,
                save_chapters_separately=job.save_chapters_separately,
                merge_chapters_at_end=job.merge_chapters_at_end,
                separate_chapters_format=job.separate_chapters_format,
                silence_between_chapters=job.silence_between_chapters,
                save_as_project=job.save_as_project,
                voice_profile=job.voice_profile,
                max_subtitle_words=job.max_subtitle_words,
                metadata_tags=job.metadata_tags,
                cover_image_path=job.cover_image_path,
                cover_image_mime=job.cover_image_mime,
                chapter_intro_delay=job.chapter_intro_delay,
                read_title_intro=job.read_title_intro,
                auto_prefix_chapter_titles=job.auto_prefix_chapter_titles,
                normalize_chapter_opening_caps=job.normalize_chapter_opening_caps,
                chunk_level=job.chunk_level,
                chunks=job.chunks,
                speakers=job.speakers,
                speaker_mode=job.speaker_mode,
                generate_epub3=job.generate_epub3,
                speaker_analysis=job.speaker_analysis,
                speaker_analysis_threshold=job.speaker_analysis_threshold,
                analysis_requested=job.analysis_requested,
                entity_summary=job.entity_summary,
                manual_overrides=job.manual_overrides,
                pronunciation_overrides=job.pronunciation_overrides,
                normalization_overrides=job.normalization_overrides,
            )

            new_job.speaker_voice_languages = list(job.speaker_voice_languages)
            new_job.applied_speaker_config = job.applied_speaker_config
            new_job.add_log(f"Retry created from job {job.id}", level="info")
            job.add_log(f"Retry scheduled as job {new_job.id}", level="info")
            self._remove_job_locked(job_id)
            return new_job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.RUNNING}:
                return False
            self._jobs.pop(job_id)
            if job_id in self._queue:
                self._queue.remove(job_id)
                self._update_queue_positions_locked()
            self._persist_state()
            return True

    def clear_finished(self, *, statuses: Optional[Iterable[JobStatus]] = None) -> int:
        finished_statuses = set(statuses or {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})
        removed = 0
        with self._lock:
            # Remove any queued entries first to avoid stale references
            filtered_queue: List[str] = []
            for job_id in self._queue:
                job = self._jobs.get(job_id)
                if job and job.status in finished_statuses:
                    continue
                filtered_queue.append(job_id)
            self._queue = filtered_queue

            for job_id, job in list(self._jobs.items()):
                if job.status in finished_statuses:
                    self._jobs.pop(job_id)
                    removed += 1

            if removed:
                self._update_queue_positions_locked()
            self._persist_state()
        return removed

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
            self._worker_thread = None

    # Internal -----------------------------------------------------------
    def _ensure_directories(self) -> None:
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._uploads_root.mkdir(parents=True, exist_ok=True)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    def _bootstrap_voice_cache(self) -> None:
        try:
            downloaded, errors = bootstrap_voice_cache(
                on_progress=lambda msg: _JOB_LOGGER.debug("[voice cache] %s", msg)
            )
        except RuntimeError as exc:
            _JOB_LOGGER.warning("Voice cache bootstrap skipped: %s", exc)
            return

        if downloaded:
            count = len(downloaded)
            suffix = "s" if count != 1 else ""
            _JOB_LOGGER.info("Voice cache ready: downloaded %d new asset%s.", count, suffix)
        if errors:
            for voice_id, message in errors.items():
                _JOB_LOGGER.warning("Voice cache failed for %s: %s", voice_id, message)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="abogen-conversion-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = None
            with self._lock:
                self._wake_event.clear()
                while self._queue and self._jobs[self._queue[0]].status in {
                    JobStatus.CANCELLED,
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                }:
                    self._queue.pop(0)
                if self._queue:
                    job = self._jobs[self._queue.pop(0)]
                else:
                    self._update_queue_positions_locked()
            if job is None:
                self._wake_event.wait(timeout=self._poll_interval)
                continue
            if job.cancel_requested:
                job.add_log("Job cancelled before start", level="warning")
                job.status = JobStatus.CANCELLED
                job.finished_at = time.time()
                continue
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        job.pause_event.set()
        job.pause_requested = False
        job.paused = False
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.add_log("Job started", level="info")
        self._persist_state()
        try:
            self._runner(job)
        except Exception as exc:  # pragma: no cover - defensive
            job.error = str(exc)
            job.status = JobStatus.FAILED
            job.finished_at = time.time()
            exc_type = exc.__class__.__name__
            job.add_log(f"Job failed ({exc_type}): {exc}", level="error")
            tb_lines = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
            for line in tb_lines[:20]:
                trimmed = line.rstrip()
                if trimmed:
                    for snippet in trimmed.splitlines():
                        job.add_log(f"TRACE: {snippet}", level="debug")
        else:
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                job.add_log("Job cancelled", level="warning")
            elif job.status != JobStatus.FAILED:
                job.status = JobStatus.COMPLETED
                job.add_log("Job completed", level="success")
                self._post_completion_hooks(job)
            job.finished_at = time.time()
        finally:
            job.pause_event.set()
            self._persist_state()
            with self._lock:
                self._update_queue_positions_locked()

    def _update_queue_positions_locked(self) -> None:
        for index, job_id in enumerate(self._queue, start=1):
            job = self._jobs.get(job_id)
            if job:
                job.queue_position = index
        self._persist_state()

    def _remove_job_locked(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        if job_id in self._queue:
            self._queue.remove(job_id)
        self._update_queue_positions_locked()

    def _post_completion_hooks(self, job: Job) -> None:
        try:
            self._maybe_send_to_audiobookshelf(job)
        except AudiobookshelfUploadError as exc:
            job.add_log(f"Audiobookshelf upload failed: {exc}", level="error")
        except Exception as exc:  # pragma: no cover - defensive guard
            job.add_log(f"Audiobookshelf integration error: {exc}", level="error")

    def _maybe_send_to_audiobookshelf(self, job: Job) -> None:
        cfg = load_config() or {}
        integration_cfg = cfg.get("audiobookshelf")
        if not isinstance(integration_cfg, Mapping):
            return
        enabled = self._coerce_bool(integration_cfg.get("enabled"), False)
        auto_send = self._coerce_bool(integration_cfg.get("auto_send"), False)
        if not (enabled and auto_send):
            return

        base_url = str(integration_cfg.get("base_url") or "").strip()
        api_token = str(integration_cfg.get("api_token") or "").strip()
        library_id = str(integration_cfg.get("library_id") or "").strip()
        folder_id = str(integration_cfg.get("folder_id") or "").strip()
        if not base_url or not api_token or not library_id:
            job.add_log(
                "Audiobookshelf upload skipped: configure base URL, API token, and library ID first.",
                level="warning",
            )
            return
        if not folder_id:
            job.add_log(
                "Audiobookshelf upload skipped: enter the folder name or ID in the Audiobookshelf settings.",
                level="warning",
            )
            return

        audio_ref = job.result.audio_path
        audio_path = audio_ref if isinstance(audio_ref, Path) else Path(str(audio_ref)) if audio_ref else None
        if not audio_path or not audio_path.exists():
            job.add_log("Audiobookshelf upload skipped: audio output not found.", level="warning")
            return

        timeout_raw = integration_cfg.get("timeout", 3600.0)
        try:
            timeout_value = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_value = 3600.0

        config = AudiobookshelfConfig(
            base_url=base_url,
            api_token=api_token,
            library_id=library_id,
            collection_id=(str(integration_cfg.get("collection_id") or "").strip() or None),
            folder_id=folder_id,
            verify_ssl=self._coerce_bool(integration_cfg.get("verify_ssl"), True),
            send_cover=self._coerce_bool(integration_cfg.get("send_cover"), True),
            send_chapters=self._coerce_bool(integration_cfg.get("send_chapters"), True),
            send_subtitles=self._coerce_bool(integration_cfg.get("send_subtitles"), False),
            timeout=timeout_value,
        )

        cover_ref = job.cover_image_path
        cover_path = None
        if config.send_cover and cover_ref:
            cover_candidate = cover_ref if isinstance(cover_ref, Path) else Path(str(cover_ref))
            if cover_candidate.exists():
                cover_path = cover_candidate

        subtitles = _existing_paths(job.result.subtitle_paths) if config.send_subtitles else None
        chapters = load_audiobookshelf_chapters(job) if config.send_chapters else None
        metadata = build_audiobookshelf_metadata(job)

        client = AudiobookshelfClient(config)

        display_title = metadata.get("title") or audio_path.stem
        try:
            existing_items = client.find_existing_items(display_title, folder_id=config.folder_id)
        except AudiobookshelfUploadError as exc:
            job.add_log(f"Audiobookshelf lookup failed: {exc}", level="error")
            return

        if existing_items:
            job.add_log(
                f"Removing existing Audiobookshelf item(s) for '{display_title}' before upload.",
                level="info",
            )
            try:
                client.delete_items(existing_items)
            except Exception as exc:
                job.add_log(f"Failed to remove existing item(s): {exc}", level="warning")

        client.upload_audiobook(
            audio_path,
            metadata=metadata,
            cover_path=cover_path,
            chapters=chapters,
            subtitles=subtitles,
        )
        job.add_log("Audiobookshelf upload queued.", level="info")

    # Persistence ------------------------------------------------------
    def _serialize_job(self, job: Job) -> Dict[str, Any]:
        result_audio = str(job.result.audio_path) if job.result.audio_path else None
        result_subtitles = [str(path) for path in job.result.subtitle_paths]
        result_artifacts = {key: str(path) for key, path in job.result.artifacts.items()}
        result_epub = str(job.result.epub_path) if job.result.epub_path else None
        return {
            "id": job.id,
            "original_filename": job.original_filename,
            "stored_path": str(job.stored_path),
            "language": job.language,
            "tts_provider": getattr(job, "tts_provider", "kokoro"),
            "voice": job.voice,
            "speed": job.speed,
            "supertonic_total_steps": getattr(job, "supertonic_total_steps", 5),
            "use_gpu": job.use_gpu,
            "subtitle_mode": job.subtitle_mode,
            "output_format": job.output_format,
            "save_mode": job.save_mode,
            "output_folder": str(job.output_folder) if job.output_folder else None,
            "replace_single_newlines": job.replace_single_newlines,
            "subtitle_format": job.subtitle_format,
            "created_at": job.created_at,
            "save_chapters_separately": job.save_chapters_separately,
            "merge_chapters_at_end": job.merge_chapters_at_end,
            "separate_chapters_format": job.separate_chapters_format,
            "silence_between_chapters": job.silence_between_chapters,
            "save_as_project": job.save_as_project,
            "voice_profile": job.voice_profile,
            "metadata_tags": job.metadata_tags,
            "max_subtitle_words": job.max_subtitle_words,
            "status": job.status.value,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "progress": job.progress,
            "total_characters": job.total_characters,
            "processed_characters": job.processed_characters,
            "error": job.error,
            "logs": [log.__dict__ for log in job.logs][-500:],
            "result": {
                "audio_path": result_audio,
                "subtitle_paths": result_subtitles,
                "artifacts": result_artifacts,
                "epub_path": result_epub,
            },
            "chapters": [dict(entry) for entry in job.chapters],
            "queue_position": job.queue_position,
            "cancel_requested": job.cancel_requested,
            "pause_requested": job.pause_requested,
            "paused": job.paused,
            "resume_token": job.resume_token,
            "cover_image_path": str(job.cover_image_path) if job.cover_image_path else None,
            "cover_image_mime": job.cover_image_mime,
            "chapter_intro_delay": job.chapter_intro_delay,
            "read_title_intro": job.read_title_intro,
            "auto_prefix_chapter_titles": job.auto_prefix_chapter_titles,
            "normalize_chapter_opening_caps": job.normalize_chapter_opening_caps,
            "chunk_level": job.chunk_level,
            "chunks": [dict(entry) for entry in job.chunks],
            "speakers": dict(job.speakers),
            "speaker_mode": job.speaker_mode,
            "generate_epub3": job.generate_epub3,
            "speaker_analysis": dict(job.speaker_analysis),
            "speaker_analysis_threshold": job.speaker_analysis_threshold,
            "analysis_requested": job.analysis_requested,
            "entity_summary": dict(job.entity_summary),
            "manual_overrides": [dict(entry) for entry in job.manual_overrides],
            "pronunciation_overrides": [dict(entry) for entry in job.pronunciation_overrides],
            "heteronym_overrides": [dict(entry) for entry in job.heteronym_overrides],
            "normalization_overrides": dict(job.normalization_overrides),
        }

    def _persist_state(self) -> None:
        try:
            with self._lock:
                snapshot = {
                    "version": STATE_VERSION,
                    "jobs": [self._serialize_job(job) for job in self._jobs.values()],
                    "queue": list(self._queue),
                }
            tmp_path = self._state_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2)
            os.replace(tmp_path, self._state_path)
        except Exception:
            # Persistence failures should not disrupt runtime; ignore.
            pass

    def _determine_state_path(self) -> Path:
        override_file = os.environ.get("ABOGEN_QUEUE_STATE_PATH")
        if override_file:
            target_path = Path(override_file).expanduser()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            return target_path

        override_dir = os.environ.get("ABOGEN_QUEUE_STATE_DIR")
        if override_dir:
            base_dir = Path(override_dir).expanduser()
        else:
            settings_override = os.environ.get("ABOGEN_SETTINGS_DIR")
            if settings_override:
                base_dir = Path(settings_override).expanduser() / "queue"
            else:
                try:
                    base_dir = Path(get_user_settings_dir()) / "queue"
                except ModuleNotFoundError:
                    base_dir = Path(get_internal_cache_path("jobs"))
        base_dir.mkdir(parents=True, exist_ok=True)
        target_path = base_dir / "queue_state.json"

        legacy_path = Path(get_internal_cache_path("jobs")) / "queue_state.json"
        if legacy_path.exists() and not target_path.exists():
            try:
                shutil.move(str(legacy_path), target_path)
            except Exception:
                try:
                    shutil.copy2(str(legacy_path), target_path)
                except Exception:
                    pass

        return target_path

    def _deserialize_job(self, payload: Dict[str, Any]) -> Job:
        stored_path = Path(payload["stored_path"])
        output_folder_raw = payload.get("output_folder")
        output_folder = Path(output_folder_raw) if output_folder_raw else None
        job = Job(
            id=payload["id"],
            original_filename=payload["original_filename"],
            stored_path=stored_path,
            language=payload.get("language", "a"),
            tts_provider=str(payload.get("tts_provider") or "kokoro"),
            voice=payload.get("voice", ""),
            speed=float(payload.get("speed", 1.0)),
            use_gpu=bool(payload.get("use_gpu", True)),
            subtitle_mode=payload.get("subtitle_mode", "Disabled"),
            output_format=payload.get("output_format", "wav"),
            save_mode=payload.get("save_mode", "Save next to input file"),
            output_folder=output_folder,
            replace_single_newlines=bool(payload.get("replace_single_newlines", False)),
            subtitle_format=payload.get("subtitle_format", "srt"),
            created_at=float(payload.get("created_at", time.time())),
            supertonic_total_steps=int(payload.get("supertonic_total_steps", 5)),
            save_chapters_separately=bool(payload.get("save_chapters_separately", False)),
            merge_chapters_at_end=bool(payload.get("merge_chapters_at_end", True)),
            separate_chapters_format=payload.get("separate_chapters_format", "wav"),
            silence_between_chapters=float(payload.get("silence_between_chapters", 2.0)),
            save_as_project=bool(payload.get("save_as_project", False)),
            voice_profile=payload.get("voice_profile"),
            metadata_tags=payload.get("metadata_tags", {}),
            max_subtitle_words=int(payload.get("max_subtitle_words", 50)),
            chapter_intro_delay=float(payload.get("chapter_intro_delay", 0.5)),
            read_title_intro=bool(payload.get("read_title_intro", False)),
            auto_prefix_chapter_titles=bool(payload.get("auto_prefix_chapter_titles", True)),
            normalize_chapter_opening_caps=bool(payload.get("normalize_chapter_opening_caps", True)),
        )
        job.status = JobStatus(payload.get("status", job.status.value))
        job.started_at = payload.get("started_at")
        job.finished_at = payload.get("finished_at")
        job.progress = float(payload.get("progress", 0.0))
        job.total_characters = int(payload.get("total_characters", 0))
        job.processed_characters = int(payload.get("processed_characters", 0))
        job.error = payload.get("error")
        job.logs = [JobLog(**entry) for entry in payload.get("logs", [])]
        result_payload = payload.get("result", {})
        audio_path_raw = result_payload.get("audio_path")
        job.result.audio_path = Path(audio_path_raw) if audio_path_raw else None
        job.result.subtitle_paths = [Path(item) for item in result_payload.get("subtitle_paths", [])]
        job.result.artifacts = {
            key: Path(value) for key, value in result_payload.get("artifacts", {}).items()
        }
        epub_path_raw = result_payload.get("epub_path")
        job.result.epub_path = Path(epub_path_raw) if epub_path_raw else None
        job.chapters = payload.get("chapters", [])
        job.queue_position = payload.get("queue_position")
        job.cancel_requested = bool(payload.get("cancel_requested", False))
        job.pause_requested = bool(payload.get("pause_requested", False))
        job.paused = bool(payload.get("paused", False))
        job.resume_token = payload.get("resume_token")
        cover_path_raw = payload.get("cover_image_path")
        job.cover_image_path = Path(cover_path_raw) if cover_path_raw else None
        job.cover_image_mime = payload.get("cover_image_mime")
        job.chunk_level = str(payload.get("chunk_level", job.chunk_level or "paragraph"))
        job.chunks = self._normalize_chunks(payload.get("chunks"))
        job.speakers = dict(payload.get("speakers", {}))
        job.speaker_mode = str(payload.get("speaker_mode", job.speaker_mode or "single"))
        job.generate_epub3 = bool(payload.get("generate_epub3", job.generate_epub3))
        job.speaker_analysis = payload.get("speaker_analysis", {})
        job.speaker_analysis_threshold = int(
            payload.get("speaker_analysis_threshold", job.speaker_analysis_threshold or 3)
        )
        job.analysis_requested = bool(payload.get("analysis_requested", job.analysis_requested))
        job.entity_summary = payload.get("entity_summary", {})
        job.manual_overrides = [dict(entry) for entry in payload.get("manual_overrides", []) if isinstance(entry, Mapping)]
        job.pronunciation_overrides = [
            dict(entry) for entry in payload.get("pronunciation_overrides", []) if isinstance(entry, Mapping)
        ]
        job.heteronym_overrides = [
            dict(entry) for entry in payload.get("heteronym_overrides", []) if isinstance(entry, Mapping)
        ]
        job.normalization_overrides = dict(payload.get("normalization_overrides", {}) or {})
        job.pause_event.set()
        return job

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return

        version = int(payload.get("version", 0) or 0)
        if version not in {STATE_VERSION, STATE_VERSION - 1}:
            return

        jobs_payload = payload.get("jobs", [])
        queue_payload = payload.get("queue", [])
        loaded_jobs: Dict[str, Job] = {}
        requeue: List[str] = []

        for entry in jobs_payload:
            try:
                job = self._deserialize_job(entry)
            except Exception:
                continue

            if job.status in {JobStatus.RUNNING, JobStatus.PAUSED}:
                job.status = JobStatus.PENDING
                job.add_log("Job restored after restart: resetting to pending queue.", level="warning")
                job.progress = 0.0
                job.processed_characters = 0
                job.pause_requested = False
                job.paused = False
                job.pause_event.set()
                requeue.append(job.id)
            elif job.status == JobStatus.PENDING:
                requeue.append(job.id)

            loaded_jobs[job.id] = job

        with self._lock:
            self._jobs = loaded_jobs
            self._queue = [job_id for job_id in queue_payload if job_id in loaded_jobs]
            for job_id in requeue:
                if job_id not in self._queue:
                    self._queue.append(job_id)
            self._update_queue_positions_locked()

        if self._queue:
            self._ensure_worker()

    @staticmethod
    def _coerce_bool(value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
            return default
        if value is None:
            return default
        return bool(value)

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_metadata_tags(values: Optional[Mapping[str, Any]]) -> Dict[str, str]:
        if not values:
            return {}
        normalized: Dict[str, str] = {}
        for key, raw_value in values.items():
            if raw_value is None:
                continue
            key_str = str(key).strip()
            if not key_str:
                continue
            normalized[key_str] = str(raw_value)
        return normalized

    @classmethod
    def _normalize_chapters(cls, chapters: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
        if not chapters:
            return []

        normalized: List[Dict[str, Any]] = []
        for order, raw in enumerate(chapters):
            if raw is None:
                continue

            if isinstance(raw, str):
                raw_dict: Dict[str, Any] = {"title": raw}
            elif isinstance(raw, dict):
                raw_dict = dict(raw)
            else:
                continue

            entry: Dict[str, Any] = {}

            id_value = raw_dict.get("id") or raw_dict.get("chapter_id") or raw_dict.get("key")
            if id_value is not None:
                entry["id"] = str(id_value)

            index_value = (
                cls._coerce_optional_int(raw_dict.get("index"))
                or cls._coerce_optional_int(raw_dict.get("original_index"))
                or cls._coerce_optional_int(raw_dict.get("source_index"))
                or cls._coerce_optional_int(raw_dict.get("chapter_index"))
            )
            if index_value is not None:
                entry["index"] = index_value

            order_value = (
                cls._coerce_optional_int(raw_dict.get("order"))
                or cls._coerce_optional_int(raw_dict.get("position"))
                or cls._coerce_optional_int(raw_dict.get("sort"))
                or cls._coerce_optional_int(raw_dict.get("sort_order"))
            )
            entry["order"] = order_value if order_value is not None else order

            source_title = (
                raw_dict.get("source_title")
                or raw_dict.get("original_title")
                or raw_dict.get("base_title")
            )
            if source_title:
                entry["source_title"] = str(source_title)

            title_value = (
                raw_dict.get("title")
                or raw_dict.get("name")
                or raw_dict.get("label")
                or raw_dict.get("chapter")
            )
            if title_value is not None:
                entry["title"] = str(title_value)
            elif source_title:
                entry["title"] = str(source_title)
            else:
                entry["title"] = f"Chapter {order + 1}"

            text_value = raw_dict.get("text")
            if text_value is None:
                text_value = raw_dict.get("content") or raw_dict.get("body") or raw_dict.get("value")
            if text_value is not None:
                entry["text"] = str(text_value)

            enabled = cls._coerce_bool(
                raw_dict.get("enabled", raw_dict.get("include", raw_dict.get("selected", True))),
                True,
            )
            if "disabled" in raw_dict and cls._coerce_bool(raw_dict.get("disabled"), False):
                enabled = False
            entry["enabled"] = enabled

            metadata_payload = raw_dict.get("metadata") or raw_dict.get("metadata_tags")
            normalized_metadata = cls._normalize_metadata_tags(metadata_payload)
            if normalized_metadata:
                entry["metadata"] = normalized_metadata

            voice_value = raw_dict.get("voice")
            if voice_value:
                entry["voice"] = str(voice_value)

            profile_value = raw_dict.get("voice_profile")
            if profile_value:
                entry["voice_profile"] = str(profile_value)

            formula_value = raw_dict.get("voice_formula") or raw_dict.get("formula")
            if formula_value:
                entry["voice_formula"] = str(formula_value)

            resolved_value = raw_dict.get("resolved_voice")
            if resolved_value:
                entry["resolved_voice"] = str(resolved_value)

            if "characters" in raw_dict:
                try:
                    entry["characters"] = int(raw_dict.get("characters", 0))
                except (TypeError, ValueError):
                    entry["characters"] = len(str(entry.get("text", "")))
            else:
                entry["characters"] = len(str(entry.get("text", "")))

            normalized.append(entry)

        return normalized

    @classmethod
    def _normalize_chunks(cls, chunks: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
        if not chunks:
            return []

        normalized: List[Dict[str, Any]] = []
        for order, raw in enumerate(chunks):
            if raw is None:
                continue
            if isinstance(raw, dict):
                entry = dict(raw)
            else:
                continue

            chunk: Dict[str, Any] = {}

            identifier = entry.get("id") or entry.get("chunk_id")
            if identifier is not None:
                chunk["id"] = str(identifier)

            try:
                chunk_index = int(entry.get("chunk_index", order))
            except (TypeError, ValueError):
                chunk_index = order
            chunk["chunk_index"] = chunk_index

            try:
                chapter_index = int(entry.get("chapter_index", 0))
            except (TypeError, ValueError):
                chapter_index = 0
            chunk["chapter_index"] = chapter_index

            level_raw = str(entry.get("level", "paragraph")).lower()
            if level_raw not in {"paragraph", "sentence"}:
                level_raw = "paragraph"
            chunk["level"] = level_raw

            text_value = entry.get("text")
            if text_value is not None:
                chunk["text"] = str(text_value)
            else:
                chunk["text"] = ""

            normalized_value = entry.get("normalized_text")
            if normalized_value is not None:
                chunk["normalized_text"] = str(normalized_value)

            for text_key in ("display_text", "original_text"):
                if text_key in entry and entry[text_key] is not None:
                    chunk[text_key] = str(entry[text_key])

            speaker_value = entry.get("speaker_id", entry.get("speaker"))
            chunk["speaker_id"] = str(speaker_value) if speaker_value else "narrator"

            for key in ("voice", "voice_profile", "voice_formula", "audio_path", "start", "end"):
                if key in entry and entry[key] is not None:
                    chunk[key] = entry[key]

            normalized.append(chunk)
        return normalized


def default_storage_root() -> Path:
    base = Path.cwd()
    uploads = base / "var" / "uploads"
    outputs = base / "var" / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)
    return outputs


def build_service(
    runner: Callable[[Job], None],
    *,
    output_root: Optional[Path] = None,
    uploads_root: Optional[Path] = None,
) -> ConversionService:
    output_root = output_root or default_storage_root()
    service = ConversionService(
        output_root=output_root,
        uploads_root=uploads_root,
        runner=runner,
    )
    return service
