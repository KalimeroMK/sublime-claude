"""Terminal adapter for PTY terminal integration."""


class TerminalAdapter:
    """Manages the integrated terminal panel for persistent shell sessions."""

    def __init__(self, session):
        self._s = session
        self.terminal_view = None

    def toggle(self) -> None:
        """Toggle the integrated terminal panel."""
        if not self.terminal_view:
            from .terminal_view import TerminalView
            self.terminal_view = TerminalView(self._s.window)
        if self.terminal_view.is_visible():
            self.terminal_view.hide()
        else:
            self.terminal_view.show(focus=False)
            if self._s.client and self._s.initialized:
                self._s.client.send("terminal_start", {})

    def handle_output(self, text: str) -> None:
        """Append text to the terminal view."""
        if text and self.terminal_view:
            try:
                self.terminal_view.append(text)
            except Exception as e:
                print(f"[Claude] terminal output error: {e}")
