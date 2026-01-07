import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, cast
from flask import request, render_template, jsonify
from flask.typing import ResponseReturnValue

from abogen.webui.service import PendingJob, JobStatus
from abogen.webui.routes.utils.service import get_service
from abogen.webui.routes.utils.settings import (
    load_settings,
    coerce_bool,
    coerce_int,
    _CHUNK_LEVEL_VALUES,
    _DEFAULT_ANALYSIS_THRESHOLD,
    _NORMALIZATION_BOOLEAN_KEYS,
    _NORMALIZATION_STRING_KEYS,
    SAVE_MODE_LABELS,
    audiobookshelf_manual_available,
)
from abogen.webui.routes.utils.voice import (
    parse_voice_formula,
    formula_from_profile,
    resolve_voice_setting,
    resolve_voice_choice,
    prepare_speaker_metadata,
    template_options,
)
from abogen.webui.routes.utils.entity import sync_pronunciation_overrides
from abogen.webui.routes.utils.epub import job_download_flags
from abogen.webui.routes.utils.common import split_profile_spec
from abogen.utils import calculate_text_length
from abogen.voice_profiles import serialize_profiles, normalize_profile_entry
from abogen.chunking import ChunkLevel, build_chunks_for_chapters
from abogen.constants import VOICES_INTERNAL
from abogen.speaker_configs import get_config
from abogen.kokoro_text_normalization import normalize_roman_numeral_titles
from dataclasses import dataclass
from pathlib import Path
import mimetypes

@dataclass
class PendingBuildResult:
    pending: PendingJob
    selected_speaker_config: Optional[str]
    config_languages: List[str]
    speaker_config_payload: Optional[Dict[str, Any]]

_WIZARD_STEP_ORDER = ["book", "chapters", "entities"]
_WIZARD_STEP_META = {
    "book": {
        "index": 1,
        "title": "Book parameters",
        "hint": "Choose your source file or paste text, then set the defaults used for chapter analysis and speaker casting.",
    },
    "chapters": {
        "index": 2,
        "title": "Select chapters",
        "hint": "Choose which chapters to convert. We'll analyse entities automatically when you continue.",
    },
    "entities": {
        "index": 3,
        "title": "Review entities",
        "hint": "Assign pronunciations, voices, and manual overrides before queueing the conversion.",
    },
}

