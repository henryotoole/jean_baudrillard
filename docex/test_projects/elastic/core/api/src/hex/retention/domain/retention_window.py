"""RetentionWindow — value object for how long a processed ping is kept.

A processed ping older than the window is eligible for pruning. The
window is a positive whole number of days; zero or negative is invalid
(it would prune everything, including just-processed rows).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetentionWindow:
    days: int

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError(f"retention window must be positive, got {self.days!r}")

    def cutoff(self, now: datetime) -> datetime:
        """The instant before which a processed ping is eligible to prune."""
        return now - timedelta(days=self.days)
