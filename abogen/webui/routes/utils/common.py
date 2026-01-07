from typing import Any, Optional, Tuple, Iterable, List
from pathlib import Path

def split_profile_spec(value: Any) -> Tuple[str, Optional[str]]:
    text = str(value or "").strip()
    if not text:
        return "", None
    lowered = text.lower()
    if lowered.startswith("profile:") or lowered.startswith("speaker:"):
        _, _, remainder = text.partition(":")
        name = remainder.strip()
        return "", name or None
    return text, None


def split_speaker_spec(value: Any) -> Tuple[str, Optional[str]]:
    """Preferred alias for split_profile_spec (supports 'speaker:' and legacy 'profile:')."""

    return split_profile_spec(value)

def existing_paths(paths: Optional[Iterable[Path]]) -> List[Path]:
    if not paths:
        return []
    return [p for p in paths if p.exists()]
