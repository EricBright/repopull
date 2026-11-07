"""Tests for the automatic-refresh scheduling policy."""

from __future__ import annotations

import unittest
from dataclasses import replace

from repopull.refresh import (
    AUTO_REFRESH_FLOOR_S,
    AUTO_REFRESH_IN_FLIGHT_RETRY_S,
    AUTO_REFRESH_MAX_S,
    AUTO_REFRESH_RECOMMENDED_S,
    NETWORK_RETRY_DELAYS_S,
    SUSPEND_DETECT_THRESHOLD_S,
    SUSPEND_POLL_INTERVAL_S,
    SUSPEND_RESUME_GRACE_S,
    RefreshAction,
    RefreshDecision,
    RefreshEvent,
    RefreshState,
    SuspendDetector,
    clamp_auto_refresh_s,
    cooldown_remaining,
    decide_refresh,
    next_delay,
    should_warn,
    wait_remaining,
)


BASE_STATE = RefreshState(
    interval_s=900,
    quitting=False,
    paused=False,
    window_available=True,
    pause_when_hidden=False,
    in_flight=False,
    has_repos=True,
    network_offline=False,
    failures=0,
    last_finished=None,
    resume_pending=False,
    now=1_000.0,
)


def state(**overrides: object) -> RefreshState:
    return replace(BASE_STATE, **overrides)


class ClampTests(unittest.TestCase):
    def test_off_stays_off(self) -> None:
        self.assertEqual(clamp_auto_refresh_s(0), 0)

    def test_below_floor_clamps_up(self) -> None:
        self.assertEqual(clamp_auto_refresh_s(1), AUTO_REFRESH_FLOOR_S)
        self.assertEqual(clamp_auto_refresh_s(299), AUTO_REFRESH_FLOOR_S)

    def test_in_range_is_preserved(self) -> None:
        self.assertEqual(clamp_auto_refresh_s(300), 300)
        self.assertEqual(clamp_auto_refresh_s(900), 900)

    def test_above_max_clamps_down(self) -> None:
        self.assertEqual(
            clamp_auto_refresh_s(AUTO_REFRESH_MAX_S + 1),
            AUTO_REFRESH_MAX_S,
        )


class WarningTests(unittest.TestCase):
    def test_off_does_not_warn(self) -> None:
        self.assertFalse(should_warn(0))

    def test_below_recommended_warns(self) -> None:
        self.assertTrue(should_warn(1))
        self.assertTrue(should_warn(AUTO_REFRESH_FLOOR_S))
        self.assertTrue(should_warn(AUTO_REFRESH_RECOMMENDED_S - 1))

    def test_at_or_above_recommended_does_not_warn(self) -> None:
        self.assertFalse(should_warn(AUTO_REFRESH_RECOMMENDED_S))
        self.assertFalse(should_warn(AUTO_REFRESH_RECOMMENDED_S + 1))


class CooldownTests(unittest.TestCase):
    def test_no_previous_run(self) -> None:
        self.assertEqual(cooldown_remaining(None, 100.0, 900), 0.0)

    def test_disabled_interval(self) -> None:
        self.assertEqual(cooldown_remaining(100.0, 200.0, 0), 0.0)

    def test_remaining_and_expired(self) -> None:
        self.assertEqual(cooldown_remaining(100.0, 500.0, 900), 500.0)
        self.assertEqual(cooldown_remaining(100.0, 1000.0, 900), 0.0)


class DelayTests(unittest.TestCase):
    def test_base_and_backoff(self) -> None:
        self.assertEqual(next_delay(900, 0), 900.0)
        self.assertEqual(next_delay(900, 1), 1800.0)
        self.assertEqual(next_delay(900, 2), 3600.0)
        self.assertEqual(next_delay(900, 3), 3600.0)

    def test_long_base_is_not_shortened_by_cap(self) -> None:
        self.assertEqual(next_delay(86_400, 0), 86_400.0)
        self.assertEqual(next_delay(86_400, 1), 86_400.0)

    def test_jitter_is_bounded(self) -> None:
        self.assertEqual(next_delay(900, 0, jitter_s=10), 910.0)
        self.assertEqual(next_delay(900, 0, jitter_s=100), 960.0)
        self.assertEqual(next_delay(900, 0, jitter_s=-1), 900.0)

    def test_off_returns_zero(self) -> None:
        self.assertEqual(next_delay(0, 0), 0.0)

    def test_network_retry_starts_short_then_caps(self) -> None:
        self.assertEqual(next_delay(900, 1, network=True), 120.0)
        self.assertEqual(next_delay(900, 2, network=True), 300.0)
        self.assertEqual(next_delay(900, 3, network=True), 900.0)
        self.assertEqual(next_delay(900, 4, network=True), 1_800.0)
        self.assertEqual(next_delay(900, 5, network=True), 3_600.0)
        self.assertEqual(
            next_delay(900, 99, network=True), NETWORK_RETRY_DELAYS_S[-1]
        )

    def test_network_retry_keeps_jitter_bounded(self) -> None:
        self.assertEqual(next_delay(900, 1, network=True, jitter_s=10), 130.0)
        self.assertEqual(next_delay(900, 1, network=True, jitter_s=100), 180.0)

    def test_wait_remaining_measures_from_last_finish(self) -> None:
        self.assertEqual(
            wait_remaining(500.0, 900, 0, 1_000.0), 400.0
        )
        self.assertEqual(
            wait_remaining(500.0, 900, 1, 1_000.0), 1_300.0
        )
        self.assertEqual(
            wait_remaining(940.0, 900, 1, 1_000.0, network=True), 60.0
        )
        self.assertEqual(
            wait_remaining(500.0, 900, 0, 2_000.0), 0.0
        )
        self.assertEqual(
            wait_remaining(None, 900, 0, 1_000.0), 900.0
        )


