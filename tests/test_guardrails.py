"""Tests for guardrails / pre-flight checks.

These tests import bridge/main.py directly and validate the real guardrail
methods on the Bridge class. Requires Python 3.10+.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest

# Ensure bridge and project root are on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import Bridge  # noqa: E402


class GuardrailsTest(unittest.TestCase):
    """Test guardrail validation using the real Bridge class."""

    def setUp(self):
        """Create a Bridge instance with a temp cwd."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)

        self.bridge = Bridge()
        self.bridge.cwd = self.temp_dir

        # Write guardrails config into .claude/settings.json
        self.claude_dir = os.path.join(self.temp_dir, ".claude")
        os.makedirs(self.claude_dir, exist_ok=True)
        self.settings_path = os.path.join(self.claude_dir, "settings.json")

    def _write_settings(self, guardrails: dict):
        """Write guardrails config to the temp project settings."""
        with open(self.settings_path, "w") as f:
            json.dump({"guardrails": guardrails}, f)

    def test_load_guardrails_empty(self):
        """Empty settings return empty guardrails."""
        guardrails = self.bridge._load_guardrails()
        self.assertEqual(guardrails, {})

    def test_load_guardrails_with_config(self):
        """Guardrails config is loaded from project settings."""
        self._write_settings({
            "blocked_commands": ["rm -rf"],
            "require_approval_for": ["git push"]
        })
        guardrails = self.bridge._load_guardrails()
        self.assertEqual(guardrails["blocked_commands"], ["rm -rf"])
        self.assertEqual(guardrails["require_approval_for"], ["git push"])

    def test_validate_safe_command(self):
        """Safe commands pass validation."""
        is_safe, warning = self.bridge._validate_bash_command("ls -la")
        self.assertTrue(is_safe)
        self.assertEqual(warning, "")

    def test_validate_rm_rf_root(self):
        """rm -rf / is blocked."""
        is_safe, warning = self.bridge._validate_bash_command("rm -rf /")
        self.assertFalse(is_safe)
        self.assertIn("Dangerous rm command", warning)

    def test_validate_rm_rf_parent(self):
        """rm -rf with .. is blocked."""
        is_safe, warning = self.bridge._validate_bash_command("rm -rf ../")
        self.assertFalse(is_safe)
        self.assertIn("parent directory", warning)

    def test_validate_blocked_git_force_push(self):
        """Blocked commands from guardrails are denied."""
        self._write_settings({
            "blocked_commands": ["git push --force"]
        })
        is_safe, warning = self.bridge._validate_bash_command("git push --force origin main")
        self.assertFalse(is_safe)
        self.assertIn("blocked by guardrail", warning.lower())

    def test_validate_blocked_rm_rf(self):
        """rm -rf can be blocked via guardrails."""
        self._write_settings({
            "blocked_commands": ["rm -rf"]
        })
        is_safe, warning = self.bridge._validate_bash_command("rm -rf node_modules")
        self.assertFalse(is_safe)
        self.assertIn("blocked by guardrail", warning.lower())

    def test_validate_no_block_without_config(self):
        """Without guardrails config, git push is not blocked."""
        is_safe, warning = self.bridge._validate_bash_command("git push origin main")
        self.assertTrue(is_safe)

    def test_pre_flight_pass(self):
        """Pre-flight checks that pass return success."""
        self._write_settings({
            "pre_flight_checks": {
                "git push": ["echo 'tests passed'"]
            }
        })
        passed, message = asyncio.run(self.bridge._run_pre_flight_checks("git push origin main"))
        self.assertTrue(passed)
        self.assertIn("passed", message)

    def test_pre_flight_fail(self):
        """Pre-flight checks that fail return error."""
        self._write_settings({
            "pre_flight_checks": {
                "git push": ["exit 1"]
            }
        })
        passed, message = asyncio.run(self.bridge._run_pre_flight_checks("git push origin main"))
        self.assertFalse(passed)
        self.assertIn("FAILED", message)

    def test_pre_flight_no_match(self):
        """Commands without pre-flight config skip checks."""
        passed, message = asyncio.run(self.bridge._run_pre_flight_checks("ls -la"))
        self.assertTrue(passed)
        self.assertEqual(message, "")

    def test_pre_flight_multiple_checks(self):
        """Multiple pre-flight checks run in order."""
        self._write_settings({
            "pre_flight_checks": {
                "git push": ["echo 'test 1'", "echo 'test 2'"]
            }
        })
        passed, message = asyncio.run(self.bridge._run_pre_flight_checks("git push"))
        self.assertTrue(passed)
        self.assertIn("test 1", message)
        self.assertIn("test 2", message)

    def test_pre_flight_phpstan_example(self):
        """Real-world example: script before git push."""
        script = os.path.join(self.temp_dir, "test_pass.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\necho 'All tests pass!'")
        os.chmod(script, 0o755)

        self._write_settings({
            "pre_flight_checks": {
                "git push": [script]
            }
        })
        passed, message = asyncio.run(self.bridge._run_pre_flight_checks("git push origin main"))
        self.assertTrue(passed)
        self.assertIn("passed", message)


if __name__ == "__main__":
    unittest.main()
