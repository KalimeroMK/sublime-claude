"""Tests for slash command parsing."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from command_parser import CommandParser, SlashCommand


class CommandParserTest(unittest.TestCase):
    """Test slash command parsing."""

    def test_parse_simple_command(self):
        """Parse simple /command."""
        result = CommandParser.parse("/clear")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "clear")
        self.assertEqual(result.args, "")
        self.assertEqual(result.raw, "/clear")

    def test_parse_with_args(self):
        """Parse command with arguments."""
        result = CommandParser.parse("/compact aggressive")
        self.assertEqual(result.name, "compact")
        self.assertEqual(result.args, "aggressive")

    def test_parse_with_multiple_args(self):
        """Parse command with multiple arguments."""
        result = CommandParser.parse("/context files only")
        self.assertEqual(result.name, "context")
        self.assertEqual(result.args, "files only")

    def test_no_slash_returns_none(self):
        """Text without slash returns None."""
        result = CommandParser.parse("hello world")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        result = CommandParser.parse("")
        self.assertIsNone(result)

    def test_whitespace_before_slash(self):
        """Leading whitespace is stripped."""
        result = CommandParser.parse("  /clear")
        self.assertEqual(result.name, "clear")

    def test_case_insensitive(self):
        """Command name is lowercased."""
        result = CommandParser.parse("/CLEAR")
        self.assertEqual(result.name, "clear")

    def test_slash_only_returns_none(self):
        """Just slash returns None."""
        result = CommandParser.parse("/")
        self.assertIsNone(result)

    def test_builtin_commands_exist(self):
        """Builtin commands are defined."""
        self.assertIn("clear", CommandParser.BUILTIN_COMMANDS)
        self.assertIn("compact", CommandParser.BUILTIN_COMMANDS)
        self.assertIn("context", CommandParser.BUILTIN_COMMANDS)

    def test_builtin_commands_have_descriptions(self):
        """Builtin commands have non-empty descriptions."""
        for name, desc in CommandParser.BUILTIN_COMMANDS.items():
            self.assertTrue(len(desc) > 0)

    def test_slash_command_dataclass(self):
        """SlashCommand stores all fields."""
        cmd = SlashCommand(name="test", args="arg1 arg2", raw="/test arg1 arg2")
        self.assertEqual(cmd.name, "test")
        self.assertEqual(cmd.args, "arg1 arg2")
        self.assertEqual(cmd.raw, "/test arg1 arg2")


if __name__ == "__main__":
    unittest.main()
