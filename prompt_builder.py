"""Prompt building utilities — self-contained unit for constructing prompts."""
from typing import List


class PromptBuilder:
    """Builder for constructing Claude prompts with context."""

    def __init__(self, base_prompt: str = ""):
        self.parts: List[str] = []
        if base_prompt:
            self.parts.append(base_prompt)

    def add_file(self, path: str, content: str) -> 'PromptBuilder':
        """Add a file with syntax highlighting."""
        self.parts.append(f"\n\nFile: `{path}`\n```\n{content}\n```")
        return self

    def add_selection(self, path: str, content: str) -> 'PromptBuilder':
        """Add a code selection."""
        self.parts.append(f"\n\nSelection from {path}:\n```\n{content}\n```")
        return self

    def build(self) -> str:
        """Build the final prompt string."""
        return "".join(self.parts)

    @staticmethod
    def file_query(prompt: str, file_path: str, content: str) -> str:
        """Quick builder for file query pattern."""
        return PromptBuilder(prompt).add_file(file_path, content).build()

    @staticmethod
    def selection_query(prompt: str, file_path: str, selection: str) -> str:
        """Quick builder for selection query pattern."""
        return PromptBuilder(prompt).add_selection(file_path, selection).build()