class DecisionTests(unittest.TestCase):
    def assert_wait(self, decision: RefreshDecision, delay: float) -> None:
        self.assertIs(decision.action, RefreshAction.WAIT)
        self.assertAlmostEqual(decision.delay_s, delay)

    def test_disabled_stops_and_clears_resume(self) -> None:
        decision = decide_refresh(
            state(interval_s=0), RefreshEvent.SCHEDULE
        )

        self.assertIs(decision.action, RefreshAction.STOP)
        self.assertTrue(decision.clear_resume)
        self.assertEqual(decision.delay_s, 0.0)

    def test_quit_and_pause_stop(self) -> None:
        for overrides in ({"quitting": True}, {"paused": True}):
            decision = decide_refresh(
                state(**overrides), RefreshEvent.SCHEDULE
            )
            self.assertIs(decision.action, RefreshAction.STOP)
            self.assertTrue(decision.clear_resume)

    def test_hidden_pause_stops(self) -> None:
        decision = decide_refresh(
            state(window_available=False, pause_when_hidden=True),
            RefreshEvent.SCHEDULE,
        )

        self.assertIs(decision.action, RefreshAction.STOP)
        self.assertTrue(decision.clear_resume)

    def test_hidden_pause_off_keeps_scheduling(self) -> None:
        decision = decide_refresh(
            state(window_available=False, pause_when_hidden=False),
            RefreshEvent.SCHEDULE,
        )

        self.assert_wait(decision, 900.0)

    def test_resume_pending_stops_without_clearing(self) -> None:
        for event in (
            RefreshEvent.SCHEDULE,
            RefreshEvent.TIMER,
            RefreshEvent.SHOW,
        ):
            decision = decide_refresh(
                state(resume_pending=True), event
            )
            self.assertIs(decision.action, RefreshAction.STOP)
            self.assertFalse(decision.clear_resume)

    def test_schedule_waits_interval(self) -> None:
        decision = decide_refresh(state(), RefreshEvent.SCHEDULE)

        self.assert_wait(decision, 900.0)
        self.assertTrue(decision.clear_resume)

    def test_schedule_waits_only_the_remaining_interval(self) -> None:
        decision = decide_refresh(
            state(last_finished=500.0), RefreshEvent.SCHEDULE
        )

        self.assert_wait(decision, 400.0)

    def test_schedule_does_not_postpone_an_overdue_run(self) -> None:
        decision = decide_refresh(
            state(last_finished=0.0), RefreshEvent.SCHEDULE
        )

        self.assert_wait(decision, 0.0)

    def test_schedule_keeps_failure_backoff_from_last_finish(self) -> None:
        decision = decide_refresh(
            state(last_finished=500.0, failures=1),
            RefreshEvent.SCHEDULE,
        )

        self.assert_wait(decision, 1_300.0)

    def test_schedule_keeps_network_retry_from_last_finish(self) -> None:
        decision = decide_refresh(
            state(
                last_finished=940.0,
                network_offline=True,
                failures=1,
            ),
            RefreshEvent.SCHEDULE,
        )

        self.assert_wait(decision, 60.0)

    def test_schedule_uses_network_retry_ladder(self) -> None:
        decision = decide_refresh(
            state(network_offline=True, failures=1),
            RefreshEvent.SCHEDULE,
        )

        self.assert_wait(decision, 120.0)

    def test_schedule_uses_failure_backoff(self) -> None:
        decision = decide_refresh(
            state(failures=1), RefreshEvent.SCHEDULE
        )

        self.assert_wait(decision, 1_800.0)

    def test_timer_runs_when_due(self) -> None:
        decision = decide_refresh(
            state(last_finished=0.0), RefreshEvent.TIMER
        )

        self.assertIs(decision.action, RefreshAction.RUN)
        self.assertTrue(decision.clear_resume)
        self.assertEqual(decision.delay_s, 0.0)

    def test_timer_waits_for_in_flight_run(self) -> None:
        decision = decide_refresh(
            state(in_flight=True), RefreshEvent.TIMER
        )

        self.assert_wait(decision, 60.0)
        self.assertTrue(decision.clear_resume)

    def test_timer_respects_cooldown(self) -> None:
        decision = decide_refresh(
            state(last_finished=500.0), RefreshEvent.TIMER
        )

        self.assert_wait(decision, 400.0)

    def test_timer_adds_jitter_to_the_remaining_cooldown(self) -> None:
        decision = decide_refresh(
            state(last_finished=500.0),
            RefreshEvent.TIMER,
            jitter_s=10.0,
        )

        self.assert_wait(decision, 410.0)

    def test_timer_without_repos_waits_interval(self) -> None:
        decision = decide_refresh(
            state(has_repos=False), RefreshEvent.TIMER
        )

        self.assert_wait(decision, 900.0)

    def test_timer_without_repos_does_not_spin_when_overdue(self) -> None:
        decision = decide_refresh(
            state(has_repos=False, last_finished=0.0), RefreshEvent.TIMER
        )

        self.assert_wait(decision, 900.0)

    def test_timer_in_flight_and_no_repos_still_waits_for_run(self) -> None:
        decision = decide_refresh(
            state(has_repos=False, in_flight=True),
            RefreshEvent.TIMER,
        )

        self.assert_wait(decision, AUTO_REFRESH_IN_FLIGHT_RETRY_S)

    def test_schedule_without_repos_waits_interval(self) -> None:
        decision = decide_refresh(
            state(has_repos=False), RefreshEvent.SCHEDULE
        )

        self.assert_wait(decision, 900.0)

    def test_timer_network_offline_runs_with_repos(self) -> None:
        decision = decide_refresh(
            state(network_offline=True), RefreshEvent.TIMER
        )

        self.assertIs(decision.action, RefreshAction.RUN)

    def test_show_catches_up_when_pause_is_due(self) -> None:
        decision = decide_refresh(
            state(
                pause_when_hidden=True,
                last_finished=0.0,
            ),
            RefreshEvent.SHOW,
        )

        self.assertIs(decision.action, RefreshAction.RUN)

    def test_show_waits_when_pause_is_not_due(self) -> None:
        decision = decide_refresh(
            state(
                pause_when_hidden=True,
                last_finished=500.0,
            ),
            RefreshEvent.SHOW,
        )

        self.assert_wait(decision, 400.0)

    def test_show_waits_for_a_sub_second_remainder(self) -> None:
        decision = decide_refresh(
            state(
                pause_when_hidden=True,
                last_finished=1_000.0,
                now=1_899.5,
            ),
            RefreshEvent.SHOW,
        )

        self.assert_wait(decision, 0.5)

    def test_show_without_pause_uses_normal_schedule(self) -> None:
        decision = decide_refresh(
            state(pause_when_hidden=False, last_finished=0.0),
            RefreshEvent.SHOW,
        )

        self.assert_wait(decision, 0.0)

    def test_show_respects_failure_backoff(self) -> None:
        decision = decide_refresh(
            state(
                pause_when_hidden=True,
                last_finished=500.0,
                failures=1,
            ),
            RefreshEvent.SHOW,
        )

        self.assert_wait(decision, 1_300.0)

    def test_show_with_in_flight_run_waits(self) -> None:
        decision = decide_refresh(
            state(
                pause_when_hidden=True,
                last_finished=0.0,
                in_flight=True,
            ),
            RefreshEvent.SHOW,
        )

        self.assert_wait(decision, AUTO_REFRESH_IN_FLIGHT_RETRY_S)

    def test_jitter_is_added_once(self) -> None:
        decision = decide_refresh(
            state(), RefreshEvent.SCHEDULE, jitter_s=10.0
        )

        self.assert_wait(decision, 910.0)


