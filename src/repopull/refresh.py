"""Pure scheduling policy for automatic status refresh."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

AUTO_REFRESH_FLOOR_S = 300
AUTO_REFRESH_RECOMMENDED_S = 900
AUTO_REFRESH_MAX_S = 86_400
AUTO_REFRESH_JITTER_S = 60
AUTO_REFRESH_BACKOFF_CAP_S = 3_600
AUTO_REFRESH_IN_FLIGHT_RETRY_S = 60.0

SUSPEND_DETECT_THRESHOLD_S = 5.0
SUSPEND_POLL_INTERVAL_S = 30.0
SUSPEND_RESUME_GRACE_S = 60.0

NETWORK_RETRY_DELAYS_S = (120.0, 300.0, 900.0, 1_800.0, 3_600.0)


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
    network: bool = False,
) -> float:
    """Backoff interval plus bounded jitter after a completed auto run.

    Network failures use their own short-first ladder: two minutes, then five,
    fifteen, thirty, and one hour. This lets a reconnect resume quickly without
    hammering a long outage every normal refresh interval.
    """
    if interval_s <= 0 and not network:
        return 0.0
    if network:
        index = min(max(failures - 1, 0), len(NETWORK_RETRY_DELAYS_S) - 1)
        delay = NETWORK_RETRY_DELAYS_S[index]
    else:
        exponent = min(max(failures, 0), 6)
        cap = max(interval_s, AUTO_REFRESH_BACKOFF_CAP_S)
        delay = min(interval_s * (2**exponent), cap)
    jitter = min(max(jitter_s, 0.0), float(AUTO_REFRESH_JITTER_S))
    return float(delay + jitter)


class RefreshEvent(Enum):
    """What just happened to the automatic-refresh timer."""

    SCHEDULE = "schedule"
    TIMER = "timer"
    SHOW = "show"


class RefreshAction(Enum):
    """What the window should do with the automatic-refresh timers."""

    STOP = "stop"
    WAIT = "wait"
    RUN = "run"


@dataclass(frozen=True, slots=True)
class RefreshState:
    """One snapshot of every input that affects an automatic-refresh decision.

    `window_available` means visible and not minimized. `interval_s` of zero
    means automatic refresh is off. `last_finished` and `now` use the same
    monotonic clock.
    """

    interval_s: int
    quitting: bool
    paused: bool
    window_available: bool
    pause_when_hidden: bool
    in_flight: bool
    has_repos: bool
    network_offline: bool
    failures: int
    last_finished: float | None
    resume_pending: bool
    now: float


@dataclass(frozen=True, slots=True)
class RefreshDecision:
    """The timer action plus its delay and whether a pending resume is cleared."""

    action: RefreshAction
    delay_s: float = 0.0
    clear_resume: bool = False


def _wait(state: RefreshState, jitter_s: float) -> RefreshDecision:
    base = next_delay(
        state.interval_s,
        state.failures,
        network=state.network_offline,
    )
    if state.network_offline:
        delay = base
    else:
        delay = max(
            base,
            cooldown_remaining(
                state.last_finished, state.now, state.interval_s
            ),
        )
    return RefreshDecision(
        RefreshAction.WAIT,
        delay_s=max(0.0, delay) + max(0.0, jitter_s),
        clear_resume=True,
    )


def decide_refresh(
    state: RefreshState,
    event: RefreshEvent,
    *,
    jitter_s: float = 0.0,
) -> RefreshDecision:
    """Decide whether to stop, wait, or run automatic refresh.

    The table is intentionally pure: callers supply the clock, visibility,
    network state, and in-flight flag. `SHOW` only catches up when
    `pause_when_hidden` is enabled; otherwise it behaves like `SCHEDULE`.
    """
    if (
        state.interval_s <= 0
        or state.quitting
        or state.paused
        or (state.pause_when_hidden and not state.window_available)
    ):
        return RefreshDecision(RefreshAction.STOP, clear_resume=True)
    if state.resume_pending:
        return RefreshDecision(RefreshAction.STOP, clear_resume=False)

    if event is RefreshEvent.TIMER:
        if state.in_flight:
            return RefreshDecision(
                RefreshAction.WAIT,
                delay_s=AUTO_REFRESH_IN_FLIGHT_RETRY_S,
                clear_resume=True,
            )
        if not state.has_repos:
            return _wait(state, jitter_s)
        if not state.network_offline:
            remaining = cooldown_remaining(
                state.last_finished, state.now, state.interval_s
            )
            if remaining > 0:
                return RefreshDecision(
                    RefreshAction.WAIT,
                    delay_s=remaining + max(0.0, jitter_s),
                    clear_resume=True,
                )
        return RefreshDecision(RefreshAction.RUN, clear_resume=True)

    if event is RefreshEvent.SHOW and state.pause_when_hidden:
        due = (
            state.last_finished is not None
            and cooldown_remaining(
                state.last_finished, state.now, state.interval_s
            )
            <= 0
        )
        if due and not state.in_flight and state.has_repos:
            return RefreshDecision(RefreshAction.RUN, clear_resume=True)

    return _wait(state, jitter_s)


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
