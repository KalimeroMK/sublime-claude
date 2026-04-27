"""Tests for session state machine."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_state import SessionState, SessionStateMachine


class SessionStateTest(unittest.TestCase):
    """Test session state machine."""

    def test_initial_state(self):
        """Default state is UNINITIALIZED."""
        sm = SessionStateMachine()
        self.assertEqual(sm.state, SessionState.UNINITIALIZED)

    def test_valid_transition_uninitialized_to_initializing(self):
        """Can transition from UNINITIALIZED to INITIALIZING."""
        sm = SessionStateMachine()
        self.assertTrue(sm.can_transition(SessionState.INITIALIZING))

    def test_valid_transition_initializing_to_ready(self):
        """Can transition from INITIALIZING to READY."""
        sm = SessionStateMachine(SessionState.INITIALIZING)
        self.assertTrue(sm.can_transition(SessionState.READY))

    def test_valid_transition_ready_to_working(self):
        """Can transition from READY to WORKING."""
        sm = SessionStateMachine(SessionState.READY)
        self.assertTrue(sm.can_transition(SessionState.WORKING))

    def test_valid_transition_working_to_ready(self):
        """Can transition from WORKING to READY."""
        sm = SessionStateMachine(SessionState.WORKING)
        self.assertTrue(sm.can_transition(SessionState.READY))

    def test_invalid_transition_uninitialized_to_ready(self):
        """Cannot skip INITIALIZING."""
        sm = SessionStateMachine(SessionState.UNINITIALIZED)
        self.assertFalse(sm.can_transition(SessionState.READY))

    def test_invalid_transition_ready_to_uninitialized(self):
        """Cannot go back to UNINITIALIZED from READY."""
        sm = SessionStateMachine(SessionState.READY)
        self.assertFalse(sm.can_transition(SessionState.UNINITIALIZED))

    def test_working_can_reenter_working(self):
        """WORKING can re-enter WORKING (for streaming)."""
        sm = SessionStateMachine(SessionState.WORKING)
        self.assertTrue(sm.can_transition(SessionState.WORKING))

    def test_error_to_initializing(self):
        """Can retry from ERROR."""
        sm = SessionStateMachine(SessionState.ERROR)
        self.assertTrue(sm.can_transition(SessionState.INITIALIZING))

    def test_error_to_uninitialized(self):
        """Can reset from ERROR."""
        sm = SessionStateMachine(SessionState.ERROR)
        self.assertTrue(sm.can_transition(SessionState.UNINITIALIZED))

    def test_transition_changes_state(self):
        """Transition actually changes state."""
        sm = SessionStateMachine(SessionState.UNINITIALIZED)
        sm.transition(SessionState.INITIALIZING)
        self.assertEqual(sm.state, SessionState.INITIALIZING)

    def test_transition_raises_on_invalid(self):
        """Invalid transition raises ValueError."""
        sm = SessionStateMachine(SessionState.UNINITIALIZED)
        with self.assertRaises(ValueError):
            sm.transition(SessionState.WORKING)

    def test_state_callback(self):
        """Callback is called on state change."""
        called_with = []
        def cb(old, new):
            called_with.append((old, new))
        
        sm = SessionStateMachine(SessionState.UNINITIALIZED)
        sm.on_change(cb)
        sm.transition(SessionState.INITIALIZING)
        
        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0], (SessionState.UNINITIALIZED, SessionState.INITIALIZING))

    def test_all_states_have_valid_transitions(self):
        """Every state has at least one valid transition."""
        for state in SessionState:
            sm = SessionStateMachine(state)
            valid = [s for s in SessionState if sm.can_transition(s)]
            self.assertTrue(len(valid) > 0, f"{state} has no valid transitions")

    def test_state_string_values(self):
        """State enum values are strings."""
        self.assertEqual(SessionState.UNINITIALIZED.value, "uninitialized")
        self.assertEqual(SessionState.INITIALIZING.value, "initializing")
        self.assertEqual(SessionState.READY.value, "ready")
        self.assertEqual(SessionState.WORKING.value, "working")
        self.assertEqual(SessionState.ERROR.value, "error")


if __name__ == "__main__":
    unittest.main()
