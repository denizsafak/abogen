from abogen.webui import conversion_runner


class DummyJob:
    def __init__(self):
        self.language = "en"
        self.voice = "M1"
        self.speakers = None
        self.manual_overrides = []
        self.pronunciation_overrides = []


def _apply(text: str, job: DummyJob) -> str:
    merged = conversion_runner._merge_pronunciation_overrides(job)
    rules = conversion_runner._compile_pronunciation_rules(merged)
    return conversion_runner._apply_pronunciation_rules(text, rules)


def test_manual_override_is_applied_even_if_pronunciation_overrides_stale():
    job = DummyJob()
    job.manual_overrides = [
        {
            "token": "Unfu*k",
            "pronunciation": "Unfuck",
        }
    ]

    out = _apply("He said Unfu*k loudly.", job)
    assert "Unfuck" in out
    assert "Unfu*k" not in out


def test_manual_override_takes_precedence_over_existing_pronunciation_override():
    job = DummyJob()
    job.pronunciation_overrides = [
        {
            "token": "Unfu*k",
            "normalized": "unfu*k",
            "pronunciation": "WRONG",
        }
    ]
    job.manual_overrides = [
        {
            "token": "Unfu*k",
            "pronunciation": "RIGHT",
        }
    ]

    out = _apply("Unfu*k.", job)
    assert "RIGHT" in out
    assert "WRONG" not in out
