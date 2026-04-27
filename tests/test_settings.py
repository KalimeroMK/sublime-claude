"""Tests for settings loading and merging."""
import unittest
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin

from settings import merge_settings, safe_json_load


class SettingsTest(unittest.TestCase):
    """Test settings utilities."""

    def test_merge_shallow(self):
        """Shallow values are overridden."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = merge_settings(base, override)
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})

    def test_merge_nested_dict(self):
        """Nested dicts are deep-merged."""
        base = {"server": {"host": "localhost", "port": 8080}}
        override = {"server": {"port": 9090}}
        result = merge_settings(base, override)
        self.assertEqual(result["server"]["host"], "localhost")
        self.assertEqual(result["server"]["port"], 9090)

    def test_merge_list_override(self):
        """Lists are replaced, not merged."""
        base = {"items": [1, 2]}
        override = {"items": [3, 4]}
        result = merge_settings(base, override)
        self.assertEqual(result["items"], [3, 4])

    def test_safe_json_load_valid(self):
        """Valid JSON loads correctly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value"}, f)
            path = f.name
        try:
            result = safe_json_load(path, default={})
            self.assertEqual(result, {"key": "value"})
        finally:
            os.unlink(path)

    def test_safe_json_load_missing(self):
        """Missing file returns default."""
        result = safe_json_load("/nonexistent/path.json", default={"fallback": True})
        self.assertEqual(result, {"fallback": True})

    def test_safe_json_load_invalid(self):
        """Invalid JSON returns default."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not json {")
            path = f.name
        try:
            result = safe_json_load(path, default={"fallback": True})
            self.assertEqual(result, {"fallback": True})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
