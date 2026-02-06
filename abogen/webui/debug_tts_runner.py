from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from abogen.debug_tts_samples import MARKER_PREFIX, MARKER_SUFFIX, build_debug_epub, iter_expected_codes
from abogen.kokoro_text_normalization import normalize_for_pipeline
from abogen.normalization_settings import build_apostrophe_config
from abogen.text_extractor import extract_from_path
from abogen.voice_cache import ensure_voice_assets
from abogen.webui.conversion_runner import SAMPLE_RATE, SPLIT_PATTERN, _select_device, _to_float32, _resolve_voice, _spec_to_voice_ids
from abogen.utils import load_numpy_kpipeline


_MARKER_RE = re.compile(re.escape(MARKER_PREFIX) + r"(?P<code>[A-Z0-9_]+)" + re.escape(MARKER_SUFFIX))


@dataclass(frozen=True)
class DebugWavArtifact:
    label: str
    filename: str
    code: Optional[str] = None
    text: Optional[str] = None


def _resolve_voice_setting(value: str) -> tuple[str, Optional[str], Optional[str]]:
    """Resolve settings voice strings into a pipeline-ready voice spec.

    Supports "profile:<name>" by converting it into a concrete voice formula.
    Returns (resolved_voice_spec, profile_name, profile_language).
    """

    from abogen.webui.routes.utils.voice import resolve_voice_setting

    return resolve_voice_setting(value)


def _load_pipeline(language: str, use_gpu: bool) -> Any:
    device = "cpu"
    if use_gpu:
        device = _select_device()
    _np, KPipeline = load_numpy_kpipeline()
    return KPipeline(lang_code=language, repo_id="hexgrad/Kokoro-82M", device=device)


def _extract_cases_from_text(text: str) -> List[Tuple[str, str]]:
    raw = str(text or "")
    matches = list(_MARKER_RE.finditer(raw))
    cases: List[Tuple[str, str]] = []
    if not matches:
        return cases
    for idx, match in enumerate(matches):
        code = match.group("code")
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        snippet = raw[start:end]
        # Keep it small and predictable: collapse whitespace.
        snippet = " ".join(snippet.strip().split())
        cases.append((code, snippet))
    return cases


def _spoken_id(code: str) -> str:
    # Make IDs pronounceable and stable (avoid reading as a word).
    out: List[str] = []
    for ch in str(code or ""):
        if ch == "_":
            out.append(" ")
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    # Add spaces between alnum to encourage letter-by-letter reading.
    spaced = " ".join("".join(out).split())
    return spaced


