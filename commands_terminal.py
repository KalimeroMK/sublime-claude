"""Terminal commands — a real PTY terminal hosted in an output panel.

The panel used to be a plain text appender that stripped CSI escapes with one
regex. That is not a terminal: `clear` was erased rather than honoured so old
output stayed on screen, `\r` never overwrote a line, and the `?2004h` /
`]0;title` sequences every shell emits around its prompt were left in the
buffer as literal junk.

The package already vendors a pyte-backed VT emulator (terminal/), which the
MCP tools use. This hosts that same Terminal in a panel, so the panel and the
agent share one implementation.
"""
import os

import sublime
import sublime_plugin

PANEL_NAME = "Claude Terminal"
PANEL_ID = "output.{}".format(PANEL_NAME)

# Settings a terminal view needs; "claude_terminal" is also what the package's
# key bindings match on, so without it every keystroke goes to the editor.
_VIEW_SETTINGS = {
    "claude_terminal": True,
    "claude_terminal_tag": "claude-panel",
    "gutter": False,
    "line_numbers": False,
    "highlight_line": False,
    "draw_centered": False,
    "word_wrap": False,
    "auto_complete": False,
    "draw_white_space": "none",
    "draw_unicode_white_space": False,
    "draw_indent_guides": False,
    "scroll_past_end": False,
    "color_scheme": "Packages/ClaudeCode/ClaudeCode.hidden-color-scheme",
}


def _get_terminal(view):
    from .terminal.terminal import Terminal
    return Terminal.from_id(view.id()) if view else None


def panel_view(window, create=False):
    """The terminal panel's view.

    create_output_panel() returns the same view but wipes its contents, so an
    existing panel is looked up instead of recreated — otherwise every toggle
    would erase the scrollback.
    """
    view = window.find_output_panel(PANEL_NAME)
    if view or not create:
        return view
    view = window.create_output_panel(PANEL_NAME)
    settings = view.settings()
    for key, value in _VIEW_SETTINGS.items():
        settings.set(key, value)
    return view


def panel_is_visible(window):
    return window.active_panel() == PANEL_ID


def start_terminal(window, view, cwd=None, cmd=None):
    """Spawn a shell against the panel view."""
    from .terminal.terminal import Terminal

    old = _get_terminal(view)
    if old:
        old.kill()
    # cleanup marks a finished terminal so it is never rendered again
    view.settings().erase("claude_terminal_view.finished")

    if not cwd and window.folders():
        cwd = window.folders()[0]
    if not cmd:
        cmd = [os.environ.get("SHELL", "/bin/bash"), "-i", "-l"]

    terminal = Terminal(view)
    terminal.start(
        cmd=cmd,
        cwd=cwd,
        env={},
        title=None,
        default_title=PANEL_NAME,
        show_in_panel=True,
        panel_name=PANEL_NAME,
        tag="claude-panel",
        # closing the view would destroy the panel; leaving it lets the exit
        # message stand and the next toggle start a fresh shell
        auto_close=False,
    )
    return terminal


def show_panel(window, focus=True):
    """Show the panel, starting or restarting the shell when needed."""
    view = panel_view(window, create=True)
    terminal = _get_terminal(view)
    if not terminal or not terminal.is_alive():
        terminal = start_terminal(window, view)
    window.run_command("show_panel", {"panel": PANEL_ID})
    if focus:
        # keystrokes only reach the terminal when its view has focus
        window.focus_view(view)
    return view


def hide_panel(window):
    window.run_command("hide_panel", {"panel": PANEL_ID})


def send_when_ready(view, text, attempts=40):
    """Write to the shell once it is actually reading.

    A freshly spawned `zsh -i -l` sources its rc files before it reads stdin,
    and anything written in that window is swallowed — so a command typed into
    a terminal the same action just started would silently vanish.
    """
    terminal = _get_terminal(view)
    if not terminal or not terminal.is_alive():
        return
    ready = any(line.strip() for line in terminal.screen.display)
    if ready or attempts <= 0:
        terminal.send_string(text)
        return
    sublime.set_timeout(lambda: send_when_ready(view, text, attempts - 1), 100)


class ClaudeToggleTerminalCommand(sublime_plugin.WindowCommand):
    """Toggle the integrated terminal panel."""

    def run(self) -> None:
        if panel_is_visible(self.window):
            hide_panel(self.window)
        else:
            show_panel(self.window)


class ClaudeTerminalSendCommand(sublime_plugin.WindowCommand):
    """Type a command into the integrated terminal without focusing it."""

    def run(self) -> None:
        view = show_panel(self.window, focus=False)

        def on_done(text: str) -> None:
            text = text.strip()
            if not text:
                return
            terminal = _get_terminal(view)
            if not terminal or not terminal.is_alive():
                sublime.status_message("Claude: terminal is not running")
                return
            send_when_ready(view, text + "\n")

        self.window.show_input_panel("Terminal:", "", on_done, None, None)


class ClaudeTerminalRestartCommand(sublime_plugin.WindowCommand):
    """Kill the panel's shell and start a fresh one."""

    def run(self) -> None:
        view = panel_view(self.window, create=True)
        view.run_command("claude_terminal_nuke")
        start_terminal(self.window, view)
        self.window.run_command("show_panel", {"panel": PANEL_ID})
        self.window.focus_view(view)

    def is_enabled(self) -> bool:
        return panel_view(self.window) is not None


class ClaudeTerminalPanelListener(sublime_plugin.EventListener):
    """Keep the shell from outliving the window that hosts it."""

    def on_pre_close_window(self, window):
        view = panel_view(window)
        terminal = _get_terminal(view)
        if terminal:
            terminal.kill()
