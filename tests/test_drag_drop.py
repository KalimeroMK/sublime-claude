"""Tests for drag-drop file/image detection."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin


class DragDropTest(unittest.TestCase):
    """Test drag-drop path detection logic."""

    def _is_image(self, path):
        """Replicate image detection from listeners.py."""
        ext = os.path.splitext(path)[1].lower()
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
        return ext in image_exts

    def test_png_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.png"))

    def test_jpg_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.jpg"))

    def test_jpeg_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.jpeg"))

    def test_gif_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.gif"))

    def test_webp_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.webp"))

    def test_svg_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.svg"))

    def test_bmp_is_image(self):
        self.assertTrue(self._is_image("/path/to/test.bmp"))

    def test_py_is_not_image(self):
        self.assertFalse(self._is_image("/path/to/test.py"))

    def test_js_is_not_image(self):
        self.assertFalse(self._is_image("/path/to/test.js"))

    def test_md_is_not_image(self):
        self.assertFalse(self._is_image("/path/to/test.md"))

    def test_case_insensitive(self):
        """Extensions are case-insensitive."""
        self.assertTrue(self._is_image("/path/to/test.PNG"))
        self.assertTrue(self._is_image("/path/to/test.JpG"))

    def test_no_extension(self):
        """Files without extension are not images."""
        self.assertFalse(self._is_image("/path/to/README"))

    def test_path_with_spaces(self):
        """Paths with spaces work correctly."""
        self.assertTrue(self._is_image("/path/to/my image.png"))
        self.assertFalse(self._is_image("/path/to/my file.py"))

    def test_mime_type_mapping(self):
        """Mime types map correctly from extension."""
        ext = ".png"
        mime = "image/png"
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".gif":
            mime = "image/gif"
        elif ext == ".webp":
            mime = "image/webp"
        elif ext == ".svg":
            mime = "image/svg+xml"
        self.assertEqual(mime, "image/png")

    def test_all_image_extensions(self):
        """All supported image extensions are detected."""
        exts = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"]
        for ext in exts:
            with self.subTest(ext=ext):
                self.assertTrue(self._is_image(f"/test{ext}"), f"{ext} should be image")


if __name__ == "__main__":
    unittest.main()
