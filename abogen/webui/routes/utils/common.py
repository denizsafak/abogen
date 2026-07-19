from typing import Any, Optional, Tuple, Iterable, List, Mapping
from pathlib import Path

from abogen.domain.settings_core import coerce_bool, split_profile_spec  # noqa: F401


def split_speaker_spec(value: Any) -> Tuple[str, Optional[str]]:
    """Preferred alias for split_profile_spec (supports 'speaker:' and legacy 'profile:')."""
    return split_profile_spec(value)


def existing_paths(paths: Optional[Iterable[Path]]) -> List[Path]:
    if not paths:
        return []
    return [p for p in paths if p.exists()]


def extract_checkbox(form: Mapping[str, Any], name: str, default: bool) -> bool:
    """Extract a boolean checkbox value from a form-like mapping.

    Handles both multi-value forms (Flask's `getlist`) and simple mappings.
    If the checkbox name is present but has no value, it means unchecked (False).
    """
    values: List[str] = []
    getter = getattr(form, "getlist", None)
    if callable(getter):
        raw_values = getter(name)
        if raw_values:
            values = list(raw_values)
    else:
        raw_flag = form.get(name)
        if raw_flag is not None:
            values = [raw_flag]
    if values:
        return coerce_bool(values[-1], default)
    if name in form:
        return False
    return default
