"""Tests for bridge/terminal.py"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))

from terminal import TerminalManager, strip_ansi


class TerminalManagerTest(unittest.TestCase):
    def test_strip_ansi(self):
        raw = "\x1b[32mhello\x1b[0m \x1b[1mworld\x1b[0m"
        self.assertEqual(strip_ansi(raw), "hello world")

    def test_strip_ansi_empty(self):
        self.assertEqual(strip_ansi(""), "")
        self.assertEqual(strip_ansi("no codes"), "no codes")

    def test_terminal_start_stop(self):
        """Terminal can start and stop without error."""
        term = TerminalManager()
        term.start()
        # Give shell time to start
        time.sleep(0.2)
        self.assertTrue(term._running)
        self.assertIsNotNone(term._pid)
        term.stop()
        self.assertFalse(term._running)
        self.assertIsNone(term._pid)

    def test_terminal_write_read(self):
        """Writing to terminal produces readable output."""
        term = TerminalManager()
        term.start()
        time.sleep(0.2)

        term.write("echo 'hello from test'\n")
        time.sleep(0.3)
        output = term.read()
        self.assertIn("hello from test", output)

        term.stop()

    def test_terminal_buffer_limit(self):
        """Buffer respects max_buffer_chars."""
        term = TerminalManager(max_buffer_chars=100)
        term.start()
        time.sleep(0.2)

        # Write a long string
        term.write("echo 'A' * 200\n")
        time.sleep(0.3)

        # Buffer should be limited
        output = term.read()
        self.assertLessEqual(len(output), 100)

        term.stop()

    def test_terminal_callback(self):
        """Callback receives output chunks."""
        received = []

        def on_output(text):
            received.append(text)

        term = TerminalManager(on_output=on_output)
        term.start()
        time.sleep(0.2)

        term.write("echo 'callback_test'\n")
        time.sleep(0.3)

        # Should have received some output
        self.assertTrue(len(received) > 0)
        full = "".join(received)
        self.assertIn("callback_test", full)

        term.stop()


if __name__ == "__main__":
    unittest.main()
