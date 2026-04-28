"""Tests for codebase_search.py TF-IDF search."""
import unittest
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codebase_search import CodebaseSearch, STOPWORDS


class CodebaseSearchTest(unittest.TestCase):
    """Test CodebaseSearch TF-IDF indexing and search."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.search = CodebaseSearch(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_init_creates_db(self):
        """Initialization creates SQLite database."""
        self.assertTrue(os.path.exists(self.search.db_path))

    def test_needs_reindex_empty(self):
        """Empty index needs reindexing."""
        self.assertTrue(self.search.needs_reindex())

    def test_index_single_file(self):
        """Indexing a file stores words."""
        self._write_file("test.py", "def authenticate():\n    return True\n")
        count = self.search.index_project(extensions=(".py",))
        self.assertEqual(count, 1)

    def test_search_finds_relevant_file(self):
        """Search returns relevant files by keyword."""
        self._write_file("auth.py", "def authenticate_user():\n    return True\n")
        self._write_file("utils.py", "def helper():\n    pass\n")
        self.search.index_project(extensions=(".py",))

        results = self.search.search("authenticate user")
        self.assertTrue(len(results) > 0)
        self.assertIn("auth.py", results[0]["path"])

    def test_search_no_results(self):
        """Search with no matching keywords returns empty."""
        self._write_file("auth.py", "def authenticate():\n    pass\n")
        self.search.index_project(extensions=(".py",))

        results = self.search.search("database connection pooling")
        self.assertEqual(len(results), 0)

    def test_search_returns_chunk(self):
        """Search result includes code chunk with line numbers."""
        content = "\n".join(f"line {i}" for i in range(50))
        content += "\ndef authenticate():\n    return True\n"
        self._write_file("auth.py", content)
        self.search.index_project(extensions=(".py",))

        results = self.search.search("authenticate")
        self.assertTrue(len(results) > 0)
        self.assertIn("chunk", results[0])
        self.assertIn("line_start", results[0])
        self.assertIn("path", results[0])
        self.assertIn("score", results[0])

    def test_fallback_search_no_index(self):
        """Fallback search works when no index exists."""
        # Delete the DB
        if os.path.exists(self.search.db_path):
            os.remove(self.search.db_path)

        self._write_file("auth.py", "def authenticate():\n    return True\n")
        results = self.search.search("authenticate")
        self.assertTrue(len(results) > 0)
        self.assertIn("auth.py", results[0]["path"])

    def test_extract_keywords_filters_stopwords(self):
        """Keyword extraction removes stopwords."""
        keywords = self.search._extract_keywords("how does the authentication work")
        for sw in ("how", "does", "the", "work"):
            self.assertNotIn(sw, keywords)
        self.assertIn("authentication", keywords)

    def test_extract_keywords_camelcase(self):
        """Keyword extraction splits CamelCase."""
        keywords = self.search._extract_keywords("AuthController login")
        self.assertIn("auth", keywords)
        self.assertIn("controller", keywords)

    def test_skip_vendor_dirs(self):
        """Indexing skips vendor/node_modules."""
        vendor_dir = os.path.join(self.tmpdir, "vendor")
        os.makedirs(vendor_dir)
        self._write_file("vendor/lib.py", "def secret(): pass\n")
        self._write_file("app.py", "def app(): pass\n")

        count = self.search.index_project(extensions=(".py",))
        self.assertEqual(count, 1)  # Only app.py

    def test_skip_large_files(self):
        """Indexing skips files > 500KB."""
        self._write_file("huge.py", "x" * 600000)
        self._write_file("small.py", "def small(): pass\n")

        count = self.search.index_project(extensions=(".py",))
        self.assertEqual(count, 1)  # Only small.py


if __name__ == "__main__":
    unittest.main()
