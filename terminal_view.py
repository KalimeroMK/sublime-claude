"""Terminal panel view for persistent shell sessions."""

import re
import sublime
from typing import Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes for plain display."""
    return _ANSI_RE.sub("", text)


class TerminalView:
    """Manages a Sublime output panel that displays terminal output."""

    def __init__(self, window: sublime.Window, panel_name: str = "claude_terminal"):
        self.window = window
        self.panel_name = panel_name
        self.view: Optional[sublime.View] = None
        self._last_size: int = 0

    def show(self, focus: bool = False) -> None:
        """Create or show the terminal panel."""
        self.view = self.window.create_output_panel(self.panel_name)
        self.view.set_read_only(True)
        self.view.settings().set("word_wrap", True)
        self.view.settings().set("gutter", False)
        self.view.settings().set("line_numbers", False)
        self.view.settings().set("claude_terminal", True)
        self.window.run_command("show_panel", {"panel": f"output.{self.panel_name}"})
        if focus:
            self.window.focus_view(self.view)

    def hide(self) -> None:
        """Hide the terminal panel."""
        self.window.run_command("hide_panel", {"panel": f"output.{self.panel_name}"})

    def is_visible(self) -> bool:
        """Check if the terminal panel is currently visible."""
        active_panel = self.window.active_panel()
        return active_panel == f"output.{self.panel_name}"

    def append(self, text: str) -> None:
        """Append text to the terminal panel (strip ANSI, handle CR)."""
        if not self.view or not self.view.is_valid():
            return

        # Strip ANSI escape codes
        text = strip_ansi(text)

        # Handle carriage returns (progress bars, spinners)
        # If the text ends with \r, we replace the last line
        if "\r" in text and not text.endswith("\n"):
            # Simple handling: if we see \r without \n, it's a line overwrite
            # For the panel, just append a newline so it doesn't overwrite
            text = text.replace("\r", "\n")

        self.view.set_read_only(False)
        self.view.run_command("append", {"characters": text})
        self.view.set_read_only(True)
        self._last_size = self.view.size()

        # Auto-scroll to bottom
        self.view.show(self.view.size())

    def clear(self) -> None:
        """Clear the terminal panel."""
        if not self.view or not self.view.is_valid():
            return
        self.view.set_read_only(False)
        self.view.run_command("select_all")
        self.view.run_command("right_delete")
        self.view.set_read_only(True)
        self._last_size = 0

    def set_name(self, name: str) -> None:
        """Set the panel title."""
        # Output panels don't support custom names directly,
        # but we can set a setting that themes might use
        if self.view and self.view.is_valid():
            self.view.set_name(name)
