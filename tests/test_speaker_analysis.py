from abogen.speaker_analysis import analyze_speakers


def _chapters():
    return [
        {
            "id": "0001",
            "index": 0,
            "title": "Test",
            "text": "",
            "enabled": True,
        }
    ]


def _chunk(text: str, idx: int) -> dict:
    return {
        "id": f"chunk-{idx}",
        "chapter_index": 0,
        "chunk_index": idx,
        "text": text,
    }


def test_analyze_speakers_infers_gender_from_pronouns():
    chunks = [
        _chunk("\"Greetings,\" said John. He adjusted his hat as he smiled.", 0),
        _chunk("\"Hello,\" said Mary. She straightened her dress as she introduced herself.", 1),
        _chunk("\"Nice to meet you,\" said Alex.", 2),
    ]

    analysis = analyze_speakers(_chapters(), chunks, threshold=1, max_speakers=0)

    john = analysis.speakers.get("john")
    mary = analysis.speakers.get("mary")
    alex = analysis.speakers.get("alex")

    assert john is not None
    assert mary is not None
    assert alex is not None

    assert john.gender == "male"
    assert mary.gender == "female"
    assert alex.gender == "unknown"


def test_analyze_speakers_ignores_leading_stopwords():
    chunks = [
        _chunk('But Volescu said, "We march at dawn."', 0),
        _chunk('Then Blue Leader shouted, "Hold the perimeter."', 1),
    ]

    analysis = analyze_speakers(_chapters(), chunks, threshold=1, max_speakers=0)

    speakers = analysis.speakers
    assert "volescu" in speakers
    assert speakers["volescu"].label == "Volescu"
    assert "blue_leader" in speakers
    assert speakers["blue_leader"].label == "Blue Leader"
    assert "but_volescu" not in speakers
    assert "then_blue_leader" not in speakers


def test_analyze_speakers_applies_threshold_suppression():
    chunks = [
        _chunk("\"Hello there,\" said Narrator.", 0),
        _chunk("\"It is lying,\" said Green.", 1),
    ]

    analysis = analyze_speakers(_chapters(), chunks, threshold=3, max_speakers=0)

    green = analysis.speakers.get("green")
    assert green is not None
    assert green.suppressed is True
    assert "green" in analysis.suppressed


def test_sample_excerpt_includes_context_paragraphs():
    chunks = [
        _chunk("The hallway was quiet as footsteps approached.", 0),
        _chunk('\"Open the door,\" said John as he reached for the handle.', 1),
        _chunk("Mary watched him closely, unsure of his intent.", 2),
    ]

    analysis = analyze_speakers(_chapters(), chunks, threshold=1, max_speakers=0)

    john = analysis.speakers.get("john")
    assert john is not None
    assert john.sample_quotes, "Expected John to have at least one sample quote"
    excerpt = john.sample_quotes[0]["excerpt"]
    assert "The hallway was quiet" in excerpt
    assert "\"Open the door,\" said John" in excerpt
    assert "Mary watched him closely" in excerpt
