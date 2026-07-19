"""Tests for voice_formulas.py — pairs_to_formula."""

from abogen.voice_formulas import pairs_to_formula


class TestPairsToFormula:
    def test_basic_pair(self):
        result = pairs_to_formula([("A", 1.0), ("B", 1.0)])
        assert result == "A*0.5+B*0.5"

    def test_unequal_weights(self):
        result = pairs_to_formula([("A", 3.0), ("B", 1.0)])
        assert result == "A*0.75+B*0.25"

    def test_single_voice(self):
        result = pairs_to_formula([("A", 1.0)])
        assert result == "A*1"

    def test_filters_zero_weight(self):
        result = pairs_to_formula([("A", 1.0), ("B", 0.0)])
        assert result == "A*1"

    def test_all_zero_returns_none(self):
        result = pairs_to_formula([("A", 0.0), ("B", 0.0)])
        assert result is None

    def test_empty_returns_none(self):
        result = pairs_to_formula([])
        assert result is None

    def test_none_values_filtered(self):
        result = pairs_to_formula([("A", 1.0), ("B", None)])
        assert result is not None

    def test_weight_normalization(self):
        result = pairs_to_formula([("A", 2.0), ("B", 2.0)])
        assert result == "A*0.5+B*0.5"

    def test_three_voices(self):
        result = pairs_to_formula([("A", 1.0), ("B", 1.0), ("C", 1.0)])
        assert "A*" in result
        assert "B*" in result
        assert "C*" in result
        assert "+" in result