def run_debug_tts_wavs(
    *,
    output_root: Path,
    settings: Mapping[str, Any],
    epub_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate WAV artifacts for the debug EPUB samples.

    Writes:
    - overall.wav: concatenation of all samples
    - case_<CODE>.wav: each sample rendered separately
    - manifest.json: metadata + file list
    """

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex
    run_dir = output_root / "debug" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if epub_path is None:
        epub_path = run_dir / "abogen_debug_samples.epub"
        build_debug_epub(epub_path)
    else:
        epub_path = Path(epub_path)

    extraction = extract_from_path(epub_path)
    combined_text = extraction.combined_text or "\n\n".join((c.text or "") for c in extraction.chapters)
    cases = _extract_cases_from_text(combined_text)

    # Prefer the canonical sample catalog for text (EPUB extraction may include headings).
    try:
        from abogen.debug_tts_samples import DEBUG_TTS_SAMPLES

        sample_text_by_code = {sample.code: sample.text for sample in DEBUG_TTS_SAMPLES}
    except Exception:
        sample_text_by_code = {}

    expected = list(iter_expected_codes())
    found_codes = {code for code, _ in cases}
    missing = [code for code in expected if code not in found_codes]
    if missing:
        raise RuntimeError(f"Debug EPUB missing expected codes: {', '.join(missing)}")

    language = str(settings.get("language") or "a").strip() or "a"
    # Kokoro's KPipeline expects short language codes like "a" (American English),
    # but older settings may store ISO-like values such as "en".
    language_aliases = {
        "en": "a",
        "en-us": "a",
        "en_us": "a",
        "en-gb": "b",
        "en_gb": "b",
        "es": "e",
        "es-es": "e",
        "fr": "f",
        "fr-fr": "f",
        "hi": "h",
        "it": "i",
        "pt": "p",
        "pt-br": "p",
        "ja": "j",
        "jp": "j",
        "zh": "z",
        "zh-cn": "z",
    }
    language = language_aliases.get(language.lower(), language)
    voice_spec = str(settings.get("default_voice") or "").strip()
    use_gpu = bool(settings.get("use_gpu", False))
    speed = float(settings.get("default_speed", 1.0) or 1.0)

    # Settings may store "profile:<name>" which is not a Kokoro voice ID.
    # Resolve it to a concrete voice formula (e.g. "af_heart*0.5+...") so Kokoro
    # doesn't attempt to download a non-existent "voices/profile:<name>.pt".
    try:
        resolved_voice, _profile_name, profile_language = _resolve_voice_setting(voice_spec)
        if resolved_voice:
            voice_spec = resolved_voice
        if profile_language:
            language = str(profile_language).strip() or language
    except Exception:
        # Voice profile resolution is best-effort; fall back to raw voice_spec.
        pass

    # Best-effort voice caching (only for known Kokoro internal voices).
    voice_ids = _spec_to_voice_ids(voice_spec)
    if voice_ids:
        try:
            ensure_voice_assets(voice_ids)
        except Exception:
            # Network / optional dependency variance; debug runner can still proceed.
            pass

    pipeline = _load_pipeline(language, use_gpu)
    voice_choice = _resolve_voice(pipeline, voice_spec, use_gpu)

    apostrophe_config = build_apostrophe_config(settings=settings)
    normalization_settings = dict(settings)

    artifacts: List[DebugWavArtifact] = []

    overall_path = run_dir / "overall.wav"
    overall_audio: List[np.ndarray] = []

    def synth(text: str, *, apply_normalization: bool = True) -> np.ndarray:
        normalized = (
            normalize_for_pipeline(
                text,
                config=apostrophe_config,
                settings=normalization_settings,
            )
            if apply_normalization
            else str(text or "")
        )
        parts: List[np.ndarray] = []
        for segment in pipeline(
            normalized,
            voice=voice_choice,
            speed=speed,
            split_pattern=SPLIT_PATTERN,
        ):
            audio = _to_float32(getattr(segment, "audio", None))
            if audio.size:
                parts.append(audio)
        if not parts:
            return np.zeros(0, dtype="float32")
        return np.concatenate(parts).astype("float32", copy=False)

    pause_1s = np.zeros(int(1.0 * SAMPLE_RATE), dtype="float32")
    between_cases = np.zeros(int(0.35 * SAMPLE_RATE), dtype="float32")

    # Per sample
    for code, snippet in cases:
        snippet = sample_text_by_code.get(code, snippet)
        if not snippet:
            continue
        id_audio = synth(_spoken_id(code), apply_normalization=False)
        text_audio = synth(snippet, apply_normalization=True)
        audio = np.concatenate([id_audio, pause_1s, text_audio]).astype("float32", copy=False)
        filename = f"case_{code}.wav"
        path = run_dir / filename
        # Write float32 PCM WAV.
        import soundfile as sf

        sf.write(path, audio, SAMPLE_RATE, subtype="FLOAT")
        artifacts.append(DebugWavArtifact(label=f"{code}", filename=filename, code=code, text=snippet))
        overall_audio.append(audio)
        overall_audio.append(between_cases)

    # Overall
    if overall_audio:
        combined = np.concatenate(overall_audio).astype("float32", copy=False)
    else:
        combined = np.zeros(0, dtype="float32")
    import soundfile as sf

    sf.write(overall_path, combined, SAMPLE_RATE, subtype="FLOAT")
    artifacts.insert(0, DebugWavArtifact(label="Overall", filename="overall.wav", code=None, text=None))

    manifest = {
        "run_id": run_id,
        "epub": str(epub_path),
        "artifacts": [artifact.__dict__ for artifact in artifacts],
        "sample_rate": SAMPLE_RATE,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
