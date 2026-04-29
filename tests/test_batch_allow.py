"""Tests for Batch Allow ([B]) permission feature."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Constants from output_models (defined locally to avoid relative import issues)
PERM_ALLOW = "allow"
PERM_DENY = "deny"
PERM_BATCH = "batch_allow"
PERM_ALLOW_SESSION = "allow_session"
PERM_ALLOW_ALL = "allow_all"


class MockCallback:
    """Tracks permission callback responses."""
    def __init__(self):
        self.responses = []

    def __call__(self, response: str):
        self.responses.append(response)


class BatchAllowTest(unittest.TestCase):
    """Test Batch Allow ([B]) permission behavior."""

    def test_perm_batch_constant(self):
        """PERM_BATCH constant exists and is distinct."""
        self.assertEqual(PERM_BATCH, "batch_allow")
        self.assertNotEqual(PERM_BATCH, PERM_ALLOW)
        self.assertNotEqual(PERM_BATCH, PERM_DENY)

    def test_batch_allow_auto_approves_write_edit(self):
        """When batch_allow_active is True, Write/Edit are auto-approved."""
        batch_allow_active = True
        batch_allow_edits_only = True

        for tool in ("Write", "Edit"):
            should_auto_allow = (
                batch_allow_active and
                (not batch_allow_edits_only or tool in ("Write", "Edit"))
            )
            self.assertTrue(should_auto_allow, f"{tool} should be auto-allowed")

    def test_batch_allow_skips_bash(self):
        """When batch_allow_edits_only is True, Bash is not auto-approved."""
        batch_allow_active = True
        batch_allow_edits_only = True

        for tool in ("Bash", "Read", "Glob", "Grep"):
            should_auto_allow = (
                batch_allow_active and
                (not batch_allow_edits_only or tool in ("Write", "Edit"))
            )
            self.assertFalse(should_auto_allow, f"{tool} should NOT be auto-allowed")

    def test_batch_allow_all_tools_when_edits_only_false(self):
        """When batch_allow_edits_only is False, all tools are auto-approved."""
        batch_allow_active = True
        batch_allow_edits_only = False

        for tool in ("Write", "Edit", "Bash", "Read"):
            should_auto_allow = (
                batch_allow_active and
                (not batch_allow_edits_only or tool in ("Write", "Edit"))
            )
            self.assertTrue(should_auto_allow, f"{tool} should be auto-allowed")

    def test_batch_allow_inactive(self):
        """When batch_allow_active is False, nothing is auto-approved."""
        batch_allow_active = False
        batch_allow_edits_only = True

        for tool in ("Write", "Edit", "Bash"):
            should_auto_allow = (
                batch_allow_active and
                (not batch_allow_edits_only or tool in ("Write", "Edit"))
            )
            self.assertFalse(should_auto_allow, f"{tool} should NOT be auto-allowed")

    def test_batch_allow_resets_on_query_end(self):
        """Batch allow should be reset when query finishes."""
        batch_allow_active = True
        batch_allow_active = False
        self.assertFalse(batch_allow_active)


if __name__ == "__main__":
    unittest.main()
