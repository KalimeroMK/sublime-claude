"""Tests for attach file command (handles both images and regular files)."""
import unittest
import sys
import os
import types
import tempfile
from unittest.mock import MagicMock

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


class AttachCommandsTest(unittest.TestCase):
    """Test attach file command (handles images + regular files)."""

    def setUp(self):
        """Reset mocks before each test."""
        core_mod.get_active_session.reset_mock()
        core_mod.get_active_session.return_value = None
        sublime.status_message.reset_mock()

    def _make_session(self):
        """Create a mock session with tracking."""
        session = MagicMock()
        session.add_context_image = MagicMock()
        session.add_context_file = MagicMock()
        return session

    def test_is_enabled_no_session(self):
        """Command is disabled when no session exists."""
        core_mod.get_active_session.return_value = None
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()
        self.assertFalse(cmd.is_enabled())

    def test_is_enabled_with_session(self):
        """Command is enabled when a session exists."""
        core_mod.get_active_session.return_value = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()
        self.assertTrue(cmd.is_enabled())

    def test_add_png_image(self):
        """PNG image is sent as binary with image/png mime type."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name

        try:
            cmd._add(session, path)
            session.add_context_image.assert_called_once()
            session.add_context_file.assert_not_called()
            args = session.add_context_image.call_args[0]
            self.assertEqual(args[1], "image/png")
            self.assertEqual(args[0], b"\x89PNG\r\n\x1a\n")
        finally:
            os.unlink(path)

    def test_add_jpg_image(self):
        """JPG image gets image/jpeg mime type."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff")
            path = f.name

        try:
            cmd._add(session, path)
            args = session.add_context_image.call_args[0]
            self.assertEqual(args[1], "image/jpeg")
        finally:
            os.unlink(path)

    def test_add_webp_image(self):
        """WEBP image gets image/webp mime type."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            f.write(b"RIFF")
            path = f.name

        try:
            cmd._add(session, path)
            args = session.add_context_image.call_args[0]
            self.assertEqual(args[1], "image/webp")
        finally:
            os.unlink(path)

    def test_add_svg_image(self):
        """SVG image gets image/svg+xml mime type."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            f.write(b"<svg></svg>")
            path = f.name

        try:
            cmd._add(session, path)
            args = session.add_context_image.call_args[0]
            self.assertEqual(args[1], "image/svg+xml")
        finally:
            os.unlink(path)

    def test_add_gif_image(self):
        """GIF image gets image/gif mime type."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(b"GIF89a")
            path = f.name

        try:
            cmd._add(session, path)
            args = session.add_context_image.call_args[0]
            self.assertEqual(args[1], "image/gif")
        finally:
            os.unlink(path)

    def test_add_text_file(self):
        """Text file is sent as text content."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')")
            path = f.name

        try:
            cmd._add(session, path)
            session.add_context_file.assert_called_once()
            session.add_context_image.assert_not_called()
            args = session.add_context_file.call_args[0]
            self.assertEqual(args[0], path)
            self.assertEqual(args[1], "print('hello')")
        finally:
            os.unlink(path)

    def test_add_nonexistent_path(self):
        """Missing file is rejected."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()
        cmd._add(session, "/nonexistent/file.py")
        session.add_context_file.assert_not_called()
        session.add_context_image.assert_not_called()

    def test_add_binary_file(self):
        """Binary file falls back gracefully with errors=replace."""
        session = self._make_session()
        cmd = commands_mod.ClaudeAttachFileCommand()
        cmd.window = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02\xff")
            path = f.name

        try:
            cmd._add(session, path)
            session.add_context_file.assert_called_once()
            session.add_context_image.assert_not_called()
        finally:
            os.unlink(path)

    def test_mime_mapping_all_extensions(self):
        """All supported image extensions map to correct mime types."""
        ext_to_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        for ext, expected_mime in ext_to_mime.items():
            with self.subTest(ext=ext):
                session = self._make_session()
                cmd = commands_mod.ClaudeAttachFileCommand()
                cmd.window = MagicMock()

                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                    f.write(b"dummy")
                    path = f.name

                try:
                    cmd._add(session, path)
                    actual_mime = session.add_context_image.call_args[0][1]
                    self.assertEqual(actual_mime, expected_mime)
                finally:
                    os.unlink(path)

    def test_image_extensions_class_constant(self):
        """_IMAGE_EXTS contains all expected extensions."""
        expected = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
        self.assertEqual(commands_mod.ClaudeAttachFileCommand._IMAGE_EXTS, expected)


if __name__ == "__main__":
    unittest.main()
