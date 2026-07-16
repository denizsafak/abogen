from __future__ import annotations

"""Progress and ETR (estimated time remaining) calculation.

Shared by Web UI and PyQt desktop GUI. Pure math, no UI dependencies.
"""
import time
from dataclasses import dataclass, field


@dataclass
class ProgressTracker:
    """Tracks character-based progress with ETR calculation.

    Usage:
        tracker = ProgressTracker(total_chars=50000)
        # ... as processing occurs:
        tracker.update(chars_done=5000)
        print(tracker.etr_str)   # "00:04:30"
        print(tracker.percent)   # 10
    """
    total_chars: int
    _start_time: float = field(default_factory=time.time, repr=False)
    _chars_done: int = field(default=0, repr=False)

    def update(self, chars_done: int) -> None:
        self._chars_done = chars_done

    @property
    def percent(self) -> int:
        if self.total_chars <= 0:
            return 0
        return min(int(self._chars_done / self.total_chars * 100), 99)

    @property
    def etr_str(self) -> str:
        elapsed = time.time() - self._start_time
        if self._chars_done <= 0 or elapsed <= 0.5:
            return "Processing..."
        avg_time_per_char = elapsed / self._chars_done
        remaining = self.total_chars - self._chars_done
        if remaining <= 0:
            return "00:00:00"
        secs = avg_time_per_char * remaining
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


def calc_etr_str(elapsed: float, done: int, total: int) -> str:
    """Standalone ETR string calculation (matches PyQt original logic).

    Args:
        elapsed: seconds since processing started
        done: items/characters processed so far
        total: total items/characters to process

    Returns:
        ETR string like "01:23:45" or "Processing..."
    """
    if done <= 0 or elapsed <= 0.5:
        return "Processing..."
    avg_time_per_item = elapsed / done
    remaining = total - done
    if remaining <= 0:
        return "00:00:00"
    secs = avg_time_per_item * remaining
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
