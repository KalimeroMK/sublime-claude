"""Tests for error handling utilities."""
import unittest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_handler import safe_json_load


class ErrorHandlerTest(unittest.TestCase):
    """Test safe_json_load."""

    def test_load_valid_json(self):
        """Valid JSON loads correctly."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump({"key": "value"}, f)
            path = f.name
        try:
            result = safe_json_load(path)
            self.assertEqual(result, {"key": "value"})
        finally:
            os.unlink(path)

    def test_missing_file_returns_default(self):
        """Missing file returns default dict."""
        result = safe_json_load("/nonexistent/path.json")
        self.assertEqual(result, {})

    def test_missing_file_returns_custom_default(self):
        """Missing file returns custom default."""
        result = safe_json_load("/nonexistent/path.json", default=[])
        self.assertEqual(result, [])

    def test_invalid_json_returns_default(self):
        """Invalid JSON returns default."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            f.write("not json")
            path = f.name
        try:
            result = safe_json_load(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
