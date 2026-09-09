"""Tests for Session._on_init in session_core.py.

_on_init runs on every connect, resume and auto-restart, so it is the single
place that decides whether a reconnected session looks alive or stale. Called
against the real function with a stand-in self — Session.__init__ builds an
OutputView and needs a live Sublime window, which a unit test has no business
constructing.
"""
import time
import unittest
from unittest.mock import MagicMock

from tests.plugin_pkg import load

session_core = load("session_core")
Session = session_core.Session

STALE = time.time() - 3 * 60 * 60


def make_self(last_idle_at=STALE):
    s = MagicMock()
    s.last_idle_at = last_idle_at
    s.last_activity = last_idle_at
    s.initialized = False
    s.working = True
    s.current_tool = "thinking"
    s.session_id = None
    s._input_mode_entered = True
    return s


class OnInitSuccessTest(unittest.TestCase):
    def test_resets_idle_clock(self):
        """Third leg of the 2ce385f fix — a session that reconnects must not
        carry its pre-sleep idle timestamp into the next auto-sleep tick."""
        s = make_self()
        Session._on_init(s, {})
        self.assertGreater(s.last_idle_at, STALE)
        self.assertAlmostEqual(s.last_idle_at, time.time(), delta=5)

    def test_resets_activity_clock(self):
        s = make_self()
        Session._on_init(s, {})
        self.assertGreater(s.last_activity, STALE)

    def test_marks_session_ready(self):
        s = make_self()
        Session._on_init(s, {})
        self.assertTrue(s.initialized)
        self.assertFalse(s.working)
        self.assertIsNone(s.current_tool)

    def test_captures_session_id(self):
        s = make_self()
        Session._on_init(s, {"session_id": "abc-123"})
        self.assertEqual(s.session_id, "abc-123")

    def test_missing_session_id_leaves_it_alone(self):
        s = make_self()
        s.session_id = "existing"
        Session._on_init(s, {})
        self.assertEqual(s.session_id, "existing")

    def test_starts_heartbeat_and_persists(self):
        s = make_self()
        Session._on_init(s, {})
        s._start_heartbeat.assert_called_once()
        s._save_session.assert_called_once()

    def test_enters_input_mode(self):
        s = make_self()
        Session._on_init(s, {})
        s._enter_input_with_draft.assert_called_once()

    def _status_text(self, s):
        return s._status.call_args[0][0]

    def test_status_plain_ready_without_extras(self):
        s = make_self()
        Session._on_init(s, {})
        self.assertEqual(self._status_text(s), "ready")

    def test_status_lists_mcp_servers(self):
        s = make_self()
        Session._on_init(s, {"mcp_servers": ["sublime"]})
        self.assertEqual(self._status_text(s), "ready (MCP: sublime)")

    def test_status_lists_mcp_and_agents(self):
        s = make_self()
        Session._on_init(s, {"mcp_servers": ["sublime"], "agents": ["planner", "reporter"]})
        self.assertEqual(
            self._status_text(s),
            "ready (MCP: sublime; agents: planner, reporter)",
        )


class OnInitErrorTest(unittest.TestCase):
    def test_error_does_not_mark_session_ready(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "boom"}})
        self.assertFalse(s.initialized)

    def test_error_leaves_idle_clock_untouched(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "boom"}})
        self.assertEqual(s.last_idle_at, STALE)

    def test_error_does_not_start_heartbeat(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "boom"}})
        s._start_heartbeat.assert_not_called()
        s._enter_input_with_draft.assert_not_called()

    def test_expired_session_gets_restart_hint(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "No conversation found"}})
        text = s.output.text.call_args[0][0]
        self.assertIn("Session expired", text)
        self.assertIn("Restart Session", text)

    def test_command_failed_treated_as_session_error(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "Command failed with code 1"}})
        self.assertIn("Session expired", s.output.text.call_args[0][0])

    def test_other_error_reports_the_message(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "connection refused"}})
        text = s.output.text.call_args[0][0]
        self.assertIn("Failed to connect", text)
        self.assertIn("connection refused", text)

    def test_error_sets_error_status(self):
        s = make_self()
        Session._on_init(s, {"error": {"message": "boom"}})
        s._status.assert_called_with("error")


if __name__ == "__main__":
    unittest.main()
