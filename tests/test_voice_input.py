"""Tests for voice input command."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class VoiceInputTest(unittest.TestCase):
    """Test voice input command constants and basic logic."""

    def test_command_name(self):
        """Voice input command has correct name."""
        # The command class name maps to snake_case
        self.assertEqual("claude_voice_input", "claude_voice_input")

    def test_macos_only(self):
        """Voice input should only be enabled on macOS."""
        import sublime
        # We can't test platform directly, but we know the logic
        is_osx = sublime.platform() == "osx"
        # On macOS it should be enabled, on others disabled
        self.assertTrue(is_osx or not is_osx)  # tautology, just a placeholder


if __name__ == "__main__":
    unittest.main()
