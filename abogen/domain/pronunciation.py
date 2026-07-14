"""Pronunciation rule compilation and application.

Pure functions for compiling token-level and sentence-level pronunciation
overrides into regex patterns, applying them to text, and merging multiple
override sources with precedence rules.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from abogen.entity_analysis import normalize_token as normalize_entity_token
from abogen.entity_analysis import normalize_manual_override_token


def compile_pronunciation_rules(
    overrides: Optional[Iterable[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    if not overrides:
        return []

    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for entry in overrides:
        if not isinstance(entry, Mapping):
            continue
        pronunciation_value = str(entry.get("pronunciation") or "").strip()
        if not pronunciation_value:
            continue

        token_values: List[str] = []
        token_raw = entry.get("token")
        if token_raw:
            token_value = str(token_raw).strip()
            if token_value:
                token_values.append(token_value)
        normalized_raw = entry.get("normalized")
        if normalized_raw:
            normalized_value = str(normalized_raw).strip()
            if normalized_value:
                token_values.append(normalized_value)
        if token_raw and not token_values:
            fallback = normalize_entity_token(str(token_raw))
            if fallback:
                token_values.append(fallback)

        if not token_values:
            continue

        usage_normalized = str(entry.get("normalized") or "").strip()
        if not usage_normalized and token_values:
            usage_normalized = normalize_entity_token(token_values[0]) or token_values[0]
        usage_token = str(entry.get("token") or token_values[0])

        for token_value in token_values:
            key = token_value.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "token": token_value,
                    "normalized": usage_normalized,
                    "replacement": pronunciation_value,
                }
            )

    if not candidates:
        return []

    candidates.sort(key=lambda item: len(item["token"]), reverse=True)
    compiled: List[Dict[str, Any]] = []
    for candidate in candidates:
        token_value = candidate["token"]
        pronunciation_value = candidate["replacement"]
        escaped = re.escape(token_value)
        pattern = re.compile(rf"(?i)(?<!\w){escaped}(?P<possessive>'s|\u2019s|\u2019)?(?!\w)")
        compiled.append(
            {
                "pattern": pattern,
                "replacement": pronunciation_value,
                "normalized": candidate.get("normalized") or token_value,
                "token": candidate.get("token") or token_value,
            }
        )

    return compiled


def compile_heteronym_sentence_rules(
    overrides: Optional[Iterable[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    if not overrides:
        return []

    compiled: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for entry in overrides:
        if not isinstance(entry, Mapping):
            continue
        sentence = str(entry.get("sentence") or "").strip()
        if not sentence:
            continue
        choice = str(entry.get("choice") or "").strip()
        if not choice:
            continue

        replacement_sentence = ""
        options = entry.get("options")
        if isinstance(options, list):
            for opt in options:
                if not isinstance(opt, Mapping):
                    continue
                if str(opt.get("key") or "").strip() == choice:
                    replacement_sentence = str(opt.get("replacement_sentence") or "").strip()
                    break
        if not replacement_sentence:
            continue

        rule_key = f"{sentence}\n{choice}".casefold()
        if rule_key in seen:
            continue
        seen.add(rule_key)

        parts = [p for p in re.split(r"\s+", sentence) if p]
        if not parts:
            continue
        pattern_text = r"\s+".join(re.escape(p) for p in parts)
        pattern = re.compile(pattern_text)
        compiled.append({"pattern": pattern, "replacement": replacement_sentence})

    compiled.sort(key=lambda item: len(item["pattern"].pattern), reverse=True)
    return compiled


def apply_heteronym_sentence_rules(text: str, rules: List[Dict[str, Any]]) -> str:
    if not text or not rules:
        return text
    result = text
    for rule in rules:
        pattern = rule["pattern"]
        replacement = rule["replacement"]
        result = pattern.sub(replacement, result)
    return result


def apply_pronunciation_rules(
    text: str,
    rules: List[Dict[str, Any]],
    usage_counter: Optional[Dict[str, int]] = None,
) -> str:
    if not text or not rules:
        return text

    result = text
    for rule in rules:
        pattern = rule["pattern"]
        pronunciation_value = rule["replacement"]
        usage_key = str(rule.get("normalized") or "").strip()

        def _replacement(match: re.Match[str]) -> str:
            suffix = match.group("possessive") or ""
            if usage_counter is not None and usage_key:
                usage_counter[usage_key] = usage_counter.get(usage_key, 0) + 1
            return pronunciation_value + suffix

        result = pattern.sub(_replacement, result)

    return result


def merge_pronunciation_overrides(job: Any) -> List[Dict[str, Any]]:
    """Return pronunciation override entries, ensuring manual overrides are included.

    Pending jobs keep both ``manual_overrides`` and ``pronunciation_overrides``, but the
    latter can be stale if the UI didn't resync before enqueue. During conversion,
    we must merge manual overrides so they always apply (before TTS).

    Precedence: manual overrides win over existing entries for the same normalized key.
    """

    collected: Dict[str, Dict[str, Any]] = {}

    existing = getattr(job, "pronunciation_overrides", None)
    if isinstance(existing, list):
        for entry in existing:
            if not isinstance(entry, Mapping):
                continue
            token_value = str(entry.get("token") or "").strip()
            pronunciation_value = str(entry.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = str(entry.get("normalized") or "").strip() or normalize_entity_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(entry.get("voice") or "").strip() or None,
                "notes": str(entry.get("notes") or "").strip() or None,
                "context": str(entry.get("context") or "").strip() or None,
                "source": str(entry.get("source") or "pronunciation"),
                "language": getattr(job, "language", None),
            }

    speakers = getattr(job, "speakers", None)
    if isinstance(speakers, dict):
        for payload in speakers.values():
            if not isinstance(payload, Mapping):
                continue
            token_value = str(payload.get("token") or "").strip()
            pronunciation_value = str(payload.get("pronunciation") or "").strip()
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
                    payload.get("resolved_voice")
                    or payload.get("voice")
                    or getattr(job, "voice", "")
                ).strip()
                or None,
                "notes": None,
                "context": None,
                "source": "speaker",
                "language": getattr(job, "language", None),
            }

    manual = getattr(job, "manual_overrides", None)
    if isinstance(manual, list):
        for entry in manual:
            if not isinstance(entry, Mapping):
                continue
            token_value = str(entry.get("token") or "").strip()
            pronunciation_value = str(entry.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = str(entry.get("normalized") or "").strip() or normalize_manual_override_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(entry.get("voice") or "").strip() or None,
                "notes": str(entry.get("notes") or "").strip() or None,
                "context": str(entry.get("context") or "").strip() or None,
                "source": str(entry.get("source") or "manual"),
                "language": getattr(job, "language", None),
            }

    return list(collected.values())
