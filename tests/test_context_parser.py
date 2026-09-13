"""Tests for context trigger and menu parsing."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context_parser import (ContextParser, ContextTrigger, ContextMenuItem,
                            ContextMenuHandler)


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
        # Assert the order by name rather than by index: the @-command list
        # grows, and positional assertions break on every addition.
        actions = [item.action for item in menu]
        self.assertEqual(
            actions,
            ["codebase", "git", "web", "model", "routes", "module", "artisan",
             "quality", "browse", "file"],
        )
        # the trailing "file" entry comes from the open_files argument
        self.assertEqual(menu[-1].label, "main.py")

    def test_build_menu_has_laravel_commands(self):
        """The Laravel context commands must be reachable from the @ menu, not
        only by typing them."""
        menu = ContextParser.build_menu(open_files=[], has_pending_context=False)
        labels = [item.label for item in menu]
        for label in ("@module", "@artisan", "@quality"):
            self.assertIn(label, labels)

    def test_build_menu_has_codebase(self):
        """Menu includes @codebase option."""
        menu = ContextParser.build_menu(
            open_files=[],
            has_pending_context=False
        )
        codebase_items = [m for m in menu if m.action == "codebase"]
        self.assertEqual(len(codebase_items), 1)
        self.assertEqual(codebase_items[0].label, "@codebase")

    def test_build_menu_has_git(self):
        """Menu includes @git option."""
        menu = ContextParser.build_menu(
            open_files=[],
            has_pending_context=False
        )
        git_items = [m for m in menu if m.action == "git"]
        self.assertEqual(len(git_items), 1)
        self.assertEqual(git_items[0].label, "@git")

    def test_build_menu_has_web(self):
        """Menu includes @web option."""
        menu = ContextParser.build_menu(
            open_files=[],
            has_pending_context=False
        )
        web_items = [m for m in menu if m.action == "web"]
        self.assertEqual(len(web_items), 1)
        self.assertEqual(web_items[0].label, "@web")

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


class ContextMenuHandlerInsertTest(unittest.TestCase):
    """@model and @routes were in the menu with no branch in the handler, so
    choosing either did nothing at all."""

    def _handler(self, inserted):
        return ContextMenuHandler(
            on_browse=lambda: inserted.append("browse"),
            on_clear=lambda: None,
            on_add_file=lambda p, c: None,
            on_insert=inserted.append,
        )

    def _pick(self, label, action):
        inserted = []
        items = [ContextMenuItem(action=action, label=label, description="")]
        self._handler(inserted).handle_selection(items, 0)
        return inserted

    def test_model_inserts_its_command(self):
        self.assertEqual(self._pick("@model", "model"), ["@model "])

    def test_module_inserts_its_command(self):
        self.assertEqual(self._pick("@module", "module"), ["@module "])

    def test_artisan_inserts_its_command(self):
        self.assertEqual(self._pick("@artisan", "artisan"), ["@artisan "])

    def test_quality_inserts_its_command(self):
        self.assertEqual(self._pick("@quality", "quality"), ["@quality "])

    def test_browse_is_not_treated_as_a_command(self):
        inserted = []
        items = [ContextMenuItem(action="browse", label="Browse...", description="")]
        self._handler(inserted).handle_selection(items, 0)
        self.assertEqual(inserted, ["browse"])

    def test_missing_callback_is_not_an_error(self):
        items = [ContextMenuItem(action="module", label="@module", description="")]
        handler = ContextMenuHandler(lambda: None, lambda: None, lambda p, c: None)
        handler.handle_selection(items, 0)  # must not raise


if __name__ == "__main__":
    unittest.main()
