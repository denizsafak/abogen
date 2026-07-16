from __future__ import annotations

import time
from unittest.mock import patch

from abogen.domain.progress import ProgressTracker, calc_etr_str


class TestCalcEtrStr:
    def test_returns_processing_when_not_started(self):
        assert calc_etr_str(0.0, 0, 100) == "Processing..."

    def test_returns_processing_when_elapsed_too_short(self):
        assert calc_etr_str(0.3, 50, 100) == "Processing..."

    def test_returns_processing_when_done_zero(self):
        assert calc_etr_str(2.0, 0, 100) == "Processing..."

    def test_returns_zero_when_complete(self):
        assert calc_etr_str(10.0, 100, 100) == "00:00:00"

    def test_returns_zero_when_overcomplete(self):
        assert calc_etr_str(10.0, 150, 100) == "00:00:00"

    def test_half_done(self):
        # 10s for 50 chars -> 10s remaining -> 00:00:10
        assert calc_etr_str(10.0, 50, 100) == "00:00:10"

    def test_one_third_done_large(self):
        # 100s for 1000 chars out of 3000 -> 200s remaining
        assert calc_etr_str(100.0, 1000, 3000) == "00:03:20"

    def test_hours_format(self):
        # 3600s for 1000 chars out of 4000 -> 3 * 3600 = 10800s remaining
        assert calc_etr_str(3600.0, 1000, 4000) == "03:00:00"

    def test_minutes_and_seconds(self):
        # 60s for 100 chars out of 200 -> 60s remaining
        assert calc_etr_str(60.0, 100, 200) == "00:01:00"


class TestProgressTracker:
    def test_percent_at_zero(self):
        t = ProgressTracker(total_chars=1000)
        assert t.percent == 0

    def test_percent_half(self):
        t = ProgressTracker(total_chars=1000)
        t.update(500)
        assert t.percent == 50

    def test_percent_capped_at_99(self):
        t = ProgressTracker(total_chars=100)
        t.update(100)
        assert t.percent == 99  # matches original behavior

    def test_etr_processing_at_start(self):
        t = ProgressTracker(total_chars=1000)
        t.update(0)
        assert t.etr_str == "Processing..."

    def test_etr_computes_correctly(self):
        t = ProgressTracker(total_chars=200)
        with patch("abogen.domain.progress.time") as mock_time:
            mock_time.time.return_value = t._start_time + 2.0
            t.update(100)
            assert t.etr_str == "00:00:02"

    def test_zero_total_chars(self):
        t = ProgressTracker(total_chars=0)
        assert t.percent == 0
