"""Tests for domain/settings_core.py — SETTINGS_REGISTRY contract."""

from abogen.domain.settings_core import (
    SETTINGS_REGISTRY,
    SETTING_KEYS,
    GUI_ONLY_KEYS,
    SHARED_KEYS,
    BOOLEAN_SETTINGS,
    FLOAT_SETTINGS,
    INT_SETTINGS,
    get_setting,
    validate_setting,
    settings_defaults,
    all_settings_defaults,
    coerce_bool,
    coerce_int,
    coerce_float,
    Setting,
)


class TestSettingSchema:
    def test_coerce_bool_from_str(self):
        s = Setting("x", bool, False)
        assert s.coerce("true") is True
        assert s.coerce("false") is False
        assert s.coerce("1") is True
        assert s.coerce("on") is True
        assert s.coerce(None) is False

    def test_coerce_int_with_bounds(self):
        s = Setting("x", int, 5, min_value=2, max_value=10)
        assert s.coerce(7) == 7
        assert s.coerce(1) == 2  # clamped to min
        assert s.coerce(20) == 10  # clamped to max
        assert s.coerce("abc") == 5  # fallback to default

    def test_coerce_float_with_bounds(self):
        s = Setting("x", float, 1.0, min_value=0.5, max_value=3.0)
        assert s.coerce(2.5) == 2.5
        assert s.coerce(0.1) == 0.5
        assert s.coerce(5.0) == 3.0

    def test_coerce_str_valid_values(self):
        s = Setting("x", str, "a", valid_values=("a", "b", "c"))
        assert s.coerce("a") == "a"
        assert s.coerce("b") == "b"
        assert s.coerce("x") == "a"  # invalid, fallback
        assert s.coerce("") == "a"  # empty, fallback

    def test_coerce_list(self):
        s = Setting("x", list, [])
        assert s.coerce([1, 2]) == [1, 2]
        assert s.coerce((1, 2)) == [1, 2]
        assert s.coerce(None) == []


class TestRegistry:
    def test_no_duplicate_keys(self):
        keys = [s.key for s in SETTINGS_REGISTRY]
        assert len(keys) == len(set(keys))

    def test_all_settings_have_valid_type(self):
        valid_types = {bool, int, float, str, list}
        for s in SETTINGS_REGISTRY:
            assert s.type_ in valid_types, f"{s.key} has invalid type {s.type_}"

    def test_min_less_than_max(self):
        for s in SETTINGS_REGISTRY:
            if s.min_value is not None and s.max_value is not None:
                assert s.min_value <= s.max_value, f"{s.key}: min > max"

    def test_default_matches_type(self):
        for s in SETTINGS_REGISTRY:
            default = s.default() if callable(s.default) else s.default
            if default is not None:
                assert isinstance(default, s.type_), (
                    f"{s.key}: default {default!r} is not {s.type_.__name__}"
                )

    def test_settings_excludes_gui_only(self):
        d = settings_defaults()
        for key in GUI_ONLY_KEYS:
            assert key not in d, f"gui_only key '{key}' should not be in settings_defaults()"

    def test_all_settings_includes_gui_only(self):
        d = all_settings_defaults()
        for s in SETTINGS_REGISTRY:
            assert s.key in d, f"missing key '{s.key}' in all_settings_defaults()"

    def test_coercion_consistency(self):
        """Every boolean setting should coerce 'true' to True."""
        for s in SETTINGS_REGISTRY:
            if s.type_ is bool:
                assert s.coerce("true") is True, f"{s.key} should coerce 'true' to True"


class TestValidation:
    def test_valid_output_format(self):
        ok, msg = validate_setting("output_format", "wav")
        assert ok

    def test_invalid_output_format(self):
        ok, msg = validate_setting("output_format", "xxx")
        assert not ok
        assert "xxx" in msg

    def test_valid_int_range(self):
        ok, _ = validate_setting("silence_between_chapters", 2.0)
        assert ok

    def test_invalid_int_below_min(self):
        ok, msg = validate_setting("silence_between_chapters", -1)
        assert not ok

    def test_unknown_setting(self):
        ok, msg = validate_setting("nonexistent_key", "value")
        assert not ok
        assert "Unknown" in msg
