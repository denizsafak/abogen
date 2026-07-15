from abogen.domain.chunk_utils import chunk_text_for_tts


def test_chunk_text_for_tts_prefers_text_over_normalized_text():
    entry = {
        # Simulate a pre-normalized chunk that lost the asterisk.
        "normalized_text": "Unfuk",
        # Raw chunk should preserve censored token for manual overrides.
        "text": "Unfu*k",
    }

    assert chunk_text_for_tts(entry) == "Unfu*k"


def test_chunk_text_for_tts_falls_back_to_original_text_then_normalized_text():
    entry = {
        "original_text": "Hello * world",
        "normalized_text": "Hello world",
    }
    assert chunk_text_for_tts(entry) == "Hello * world"

    entry2 = {
        "normalized_text": "Only normalized",
    }
    assert chunk_text_for_tts(entry2) == "Only normalized"