class SuspendDetectorTests(unittest.TestCase):
    def test_first_poll_is_a_baseline(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(detector.poll(100.0, 100.0), 0.0)

    def test_short_offset_change_is_ignored(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(detector.poll(104.0, 100.0), 0.0)
        self.assertEqual(detector.poll(103.0, 100.0), 0.0)

    def test_gap_at_the_threshold_is_reported(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(detector.poll(105.0, 100.0), 5.0)

    def test_gap_above_the_threshold_is_reported(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertAlmostEqual(detector.poll(105.2, 100.0), 5.2)

    def test_suspend_gap_is_reported_once(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(detector.poll(700.0, 100.0), 600.0)
        self.assertEqual(detector.poll(710.0, 110.0), 0.0)

    def test_negative_offset_resets_baseline(self) -> None:
        detector = SuspendDetector(50.0)

        self.assertEqual(detector.poll(100.0, 200.0), 0.0)
        self.assertEqual(detector.poll(500.0, 200.0), 300.0)

    def test_resume_grace_is_a_minute(self) -> None:
        self.assertEqual(SUSPEND_RESUME_GRACE_S, 60.0)

    def test_suspend_poll_interval_is_thirty_seconds(self) -> None:
        self.assertEqual(SUSPEND_POLL_INTERVAL_S, 30.0)
