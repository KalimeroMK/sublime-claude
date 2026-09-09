"""Tests for core.py auto-sleep — the real _check_auto_sleep, not a replica.

Regression cover for 2ce385f ("prevent auto-sleep loop after sleep/wake"):
last_idle_at is only set when a session enters input mode, so after wake() it
still held the pre-sleep timestamp and the very next 60s tick slept the session
again — wake, sleep, wake, sleep. The guard under test is that a session whose
last_idle_at was reset is left alone.
"""
import time
import unittest
from unittest.mock import MagicMock

from tests.plugin_pkg import (
    FakeSettings,
    RecordingTimeout,
    load,
    reset_sessions,
    sublime,
)

core = load("core")

# A timestamp far enough in the past that auto-sleep would fire on it.
STALE = time.time() - 3 * 60 * 60


class FakeSession:
    """Only the fields _check_auto_sleep actually reads."""

    def __init__(self, name="s", initialized=True, working=False,
                 is_sleeping=False, last_idle_at=0.0, window=None):
        self.name = name
        self.initialized = initialized
        self.working = working
        self.is_sleeping = is_sleeping
        self.last_idle_at = last_idle_at
        self.window = window
        self.slept = 0
        self.stopped = 0

    def sleep(self):
        self.slept += 1
        self.is_sleeping = True

    def stop(self):
        self.stopped += 1


class AutoSleepTestBase(unittest.TestCase):
    def setUp(self):
        self.sessions = reset_sessions()
        self.settings = FakeSettings({"auto_sleep_minutes": 60})
        self.timeout = RecordingTimeout()
        self._orig_load = sublime.load_settings
        self._orig_timeout = sublime.set_timeout
        sublime.load_settings = lambda name: self.settings
        sublime.set_timeout = self.timeout
        core._auto_sleep_timer = None

    def tearDown(self):
        sublime.load_settings = self._orig_load
        sublime.set_timeout = self._orig_timeout
        core._auto_sleep_timer = None

    def add(self, **kw):
        s = FakeSession(**kw)
        self.sessions[len(self.sessions) + 1] = s
        return s

    @staticmethod
    def minutes_ago(n):
        return time.time() - n * 60


class CheckAutoSleepTest(AutoSleepTestBase):
    def test_sleeps_session_idle_past_threshold(self):
        s = self.add(last_idle_at=self.minutes_ago(90))
        core._check_auto_sleep()
        self.assertEqual(s.slept, 1)

    def test_freshly_woken_session_is_not_slept(self):
        """The 2ce385f regression: wake() resets last_idle_at, so the next
        tick must leave the session alone instead of re-sleeping it."""
        s = self.add(last_idle_at=time.time())
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_stale_last_idle_at_would_resleep_immediately(self):
        """Pins the failure mode: without the wake() reset, a session that was
        idle long before sleeping is slept again on the very first tick."""
        s = self.add(last_idle_at=self.minutes_ago(120), is_sleeping=False)
        core._check_auto_sleep()
        self.assertEqual(s.slept, 1)
        # and with the reset applied, it survives
        s2 = self.add(last_idle_at=time.time(), is_sleeping=False)
        core._check_auto_sleep()
        self.assertEqual(s2.slept, 0)

    def test_never_idle_session_is_not_slept(self):
        """last_idle_at == 0 means input mode was never entered."""
        s = self.add(last_idle_at=0)
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_working_session_is_not_slept(self):
        s = self.add(last_idle_at=self.minutes_ago(90), working=True)
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_already_sleeping_session_is_not_slept_again(self):
        s = self.add(last_idle_at=self.minutes_ago(90), is_sleeping=True)
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_uninitialized_session_is_not_slept(self):
        s = self.add(last_idle_at=self.minutes_ago(90), initialized=False)
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_boundary_just_under_threshold_survives(self):
        s = self.add(last_idle_at=self.minutes_ago(59))
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_only_stale_sessions_sleep(self):
        stale = self.add(name="stale", last_idle_at=self.minutes_ago(90))
        fresh = self.add(name="fresh", last_idle_at=time.time())
        core._check_auto_sleep()
        self.assertEqual((stale.slept, fresh.slept), (1, 0))


