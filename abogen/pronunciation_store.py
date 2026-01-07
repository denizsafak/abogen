from __future__ import annotations

import json
import sqlite3
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .entity_analysis import normalize_token
from .utils import get_internal_cache_path, get_user_settings_dir

_DB_LOCK = threading.RLock()
_SCHEMA_VERSION = 1


def _store_path() -> Path:
    try:
        base_dir = Path(get_user_settings_dir())
    except ModuleNotFoundError:
        base_dir = Path(get_internal_cache_path("pronunciations"))
    target = base_dir / "overrides.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _migrate_legacy_sqlite(target_json_path: Path) -> None:
    try:
        base_dir = Path(get_user_settings_dir())
    except ModuleNotFoundError:
        base_dir = Path(get_internal_cache_path("pronunciations"))
    
    sqlite_path = base_dir / "pronunciations.db"
    if not sqlite_path.exists():
        return

    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        
        # Check if table exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='overrides'")
        if not cursor.fetchone():
            conn.close()
            return

        cursor = conn.execute("SELECT * FROM overrides")
        rows = cursor.fetchall()
        
        data = {"version": _SCHEMA_VERSION, "overrides": {}}
        
        for row in rows:
            lang = row["language"]
            if lang not in data["overrides"]:
                data["overrides"][lang] = {}
            
            entry = {
                "id": str(row["id"]),
                "normalized": row["normalized"],
                "token": row["token"],
                "language": row["language"],
                "pronunciation": row["pronunciation"],
                "voice": row["voice"],
                "notes": row["notes"],
                "context": row["context"],
                "usage_count": row["usage_count"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            data["overrides"][lang][row["normalized"]] = entry
            
        conn.close()
        
        # Save to JSON
        with open(target_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        # Rename old DB
        sqlite_path.rename(sqlite_path.with_suffix(".db.bak"))
        
    except Exception:
        pass


def _load_db() -> Dict[str, Any]:
    path = _store_path()
    if not path.exists():
        _migrate_legacy_sqlite(path)
        if not path.exists():
            return {"version": _SCHEMA_VERSION, "overrides": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": _SCHEMA_VERSION, "overrides": {}}


def _save_db(data: Dict[str, Any]) -> None:
    path = _store_path()
    # Atomic write
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    shutil.move(str(temp_path), str(path))


def load_overrides(language: str, tokens: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    normalized_tokens = {normalize_token(token) for token in tokens if token}
    if not normalized_tokens:
        return {}
    
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        results: Dict[str, Dict[str, Any]] = {}
        for normalized in normalized_tokens:
            if normalized in lang_overrides:
                results[normalized] = lang_overrides[normalized]
        return results


def search_overrides(language: str, query: str, *, limit: int = 15) -> List[Dict[str, Any]]:
    if not query:
        return []
    
    query = query.lower()
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        matches = []
        for entry in lang_overrides.values():
            if query in entry["normalized"] or query in entry["token"].lower():
                matches.append(entry)
        
        # Sort by usage count desc, then updated_at desc
        matches.sort(key=lambda x: (x.get("usage_count", 0), x.get("updated_at", 0)), reverse=True)
        return matches[:limit]


def save_override(
    *,
    language: str,
    token: str,
    pronunciation: Optional[str] = None,
    voice: Optional[str] = None,
    notes: Optional[str] = None,
    context: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = normalize_token(token)
    if not normalized:
        raise ValueError("Provide a token to override")
    
    timestamp = time.time()
    with _DB_LOCK:
        db = _load_db()
        overrides = db.setdefault("overrides", {})
        lang_overrides = overrides.setdefault(language, {})
        
        existing = lang_overrides.get(normalized)
        
        if existing:
            entry = existing
            entry["token"] = token
            entry["pronunciation"] = pronunciation
            entry["voice"] = voice
            entry["notes"] = notes
            entry["context"] = context
            entry["updated_at"] = timestamp
        else:
            entry = {
                "id": str(uuid.uuid4()),
                "normalized": normalized,
                "token": token,
                "language": language,
                "pronunciation": pronunciation,
                "voice": voice,
                "notes": notes,
                "context": context,
                "usage_count": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            lang_overrides[normalized] = entry
            
        _save_db(db)
        return entry


def delete_override(*, language: str, token: str) -> None:
    normalized = normalize_token(token)
    if not normalized:
        return
    
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        if normalized in lang_overrides:
            del lang_overrides[normalized]
            _save_db(db)


def all_overrides(language: str) -> List[Dict[str, Any]]:
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        results = list(lang_overrides.values())
        results.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return results


def increment_usage(*, language: str, token: str, amount: int = 1) -> None:
    normalized = normalize_token(token)
    if not normalized:
        return
    
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        if normalized in lang_overrides:
            entry = lang_overrides[normalized]
            entry["usage_count"] = entry.get("usage_count", 0) + amount
            entry["updated_at"] = time.time()
            _save_db(db)


def get_override_stats(language: str) -> Dict[str, int]:
    with _DB_LOCK:
        db = _load_db()
        lang_overrides = db.get("overrides", {}).get(language, {})
        
        total = len(lang_overrides)
        with_pronunciation = sum(1 for x in lang_overrides.values() if x.get("pronunciation"))
        with_voice = sum(1 for x in lang_overrides.values() if x.get("voice"))
        
        return {
            "total": total,
            "filtered": total,
            "with_pronunciation": with_pronunciation,
            "with_voice": with_voice,
        }