_SUPPLEMENT_TITLE_PATTERNS: List[tuple[re.Pattern[str], float]] = [
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
    (re.compile(r"\bglossary\b"), 2.0),
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

_SUPPLEMENT_TEXT_KEYWORDS: List[tuple[str, float]] = [
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
    if total_count <= 1:
        return True
    score = supplement_score(title, text, index)
    return score < 1.9


def ensure_at_least_one_chapter_enabled(chapters: List[Dict[str, Any]]) -> None:
    if not chapters:
        return
    if any(chapter.get("enabled") for chapter in chapters):
        return
    best_index = max(range(len(chapters)), key=lambda idx: chapters[idx].get("characters", 0))
    chapters[best_index]["enabled"] = True

def apply_prepare_form(
    pending: PendingJob, form: Mapping[str, Any]
) -> tuple[
    ChunkLevel,
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[str],
    int,
    str,
    bool,
    bool,
]:
    raw_chunk_level = (form.get("chunk_level") or pending.chunk_level or "paragraph").strip().lower()
    if raw_chunk_level not in _CHUNK_LEVEL_VALUES:
        raw_chunk_level = pending.chunk_level if pending.chunk_level in _CHUNK_LEVEL_VALUES else "paragraph"
    pending.chunk_level = raw_chunk_level
    chunk_level_literal = cast(ChunkLevel, pending.chunk_level)

    pending.speaker_mode = "single"

    pending.generate_epub3 = coerce_bool(form.get("generate_epub3"), False)

    threshold_default = getattr(pending, "speaker_analysis_threshold", _DEFAULT_ANALYSIS_THRESHOLD)
    raw_threshold = form.get("speaker_analysis_threshold")
    if raw_threshold is not None:
        pending.speaker_analysis_threshold = coerce_int(
            raw_threshold,
            threshold_default,
            minimum=1,
            maximum=25,
        )
    else:
        pending.speaker_analysis_threshold = threshold_default

    if not pending.speakers:
        narrator: Dict[str, Any] = {
            "id": "narrator",
            "label": "Narrator",
            "voice": pending.voice,
        }
        if pending.voice_profile:
            narrator["voice_profile"] = pending.voice_profile
        pending.speakers = {"narrator": narrator}
    else:
        existing_narrator = pending.speakers.get("narrator")
        if isinstance(existing_narrator, dict):
            existing_narrator.setdefault("id", "narrator")
            existing_narrator["label"] = existing_narrator.get("label", "Narrator")
            existing_narrator["voice"] = pending.voice
            if pending.voice_profile:
                existing_narrator["voice_profile"] = pending.voice_profile
            pending.speakers["narrator"] = existing_narrator

    selected_config = (form.get("applied_speaker_config") or "").strip()
    apply_config_requested = str(form.get("apply_speaker_config", "")).strip() in {"1", "true", "on"}
    persist_config_requested = str(form.get("save_speaker_config", "")).strip() in {"1", "true", "on"}

    pending.applied_speaker_config = selected_config or None

    errors: List[str] = []

    if isinstance(pending.speakers, dict):
        for speaker_id, payload in list(pending.speakers.items()):
            if not isinstance(payload, dict):
                continue
            field_key = f"speaker-{speaker_id}-pronunciation"
            raw_value = form.get(field_key, "")
            pronunciation = raw_value.strip()
            if pronunciation:
                payload["pronunciation"] = pronunciation
            else:
                payload.pop("pronunciation", None)

            voice_value = (form.get(f"speaker-{speaker_id}-voice") or "").strip()
            formula_key = f"speaker-{speaker_id}-formula"
            formula_value = (form.get(formula_key) or "").strip()
            has_formula = False
            if formula_value:
                try:
                    parse_voice_formula(formula_value)
                except ValueError as exc:
                    label = payload.get("label") or speaker_id.replace("_", " ").title()
                    errors.append(f"Invalid custom mix for {label}: {exc}")
                else:
                    payload["voice_formula"] = formula_value
                    payload["resolved_voice"] = formula_value
                    payload.pop("voice_profile", None)
                    has_formula = True
            else:
                payload.pop("voice_formula", None)

            if voice_value == "__custom_mix":
                voice_value = ""

            if voice_value:
                payload["voice"] = voice_value
                if not has_formula:
                    payload["resolved_voice"] = voice_value
            else:
                payload.pop("voice", None)
                if not has_formula:
                    payload.pop("resolved_voice", None)

            lang_key = f"speaker-{speaker_id}-languages"
            languages: List[str] = []
            getter = getattr(form, "getlist", None)
            if callable(getter):
                values = cast(Iterable[str], getter(lang_key))
                languages = [code.strip() for code in values if code]
            else:
                raw_langs = form.get(lang_key)
                if isinstance(raw_langs, str):
                    languages = [item.strip() for item in raw_langs.split(",") if item.strip()]
            payload["config_languages"] = languages

    profiles = serialize_profiles()
    raw_delay = form.get("chapter_intro_delay")
    if raw_delay is not None:
        raw_normalized = raw_delay.strip()
        if raw_normalized:
            try:
                pending.chapter_intro_delay = max(0.0, float(raw_normalized))
            except ValueError:
                errors.append("Enter a valid number for the chapter intro delay.")
        else:
            pending.chapter_intro_delay = 0.0

    intro_values: List[str] = []
    getter = getattr(form, "getlist", None)
    if callable(getter):
        raw_intro_values = getter("read_title_intro")
        if raw_intro_values:
            intro_values = list(cast(Iterable[str], raw_intro_values))
    else:
        raw_intro = form.get("read_title_intro")
        if raw_intro is not None:
            intro_values = [raw_intro]
    if intro_values:
        pending.read_title_intro = coerce_bool(intro_values[-1], pending.read_title_intro)
    elif hasattr(form, "__contains__") and "read_title_intro" in form:
        pending.read_title_intro = False

    outro_values: List[str] = []
    if callable(getter):
        raw_outro_values = getter("read_closing_outro")
        if raw_outro_values:
            outro_values = list(cast(Iterable[str], raw_outro_values))
    else:
        raw_outro = form.get("read_closing_outro")
        if raw_outro is not None:
            outro_values = [raw_outro]
    if outro_values:
        pending.read_closing_outro = coerce_bool(
            outro_values[-1], getattr(pending, "read_closing_outro", True)
        )
    elif hasattr(form, "__contains__") and "read_closing_outro" in form:
        pending.read_closing_outro = False

    caps_values: List[str] = []
    if callable(getter):
        raw_caps_values = getter("normalize_chapter_opening_caps")
        if raw_caps_values:
            caps_values = list(cast(Iterable[str], raw_caps_values))
    else:
        raw_caps = form.get("normalize_chapter_opening_caps")
        if raw_caps is not None:
            caps_values = [raw_caps]
    if caps_values:
        pending.normalize_chapter_opening_caps = coerce_bool(
            caps_values[-1], getattr(pending, "normalize_chapter_opening_caps", True)
        )
    elif hasattr(form, "__contains__") and "normalize_chapter_opening_caps" in form:
        pending.normalize_chapter_opening_caps = False

    overrides: List[Dict[str, Any]] = []
    selected_total = 0

    for index, chapter in enumerate(pending.chapters):
        enabled = form.get(f"chapter-{index}-enabled") == "on"
        title_input = (form.get(f"chapter-{index}-title") or "").strip()
        title = title_input or chapter.get("title") or f"Chapter {index + 1}"
        voice_selection = form.get(f"chapter-{index}-voice", "__default")
        formula_input = (form.get(f"chapter-{index}-formula") or "").strip()

        entry: Dict[str, Any] = {
            "id": chapter.get("id") or f"{index:04d}",
            "index": index,
            "order": index,
            "source_title": chapter.get("title") or title,
            "title": title,
            "text": chapter.get("text", ""),
            "enabled": enabled,
        }
        entry["characters"] = calculate_text_length(entry["text"])

        if enabled:
            if voice_selection.startswith("voice:"):
                entry["voice"] = voice_selection.split(":", 1)[1]
                entry["resolved_voice"] = entry["voice"]
            elif voice_selection.startswith("profile:"):
                profile_name = voice_selection.split(":", 1)[1]
                entry["voice_profile"] = profile_name
                profile_entry = profiles.get(profile_name) or {}
                formula_value = formula_from_profile(profile_entry)
                if formula_value:
                    entry["voice_formula"] = formula_value
                    entry["resolved_voice"] = formula_value
                else:
                    errors.append(f"Profile '{profile_name}' has no configured voices.")
            elif voice_selection == "formula":
                if not formula_input:
                    errors.append(f"Provide a custom formula for chapter {index + 1}.")
                else:
                    try:
                        parse_voice_formula(formula_input)
                    except ValueError as exc:
                        errors.append(str(exc))
                    else:
                        entry["voice_formula"] = formula_input
                        entry["resolved_voice"] = formula_input
            selected_total += entry["characters"]

        overrides.append(entry)
        pending.chapters[index] = dict(entry)

    enabled_overrides = [entry for entry in overrides if entry.get("enabled")]

    heteronym_entries = getattr(pending, "heteronym_overrides", None)
    if isinstance(heteronym_entries, list) and heteronym_entries:
        for entry in heteronym_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("entry_id") or entry.get("id") or "").strip()
            if not entry_id:
                continue
            raw_choice = form.get(f"heteronym-{entry_id}-choice")
            if raw_choice is None:
                continue
            choice = str(raw_choice).strip()
            if not choice:
                continue
            options = entry.get("options")
            if isinstance(options, list) and options:
                allowed = {
                    str(opt.get("key")).strip()
                    for opt in options
                    if isinstance(opt, dict) and str(opt.get("key") or "").strip()
                }
                if allowed and choice not in allowed:
                    continue
            entry["choice"] = choice

    sync_pronunciation_overrides(pending)

    return (
        chunk_level_literal,
        overrides,
        enabled_overrides,
        errors,
        selected_total,
        selected_config,
        apply_config_requested,
        persist_config_requested,
    )

def apply_book_step_form(
    pending: PendingJob,
    form: Mapping[str, Any],
    *,
    settings: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> None:
    language_fallback = pending.language or settings.get("language", "en")
    raw_language = (form.get("language") or language_fallback or "en").strip()
    if raw_language:
        pending.language = raw_language

    subtitle_mode = (form.get("subtitle_mode") or pending.subtitle_mode or "Disabled").strip()
    if subtitle_mode:
        pending.subtitle_mode = subtitle_mode

    pending.generate_epub3 = coerce_bool(form.get("generate_epub3"), bool(pending.generate_epub3))

    chunk_level_default = str(settings.get("chunk_level", "paragraph")).strip().lower()
    raw_chunk_level = (form.get("chunk_level") or pending.chunk_level or chunk_level_default).strip().lower()
    if raw_chunk_level not in _CHUNK_LEVEL_VALUES:
        raw_chunk_level = chunk_level_default if chunk_level_default in _CHUNK_LEVEL_VALUES else (pending.chunk_level or "paragraph")
    pending.chunk_level = raw_chunk_level

    threshold_default = pending.speaker_analysis_threshold or settings.get("speaker_analysis_threshold", _DEFAULT_ANALYSIS_THRESHOLD)
    raw_threshold = form.get("speaker_analysis_threshold")
    if raw_threshold is not None:
        pending.speaker_analysis_threshold = coerce_int(
            raw_threshold,
            threshold_default,
            minimum=1,
            maximum=25,
        )

    raw_delay = form.get("chapter_intro_delay")
    if raw_delay is not None:
        try:
            pending.chapter_intro_delay = max(0.0, float(str(raw_delay).strip() or 0.0))
        except ValueError:
            pass

    intro_default = pending.read_title_intro if isinstance(pending.read_title_intro, bool) else bool(settings.get("read_title_intro", False))
    intro_values: List[str] = []
    getter = getattr(form, "getlist", None)
    if callable(getter):
        raw_intro_values = getter("read_title_intro")
        if raw_intro_values:
            intro_values = list(cast(Iterable[str], raw_intro_values))
    else:
        raw_intro_flag = form.get("read_title_intro")
        if raw_intro_flag is not None:
            intro_values = [raw_intro_flag]
    if intro_values:
        pending.read_title_intro = coerce_bool(intro_values[-1], intro_default)
    elif hasattr(form, "__contains__") and "read_title_intro" in form:
        pending.read_title_intro = False
    else:
        pending.read_title_intro = intro_default

    outro_default = (
        pending.read_closing_outro
        if isinstance(getattr(pending, "read_closing_outro", None), bool)
        else bool(settings.get("read_closing_outro", True))
    )
    outro_values: List[str] = []
    if callable(getter):
        raw_outro_values = getter("read_closing_outro")
        if raw_outro_values:
            outro_values = list(cast(Iterable[str], raw_outro_values))
    else:
        raw_outro_flag = form.get("read_closing_outro")
        if raw_outro_flag is not None:
            outro_values = [raw_outro_flag]
    if outro_values:
        pending.read_closing_outro = coerce_bool(outro_values[-1], outro_default)
    elif hasattr(form, "__contains__") and "read_closing_outro" in form:
        pending.read_closing_outro = False
    else:
        pending.read_closing_outro = outro_default

    caps_default = (
        pending.normalize_chapter_opening_caps
        if isinstance(getattr(pending, "normalize_chapter_opening_caps", None), bool)
        else bool(settings.get("normalize_chapter_opening_caps", True))
    )
    caps_values: List[str] = []
    getter = getattr(form, "getlist", None)
    if callable(getter):
        raw_caps_values = getter("normalize_chapter_opening_caps")
        if raw_caps_values:
            caps_values = list(cast(Iterable[str], raw_caps_values))
    else:
        raw_caps_flag = form.get("normalize_chapter_opening_caps")
        if raw_caps_flag is not None:
            caps_values = [raw_caps_flag]
    if caps_values:
        pending.normalize_chapter_opening_caps = coerce_bool(caps_values[-1], caps_default)
    elif hasattr(form, "__contains__") and "normalize_chapter_opening_caps" in form:
        pending.normalize_chapter_opening_caps = False
    else:
        pending.normalize_chapter_opening_caps = caps_default

    def _extract_checkbox(name: str, default: bool) -> bool:
        values: List[str] = []
        getter = getattr(form, "getlist", None)
        if callable(getter):
            raw_values = getter(name)
            if raw_values:
                values = list(cast(Iterable[str], raw_values))
        else:
            raw_flag = form.get(name)
            if raw_flag is not None:
                values = [raw_flag]
        if values:
            return coerce_bool(values[-1], default)
        if hasattr(form, "__contains__") and name in form:
            return False
        return default

    overrides_existing = getattr(pending, "normalization_overrides", None)
    overrides: Dict[str, Any] = dict(overrides_existing or {})
    for key in _NORMALIZATION_BOOLEAN_KEYS:
        default_toggle = overrides.get(key, bool(settings.get(key, True)))
        overrides[key] = _extract_checkbox(key, default_toggle)
    for key in _NORMALIZATION_STRING_KEYS:
        default_val = overrides.get(key, str(settings.get(key, "")))
        val = form.get(key)
        if val is not None:
            overrides[key] = str(val)
        else:
            overrides[key] = default_val
    pending.normalization_overrides = overrides

    speed_value = form.get("speed")
    if speed_value is not None:
        try:
            pending.speed = float(speed_value)
        except ValueError:
            pass

    # NOTE: Do not auto-set a global TTS provider at the book level based on the
    # narrator defaults. Provider is resolved per-speaker/per-chunk from the voice
    # spec (e.g. "speaker:Name" for saved speakers, or a Kokoro mix formula).
    # This enables mixed-provider conversions (e.g. narrator=SuperTonic, characters=Kokoro).
    provider_value = str(form.get("tts_provider") or "").strip().lower()
    if provider_value in {"kokoro", "supertonic"}:
        pending.tts_provider = provider_value

    # Determine the base speaker selection (saved speaker ref or raw voice).
    narrator_voice_raw = (
        form.get("voice")
        or pending.voice
        or settings.get("default_speaker")
        or settings.get("default_voice")
        or ""
    ).strip()

    profiles_map = dict(profiles) if isinstance(profiles, Mapping) else dict(profiles or {})
    base_spec, _selected_speaker_name = split_profile_spec(narrator_voice_raw)

    profile_selection = (form.get("voice_profile") or pending.voice_profile or "__standard").strip()
    custom_formula_raw = (form.get("voice_formula") or "").strip()
    narrator_voice_raw = (base_spec or narrator_voice_raw or settings.get("default_voice") or "").strip()
    resolved_default_voice, inferred_profile, _ = resolve_voice_setting(
        narrator_voice_raw,
        profiles=profiles_map,
    )

    if profile_selection in {"__standard", "", None} and inferred_profile:
        profile_selection = inferred_profile

    if profile_selection == "__formula":
        profile_name = ""
        custom_formula = custom_formula_raw
    elif profile_selection in {"__standard", "", None}:
        profile_name = ""
        custom_formula = ""
    else:
        profile_name = profile_selection
        custom_formula = ""

    base_voice_spec = resolved_default_voice or narrator_voice_raw
    if not base_voice_spec and VOICES_INTERNAL:
        base_voice_spec = VOICES_INTERNAL[0]

    voice_choice, resolved_language, selected_profile = resolve_voice_choice(
        pending.language,
        base_voice_spec,
        profile_name,
        custom_formula,
        profiles_map,
    )

    if resolved_language:
        pending.language = resolved_language

    if profile_selection == "__formula" and custom_formula_raw:
        pending.voice = custom_formula_raw
        pending.voice_profile = None
    elif profile_selection not in {"__standard", "", None, "__formula"}:
        pending.voice_profile = selected_profile or profile_selection
        pending.voice = voice_choice
    else:
        pending.voice_profile = None
        fallback_voice = base_voice_spec or narrator_voice_raw
        pending.voice = voice_choice or fallback_voice

    pending.applied_speaker_config = (form.get("speaker_config") or "").strip() or None

    # Metadata updates
    if "meta_title" in form:
        pending.metadata_tags["title"] = str(form.get("meta_title", "")).strip()

    if "meta_subtitle" in form:
        pending.metadata_tags["subtitle"] = str(form.get("meta_subtitle", "")).strip()

    if "meta_author" in form:
        authors = str(form.get("meta_author", "")).strip()
        pending.metadata_tags["authors"] = authors
        pending.metadata_tags["author"] = authors

    if "meta_series" in form:
        series = str(form.get("meta_series", "")).strip()
        pending.metadata_tags["series"] = series
        pending.metadata_tags["series_name"] = series
        pending.metadata_tags["seriesname"] = series
        pending.metadata_tags["series_title"] = series
        pending.metadata_tags["seriestitle"] = series
        # If user manually edits series, update opds_series too so it persists
        if "opds_series" in pending.metadata_tags:
            pending.metadata_tags["opds_series"] = series

    if "meta_series_index" in form:
        idx = str(form.get("meta_series_index", "")).strip()
        pending.metadata_tags["series_index"] = idx
        pending.metadata_tags["series_sequence"] = idx

    if "meta_publisher" in form:
        pending.metadata_tags["publisher"] = str(form.get("meta_publisher", "")).strip()

    if "meta_description" in form:
        desc = str(form.get("meta_description", "")).strip()
        pending.metadata_tags["description"] = desc
        pending.metadata_tags["summary"] = desc

    if coerce_bool(form.get("remove_cover"), False):
        pending.cover_image_path = None
        pending.cover_image_mime = None

def persist_cover_image(extraction_result: Any, stored_path: Path) -> tuple[Optional[Path], Optional[str]]:
    cover_bytes = getattr(extraction_result, "cover_image", None)
    if not cover_bytes:
        return None, None

    mime = getattr(extraction_result, "cover_mime", None)
    extension = mimetypes.guess_extension(mime or "") or ".png"
    base_stem = Path(stored_path).stem or "cover"
    candidate = stored_path.parent / f"{base_stem}_cover{extension}"
    counter = 1
    while candidate.exists():
        candidate = stored_path.parent / f"{base_stem}_cover_{counter}{extension}"
        counter += 1

    try:
        candidate.write_bytes(cover_bytes)
    except OSError:
        return None, None

    return candidate, mime

def build_pending_job_from_extraction(
    *,
    stored_path: Path,
    original_name: str,
    extraction: Any,
    form: Mapping[str, Any],
    settings: Mapping[str, Any],
    profiles: Mapping[str, Any],
    metadata_overrides: Optional[Mapping[str, Any]] = None,
) -> PendingBuildResult:
    profiles_map = dict(profiles)
    cover_path, cover_mime = persist_cover_image(extraction, stored_path)

    if getattr(extraction, "chapters", None):
        original_titles = [chapter.title for chapter in extraction.chapters]
        normalized_titles = normalize_roman_numeral_titles(original_titles)
        if normalized_titles != original_titles:
            for chapter, new_title in zip(extraction.chapters, normalized_titles):
                chapter.title = new_title

    metadata_tags = dict(getattr(extraction, "metadata", {}) or {})
    if metadata_overrides:
        normalized_keys = {str(existing_key).casefold(): str(existing_key) for existing_key in metadata_tags.keys()}
        for key, value in metadata_overrides.items():
            if value is None:
                continue
            key_text = str(key or "").strip()
            if not key_text:
                continue
            value_text = str(value).strip()
            if not value_text:
                continue
            lookup = key_text.casefold()
            existing_key = normalized_keys.get(lookup)
            if existing_key:
                existing_value = str(metadata_tags.get(existing_key) or "").strip()
                if existing_value:
                    continue
                target_key = existing_key
            else:
                target_key = key_text
                normalized_keys[lookup] = target_key
            metadata_tags[target_key] = value_text

    total_chars = getattr(extraction, "total_characters", None) or calculate_text_length(
        getattr(extraction, "combined_text", "")
    )
    chapters_source = getattr(extraction, "chapters", []) or []
    total_chapter_count = len(chapters_source)
    chapters_payload: List[Dict[str, Any]] = []
    for index, chapter in enumerate(chapters_source):
        enabled = should_preselect_chapter(chapter.title, chapter.text, index, total_chapter_count)
        chapters_payload.append(
            {
                "id": f"{index:04d}",
                "index": index,
                "title": chapter.title,
                "text": chapter.text,
                "characters": calculate_text_length(chapter.text),
                "enabled": enabled,
            }
        )

    if not chapters_payload:
        chapters_payload.append(
            {
                "id": "0000",
                "index": 0,
                "title": original_name,
                "text": "",
                "characters": 0,
                "enabled": True,
            }
        )

    ensure_at_least_one_chapter_enabled(chapters_payload)

    language = str(form.get("language") or "a").strip() or "a"
    profiles_map = dict(profiles) if isinstance(profiles, Mapping) else dict(profiles or {})
    default_voice_setting = settings.get("default_voice") or ""
    resolved_default_voice, inferred_profile, inferred_language = resolve_voice_setting(
        default_voice_setting,
        profiles=profiles_map,
    )
    base_voice_input = str(form.get("voice") or "").strip()
    profile_selection = (form.get("voice_profile") or "__standard").strip()
    custom_formula_raw = str(form.get("voice_formula") or "").strip()

    if profile_selection in {"__standard", ""} and inferred_profile:
        profile_selection = inferred_profile

    base_voice = base_voice_input or resolved_default_voice or str(default_voice_setting).strip()
    if not base_voice and VOICES_INTERNAL:
        base_voice = VOICES_INTERNAL[0]
    selected_speaker_config = (form.get("speaker_config") or "").strip()
    speaker_config_payload = get_config(selected_speaker_config) if selected_speaker_config else None

    if profile_selection == "__formula":
        profile_name = ""
        custom_formula = custom_formula_raw
    elif profile_selection in {"__standard", ""}:
        profile_name = ""
        custom_formula = ""
    else:
        profile_name = profile_selection
        custom_formula = ""

    voice, language, selected_profile = resolve_voice_choice(
        language,
        base_voice,
        profile_name,
        custom_formula,
        profiles_map,
    )

    try:
        speed = float(form.get("speed", 1.0))
    except (TypeError, ValueError):
        speed = 1.0

    subtitle_mode = str(form.get("subtitle_mode") or "Disabled")
    output_format = settings["output_format"]
    subtitle_format = settings["subtitle_format"]
    save_mode_key = settings["save_mode"]
    save_mode = SAVE_MODE_LABELS.get(save_mode_key, SAVE_MODE_LABELS["save_next_to_input"])
    replace_single_newlines = settings["replace_single_newlines"]
    use_gpu = settings["use_gpu"]
    save_chapters_separately = settings["save_chapters_separately"]
    merge_chapters_at_end = settings["merge_chapters_at_end"] or not save_chapters_separately
    save_as_project = settings["save_as_project"]
    separate_chapters_format = settings["separate_chapters_format"]
    silence_between_chapters = settings["silence_between_chapters"]
    chapter_intro_delay = settings["chapter_intro_delay"]
    read_title_intro = settings["read_title_intro"]
    read_closing_outro = settings.get("read_closing_outro", True)
    normalize_chapter_opening_caps = settings["normalize_chapter_opening_caps"]
    max_subtitle_words = settings["max_subtitle_words"]
    auto_prefix_chapter_titles = settings["auto_prefix_chapter_titles"]

    chunk_level_default = str(settings.get("chunk_level", "paragraph")).strip().lower()
    raw_chunk_level = str(form.get("chunk_level") or chunk_level_default).strip().lower()
    if raw_chunk_level not in _CHUNK_LEVEL_VALUES:
        raw_chunk_level = chunk_level_default if chunk_level_default in _CHUNK_LEVEL_VALUES else "paragraph"
    chunk_level_value = raw_chunk_level
    chunk_level_literal = cast(ChunkLevel, chunk_level_value)

    speaker_mode_value = "single"

    generate_epub3_default = bool(settings.get("generate_epub3", False))
    generate_epub3 = coerce_bool(form.get("generate_epub3"), generate_epub3_default)

    selected_chapter_sources = [entry for entry in chapters_payload if entry.get("enabled")]
    raw_chunks = build_chunks_for_chapters(selected_chapter_sources, level=chunk_level_literal)
    analysis_chunks = build_chunks_for_chapters(selected_chapter_sources, level="sentence")

    analysis_threshold = coerce_int(
        settings.get("speaker_analysis_threshold"),
        _DEFAULT_ANALYSIS_THRESHOLD,
        minimum=1,
        maximum=25,
    )

    initial_analysis = False
    (
        processed_chunks,
        speakers,
        analysis_payload,
        config_languages,
        _,
    ) = prepare_speaker_metadata(
        chapters=selected_chapter_sources,
        chunks=raw_chunks,
        analysis_chunks=analysis_chunks,
        voice=voice,
        voice_profile=selected_profile or None,
        threshold=analysis_threshold,
        run_analysis=initial_analysis,
        speaker_config=speaker_config_payload,
        apply_config=bool(speaker_config_payload),
    )

    def _extract_checkbox(name: str, default: bool) -> bool:
        values: List[str] = []
        getter = getattr(form, "getlist", None)
        if callable(getter):
            raw_values = getter(name)
            if raw_values:
                values = list(cast(Iterable[str], raw_values))
        else:
            raw_flag = form.get(name)
            if raw_flag is not None:
                values = [raw_flag]
        if values:
            return coerce_bool(values[-1], default)
        return default

    normalization_overrides = {}
    for key in _NORMALIZATION_BOOLEAN_KEYS:
        default_val = bool(settings.get(key, True))
        normalization_overrides[key] = _extract_checkbox(key, default_val)

    for key in _NORMALIZATION_STRING_KEYS:
        default_val = str(settings.get(key, ""))
        val = form.get(key)
        if val is not None:
            normalization_overrides[key] = str(val)
        else:
            normalization_overrides[key] = default_val

    pending = PendingJob(
        id=uuid.uuid4().hex,
        original_filename=original_name,
        stored_path=stored_path,
        language=language,
        voice=voice,
        speed=speed,
        use_gpu=use_gpu,
        subtitle_mode=subtitle_mode,
        output_format=output_format,
        save_mode=save_mode,
        output_folder=None,
        replace_single_newlines=replace_single_newlines,
        subtitle_format=subtitle_format,
        total_characters=total_chars,
        save_chapters_separately=save_chapters_separately,
        merge_chapters_at_end=merge_chapters_at_end,
        separate_chapters_format=separate_chapters_format,
        silence_between_chapters=silence_between_chapters,
        save_as_project=save_as_project,
        voice_profile=selected_profile or None,
        max_subtitle_words=max_subtitle_words,
        metadata_tags=metadata_tags,
        chapters=chapters_payload,
        normalization_overrides=normalization_overrides,
        created_at=time.time(),
        cover_image_path=cover_path,
        cover_image_mime=cover_mime,
        chapter_intro_delay=chapter_intro_delay,
        read_title_intro=bool(read_title_intro),
        read_closing_outro=bool(read_closing_outro),
        normalize_chapter_opening_caps=bool(normalize_chapter_opening_caps),
        auto_prefix_chapter_titles=bool(auto_prefix_chapter_titles),
        chunk_level=chunk_level_value,
        speaker_mode=speaker_mode_value,
        generate_epub3=generate_epub3,
        chunks=processed_chunks,
        speakers=speakers,
        speaker_analysis=analysis_payload,
        speaker_analysis_threshold=analysis_threshold,
        analysis_requested=initial_analysis,
    )

    return PendingBuildResult(
        pending=pending,
        selected_speaker_config=selected_speaker_config or None,
        config_languages=list(config_languages or []),
        speaker_config_payload=speaker_config_payload,
    )

def render_jobs_panel() -> str:
    jobs = get_service().list_jobs()
    active_statuses = {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED}
    active_jobs = [job for job in jobs if job.status in active_statuses]
    active_jobs.sort(key=lambda job: ((job.queue_position or 10_000), -job.created_at))
    finished_jobs = [job for job in jobs if job.status not in active_statuses]
    download_flags = {job.id: job_download_flags(job) for job in jobs}
    return render_template(
        "partials/jobs.html",
        active_jobs=active_jobs,
        finished_jobs=finished_jobs[:5],
        total_finished=len(finished_jobs),
        JobStatus=JobStatus,
        download_flags=download_flags,
        audiobookshelf_manual_available=audiobookshelf_manual_available(),
    )


def normalize_wizard_step(step: Optional[str], pending: Optional[PendingJob] = None) -> str:
    if pending is None:
        default_step = "book"
    else:
        default_step = "chapters"
    if not step:
        chosen = default_step
    else:
        normalized = step.strip().lower()
        if normalized in {"", "upload", "settings"}:
            chosen = default_step
        elif normalized == "speakers":
            chosen = "entities"
        elif normalized in _WIZARD_STEP_ORDER:
            chosen = normalized
        else:
            chosen = default_step
    return chosen


def wants_wizard_json() -> bool:
    format_hint = request.args.get("format", "").strip().lower()
    if format_hint == "json":
        return True
    accept_header = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept_header:
        return True
    requested_with = (request.headers.get("X-Requested-With") or "").lower()
    if requested_with in {"xmlhttprequest", "fetch"}:
        return True
    wizard_header = (request.headers.get("X-Abogen-Wizard") or "").lower()
    return wizard_header == "json"


def render_wizard_partial(
    pending: Optional[PendingJob],
    step: str,
    *,
    error: Optional[str] = None,
    notice: Optional[str] = None,
) -> str:
    templates = {
        "book": "partials/new_job_step_book.html",
        "chapters": "partials/new_job_step_chapters.html",
        "entities": "partials/new_job_step_entities.html",
    }
    template_name = templates[step]
    context: Dict[str, Any] = {
        "pending": pending,
        "readonly": False,
        "options": template_options(),
        "settings": load_settings(),
        "error": error,
        "notice": notice,
    }
    return render_template(template_name, **context)


def wizard_step_payload(
    pending: Optional[PendingJob],
    step: str,
    html: str,
    *,
    error: Optional[str] = None,
    notice: Optional[str] = None,
) -> Dict[str, Any]:
    meta = _WIZARD_STEP_META.get(step, {})
    try:
        active_index = _WIZARD_STEP_ORDER.index(step)
    except ValueError:
        active_index = 0
    max_recorded_index = active_index
    if pending is not None:
        stored_index = int(getattr(pending, "wizard_max_step_index", -1))
        if stored_index < 0:
            stored_index = -1
        max_recorded_index = max(active_index, stored_index)
        max_allowed = len(_WIZARD_STEP_ORDER) - 1
        if max_recorded_index > max_allowed:
            max_recorded_index = max_allowed
        if stored_index != max_recorded_index:
            pending.wizard_max_step_index = max_recorded_index
            get_service().store_pending_job(pending)
    else:
        max_allowed = len(_WIZARD_STEP_ORDER) - 1
        if max_recorded_index > max_allowed:
            max_recorded_index = max_allowed
    completed = [slug for idx, slug in enumerate(_WIZARD_STEP_ORDER) if idx <= max_recorded_index]
    return {
        "step": step,
        "step_index": int(meta.get("index", active_index + 1)),
        "total_steps": len(_WIZARD_STEP_ORDER),
        "title": meta.get("title", ""),
        "hint": meta.get("hint", ""),
        "html": html,
        "completed_steps": completed,
        "pending_id": pending.id if pending else "",
        "filename": pending.original_filename if pending and pending.original_filename else "",
        "error": error or "",
        "notice": notice or "",
    }


def wizard_json_response(
    pending: Optional[PendingJob],
    step: str,
    *,
    error: Optional[str] = None,
    notice: Optional[str] = None,
    status: int = 200,
) -> ResponseReturnValue:
    html = render_wizard_partial(pending, step, error=error, notice=notice)
    payload = wizard_step_payload(pending, step, html, error=error, notice=notice)
    return jsonify(payload), status