class AutoSleepDisabledTest(AutoSleepTestBase):
    def test_zero_minutes_disables_auto_sleep(self):
        self.settings.set("auto_sleep_minutes", 0)
        s = self.add(last_idle_at=self.minutes_ago(600))
        core._check_auto_sleep()
        self.assertEqual(s.slept, 0)

    def test_disabled_does_not_rearm_timer(self):
        self.settings.set("auto_sleep_minutes", 0)
        self.add(last_idle_at=self.minutes_ago(600))
        core._check_auto_sleep()
        self.assertEqual(self.timeout.calls, [])


class ScheduleAutoSleepTest(AutoSleepTestBase):
    def test_arms_a_single_timer(self):
        self.add(last_idle_at=time.time())
        core.schedule_auto_sleep()
        self.assertEqual(len(self.timeout.calls), 1)

    def test_repeated_calls_do_not_stack_timers(self):
        self.add(last_idle_at=time.time())
        for _ in range(5):
            core.schedule_auto_sleep()
        self.assertEqual(len(self.timeout.calls), 1)

    def test_no_timer_without_sessions(self):
        core.schedule_auto_sleep()
        self.assertEqual(self.timeout.calls, [])

    def test_check_rearms_itself_once(self):
        self.add(last_idle_at=time.time())
        core._check_auto_sleep()
        self.assertEqual(len(self.timeout.calls), 1)
        self.assertEqual(self.timeout.calls[0][1], 60000)


class WakeResetsIdleClockTest(unittest.TestCase):
    """Direct cover for the 2ce385f fix itself.

    _check_auto_sleep only ever *reads* last_idle_at; the loop was caused by
    wake()/auto_restart() leaving the pre-sleep timestamp in place. These
    assert the reset happens, so removing it fails here rather than showing up
    as a mysterious wake-sleep-wake cycle at runtime.
    """

    def setUp(self):
        self.bridge_mod = load("session_bridge")
        self.settings = FakeSettings({"auto_sleep_minutes": 60})
        self._orig_load = sublime.load_settings
        sublime.load_settings = lambda name: self.settings

    def tearDown(self):
        sublime.load_settings = self._orig_load

    def _manager(self, **session_kw):
        """BridgeManager over a fake session, with start() stubbed out so the
        test never spawns a bridge subprocess."""
        s = MagicMock()
        s.client = None
        s.initialized = False
        s.working = False
        s.session_id = "sess-1"
        s.last_idle_at = STALE
        s._pending_resume_at = None
        s.output.is_input_mode.return_value = False
        for k, v in session_kw.items():
            setattr(s, k, v)

        mgr = self.bridge_mod.BridgeManager(s)
        mgr.start = lambda resume_session_at=None: None
        return mgr, s

    def test_wake_resets_last_idle_at(self):
        mgr, s = self._manager()
        mgr.wake()
        self.assertGreater(s.last_idle_at, STALE)
        self.assertAlmostEqual(s.last_idle_at, time.time(), delta=5)

    def test_auto_restart_resets_last_idle_at(self):
        mgr, s = self._manager()
        self.assertTrue(mgr.auto_restart())
        self.assertGreater(s.last_idle_at, STALE)
        self.assertAlmostEqual(s.last_idle_at, time.time(), delta=5)

    def test_woken_session_survives_the_next_tick(self):
        """End to end: wake, then run the real auto-sleep check."""
        mgr, s = self._manager()
        mgr.wake()

        sessions = reset_sessions()
        session = FakeSession(last_idle_at=s.last_idle_at)
        sessions[1] = session
        timeout = RecordingTimeout()
        orig_timeout = sublime.set_timeout
        sublime.set_timeout = timeout
        try:
            core._auto_sleep_timer = None
            core._check_auto_sleep()
        finally:
            sublime.set_timeout = orig_timeout
            core._auto_sleep_timer = None

        self.assertEqual(session.slept, 0, "freshly woken session was auto-slept again")

    def test_auto_restart_without_session_id_bails(self):
        mgr, s = self._manager(session_id=None)
        self.assertFalse(mgr.auto_restart())

    def test_wake_bails_when_already_initialized(self):
        mgr, s = self._manager(initialized=True)
        mgr.wake()
        self.assertEqual(s.last_idle_at, STALE)


if __name__ == "__main__":
    unittest.main()
