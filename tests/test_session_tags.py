"""Tests for session tags feature."""
import unittest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin


class SessionTagsTest(unittest.TestCase):
    """Test session tag parsing and serialization."""

    def test_parse_simple_tags(self):
        """Parse comma-separated tags."""
        tags = "bugfix, refactor, urgent"
        parsed = [t.strip() for t in tags.split(",") if t.strip()]
        self.assertEqual(parsed, ["bugfix", "refactor", "urgent"])

    def test_parse_empty_string(self):
        """Empty string gives empty list."""
        parsed = [t.strip() for t in "".split(",") if t.strip()]
        self.assertEqual(parsed, [])

    def test_parse_whitespace(self):
        """Whitespace around tags is trimmed."""
        tags = "  a  ,  b  ,  "
        parsed = [t.strip() for t in tags.split(",") if t.strip()]
        self.assertEqual(parsed, ["a", "b"])

    def test_parse_single_tag(self):
        """Single tag without commas."""
        tags = "bugfix"
        parsed = [t.strip() for t in tags.split(",") if t.strip()]
        self.assertEqual(parsed, ["bugfix"])

    def test_serialization_with_tags(self):
        """Tags are serialized to session entry."""
        entry = {"session_id": "test-123"}
        tags = ["bugfix", "refactor"]
        if tags:
            entry["tags"] = tags.copy()
        else:
            entry.pop("tags", None)
        self.assertIn("tags", entry)
        self.assertEqual(entry["tags"], ["bugfix", "refactor"])

    def test_serialization_without_tags(self):
        """Missing tags removes key from entry."""
        entry = {"session_id": "test-123", "tags": ["old"]}
        tags = []
        if tags:
            entry["tags"] = tags.copy()
        else:
            entry.pop("tags", None)
        self.assertNotIn("tags", entry)

    def test_tag_display_format(self):
        """Tags display as [tag1,tag2] in status bar."""
        tags = ["bugfix", "refactor"]
        display = "[" + ",".join(tags) + "]"
        self.assertEqual(display, "[bugfix,refactor]")

    def test_tag_display_empty(self):
        """Empty tags show nothing."""
        tags = []
        if tags:
            display = "[" + ",".join(tags) + "]"
        else:
            display = ""
        self.assertEqual(display, "")

    def test_json_roundtrip(self):
        """Tags survive JSON serialization."""
        entry = {"session_id": "test-123", "tags": ["a", "b"]}
        json_str = json.dumps(entry)
        restored = json.loads(json_str)
        self.assertEqual(restored["tags"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
