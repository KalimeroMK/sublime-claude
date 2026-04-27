"""Tests for logging utilities."""
import unittest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import Logger


class LoggerTest(unittest.TestCase):
    """Test logger functionality."""

    def setUp(self):
        self.temp_log = tempfile.NamedTemporaryFile(mode='w', delete=False)
        self.temp_log.close()
        self.logger = Logger(self.temp_log.name)

    def tearDown(self):
        if os.path.exists(self.temp_log.name):
            os.unlink(self.temp_log.name)

    def test_log_writes_message(self):
        """Log writes message to file."""
        self.logger.log("test message")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("test message", content)

    def test_info_prefix(self):
        """Info uses correct prefix."""
        self.logger.info("info msg")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("  info msg", content)

    def test_error_prefix(self):
        """Error uses correct prefix."""
        self.logger.error("error msg")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("ERROR: error msg", content)

    def test_debug_prefix(self):
        """Debug uses correct prefix."""
        self.logger.debug("debug msg")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("DEBUG: debug msg", content)

    def test_custom_prefix(self):
        """Custom prefix can be specified."""
        self.logger.log("msg", prefix="[CUSTOM] ")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("[CUSTOM] msg", content)

    def test_separator(self):
        """Separator writes line of characters."""
        self.logger.separator(char="-", length=10)
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("----------", content)
        self.assertNotIn("----------\n----------", content)

    def test_multiple_messages(self):
        """Multiple messages are on separate lines."""
        self.logger.info("first")
        self.logger.info("second")
        with open(self.temp_log.name) as f:
            lines = f.read().strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_clear_removes_file(self):
        """Clear removes the log file."""
        self.logger.info("before")
        self.logger.clear()
        self.assertFalse(os.path.exists(self.temp_log.name))

    def test_logger_does_not_fail_on_bad_path(self):
        """Logger silently fails on unwritable path."""
        bad_logger = Logger("/nonexistent/dir/log.txt")
        bad_logger.info("should not crash")

    def test_default_prefix(self):
        """Default prefix is used when none specified."""
        custom_logger = Logger(self.temp_log.name, prefix="[APP] ")
        custom_logger.log("msg")
        with open(self.temp_log.name) as f:
            content = f.read()
        self.assertIn("[APP] msg", content)


if __name__ == "__main__":
    unittest.main()
