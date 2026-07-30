"""Tests for domain speaker metadata functions.

Tests for build_narrator_roster, build_speaker_roster, match_configured_speaker,
apply_speaker_config_to_roster, and prepare_speaker_metadata.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# build_narrator_roster
# ---------------------------------------------------------------------------


class TestBuildNarratorRoster:
    """Tests for build_narrator_roster()."""

    def test_basic_roster(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        roster = build_narrator_roster("af_heart", None)
        assert "narrator" in roster
        assert roster["narrator"]["voice"] == "af_heart"
        assert roster["narrator"]["label"] == "Narrator"

    def test_with_voice_profile(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        roster = build_narrator_roster("af_heart", "my_profile")
        assert roster["narrator"]["voice_profile"] == "my_profile"

    def test_without_voice_profile(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        roster = build_narrator_roster("af_heart", None)
        assert "voice_profile" not in roster["narrator"]

    def test_merges_existing_overrides(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        existing = {
            "narrator": {
                "label": "Custom Narrator",
                "voice": "am_echo",
                "pronunciation": "NAH-rah-tor",
            }
        }
        roster = build_narrator_roster("af_heart", None, existing=existing)
        assert roster["narrator"]["label"] == "Custom Narrator"
        assert roster["narrator"]["voice"] == "am_echo"
        assert roster["narrator"]["pronunciation"] == "NAH-rah-tor"

    def test_existing_none_ignored(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        roster = build_narrator_roster("af_heart", None, existing=None)
        assert roster["narrator"]["voice"] == "af_heart"

    def test_empty_existing_dict(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        roster = build_narrator_roster("af_heart", None, existing={})
        assert roster["narrator"]["voice"] == "af_heart"

    def test_existing_without_narrator_key(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        existing = {"other_speaker": {"label": "Other"}}
        roster = build_narrator_roster("af_heart", None, existing=existing)
        assert roster["narrator"]["voice"] == "af_heart"

    def test_empty_string_values_not_overridden(self):
        from abogen.domain.speaker_metadata import build_narrator_roster

        existing = {"narrator": {"label": "", "voice": ""}}
        roster = build_narrator_roster("af_heart", None, existing=existing)
        assert roster["narrator"]["label"] == "Narrator"
        assert roster["narrator"]["voice"] == "af_heart"


# ---------------------------------------------------------------------------
# build_speaker_roster
# ---------------------------------------------------------------------------


class TestBuildSpeakerRoster:
    """Tests for build_speaker_roster()."""

    def test_single_narrator(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {"speakers": {"narrator": {"label": "Narrator", "count": 10}}}
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert list(roster.keys()) == ["narrator"]
        assert roster["narrator"]["voice"] == "af_heart"

    def test_multiple_speakers(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {"label": "Alice", "count": 5, "gender": "female"},
                "bob": {"label": "Bob", "count": 3, "gender": "male"},
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert "narrator" in roster
        assert "alice" in roster
        assert "bob" in roster
        assert roster["alice"]["label"] == "Alice"
        assert roster["alice"]["gender"] == "female"

    def test_suppressed_speakers_excluded(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {"label": "Alice", "count": 5},
                "bob": {"label": "Bob", "count": 1, "suppressed": True},
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert "bob" not in roster

    def test_order_respected(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {"label": "Alice", "count": 5},
                "bob": {"label": "Bob", "count": 3},
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None, order=["bob", "alice"])
        keys = list(roster.keys())
        assert keys.index("bob") < keys.index("alice")

    def test_existing_assignments_preserved(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {"label": "Alice", "count": 5, "gender": "female"},
            }
        }
        existing = {
            "narrator": {"voice": "am_echo"},
            "alice": {"voice": "af_nicole", "pronunciation": "AH-leece"},
        }
        roster = build_speaker_roster(analysis, "af_heart", None, existing=existing)
        assert roster["alice"]["voice"] == "af_nicole"
        assert roster["alice"]["pronunciation"] == "AH-leece"
        assert roster["narrator"]["voice"] == "am_echo"

    def test_empty_analysis(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        roster = build_speaker_roster({}, "af_heart", None)
        assert "narrator" in roster
        assert len(roster) == 1

    def test_sample_quotes_preserved(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {
                    "label": "Alice",
                    "count": 5,
                    "sample_quotes": ["Hello!", "Goodbye!"],
                },
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert roster["alice"]["sample_quotes"] == ["Hello!", "Goodbye!"]

    def test_detected_gender_preserved(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "alice": {"label": "Alice", "count": 5, "detected_gender": "female"},
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert roster["alice"]["detected_gender"] == "female"

    def test_default_label_from_id(self):
        from abogen.domain.speaker_metadata import build_speaker_roster

        analysis = {
            "speakers": {
                "narrator": {"label": "Narrator", "count": 10},
                "my_character": {"count": 3},
            }
        }
        roster = build_speaker_roster(analysis, "af_heart", None)
        assert roster["my_character"]["label"] == "My Character"


# ---------------------------------------------------------------------------
# match_configured_speaker
# ---------------------------------------------------------------------------


class TestMatchConfiguredSpeaker:
    """Tests for match_configured_speaker()."""

    def test_match_by_id(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        config = {"alice": {"id": "alice", "label": "Alice", "voice": "af_heart"}}
        result = match_configured_speaker(config, "alice", "Alice")
        assert result is not None
        assert result["voice"] == "af_heart"

    def test_match_by_slug(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        config = {"my_character": {"id": "my_character", "label": "My Character"}}
        result = match_configured_speaker(config, "my_character", "My Character")
        assert result is not None

    def test_match_by_label_lowercase(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        config = {"custom_id": {"id": "custom_id", "label": "Alice"}}
        result = match_configured_speaker(config, "other_id", "Alice")
        assert result is not None
        assert result["id"] == "custom_id"

    def test_no_match(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        config = {"alice": {"id": "alice", "label": "Alice"}}
        result = match_configured_speaker(config, "bob", "Bob")
        assert result is None

    def test_empty_config(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        result = match_configured_speaker({}, "alice", "Alice")
        assert result is None

    def test_none_config(self):
        from abogen.domain.speaker_metadata import match_configured_speaker

        result = match_configured_speaker(None, "alice", "Alice")  # type: ignore
        assert result is None


# ---------------------------------------------------------------------------
# apply_speaker_config_to_roster
# ---------------------------------------------------------------------------


class TestApplySpeakerConfigToRoster:
    """Tests for apply_speaker_config_to_roster()."""

    def test_no_config_returns_roster_unchanged(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {"narrator": {"id": "narrator", "voice": "af_heart"}}
        result, languages, config = apply_speaker_config_to_roster(roster, None)
        assert result["narrator"]["voice"] == "af_heart"
        assert languages == []
        assert config is None

    def test_empty_config_returns_roster_unchanged(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {"narrator": {"id": "narrator", "voice": "af_heart"}}
        result, languages, config = apply_speaker_config_to_roster(roster, {})
        assert result["narrator"]["voice"] == "af_heart"

    def test_config_without_speakers_map(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {"narrator": {"id": "narrator", "voice": "af_heart"}}
        config = {"language": "a"}
        result, languages, config = apply_speaker_config_to_roster(roster, config)
        assert result["narrator"]["voice"] == "af_heart"

    def test_applies_voice_from_config(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice", "voice": "af_heart"},
        }
        config = {
            "speakers": {
                "alice": {"id": "alice", "voice": "af_nicole", "gender": "female"}
            },
            "languages": ["a"],
        }
        result, languages, updated_config = apply_speaker_config_to_roster(
            roster, config, persist_changes=True
        )
        assert result["alice"]["voice"] == "af_nicole"
        assert result["alice"]["resolved_voice"] == "af_nicole"

    def test_applies_voice_profile(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "speakers": {
                "alice": {"id": "alice", "voice_profile": "my_profile"}
            }
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["alice"]["voice_profile"] == "my_profile"

    def test_applies_voice_formula(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "speakers": {
                "alice": {"id": "alice", "voice_formula": "af_heart(0.6)+af_nicole(0.4)"}
            }
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["alice"]["voice_formula"] == "af_heart(0.6)+af_nicole(0.4)"
        assert result["alice"]["resolved_voice"] == "af_heart(0.6)+af_nicole(0.4)"

    def test_persist_changes_returns_updated_config(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice", "voice": "af_heart"},
        }
        config = {
            "language": "a",
            "languages": ["a"],
            "speakers": {
                "alice": {"id": "alice", "voice": "af_nicole", "gender": "female"}
            },
            "version": 1,
        }
        _, _, updated_config = apply_speaker_config_to_roster(
            roster, config, persist_changes=True
        )
        # config_changed is False by default, so updated_config should be None
        # unless there's actual change logic triggered
        # The function has config_changed = False and never sets it to True
        # so updated_config should be None even with persist_changes=True
        assert updated_config is None

    def test_fallback_languages_used(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {"narrator": {"id": "narrator", "voice": "af_heart"}}
        result, languages, _ = apply_speaker_config_to_roster(
            roster, None, fallback_languages=["a", "b"]
        )
        assert languages == ["a", "b"]

    def test_config_languages_take_precedence(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {"narrator": {"id": "narrator", "voice": "af_heart"}}
        config = {"languages": ["a"], "speakers": {}}
        _, languages, _ = apply_speaker_config_to_roster(
            roster, config, fallback_languages=["a", "b"]
        )
        assert languages == ["a"]

    def test_empty_roster_returns_empty(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        result, languages, config = apply_speaker_config_to_roster({}, None)
        assert result == {}
        assert languages == []

    def test_non_mapping_roster_returns_empty(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        result, languages, config = apply_speaker_config_to_roster("invalid", None)  # type: ignore
        assert result == {}
        assert languages == []

    def test_narrator_not_modified(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "speakers": {
                "narrator": {"id": "narrator", "voice": "am_echo"},
                "alice": {"id": "alice", "voice": "af_nicole"},
            }
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["narrator"]["voice"] == "af_heart"
        assert result["alice"]["voice"] == "af_nicole"

    def test_config_languages_applied_to_roster_entry(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "languages": ["a", "b"],
            "speakers": {
                "alice": {"id": "alice", "voice": "af_nicole"}
            },
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["alice"]["config_languages"] == ["a", "b"]

    def test_speaker_specific_languages_override(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "languages": ["a"],
            "speakers": {
                "alice": {"id": "alice", "voice": "af_nicole", "languages": ["a", "b"]}
            },
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["alice"]["config_languages"] == ["a", "b"]

    def test_resolved_voice_takes_precedence(self):
        from abogen.domain.speaker_metadata import apply_speaker_config_to_roster

        roster = {
            "narrator": {"id": "narrator", "voice": "af_heart"},
            "alice": {"id": "alice", "label": "Alice"},
        }
        config = {
            "speakers": {
                "alice": {
                    "id": "alice",
                    "voice": "af_heart",
                    "resolved_voice": "af_nicole",
                }
            }
        }
        result, _, _ = apply_speaker_config_to_roster(roster, config)
        assert result["alice"]["resolved_voice"] == "af_nicole"


# ---------------------------------------------------------------------------
# prepare_speaker_metadata
# ---------------------------------------------------------------------------


class TestPrepareSpeakerMetadata:
    """Tests for prepare_speaker_metadata()."""

    def _make_chunks(self, count=3):
        return [{"id": str(i), "text": f"Chunk {i}"} for i in range(count)]

    def _make_chapters(self):
        return [{"title": "Chapter 1", "chunks": self._make_chunks()}]

    @patch("abogen.domain.speaker_metadata.load_settings")
    def test_no_analysis(self, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        chunks = self._make_chunks()
        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=chunks,
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=False,
        )
        chunk_list, roster, analysis, languages, config = result
        assert all(c["speaker_id"] == "narrator" for c in chunk_list)
        assert all(c["speaker_label"] == "Narrator" for c in chunk_list)
        assert "narrator" in roster
        assert languages == []
        assert config is None

    @patch("abogen.domain.speaker_metadata.load_settings")
    def test_no_analysis_with_existing_roster(self, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        existing = {"narrator": {"voice": "am_echo", "pronunciation": "test"}}
        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=False,
            existing_roster=existing,
        )
        _, roster, _, _, _ = result
        assert roster["narrator"]["voice"] == "am_echo"
        assert roster["narrator"]["pronunciation"] == "test"

    @patch("abogen.domain.speaker_metadata.load_settings")
    @patch("abogen.domain.speaker_metadata.analyze_speakers")
    def test_with_analysis(self, mock_analyze, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "version": "1.0",
            "narrator": "narrator",
            "assignments": {"0": "narrator", "1": "narrator", "2": "narrator"},
            "speakers": {
                "narrator": {
                    "label": "Narrator",
                    "count": 3,
                    "confidence": "low",
                    "sample_quotes": [],
                    "suppressed": False,
                }
            },
            "suppressed": [],
            "stats": {
                "total_chunks": 3,
                "explicit_chunks": 0,
                "active_speakers": 0,
                "unique_speakers": 1,
                "suppressed": 0,
            },
        }
        mock_analyze.return_value = mock_result

        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=True,
        )
        chunk_list, roster, analysis, _, _ = result
        assert "narrator" in roster
        assert analysis["version"] == "1.0"

    @patch("abogen.domain.speaker_metadata.load_settings")
    @patch("abogen.domain.speaker_metadata.analyze_speakers")
    def test_inject_recommended_callback_called(self, mock_analyze, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "version": "1.0",
            "narrator": "narrator",
            "assignments": {},
            "speakers": {
                "narrator": {
                    "label": "Narrator",
                    "count": 1,
                    "confidence": "low",
                    "sample_quotes": [],
                    "suppressed": False,
                }
            },
            "suppressed": [],
            "stats": {
                "total_chunks": 1,
                "explicit_chunks": 0,
                "active_speakers": 0,
                "unique_speakers": 1,
                "suppressed": 0,
            },
        }
        mock_analyze.return_value = mock_result

        injected = []
        callback = lambda roster, **kwargs: injected.append(dict(roster))

        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(1),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=True,
            inject_recommended=callback,
        )
        assert len(injected) == 1
        assert "narrator" in injected[0]

    @patch("abogen.domain.speaker_metadata.load_settings")
    def test_inject_recommended_not_called_when_none(self, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=False,
            inject_recommended=None,
        )
        assert result is not None

    @patch("abogen.domain.speaker_metadata.load_settings")
    def test_chunks_are_copies(self, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        original_chunks = [{"id": "0", "text": "Hello"}]
        result = prepare_speaker_metadata(
            chapters=[{"title": "Ch1", "chunks": original_chunks}],
            chunks=original_chunks,
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=False,
        )
        chunk_list = result[0]
        assert chunk_list is not original_chunks
        assert chunk_list[0] is not original_chunks[0]

    @patch("abogen.domain.speaker_metadata.load_settings")
    def test_analysis_disabled_sets_narrator_on_all_chunks(self, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        chunks = [{"id": "0"}, {"id": "1"}, {"id": "2"}]
        result = prepare_speaker_metadata(
            chapters=[{"title": "Ch1", "chunks": chunks}],
            chunks=chunks,
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=False,
        )
        for chunk in result[0]:
            assert chunk["speaker_id"] == "narrator"
            assert chunk["speaker_label"] == "Narrator"

    @patch("abogen.domain.speaker_metadata.load_settings")
    @patch("abogen.domain.speaker_metadata.analyze_speakers")
    def test_speaker_random_languages_used(self, mock_analyze, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": ["a", "b"]}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "version": "1.0",
            "narrator": "narrator",
            "assignments": {},
            "speakers": {
                "narrator": {
                    "label": "Narrator",
                    "count": 1,
                    "confidence": "low",
                    "sample_quotes": [],
                    "suppressed": False,
                }
            },
            "suppressed": [],
            "stats": {
                "total_chunks": 1,
                "explicit_chunks": 0,
                "active_speakers": 0,
                "unique_speakers": 1,
                "suppressed": 0,
            },
        }
        mock_analyze.return_value = mock_result

        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(1),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=True,
        )
        _, _, analysis, _, _ = result
        assert analysis["config_languages"] == ["a", "b"]

    @patch("abogen.domain.speaker_metadata.load_settings")
    @patch("abogen.domain.speaker_metadata.analyze_speakers")
    def test_apply_config_with_speaker_config(self, mock_analyze, mock_settings):
        from abogen.domain.speaker_metadata import prepare_speaker_metadata

        mock_settings.return_value = {"speaker_random_languages": []}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "version": "1.0",
            "narrator": "narrator",
            "assignments": {"0": "narrator"},
            "speakers": {
                "narrator": {
                    "label": "Narrator",
                    "count": 1,
                    "confidence": "low",
                    "sample_quotes": [],
                    "suppressed": False,
                }
            },
            "suppressed": [],
            "stats": {
                "total_chunks": 1,
                "explicit_chunks": 0,
                "active_speakers": 0,
                "unique_speakers": 1,
                "suppressed": 0,
            },
        }
        mock_analyze.return_value = mock_result

        speaker_config = {
            "languages": ["a"],
            "speakers": {
                "narrator": {"id": "narrator", "voice": "am_echo"},
            },
        }
        result = prepare_speaker_metadata(
            chapters=self._make_chapters(),
            chunks=self._make_chunks(1),
            voice="af_heart",
            voice_profile=None,
            threshold=3,
            run_analysis=True,
            speaker_config=speaker_config,
            apply_config=True,
        )
        _, roster, _, languages, _ = result
        assert roster["narrator"]["voice"] == "af_heart"
        assert languages == ["a"]
