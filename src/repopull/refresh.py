"""Pure scheduling policy for automatic status refresh."""

from __future__ import annotations

from dataclasses import dataclass

AUTO_REFRESH_FLOOR_S = 300
AUTO_REFRESH_RECOMMENDED_S = 900
AUTO_REFRESH_MAX_S = 86_400
AUTO_REFRESH_JITTER_S = 60
AUTO_REFRESH_BACKOFF_CAP_S = 3_600

SUSPEND_DETECT_THRESHOLD_S = 5.0
SUSPEND_POLL_INTERVAL_S = 30.0
SUSPEND_RESUME_GRACE_S = 60.0


def clamp_auto_refresh_s(seconds: int) -> int:
    """Clamp an automatic-refresh interval; 0 means off."""
    if seconds <= 0:
        return 0
    if seconds < AUTO_REFRESH_FLOOR_S:
        return AUTO_REFRESH_FLOOR_S
    if seconds > AUTO_REFRESH_MAX_S:
        return AUTO_REFRESH_MAX_S
    return seconds


def should_warn(seconds: int) -> bool:
    """True for intervals below the recommended minimum, but not off."""
    return 0 < seconds < AUTO_REFRESH_RECOMMENDED_S


def cooldown_remaining(
    last_finished: float | None,
    now: float,
    interval_s: int,
) -> float:
    """Seconds still owed before another automatic refresh is allowed."""
    if last_finished is None or interval_s <= 0:
        return 0.0
    return max(0.0, last_finished + interval_s - now)


def next_delay(
    interval_s: int,
    failures: int,
    *,
    jitter_s: float = 0.0,
) -> float:
    """Backoff interval plus bounded jitter after a completed auto run."""
    if interval_s <= 0:
        return 0.0
    exponent = min(max(failures, 0), 6)
    cap = max(interval_s, AUTO_REFRESH_BACKOFF_CAP_S)
    delay = min(interval_s * (2**exponent), cap)
    jitter = min(max(jitter_s, 0.0), float(AUTO_REFRESH_JITTER_S))
    return float(delay + jitter)


@dataclass
class SuspendDetector:
    """Detect suspend time from the boottime-minus-monotonic offset.

    `CLOCK_BOOTTIME` includes time spent suspended; `CLOCK_MONOTONIC` does not.
    Their offset is therefore stable while awake and grows by the suspend
    duration. The first offset is a baseline, not a suspend.
    """

    offset_s: float

    def poll(
        self,
        boottime_s: float,
        monotonic_s: float,
        *,
        threshold_s: float = SUSPEND_DETECT_THRESHOLD_S,
    ) -> float:
        """Return seconds suspended since the previous poll, or 0."""
        offset = max(0.0, boottime_s - monotonic_s)
        gap = offset - self.offset_s
        self.offset_s = offset
        if gap < threshold_s:
            return 0.0
        return gap
