import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import monitor
from monitor import Bar, M5, day_bounds, grid, hun, ny_time, replay

DAY = date(2026, 11, 23)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        start, end = day_bounds(DAY)
        self.prior = [Bar(stamp, 1.20, 1.10, 1.15) for stamp in grid(start, end)]
        self.window = ny_time(DAY, 3)
        self.before = [
            Bar(self.window - (5 - i) * M5, high, low, 1.16)
            for i, (high, low) in enumerate([
                (1.18, 1.14), (1.19, 1.13), (1.20, 1.12), (1.19, 1.13), (1.18, 1.14)
            ])
        ]

    def bar(self, i, high=1.18, low=1.14, close=1.16):
        return Bar(self.window + i * M5, high, low, close)

    def play(self, bars, minute=None):
        as_of = bars[-1].end if minute is None else ny_time(DAY, 3, minute)
        return replay(DAY, self.prior + self.before + bars, as_of)

    def test_long(self):
        confirm = self.bar(1, high=1.22, close=1.21)
        sweep, mss, status = self.play([self.bar(0, low=1.09), confirm])
        self.assertEqual((sweep.long, sweep.daily_level, sweep.mss_level, mss, status),
                         (True, 1.10, 1.20, confirm, "mss"))

    def test_short(self):
        confirm = self.bar(1, low=1.105, close=1.11)
        sweep, mss, status = self.play([self.bar(0, high=1.21), confirm])
        self.assertEqual((sweep.long, sweep.daily_level, sweep.mss_level, mss, status),
                         (False, 1.20, 1.12, confirm, "mss"))

    def test_retouch_wins_even_on_confirming_bar_and_locks_day(self):
        sweep, mss, status = self.play([
            self.bar(0, low=1.09),
            self.bar(1, low=1.09, high=1.22, close=1.21),
            self.bar(2, high=1.22, close=1.21),
        ])
        self.assertTrue(sweep.long)
        self.assertIsNone(mss)
        self.assertEqual(status, "invalidated")

    def test_last_entry(self):
        bars = [self.bar(0, low=1.09), *(self.bar(i) for i in range(1, 10))]
        confirm = self.bar(10, high=1.22, close=1.21)
        _, mss, _ = self.play([*bars, confirm])
        self.assertEqual(mss.end, ny_time(DAY, 3, 55))

    def test_0400_is_too_late(self):
        bars = [self.bar(0, low=1.09), *(self.bar(i) for i in range(1, 11))]
        _, mss, status = self.play([*bars, self.bar(11, high=1.22, close=1.21)])
        self.assertIsNone(mss)
        self.assertEqual(status, "expired")

    def test_wick_and_exact_close_do_not_confirm(self):
        _, mss, _ = self.play([self.bar(0, low=1.09), self.bar(1, high=1.22, close=1.20)])
        self.assertIsNone(mss)

    def test_double_sweep_locks_day(self):
        sweep, _, status = self.play([self.bar(0, high=1.21, low=1.09), self.bar(1, low=1.09)])
        self.assertIsNone(sweep)
        self.assertEqual(status, "double_sweep")

    def test_touch_or_close_on_daily_level(self):
        sweep, _, _ = self.play([self.bar(0, low=1.10), self.bar(1, low=1.09, close=1.10)])
        self.assertIsNone(sweep)

    def test_monday_friday_and_dst(self):
        start, end = day_bounds(DAY)
        self.assertEqual(start.astimezone(monitor.NY).weekday(), 3)
        self.assertEqual(end.astimezone(monitor.NY).weekday(), 4)
        self.assertIn("09:00", hun(ny_time(DAY, 3)))
        for day in (date(2026, 3, 16), date(2026, 10, 26)):
            self.assertIn("08:00", hun(ny_time(day, 3)))

    def test_restart_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(monitor, "STATE", Path(folder) / "state.json"):
                persisted = []
                key = f"{DAY}:sweep"
                self.assertTrue(monitor.claim(key, lambda: persisted.append(key)))
                self.assertFalse(monitor.claim(key, lambda: persisted.append(key)))
                self.assertEqual(persisted, [key])

    def test_resume_replays_sweep_and_suppresses_stale_mss(self):
        sweep, mss, _ = self.play([self.bar(0, low=1.09), self.bar(1, high=1.22, close=1.21)])
        with patch.object(monitor, "claim") as claim:
            monitor.notify_events(DAY, sweep, mss, mss.end + timedelta(seconds=30), lambda: None)
            claim.assert_not_called()

    def test_partial_prior_day_is_invalid(self):
        self.prior.pop()
        self.assertEqual(self.play([self.bar(0, low=1.09)])[2], "incomplete_previous_day")


if __name__ == "__main__":
    unittest.main()
