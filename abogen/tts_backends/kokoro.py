def load_numpy_kpipeline():
    import numpy as np
    from kokoro import KPipeline  # type: ignore[import-not-found]

    return np, KPipeline


def create_kokoro_backend(**kwargs):
    """Create a Kokoro TTS backend instance.

    Args:
        lang_code: Language code (e.g. "a" for American English).
        repo_id: HuggingFace repo id. Defaults to "hexgrad/Kokoro-82M".
        device: Device to use ("cpu", "cuda", "mps"). Defaults to "cpu".

    Returns:
        KPipeline instance.
    """
    _np, KPipeline = load_numpy_kpipeline()
    return KPipeline(
        lang_code=kwargs["lang_code"],
        repo_id=kwargs.get("repo_id", "hexgrad/Kokoro-82M"),
        device=kwargs.get("device", "cpu"),
    )


from abogen.tts_backend import TTSBackendMetadata
from abogen.tts_backend_registry import register_backend

register_backend(
    metadata=TTSBackendMetadata(
        id="kokoro",
        name="Kokoro",
        description="Kokoro TTS engine",
    ),
    factory=create_kokoro_backend,
)
