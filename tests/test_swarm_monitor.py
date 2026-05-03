"""Tests for Agent Swarm Monitor command."""
import unittest
import sys
import os
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin

# Setup package mocks before importing commands
claude_pkg = types.ModuleType('ClaudeCode')
claude_pkg.__path__ = ['.']
sys.modules['ClaudeCode'] = claude_pkg

core_mod = types.ModuleType('ClaudeCode.core')
core_mod.get_active_session = MagicMock(return_value=None)
core_mod.get_session_for_view = MagicMock(return_value=None)
core_mod.create_session = MagicMock()
sys.modules['ClaudeCode.core'] = core_mod

session_mod = types.ModuleType('ClaudeCode.session')
session_mod.Session = MagicMock()
session_mod.load_saved_sessions = MagicMock(return_value=[])
session_mod.load_bookmarks = MagicMock(return_value=set())
session_mod.toggle_bookmark = MagicMock(return_value=True)
sys.modules['ClaudeCode.session'] = session_mod

ctx_mod = types.ModuleType('ClaudeCode.context_parser')
ctx_mod.ContextParser = MagicMock()
ctx_mod.ContextMenuItem = MagicMock()
ctx_mod.ContextMenuHandler = MagicMock()
sys.modules['ClaudeCode.context_parser'] = ctx_mod

out_mod = types.ModuleType('ClaudeCode.output')
out_mod.OutputManager = MagicMock()
sys.modules['ClaudeCode.output'] = out_mod

# Import commands module
import importlib.util
spec = importlib.util.spec_from_file_location('ClaudeCode.commands',
    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'commands.py'))
commands_mod = importlib.util.module_from_spec(spec)
sys.modules['ClaudeCode.commands'] = commands_mod
spec.loader.exec_module(commands_mod)


class SwarmMonitorTest(unittest.TestCase):
    """Test Agent Swarm Monitor command."""

    def setUp(self):
        """Reset session registry before each test."""
        sublime._claude_sessions = {}

    def test_is_enabled_no_sessions(self):
        """Command is disabled when no sessions exist."""
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        cmd.window = MagicMock()
        self.assertFalse(cmd.is_enabled())

    def test_is_enabled_with_sessions(self):
        """Command is enabled when sessions exist."""
        mock_session = MagicMock()
        sublime._claude_sessions[1] = mock_session
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        cmd.window = MagicMock()
        self.assertTrue(cmd.is_enabled())

    def test_status_icon_working(self):
        """Working session shows 🟢 Working."""
        session = MagicMock()
        session.working = True
        session.is_sleeping = False
        session.initialized = True
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        self.assertEqual(cmd._status_icon(session), "🟢 Working")

    def test_status_icon_sleeping(self):
        """Sleeping session shows 💤 Sleeping."""
        session = MagicMock()
        session.working = False
        session.is_sleeping = True
        session.initialized = False
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        self.assertEqual(cmd._status_icon(session), "💤 Sleeping")

    def test_status_icon_connecting(self):
        """Uninitialized session shows 🟡 Connecting."""
        session = MagicMock()
        session.working = False
        session.is_sleeping = False
        session.initialized = False
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        self.assertEqual(cmd._status_icon(session), "🟡 Connecting")

    def test_status_icon_idle(self):
        """Initialized non-working session shows ⏸ Idle."""
        session = MagicMock()
        session.working = False
        session.is_sleeping = False
        session.initialized = True
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        self.assertEqual(cmd._status_icon(session), "⏸ Idle")

    def test_status_icon_respects_working_over_sleeping(self):
        """Working takes precedence over sleeping."""
        session = MagicMock()
        session.working = True
        session.is_sleeping = True
        session.initialized = False
        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        self.assertEqual(cmd._status_icon(session), "🟢 Working")

    def test_panel_shows_sessions(self):
        """Panel shows session data in markdown table format."""
        # Create mock sessions
        session1 = MagicMock()
        session1.window = MagicMock()  # Same window as command
        session1.display_name = "Main"
        session1.backend = "claude"
        session1.query_count = 5
        session1.total_cost = 0.1234
        session1.parent_view_id = None
        session1.tags = ["bugfix"]
        session1.working = False
        session1.is_sleeping = False
        session1.initialized = True

        session2 = MagicMock()
        session2.window = session1.window  # Same window
        session2.display_name = "Worker"
        session2.backend = "openai"
        session2.query_count = 2
        session2.total_cost = 0.0567
        session2.parent_view_id = 100
        session2.tags = []
        session2.working = True
        session2.is_sleeping = False
        session2.initialized = True

        sublime._claude_sessions[100] = session1
        sublime._claude_sessions[200] = session2

        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        cmd.window = session1.window

        # Capture panel creation
        panel_mock = MagicMock()
        cmd.window.create_output_panel = MagicMock(return_value=panel_mock)

        cmd.run()

        # Verify panel was created and shown
        cmd.window.create_output_panel.assert_called_once_with("claude_swarm")
        cmd.window.run_command.assert_called_with("show_panel", {"panel": "output.claude_swarm"})

        # Verify markdown syntax was set
        panel_mock.set_syntax_file.assert_called_once()
        self.assertIn("Markdown", panel_mock.set_syntax_file.call_args[0][0])

    def test_panel_skips_other_windows(self):
        """Sessions from other windows are not shown."""
        other_window = MagicMock()
        this_window = MagicMock()

        session_other = MagicMock()
        session_other.window = other_window
        session_other.display_name = "Other"

        sublime._claude_sessions[1] = session_other

        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        cmd.window = this_window

        cmd.window.create_output_panel = MagicMock(return_value=MagicMock())

        cmd.run()

        # No sessions in this window — should show status message, not create panel
        cmd.window.create_output_panel.assert_not_called()

    def test_parent_session_lookup(self):
        """Subsession shows parent name if available."""
        parent = MagicMock()
        parent.display_name = "Parent Session"
        sublime._claude_sessions[50] = parent

        child = MagicMock()
        child.window = MagicMock()
        child.display_name = "Child"
        child.backend = "claude"
        child.query_count = 1
        child.total_cost = 0.01
        child.parent_view_id = 50
        child.tags = []
        child.working = False
        child.is_sleeping = False
        child.initialized = True

        sublime._claude_sessions[60] = child

        cmd = commands_mod.ClaudeCodeSwarmMonitorCommand()
        cmd.window = child.window
        cmd.window.create_output_panel = MagicMock(return_value=MagicMock())

        cmd.run()

        # Should find parent by view_id
        cmd.window.create_output_panel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
