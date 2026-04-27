"""Tests for context trigger and menu parsing."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context_parser import ContextParser, ContextTrigger, ContextMenuItem


class ContextParserTest(unittest.TestCase):
    """Test context parsing."""

    def test_trigger_at_cursor(self):
        """@ at cursor position triggers."""
        result = ContextParser.check_trigger("hello @", 7)
        self.assertIsNotNone(result)
        self.assertEqual(result.position, 7)

    def test_no_trigger(self):
        """Text without @ returns None."""
        result = ContextParser.check_trigger("hello world", 5)
        self.assertIsNone(result)

    def test_cursor_at_zero(self):
        """Cursor at position 0 returns None."""
        result = ContextParser.check_trigger("@hello", 0)
        self.assertIsNone(result)

    def test_trigger_in_middle(self):
        """@ in middle of text triggers."""
        result = ContextParser.check_trigger("hello @world", 7)
        self.assertIsNotNone(result)
        self.assertEqual(result.position, 7)

    def test_trigger_char_constant(self):
        """Trigger char is @."""
        self.assertEqual(ContextParser.TRIGGER_CHAR, "@")

    def test_build_menu_basic(self):
        """Menu has basic items."""
        menu = ContextParser.build_menu(
            open_files=[("main.py", "/proj/main.py")],
            has_pending_context=False
        )
        self.assertTrue(len(menu) > 0)
        # First item should be "browse" action
        self.assertEqual(menu[0].action, "browse")

    def test_build_menu_with_files(self):
        """Menu includes open files."""
        menu = ContextParser.build_menu(
            open_files=[("a.py", "/proj/a.py"), ("b.py", "/proj/b.py")],
            has_pending_context=False
        )
        file_items = [m for m in menu if m.action == "file"]
        self.assertEqual(len(file_items), 2)

    def test_build_menu_with_context_clear(self):
        """Menu includes clear when pending context exists."""
        menu = ContextParser.build_menu(
            open_files=[],
            has_pending_context=True
        )
        clear_items = [m for m in menu if m.action == "clear"]
        self.assertEqual(len(clear_items), 1)

    def test_build_menu_without_clear(self):
        """Menu excludes clear when no pending context."""
        menu = ContextParser.build_menu(
            open_files=[],
            has_pending_context=False
        )
        clear_items = [m for m in menu if m.action == "clear"]
        self.assertEqual(len(clear_items), 0)

    def test_context_menu_item(self):
        """ContextMenuItem stores fields."""
        item = ContextMenuItem(action="file", label="main.py", description="Open file", data="/path")
        self.assertEqual(item.action, "file")
        self.assertEqual(item.label, "main.py")
        self.assertEqual(item.description, "Open file")
        self.assertEqual(item.data, "/path")

    def test_context_trigger_defaults(self):
        """ContextTrigger defaults are correct."""
        trigger = ContextTrigger(position=5)
        self.assertEqual(trigger.position, 5)
        self.assertTrue(trigger.triggered)


if __name__ == "__main__":
    unittest.main()
