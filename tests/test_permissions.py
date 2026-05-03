"""Tests for the shared permissions module."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from permissions import (
    parse_permission_pattern,
    extract_bash_commands,
    make_auto_allow_pattern,
    match_permission_pattern,
)


class ParsePermissionPatternTest(unittest.TestCase):
    def test_simple_tool(self):
        self.assertEqual(parse_permission_pattern("Bash"), ("Bash", None))

    def test_tool_with_specifier(self):
        self.assertEqual(parse_permission_pattern("Bash(git:*)"), ("Bash", "git:*"))

    def test_read_with_path(self):
        self.assertEqual(parse_permission_pattern("Read(/src/**)"), ("Read", "/src/**"))


class ExtractBashCommandsTest(unittest.TestCase):
    def test_simple_command(self):
        self.assertEqual(extract_bash_commands("git status"), ["git"])

    def test_chain(self):
        self.assertEqual(extract_bash_commands("cd /tmp && git status"), ["cd", "git"])

    def test_pipes(self):
        self.assertEqual(extract_bash_commands("cat file | grep foo"), ["cat", "grep"])

    def test_env_vars(self):
        self.assertEqual(extract_bash_commands("FOO=bar make build"), ["make"])

    def test_wrappers(self):
        self.assertEqual(extract_bash_commands("timeout --signal=TERM 30 python script.py"), ["python"])

    def test_xargs(self):
        self.assertEqual(extract_bash_commands("find . | xargs rm"), ["find", "rm"])

    def test_path_prefix(self):
        self.assertEqual(extract_bash_commands("/usr/bin/git status"), ["git"])


class MakeAutoAllowPatternTest(unittest.TestCase):
    def test_bash_simple(self):
        self.assertEqual(
            make_auto_allow_pattern("Bash", {"command": "git status"}),
            "Bash(git:*)"
        )

    def test_bash_trivial_skipped(self):
        self.assertEqual(
            make_auto_allow_pattern("Bash", {"command": "cd /tmp && git status"}),
            "Bash(git:*)"
        )

    def test_read(self):
        self.assertEqual(
            make_auto_allow_pattern("Read", {"file_path": "/project/src/main.py"}),
            "Read(/project/src/)"
        )

    def test_skill(self):
        self.assertEqual(
            make_auto_allow_pattern("Skill", {"skill": "my-skill"}),
            "Skill(my-skill)"
        )

    def test_other_tool(self):
        self.assertEqual(make_auto_allow_pattern("Glob", {"pattern": "*.py"}), "Glob")


class MatchPermissionPatternTest(unittest.TestCase):
    def test_simple_tool_match(self):
        self.assertTrue(match_permission_pattern("Bash", {"command": "ls"}, "Bash"))

    def test_tool_name_mismatch(self):
        self.assertFalse(match_permission_pattern("Read", {"file_path": "/a"}, "Bash"))

    def test_bash_prefix_match(self):
        self.assertTrue(match_permission_pattern("Bash", {"command": "git status"}, "Bash(git:*)"))

    def test_bash_prefix_no_match(self):
        self.assertFalse(match_permission_pattern("Bash", {"command": "ls -la"}, "Bash(git:*)"))

    def test_bash_exact_match(self):
        self.assertTrue(match_permission_pattern("Bash", {"command": "git status"}, "Bash(git status)"))

    def test_bash_glob_match(self):
        self.assertTrue(match_permission_pattern("Bash", {"command": "git status"}, "Bash(git*)"))

    def test_read_directory_match(self):
        self.assertTrue(match_permission_pattern("Read", {"file_path": "/src/main.py"}, "Read(/src/)"))

    def test_read_same_dir(self):
        self.assertTrue(match_permission_pattern("Read", {"file_path": "/src/bar.py"}, "Read(/src/foo.py)"))

    def test_read_exact_match(self):
        self.assertTrue(match_permission_pattern("Read", {"file_path": "/src/foo.py"}, "Read(/src/foo.py)"))

    def test_read_glob_match(self):
        self.assertTrue(match_permission_pattern("Read", {"file_path": "/src/main.py"}, "Read(/src/*.py)"))

    def test_skill_match(self):
        self.assertTrue(match_permission_pattern("Skill", {"skill": "my-skill"}, "Skill(my-skill)"))

    def test_wildcard_tool_name(self):
        self.assertTrue(match_permission_pattern("mcp__foo__", {}, "mcp__*__"))

    def test_webfetch_prefix(self):
        self.assertTrue(match_permission_pattern('WebFetch', {'url': 'https://example.com/page'}, 'WebFetch(https://example.com/:*)'))


if __name__ == "__main__":
    unittest.main()
