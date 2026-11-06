"""Pure scheduling policy for automatic status refresh."""

from __future__ import annotations

AUTO_REFRESH_FLOOR_S = 300
AUTO_REFRESH_RECOMMENDED_S = 900
AUTO_REFRESH_MAX_S = 86_400
AUTO_REFRESH_JITTER_S = 60
AUTO_REFRESH_BACKOFF_CAP_S = 3_600


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
