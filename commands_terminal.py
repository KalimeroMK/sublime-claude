"""Terminal-related commands for Claude Code."""

import sublime
import sublime_plugin

from .core import get_active_session


class ClaudeToggleTerminalCommand(sublime_plugin.WindowCommand):
    """Toggle the integrated terminal panel for the active session."""

    def run(self) -> None:
        session = get_active_session(self.window)
        if not session:
            sublime.status_message("Claude: No active session")
            return

        if not session.terminal_view:
            from .terminal_view import TerminalView
            session.terminal_view = TerminalView(self.window)

        if session.terminal_view.is_visible():
            session.terminal_view.hide()
        else:
            session.terminal_view.show(focus=False)
            # Start terminal in bridge if not already running
            if session.client:
                session.client.send("terminal_start", {})

    def is_enabled(self) -> bool:
        return get_active_session(self.window) is not None


class ClaudeTerminalSendCommand(sublime_plugin.WindowCommand):
    """Send a command to the integrated terminal."""

    def run(self) -> None:
        session = get_active_session(self.window)
        if not session:
            sublime.status_message("Claude: No active session")
            return

        # Show terminal if hidden
        if session.terminal_view and not session.terminal_view.is_visible():
            session.terminal_view.show(focus=False)

        def on_done(text: str) -> None:
            text = text.strip()
            if not text:
                return
            if session.client:
                # Append locally for instant feedback, then send to bridge
                if session.terminal_view:
                    session.terminal_view.append(text + "\n")
                session.client.send("terminal_write", {"text": text + "\n"})

        self.window.show_input_panel(
            "Terminal:",
            "",
            on_done,
            None,
            None
        )

    def is_enabled(self) -> bool:
        return get_active_session(self.window) is not None
