import re
from typing import Iterable, List, Optional, Tuple

from abogen.tts_plugin.utils import get_voices


# Calls parsing and loads the voice to gpu or cpu
def get_new_voice(pipeline, formula, use_gpu):
    try:
        weighted_voice = parse_voice_formula(pipeline, formula)
        # device = "cuda" if use_gpu else "cpu"
        # Setting the device "cuda" gives "Error occurred: split_with_sizes(): argument 'split_sizes' (position 2)"
        # error when the device is gpu. So disabling this for now.
        device = "cpu"
        return weighted_voice.to(device)
    except Exception as e:
        raise ValueError(f"Failed to create voice: {str(e)}")


def parse_formula_terms(formula: str) -> List[Tuple[str, float]]:
    if not formula or not formula.strip():
        raise ValueError("Empty voice formula")

    terms: List[Tuple[str, float]] = []
    kokoro_voices = get_voices("kokoro")
    for segment in formula.split("+"):
        part = segment.strip()
        if not part:
            continue
        if "*" not in part:
            raise ValueError("Each component must be in the form voice*weight")
        voice_name, raw_weight = part.split("*", 1)
        voice_name = voice_name.strip()
        if voice_name not in kokoro_voices:
            raise ValueError(f"Unknown voice: {voice_name}")
        try:
            weight = float(raw_weight.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid weight for {voice_name}") from exc
        if weight <= 0:
            raise ValueError(f"Weight for {voice_name} must be positive")
        terms.append((voice_name, weight))

    if not terms:
        raise ValueError("Voice weights must sum to a positive value")

    return terms


def parse_voice_formula(pipeline, formula):
    terms = parse_formula_terms(formula)

    total_weight = sum(weight for _, weight in terms)
    if total_weight <= 0:
        raise ValueError("Voice weights must sum to a positive value")

    weighted_sum = None

    for voice_name, weight in terms:
        normalized_weight = weight / total_weight if total_weight > 0 else weight

        voice_tensor = pipeline.load_single_voice(voice_name)

        if weighted_sum is None:
            weighted_sum = normalized_weight * voice_tensor
        else:
            weighted_sum += normalized_weight * voice_tensor

    if weighted_sum is None:
        raise ValueError("Voice formula produced no components")

    return weighted_sum


def pairs_to_formula(pairs: Iterable[Tuple[str, float]]) -> Optional[str]:
    """Build a voice formula string from (voice_name, weight) pairs.

    Normalizes weights to sum to 1.0 and formats as "voice1*0.5+voice2*0.5".

    Args:
        pairs: Iterable of (voice_name, weight) tuples. Zero-weight entries
            are filtered out.

    Returns:
        Formula string, or None if no valid entries.
    """
    voices = [(voice, float(weight)) for voice, weight in pairs if weight is not None and float(weight) > 0]
    if not voices:
        return None
    total = sum(weight for _, weight in voices)
    if total <= 0:
        return None

    def _format_value(value: float) -> str:
        normalized = value / total if total else 0.0
        return (f"{normalized:.4f}").rstrip("0").rstrip(".") or "0"

    parts = [f"{voice}*{_format_value(weight)}" for voice, weight in voices]
    return "+".join(parts)


def calculate_sum_from_formula(formula):
    weights = re.findall(r"\* *([\d.]+)", formula)
    total_sum = sum(float(weight) for weight in weights)
    return total_sum


def extract_voice_ids(formula: str) -> List[str]:
    return [voice for voice, _ in parse_formula_terms(formula)]
