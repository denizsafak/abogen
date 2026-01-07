from abogen.webui.routes.utils import preview


def test_preview_applies_manual_override_before_normalization(monkeypatch):
    # Don't run real TTS/normalization; just exercise the override stage by
    # forcing provider=kokoro and then stubbing normalize_for_pipeline.

    monkeypatch.setattr(preview, "get_preview_pipeline", lambda language, device: None)

    # Stub normalize_for_pipeline to be identity; we only care that overrides run.
    class _Norm:
        @staticmethod
        def normalize_for_pipeline(text):
            return text

    monkeypatch.setitem(__import__("sys").modules, "abogen.kokoro_text_normalization", _Norm)

    # And stub the kokoro pipeline path so generate_preview_audio won't proceed.
    # We'll instead validate by calling the override logic through generate_preview_audio
    # with provider=supertonic and stub SupertonicPipeline to capture input.
    captured = {}

    class DummyPipeline:
        def __init__(self, **kwargs):
            pass

        def __call__(self, text, **kwargs):
            captured["text"] = text
            return iter(())

    monkeypatch.setitem(__import__("sys").modules, "abogen.tts_supertonic", type("M", (), {"SupertonicPipeline": DummyPipeline}))

    try:
        preview.generate_preview_audio(
            text="He said Unfu*k loudly.",
            voice_spec="M1",
            language="en",
            speed=1.0,
            use_gpu=False,
            tts_provider="supertonic",
            manual_overrides=[{"token": "Unfu*k", "pronunciation": "Unfuck"}],
        )
    except Exception:
        # generate_preview_audio will raise because no audio chunks; that's fine.
        pass

    assert "text" in captured
    assert "Unfuck" in captured["text"]
    assert "Unfu*k" not in captured["text"]
