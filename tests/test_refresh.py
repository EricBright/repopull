"""Tests for the automatic-refresh scheduling policy."""

from __future__ import annotations

import unittest

from repopull.refresh import (
    AUTO_REFRESH_FLOOR_S,
    AUTO_REFRESH_MAX_S,
    AUTO_REFRESH_RECOMMENDED_S,
    SUSPEND_DETECT_THRESHOLD_S,
    SUSPEND_RESUME_GRACE_S,
    SuspendDetector,
    clamp_auto_refresh_s,
    cooldown_remaining,
    next_delay,
    should_warn,
)


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


class SuspendDetectorTests(unittest.TestCase):
    def test_first_poll_is_a_baseline(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(detector.poll(100.0, 100.0), 0.0)

    def test_short_offset_change_is_ignored(self) -> None:
        detector = SuspendDetector(0.0)

        self.assertEqual(
            detector.poll(100.0 + SUSPEND_DETECT_THRESHOLD_S - 1, 100.0),
            0.0,
        )
        self.assertEqual(detector.poll(103.0, 100.0), 0.0)

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
