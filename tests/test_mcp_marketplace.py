"""Tests for MCP Marketplace command."""
import unittest
import sys
import os
import types
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch

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


class McpMarketplaceTest(unittest.TestCase):
    """Test MCP Marketplace command."""

    def setUp(self):
        """Create temp directory for config tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)

    def test_load_marketplace_empty(self):
        """Empty/nonexistent marketplace returns empty dict."""
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd._MARKETPLACE_PATH = os.path.join(self.temp_dir, "nonexistent.json")
        result = cmd._load_marketplace()
        self.assertEqual(result, {})

    def test_load_marketplace_valid(self):
        """Valid marketplace JSON returns servers dict."""
        marketplace = {
            "servers": {
                "fetch": {"name": "Web Fetch", "install_type": "npm"},
                "git": {"name": "Git", "install_type": "npm"}
            }
        }
        path = os.path.join(self.temp_dir, "marketplace.json")
        with open(path, "w") as f:
            json.dump(marketplace, f)

        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd._MARKETPLACE_PATH = path
        result = cmd._load_marketplace()
        self.assertEqual(len(result), 2)
        self.assertEqual(result["fetch"]["name"], "Web Fetch")
        self.assertEqual(result["git"]["name"], "Git")

    def test_load_marketplace_invalid_json(self):
        """Invalid JSON returns empty dict."""
        path = os.path.join(self.temp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not json")

        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd._MARKETPLACE_PATH = path
        result = cmd._load_marketplace()
        self.assertEqual(result, {})

    def test_get_config_path_project(self):
        """With project folder, returns .mcp.json in project root."""
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = ["/my/project"]
        path = cmd._get_config_path()
        self.assertEqual(path, "/my/project/.mcp.json")

    def test_get_config_path_no_project(self):
        """Without project folder, returns ~/.claude.json."""
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = []
        path = cmd._get_config_path()
        self.assertEqual(path, os.path.expanduser("~/.claude.json"))

    def test_command_exists_found(self):
        """Existing command returns True."""
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        self.assertTrue(cmd._command_exists("python3"))

    def test_command_exists_not_found(self):
        """Nonexistent command returns False."""
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        self.assertFalse(cmd._command_exists("not_a_real_command_12345"))

    def test_install_server_creates_config(self):
        """Install creates new config file with server entry."""
        config_path = os.path.join(self.temp_dir, ".mcp.json")
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = [self.temp_dir]

        server_info = {
            "name": "Test Server",
            "install_type": "npm",
            "package": "@test/server",
            "runtime": "npx",
            "args": ["-y", "@test/server"],
            "env": {"API_KEY": "your-key"}
        }

        cmd._install_server("test-server", server_info)

        self.assertTrue(os.path.exists(config_path))
        with open(config_path, "r") as f:
            config = json.load(f)

        self.assertIn("mcpServers", config)
        self.assertIn("test-server", config["mcpServers"])
        self.assertEqual(config["mcpServers"]["test-server"]["command"], "npx")
        self.assertEqual(config["mcpServers"]["test-server"]["args"], ["-y", "@test/server"])
        self.assertEqual(config["mcpServers"]["test-server"]["env"], {"API_KEY": "your-key"})

    def test_install_server_updates_existing(self):
        """Install updates existing config without overwriting other servers."""
        config_path = os.path.join(self.temp_dir, ".mcp.json")
        existing = {"mcpServers": {"old-server": {"command": "echo", "args": ["old"]}}}
        with open(config_path, "w") as f:
            json.dump(existing, f)

        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = [self.temp_dir]

        server_info = {
            "name": "New Server",
            "install_type": "npm",
            "runtime": "npx",
            "args": ["-y", "@new/server"],
        }

        cmd._install_server("new-server", server_info)

        with open(config_path, "r") as f:
            config = json.load(f)

        self.assertIn("old-server", config["mcpServers"])
        self.assertIn("new-server", config["mcpServers"])

    def test_install_server_resolves_project_root(self):
        """${project_root} in args is replaced with actual path."""
        config_path = os.path.join(self.temp_dir, ".mcp.json")
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = [self.temp_dir]

        server_info = {
            "name": "Filesystem",
            "install_type": "npm",
            "runtime": "npx",
            "args": ["-y", "@mcp/server-filesystem", "${project_root}"],
        }

        cmd._install_server("filesystem", server_info)

        with open(config_path, "r") as f:
            config = json.load(f)

        self.assertEqual(
            config["mcpServers"]["filesystem"]["args"][2],
            self.temp_dir
        )

    def test_install_server_resolves_database_path(self):
        """${database_path} in args is replaced with default path."""
        config_path = os.path.join(self.temp_dir, ".mcp.json")
        cmd = commands_mod.ClaudeMcpMarketplaceCommand()
        cmd.window = MagicMock()
        cmd.window.folders.return_value = [self.temp_dir]

        server_info = {
            "name": "SQLite",
            "install_type": "npm",
            "runtime": "npx",
            "args": ["-y", "@mcp/server-sqlite", "${database_path}"],
        }

        cmd._install_server("sqlite", server_info)

        with open(config_path, "r") as f:
            config = json.load(f)

        expected_path = os.path.join(self.temp_dir, "data.db")
        self.assertEqual(
            config["mcpServers"]["sqlite"]["args"][2],
            expected_path
        )


if __name__ == "__main__":
    unittest.main()
