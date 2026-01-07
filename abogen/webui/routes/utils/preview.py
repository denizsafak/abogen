import io
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import numpy as np
import soundfile as sf
from flask import current_app, send_file
from flask.typing import ResponseReturnValue


SPLIT_PATTERN = r"\n+"
SAMPLE_RATE = 24000

_preview_pipelines: Dict[Tuple[str, str], Any] = {}
_preview_pipeline_lock = threading.Lock()


def _select_device() -> str:
    import platform

    system = platform.system()
    if system == "Darwin" and platform.processor() == "arm":
        return "mps"
    return "cuda"


def _to_float32(audio_segment) -> np.ndarray:
    if audio_segment is None:
        return np.zeros(0, dtype="float32")

    tensor = audio_segment
    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        try:
            tensor = tensor.cpu()
        except Exception:
            pass
    if hasattr(tensor, "numpy"):
        return np.asarray(tensor.numpy(), dtype="float32").reshape(-1)
    return np.asarray(tensor, dtype="float32").reshape(-1)

def get_preview_pipeline(language: str, device: str) -> Any:
    key = (language, device)
    with _preview_pipeline_lock:
        pipeline = _preview_pipelines.get(key)
        if pipeline is not None:
            return pipeline
        from abogen.utils import load_numpy_kpipeline

        _, KPipeline = load_numpy_kpipeline()
        pipeline = KPipeline(lang_code=language, repo_id="hexgrad/Kokoro-82M", device=device)
        _preview_pipelines[key] = pipeline
        return pipeline

def generate_preview_audio(
    text: str,
    voice_spec: str,
    language: str,
    speed: float,
    use_gpu: bool,
    tts_provider: str = "kokoro",
    supertonic_total_steps: int = 5,
    max_seconds: float = 8.0,
    pronunciation_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
    manual_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
    speakers: Optional[Mapping[str, Any]] = None,
) -> bytes:
    if not text.strip():
        raise ValueError("Preview text is required")

    provider = (tts_provider or "kokoro").strip().lower()

    # Apply pronunciation/manual overrides first so tokens like `Unfu*k` still match
    # before any downstream normalization potentially strips punctuation.
    source_text = text
    if pronunciation_overrides or manual_overrides or speakers:
        try:
            from abogen.webui import conversion_runner as runner

            class _PreviewJob:
                def __init__(self):
                    self.language = language
                    self.voice = voice_spec
                    self.speakers = speakers
                    self.manual_overrides = list(manual_overrides or [])
                    self.pronunciation_overrides = list(pronunciation_overrides or [])

            job = _PreviewJob()
            merged = runner._merge_pronunciation_overrides(job)
            rules = runner._compile_pronunciation_rules(merged)
            source_text = runner._apply_pronunciation_rules(source_text, rules)
        except Exception:
            current_app.logger.exception("Preview override application failed; using raw text")
            source_text = text

    normalized_text = source_text
    if provider != "supertonic":
        try:
            from abogen.kokoro_text_normalization import normalize_for_pipeline

            normalized_text = normalize_for_pipeline(source_text)
        except Exception:
            current_app.logger.exception("Preview normalization failed; using raw text")
            normalized_text = source_text

    if provider == "supertonic":
        from abogen.tts_supertonic import SupertonicPipeline

        pipeline = SupertonicPipeline(sample_rate=SAMPLE_RATE, auto_download=True, total_steps=supertonic_total_steps)
        segments = pipeline(
            normalized_text,
            voice=voice_spec,
            speed=speed,
            split_pattern=SPLIT_PATTERN,
            total_steps=supertonic_total_steps,
        )
    else:
        device = "cpu"
        if use_gpu:
            try:
                device = _select_device()
            except Exception:
                device = "cpu"
                use_gpu = False

        pipeline = get_preview_pipeline(language, device)
        if pipeline is None:
            raise RuntimeError("Preview pipeline is unavailable")

        voice_choice: Any = voice_spec
        if voice_spec and "*" in voice_spec:
            from abogen.voice_formulas import get_new_voice

            voice_choice = get_new_voice(pipeline, voice_spec, use_gpu)

        segments = pipeline(
            normalized_text,
            voice=voice_choice,
            speed=speed,
            split_pattern=SPLIT_PATTERN,
        )

    audio_chunks: List[np.ndarray] = []
    accumulated = 0
    max_samples = int(max(1.0, max_seconds) * SAMPLE_RATE)

    for segment in segments:
        graphemes = getattr(segment, "graphemes", "").strip()
        if not graphemes:
            continue
        audio = _to_float32(getattr(segment, "audio", None))
        if audio.size == 0:
            continue
        remaining = max_samples - accumulated
        if remaining <= 0:
            break
        if audio.shape[0] > remaining:
            audio = audio[:remaining]
        audio_chunks.append(audio)
        accumulated += audio.shape[0]
        if accumulated >= max_samples:
            break

    if not audio_chunks:
        raise RuntimeError("Preview could not be generated")

    audio_data = np.concatenate(audio_chunks)
    buffer = io.BytesIO()
    sf.write(buffer, audio_data, SAMPLE_RATE, format="WAV")
    return buffer.getvalue()

def synthesize_preview(
    text: str,
    voice_spec: str,
    language: str,
    speed: float,
    use_gpu: bool,
    tts_provider: str = "kokoro",
    supertonic_total_steps: int = 5,
    max_seconds: float = 8.0,
    pronunciation_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
    manual_overrides: Optional[Iterable[Mapping[str, Any]]] = None,
    speakers: Optional[Mapping[str, Any]] = None,
) -> ResponseReturnValue:
    try:
        audio_bytes = generate_preview_audio(
            text=text,
            voice_spec=voice_spec,
            language=language,
            speed=speed,
            use_gpu=use_gpu,
            tts_provider=tts_provider,
            supertonic_total_steps=supertonic_total_steps,
            max_seconds=max_seconds,
            pronunciation_overrides=pronunciation_overrides,
            manual_overrides=manual_overrides,
            speakers=speakers,
        )
    except Exception as e:
        raise e

    buffer = io.BytesIO(audio_bytes)
    response = send_file(
        buffer,
        mimetype="audio/wav",
        as_attachment=False,
        download_name="speaker_preview.wav",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
