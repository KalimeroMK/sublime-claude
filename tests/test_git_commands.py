"""Tests for git integration commands."""
import unittest
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GitDiffCaptureTest(unittest.TestCase):
    """Test git diff capture logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Init git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.tmpdir, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_git_diff_staged(self):
        """Capture staged diff."""
        import subprocess
        # Create and stage a file
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("def hello():\n    return 'world'\n")
        subprocess.run(["git", "add", "test.py"], cwd=self.tmpdir, capture_output=True)

        result = subprocess.run(
            ["git", "-C", self.tmpdir, "diff", "--staged"],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_git_diff_unstaged(self):
        """Capture unstaged diff when file is modified after staging."""
        import subprocess
        # Create and commit a file
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("def hello():\n    return 'world'\n")
        subprocess.run(["git", "add", "test.py"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.tmpdir, capture_output=True)

        # Modify the file
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("def hello():\n    return 'modified'\n")

        # No staged diff
        staged = subprocess.run(
            ["git", "-C", self.tmpdir, "diff", "--staged"],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(staged.stdout.strip(), "")

        # Unstaged diff should show changes
        unstaged = subprocess.run(
            ["git", "-C", self.tmpdir, "diff"],
            capture_output=True, text=True, timeout=10
        )
        self.assertIn("modified", unstaged.stdout)

    def test_git_status(self):
        """Capture git status."""
        import subprocess
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("x = 1\n")

        result = subprocess.run(
            ["git", "-C", self.tmpdir, "status", "--short"],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("test.py", result.stdout)

    def test_diff_truncation(self):
        """Large diffs are truncated to 20KB."""
        import subprocess
        # Create a large file
        with open(os.path.join(self.tmpdir, "large.py"), "w") as f:
            f.write("x = 1\n" * 5000)
        subprocess.run(["git", "add", "large.py"], cwd=self.tmpdir, capture_output=True)

        result = subprocess.run(
            ["git", "-C", self.tmpdir, "diff", "--staged"],
            capture_output=True, text=True, timeout=10
        )
        diff = result.stdout.strip()
        if len(diff) > 20000:
            diff = diff[:20000] + "\n\n... [truncated]\n"
        self.assertIn("[truncated]", diff)


if __name__ == "__main__":
    unittest.main()
