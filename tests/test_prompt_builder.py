"""Tests for prompt building utilities."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompt_builder import PromptBuilder


class PromptBuilderTest(unittest.TestCase):
    """Test prompt builder."""

    def test_empty_builder(self):
        """Empty builder returns empty string."""
        pb = PromptBuilder()
        self.assertEqual(pb.build(), "")

    def test_base_prompt(self):
        """Base prompt is included."""
        pb = PromptBuilder("Explain this code")
        self.assertEqual(pb.build(), "Explain this code")

    def test_add_text(self):
        """Text is appended."""
        pb = PromptBuilder("Base").add_text(" more")
        self.assertEqual(pb.build(), "Base more")

    def test_add_file(self):
        """File includes path and content."""
        pb = PromptBuilder().add_file("src/main.py", "print('hello')")
        result = pb.build()
        self.assertIn("File: `src/main.py`", result)
        self.assertIn("print('hello')", result)
        self.assertIn("```", result)

    def test_add_selection(self):
        """Selection includes path and content."""
        pb = PromptBuilder().add_selection("src/main.py", "def foo(): pass")
        result = pb.build()
        self.assertIn("Selection from src/main.py", result)
        self.assertIn("def foo(): pass", result)

    def test_add_folder(self):
        """Folder includes path."""
        pb = PromptBuilder().add_folder("/project/src")
        result = pb.build()
        self.assertIn("Folder: /project/src", result)

    def test_chaining(self):
        """Methods can be chained."""
        pb = (PromptBuilder("Q")
              .add_text("uestion")
              .add_file("a.py", "x = 1")
              .add_folder("/proj"))
        result = pb.build()
        self.assertIn("Question", result)
        self.assertIn("a.py", result)
        self.assertIn("/proj", result)

    def test_file_query_static(self):
        """Static file query builder works."""
        result = PromptBuilder.file_query("Explain", "main.py", "code")
        self.assertIn("Explain", result)
        self.assertIn("main.py", result)
        self.assertIn("code", result)

    def test_selection_query_static(self):
        """Static selection query builder works."""
        result = PromptBuilder.selection_query("Refactor", "main.py", "def old(): pass")
        self.assertIn("Refactor", result)
        self.assertIn("main.py", result)
        self.assertIn("def old(): pass", result)

    def test_add_context_items(self):
        """Context items are added."""
        class FakeItem:
            content = "item content"
        
        pb = PromptBuilder().add_context_items([FakeItem()])
        result = pb.build()
        self.assertIn("item content", result)

    def test_returns_self_for_chaining(self):
        """Each method returns self."""
        pb = PromptBuilder()
        self.assertIs(pb.add_text("x"), pb)
        self.assertIs(pb.add_file("a", "b"), pb)
        self.assertIs(pb.add_selection("a", "b"), pb)
        self.assertIs(pb.add_folder("a"), pb)


if __name__ == "__main__":
    unittest.main()
