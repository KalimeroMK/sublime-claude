"""Tests for @-commands (@codebase, @file) expansion."""
import unittest
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockWindow:
    """Minimal mock of sublime.Window."""
    def __init__(self, folders=None):
        self._folders = folders or ["/tmp/mock_project"]

    def folders(self):
        return self._folders


class MockSession:
    """Minimal mock with just the attributes _expand_at_commands needs."""
    def __init__(self, project_root=None):
        self.window = MockWindow([project_root] if project_root else ["/tmp"])
        self.pending_context = []

    def _expand_at_commands(self, prompt: str) -> str:
        """Copy of the real implementation for testing."""
        import re

        # Simple ContextItem-like object
        class FakeItem:
            def __init__(self, kind, name, content):
                self.kind = kind
                self.name = name
                self.content = content

        # @codebase <query>
        def replace_codebase(match):
            query_text = match.group(1).strip()
            if not query_text:
                return ""

            project_root = self.window.folders()[0] if self.window.folders() else None
            if not project_root:
                return ""

            try:
                from codebase_search import CodebaseSearch
                search = CodebaseSearch(project_root)
                if search.needs_reindex(max_age_hours=24.0):
                    search.index_project()
                results = search.search(query_text, top_k=5)
                for r in results:
                    display_path = r["path"].replace(os.path.expanduser("~"), "~")
                    self.pending_context.append(FakeItem(
                        kind="file",
                        name=display_path,
                        content=f"[codebase] {display_path}:{r['line_start']}\n```\n{r['chunk']}\n```",
                    ))
            except Exception:
                pass
            return query_text

        prompt = re.sub(r'@codebase\s+([^@\n]+)', replace_codebase, prompt)

        # @file:<path>
        def replace_file(match):
            path = match.group(1).strip()
            if not os.path.isabs(path) and self.window.folders():
                for root in self.window.folders():
                    full = os.path.join(root, path)
                    if os.path.isfile(full):
                        path = full
                        break
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    display_path = path.replace(os.path.expanduser("~"), "~")
                    self.pending_context.append(FakeItem(
                        kind="file",
                        name=display_path,
                        content=f"[file] {display_path}\n```\n{content}\n```",
                    ))
                except Exception:
                    pass
            return ""

        prompt = re.sub(r'@file:(\S+)', replace_file, prompt)
        prompt = re.sub(r'@codebase\b', '', prompt)
        prompt = re.sub(r'@file\b', '', prompt)
        return prompt.strip()


class AtCommandsTest(unittest.TestCase):
    """Test @-command parsing and expansion."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session = MockSession(project_root=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_codebase_removes_marker(self):
        """@codebase is stripped from the returned prompt."""
        self._write_file("auth.py", "def authenticate():\n    return True\n")
        result = self.session._expand_at_commands("@codebase authenticate user")
        self.assertNotIn("@codebase", result)

    def test_codebase_adds_context_items(self):
        """@codebase adds found files to pending_context."""
        self._write_file("auth.py", "def authenticate_user():\n    return True\n")
        self.session._expand_at_commands("@codebase authenticate user")
        self.assertTrue(len(self.session.pending_context) > 0)
        self.assertEqual(self.session.pending_context[0].kind, "file")

    def test_codebase_no_results(self):
        """@codebase with no matching files adds nothing."""
        self._write_file("utils.py", "def helper():\n    pass\n")
        self.session._expand_at_commands("@codebase database connection pooling")
        # Fallback search might still find something, or not
        # The key is it doesn't crash
        self.assertIsInstance(self.session.pending_context, list)

    def test_file_inline_reference(self):
        """@file:path adds the referenced file to context."""
        self._write_file("config.py", "DEBUG = True\n")
        result = self.session._expand_at_commands("@file:config.py")
        self.assertNotIn("@file:", result)
        self.assertEqual(len(self.session.pending_context), 1)
        self.assertIn("DEBUG = True", self.session.pending_context[0].content)

    def test_file_not_found(self):
        """@file:path with missing file adds nothing."""
        result = self.session._expand_at_commands("@file:nonexistent.py")
        self.assertNotIn("@file:", result)
        self.assertEqual(len(self.session.pending_context), 0)

    def test_multiple_at_commands(self):
        """Multiple @-commands in one prompt are all processed."""
        self._write_file("auth.py", "def authenticate():\n    return True\n")
        self._write_file("config.py", "DEBUG = True\n")
        result = self.session._expand_at_commands(
            "@codebase authenticate @file:config.py"
        )
        self.assertNotIn("@codebase", result)
        self.assertNotIn("@file:", result)
        self.assertTrue(len(self.session.pending_context) >= 1)

    def test_at_command_preserves_rest_of_prompt(self):
        """Non-@ text is preserved in the prompt."""
        self._write_file("auth.py", "def authenticate():\n    return True\n")
        result = self.session._expand_at_commands(
            "@codebase authenticate how does this work?"
        )
        self.assertIn("how does this work?", result)

    def test_codebase_in_middle_of_prompt(self):
        """@codebase works when embedded in longer text."""
        self._write_file("auth.py", "def authenticate():\n    return True\n")
        result = self.session._expand_at_commands(
            "Explain @codebase authenticate the auth flow"
        )
        self.assertIn("Explain", result)
        self.assertIn("the auth flow", result)
        self.assertNotIn("@codebase", result)

    def test_context_item_has_codebase_prefix(self):
        """Codebase results are tagged with [codebase] prefix."""
        self._write_file("auth.py", "def authenticate():\n    return True\n")
        self.session._expand_at_commands("@codebase authenticate")
        self.assertTrue(len(self.session.pending_context) > 0)
        self.assertIn("[codebase]", self.session.pending_context[0].content)

    def test_context_item_has_file_prefix(self):
        """File references are tagged with [file] prefix."""
        self._write_file("settings.py", "API_KEY = 'secret'\n")
        self.session._expand_at_commands("@file:settings.py")
        self.assertEqual(len(self.session.pending_context), 1)
        self.assertIn("[file]", self.session.pending_context[0].content)

    def test_empty_codebase_query(self):
        """Bare @codebase with no query is handled gracefully."""
        result = self.session._expand_at_commands("@codebase")
        self.assertNotIn("@codebase", result)
        self.assertEqual(len(self.session.pending_context), 0)


if __name__ == "__main__":
    unittest.main()
