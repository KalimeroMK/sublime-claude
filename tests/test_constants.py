"""Tests for constants and configuration values."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    APP_NAME, DEFAULT_SESSION_NAME, PLUGIN_NAME,
    USER_SETTINGS_DIR, USER_SETTINGS_FILE, USER_PROFILES_DIR,
    PROJECT_SETTINGS_DIR, PROJECT_SUBLIME_TOOLS_DIR,
    SETTINGS_FILE, PROFILES_FILE, SESSIONS_FILE, MCP_CONFIG_FILE,
    MCP_SOCKET_PATH, BRIDGE_LOG_PATH, LOG_PREFIX_INFO, LOG_PREFIX_ERROR,
    OUTPUT_VIEW_SETTING, FONT_SIZE,
    STATUS_ACTIVE_WORKING, STATUS_ACTIVE_IDLE,
    STATUS_INACTIVE_WORKING, STATUS_INACTIVE_IDLE,
    SPINNER_FRAMES, INPUT_MARKER,
)


class ConstantsTest(unittest.TestCase):
    """Test constants are correctly defined."""

    def test_app_name(self):
        self.assertEqual(APP_NAME, "Claude")

    def test_default_session_name(self):
        self.assertEqual(DEFAULT_SESSION_NAME, "Claude")

    def test_plugin_name(self):
        self.assertEqual(PLUGIN_NAME, "ClaudeCode")

    def test_user_settings_dir_is_path(self):
        self.assertTrue(str(USER_SETTINGS_DIR).endswith(".claude"))

    def test_user_settings_file_is_json(self):
        self.assertTrue(str(USER_SETTINGS_FILE).endswith(".claude.json"))

    def test_project_settings_dir(self):
        self.assertEqual(PROJECT_SETTINGS_DIR, ".claude")

    def test_settings_file(self):
        self.assertEqual(SETTINGS_FILE, "settings.json")

    def test_sessions_file(self):
        self.assertEqual(SESSIONS_FILE, ".sessions.json")

    def test_mcp_config_file(self):
        self.assertEqual(MCP_CONFIG_FILE, ".mcp.json")

    def test_mcp_socket_path(self):
        self.assertTrue(MCP_SOCKET_PATH.startswith("/tmp/"))

    def test_bridge_log_path(self):
        self.assertTrue(BRIDGE_LOG_PATH.startswith("/tmp/"))

    def test_log_prefixes(self):
        self.assertEqual(LOG_PREFIX_INFO, "  ")
        self.assertEqual(LOG_PREFIX_ERROR, "ERROR: ")

    def test_output_view_setting(self):
        self.assertEqual(OUTPUT_VIEW_SETTING, "claude_output")

    def test_font_size(self):
        self.assertEqual(FONT_SIZE, 12)

    def test_status_indicators(self):
        """Status indicators are single unicode characters."""
        self.assertEqual(STATUS_ACTIVE_WORKING, "◉")
        self.assertEqual(STATUS_ACTIVE_IDLE, "◇")
        self.assertEqual(STATUS_INACTIVE_WORKING, "•")
        self.assertEqual(STATUS_INACTIVE_IDLE, "")

    def test_spinner_frames(self):
        """Spinner has 10 frames."""
        self.assertEqual(len(SPINNER_FRAMES), 10)

    def test_input_marker(self):
        self.assertEqual(INPUT_MARKER, "◎ ")

    def test_constants_are_strings(self):
        """All main string constants are non-empty."""
        self.assertTrue(len(APP_NAME) > 0)
        self.assertTrue(len(PLUGIN_NAME) > 0)
        self.assertTrue(len(SETTINGS_FILE) > 0)


if __name__ == "__main__":
    unittest.main()
