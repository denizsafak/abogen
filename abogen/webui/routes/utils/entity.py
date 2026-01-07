import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional

from abogen.webui.service import PendingJob
from abogen.entity_analysis import (
    extract_entities,
    merge_override,
    normalize_token as normalize_entity_token,
    normalize_manual_override_token,
    search_tokens as search_entity_tokens,
)
from abogen.pronunciation_store import (
    delete_override as delete_pronunciation_override,
    load_overrides as load_pronunciation_overrides,
    save_override as save_pronunciation_override,
    search_overrides as search_pronunciation_overrides,
)
from abogen.webui.routes.utils.settings import load_settings
from abogen.heteronym_overrides import extract_heteronym_overrides

def collect_pronunciation_overrides(pending: PendingJob) -> List[Dict[str, Any]]:
    language = pending.language or "en"
    collected: Dict[str, Dict[str, Any]] = {}

    summary = pending.entity_summary or {}
    for group in ("people", "entities"):
        entries = summary.get(group)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            override_payload = entry.get("override")
            if not isinstance(override_payload, Mapping):
                continue
            token_value = str(entry.get("label") or override_payload.get("token") or "").strip()
            pronunciation_value = str(override_payload.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = normalize_entity_token(entry.get("normalized") or token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(override_payload.get("voice") or "").strip() or None,
                "notes": str(override_payload.get("notes") or "").strip() or None,
                "context": str(override_payload.get("context") or "").strip() or None,
                "source": f"{group}-override",
                "language": language,
            }

    if isinstance(pending.speakers, Mapping):
        for speaker_payload in pending.speakers.values():
            if not isinstance(speaker_payload, Mapping):
                continue
            token_value = str(speaker_payload.get("label") or "").strip()
            pronunciation_value = str(speaker_payload.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = normalize_entity_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(
                    speaker_payload.get("resolved_voice")
                    or speaker_payload.get("voice")
                    or pending.voice
                ).strip()
                or None,
                "notes": None,
                "context": None,
                "source": "speaker",
                "language": language,
            }

    for manual_entry in pending.manual_overrides or []:
        if not isinstance(manual_entry, Mapping):
            continue
        token_value = str(manual_entry.get("token") or "").strip()
        pronunciation_value = str(manual_entry.get("pronunciation") or "").strip()
        if not token_value or not pronunciation_value:
            continue
        normalized = manual_entry.get("normalized") or normalize_manual_override_token(token_value)
        if not normalized:
            continue
        collected[normalized] = {
            "token": token_value,
            "normalized": normalized,
            "pronunciation": pronunciation_value,
            "voice": str(manual_entry.get("voice") or "").strip() or None,
            "notes": str(manual_entry.get("notes") or "").strip() or None,
            "context": str(manual_entry.get("context") or "").strip() or None,
            "source": str(manual_entry.get("source") or "manual"),
            "language": language,
        }

    return list(collected.values())


def sync_pronunciation_overrides(pending: PendingJob) -> None:
    pending.pronunciation_overrides = collect_pronunciation_overrides(pending)

    if not pending.pronunciation_overrides:
        return

    summary = pending.entity_summary or {}
    manual_map: Dict[str, Mapping[str, Any]] = {}
    for override in pending.manual_overrides or []:
        if not isinstance(override, Mapping):
            continue
        normalized = override.get("normalized") or normalize_entity_token(override.get("token") or "")
        pronunciation_value = str(override.get("pronunciation") or "").strip()
        if not normalized or not pronunciation_value:
            continue
        manual_map[normalized] = override
    for group in ("people", "entities"):
        entries = summary.get(group)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            normalized = normalize_entity_token(entry.get("normalized") or entry.get("label") or "")
            manual_override = manual_map.get(normalized)
            if manual_override:
                entry["override"] = {
                    "token": manual_override.get("token"),
                    "pronunciation": manual_override.get("pronunciation"),
                    "voice": manual_override.get("voice"),
                    "notes": manual_override.get("notes"),
                    "context": manual_override.get("context"),
                    "source": manual_override.get("source"),
                }


def refresh_entity_summary(pending: PendingJob, chapters: Iterable[Mapping[str, Any]]) -> None:
    settings = load_settings()
    language = pending.language or "en"
    chapter_list: List[Mapping[str, Any]] = [chapter for chapter in chapters if isinstance(chapter, Mapping)]
    if not chapter_list:
        pending.entity_summary = {}
        pending.entity_cache_key = ""
        pending.pronunciation_overrides = pending.pronunciation_overrides or []
        pending.heteronym_overrides = pending.heteronym_overrides or []
        return

    enabled_only = [chapter for chapter in chapter_list if chapter.get("enabled")]
    target_chapters = enabled_only or chapter_list

    # Always compute heteronym overrides (English only). Preserve any prior selections.
    try:
        pending.heteronym_overrides = extract_heteronym_overrides(
            target_chapters,
            language=language,
            existing=getattr(pending, "heteronym_overrides", None),
        )
    except Exception:
        pending.heteronym_overrides = getattr(pending, "heteronym_overrides", []) or []

    if not bool(settings.get("enable_entity_recognition", True)):
        pending.entity_summary = {}
        pending.entity_cache_key = ""
        pending.pronunciation_overrides = pending.pronunciation_overrides or []
        return

    result = extract_entities(target_chapters, language=language)
    summary = dict(result.summary)
    tokens: List[str] = []
    for group in ("people", "entities"):
        entries = summary.get(group)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            token_value = str(entry.get("normalized") or entry.get("label") or "").strip()
            if token_value:
                tokens.append(token_value)

    overrides_from_store = load_pronunciation_overrides(language=language, tokens=tokens)
    merged_summary = merge_override(summary, overrides_from_store)
    if result.errors:
        merged_summary["errors"] = list(result.errors)
    merged_summary["cache_key"] = result.cache_key
    pending.entity_summary = merged_summary
    pending.entity_cache_key = result.cache_key
    sync_pronunciation_overrides(pending)


def find_manual_override(pending: PendingJob, identifier: str) -> Optional[Dict[str, Any]]:
    for entry in pending.manual_overrides or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == identifier or entry.get("normalized") == identifier:
            return entry
    return None


def upsert_manual_override(pending: PendingJob, payload: Mapping[str, Any]) -> Dict[str, Any]:
    token_value = str(payload.get("token") or "").strip()
    if not token_value:
        raise ValueError("Token is required")
    pronunciation_value = str(payload.get("pronunciation") or "").strip()
    voice_value = str(payload.get("voice") or "").strip()
    notes_value = str(payload.get("notes") or "").strip()
    context_value = str(payload.get("context") or "").strip()
    normalized = payload.get("normalized") or normalize_manual_override_token(token_value)
    if not normalized:
        raise ValueError("Token is required")

    existing = find_manual_override(pending, payload.get("id", "")) or find_manual_override(pending, normalized)
    timestamp = time.time()
    language = pending.language or "en"

    if existing:
        existing.update(
            {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": voice_value,
                "notes": notes_value,
                "context": context_value,
                "updated_at": timestamp,
            }
        )
        manual_entry = existing
    else:
        manual_entry = {
            "id": payload.get("id") or uuid.uuid4().hex,
            "token": token_value,
            "normalized": normalized,
            "pronunciation": pronunciation_value,
            "voice": voice_value,
            "notes": notes_value,
            "context": context_value,
            "language": language,
            "source": payload.get("source") or "manual",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if isinstance(pending.manual_overrides, list):
            pending.manual_overrides.append(manual_entry)
        else:
            pending.manual_overrides = [manual_entry]

    save_pronunciation_override(
        language=language,
        token=token_value,
        pronunciation=pronunciation_value or None,
        voice=voice_value or None,
        notes=notes_value or None,
        context=context_value or None,
    )

    sync_pronunciation_overrides(pending)
    return dict(manual_entry)


def delete_manual_override(pending: PendingJob, override_id: str) -> bool:
    if not override_id:
        return False
    entries = pending.manual_overrides or []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == override_id:
            token_value = entry.get("token") or ""
            language = pending.language or "en"
            delete_pronunciation_override(language=language, token=token_value)
            entries.pop(index)
            pending.manual_overrides = entries
            sync_pronunciation_overrides(pending)
            return True
    return False


def search_manual_override_candidates(pending: PendingJob, query: str, *, limit: int = 15) -> List[Dict[str, Any]]:
    normalized_query = (query or "").strip()
    summary_index = (pending.entity_summary or {}).get("index", {})
    matches = search_entity_tokens(summary_index, normalized_query, limit=limit)
    registry: Dict[str, Dict[str, Any]] = {}

    for entry in matches:
        normalized = normalize_entity_token(entry.get("normalized") or entry.get("token") or "")
        if not normalized:
            continue
        registry.setdefault(
            normalized,
            {
                "token": entry.get("token"),
                "normalized": normalized,
                "category": entry.get("category") or "entity",
                "count": entry.get("count", 0),
                "samples": entry.get("samples", []),
                "source": "entity",
            },
        )

    language = pending.language or "en"
    store_matches = search_pronunciation_overrides(language=language, query=normalized_query, limit=limit)
    for entry in store_matches:
        normalized = entry.get("normalized")
        if not normalized:
            continue
        registry.setdefault(
            normalized,
            {
                "token": entry.get("token"),
                "normalized": normalized,
                "category": "history",
                "count": entry.get("usage_count", 0),
                "samples": [entry.get("context")] if entry.get("context") else [],
                "source": "history",
                "pronunciation": entry.get("pronunciation"),
                "voice": entry.get("voice"),
            },
        )

    for entry in pending.manual_overrides or []:
        if not isinstance(entry, Mapping):
            continue
        normalized = entry.get("normalized")
        if not normalized:
            continue
        registry.setdefault(
            normalized,
            {
                "token": entry.get("token"),
                "normalized": normalized,
                "category": "manual",
                "count": 0,
                "samples": [entry.get("context")] if entry.get("context") else [],
                "source": "manual",
                "pronunciation": entry.get("pronunciation"),
                "voice": entry.get("voice"),
            },
        )

    ordered = sorted(registry.values(), key=lambda item: (-int(item.get("count") or 0), item.get("token") or ""))
    if limit:
        return ordered[:limit]
    return ordered


def pending_entities_payload(pending: PendingJob) -> Dict[str, Any]:
    settings = load_settings()
    recognition_enabled = bool(settings.get("enable_entity_recognition", True))
    return {
        "summary": pending.entity_summary or {},
        "manual_overrides": pending.manual_overrides or [],
        "pronunciation_overrides": pending.pronunciation_overrides or [],
        "heteronym_overrides": getattr(pending, "heteronym_overrides", None) or [],
        "cache_key": pending.entity_cache_key,
        "language": pending.language or "en",
        "recognition_enabled": recognition_enabled,
    }
