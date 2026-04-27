"""Tests for error handling utilities."""
import unittest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_handler import handle_json_error, handle_file_error


class ErrorHandlerTest(unittest.TestCase):
    """Test error handling decorators."""

    def test_json_error_returns_default(self):
        """JSON error returns default value."""
        @handle_json_error(default={"fallback": True})
        def parse_bad_json():
            return json.loads("not json")
        
        result = parse_bad_json()
        self.assertEqual(result, {"fallback": True})

    def test_json_error_returns_error_dict(self):
        """JSON error returns error dict when no default."""
        @handle_json_error()
        def parse_bad_json():
            return json.loads("not json")
        
        result = parse_bad_json()
        self.assertIn("error", result)
        self.assertIn("Invalid JSON", result["error"])

    def test_json_success_passthrough(self):
        """Valid JSON passes through normally."""
        @handle_json_error(default={"fallback": True})
        def parse_good_json():
            return json.loads('{"key": "value"}')
        
        result = parse_good_json()
        self.assertEqual(result, {"key": "value"})

    def test_file_error_returns_default(self):
        """File error returns default value."""
        @handle_file_error(default="default_content")
        def read_missing():
            with open("/nonexistent/path.txt") as f:
                return f.read()
        
        result = read_missing()
        self.assertEqual(result, "default_content")

    def test_file_error_returns_error_dict(self):
        """File error returns error dict when no default."""
        @handle_file_error()
        def read_missing():
            with open("/nonexistent/path.txt") as f:
                return f.read()
        
        result = read_missing()
        self.assertIn("error", result)

    def test_file_success_passthrough(self):
        """Valid file operation passes through."""
        import tempfile
        
        @handle_file_error(default="fallback")
        def read_temp():
            with open(temp_path) as f:
                return f.read()
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("hello")
            temp_path = f.name
        
        try:
            result = read_temp()
            self.assertEqual(result, "hello")
        finally:
            os.unlink(temp_path)

    def test_generic_exception_returns_default(self):
        """Generic exceptions are caught too."""
        @handle_json_error(default="fallback")
        def raise_error():
            raise ValueError("something broke")
        
        result = raise_error()
        self.assertEqual(result, "fallback")

    def test_error_dict_contains_message(self):
        """Error dict contains the exception message."""
        @handle_json_error()
        def raise_specific():
            raise RuntimeError("specific error")
        
        result = raise_specific()
        self.assertIn("specific error", result["error"])


if __name__ == "__main__":
    unittest.main()
