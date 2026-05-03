"""Input mode controller mixin for OutputView."""
import sublime

from .constants import INPUT_MODE_SETTING


class InputModeControllerMixin:
    """Mixin for managing the inline input mode (typing area at bottom of view)."""

    def enter_input_mode(self) -> None:
        """Enter input mode - show prompt marker and allow typing."""
        if not self.view or not self.view.is_valid():
            return
        if self._input_mode:
            return

        # Check session-level working flag (authoritative busy state)
        from . import claude_code
        session = claude_code.get_session_for_view(self.view)
        if session and session.working:
            return

        # Exit any current conversation's working state
        if self.current and self.current.working:
            return  # Can't input while working

        # Additional safety: check if there's a pending render that should complete first
        if self._render_pending:
            # Schedule input mode entry after pending render completes
            sublime.set_timeout(self.enter_input_mode, 20)
            return

        # Safety: check for and clean up any stale input markers from previous sessions
        # This can happen after Sublime restart when OutputView state is lost but view content remains
        # BUT: Don't clean up fresh context that was just added
        has_pending_context = session and session.pending_context

        content = self.view.substr(sublime.Region(0, self.view.size()))
        if content:
            lines = content.split('\n')
            # Check last few lines for stale input markers
            cleanup_start = -1
            for i in range(len(lines) - 1, max(-1, len(lines) - 5), -1):
                line = lines[i]
                # Input marker: starts with "◎ " but no " ▶" (which prompts have)
                is_input_marker = line.startswith(self._input_marker) and ' ▶' not in line
                # Context line: only treat as stale if we don't have actual pending context
                is_context_line = line.startswith('📎 ') and not has_pending_context
                # Background task hint lines from previous input mode
                is_bg_hint = line.strip().startswith(('⚙ ', '✔ ', '✘ '))
                if is_input_marker or is_context_line or is_bg_hint:
                    cleanup_start = len('\n'.join(lines[:i]))
                    if i > 0:
                        cleanup_start += 1
                    continue
                elif line.strip():
                    break
            if cleanup_start >= 0 and cleanup_start < self.view.size():
                self.view.set_read_only(False)
                self.view.run_command("claude_replace", {
                    "start": cleanup_start,
                    "end": self.view.size(),
                    "text": ""
                })
                # Reset context region since we just deleted content
                self._pending_context_region = (0, 0)

        # Set read-only false first but DON'T set _input_mode yet
        # This prevents on_modified from saving wrong draft during setup
        self.view.set_read_only(False)

        # Clear any existing context region since we'll render it with input
        if self._pending_context_region[1] > self._pending_context_region[0]:
            self._replace(self._pending_context_region[0], self._pending_context_region[1], "")
            self._pending_context_region = (0, 0)
            # _replace sets view to read-only, so set it back to False for append operations
            self.view.set_read_only(False)

        # Build input area (context + marker)
        self._input_area_start = self.view.size()

        # Add newline prefix only if view has content AND doesn't already end with newline
        prefix = ""
        if self.view.size() > 0:
            last_char = self.view.substr(self.view.size() - 1)
            if last_char != "\n":
                prefix = "\n"

        if prefix:
            self.view.run_command("append", {"characters": prefix})
        self._input_area_start = self.view.size()

        # Add background task hints
        bg_tools = self.active_background_tools()
        if bg_tools:
            for bt in bg_tools:
                detail = f": {bt.result[:60]}..." if bt.result and len(bt.result) > 60 else f": {bt.result}" if bt.result else ""
                self.view.run_command("append", {"characters": f"  ⚙ {bt.name}{detail}\n"})

        # Add context line if any
        from . import claude_code
        session = claude_code.get_session_for_view(self.view)
        if session and session.pending_context:
            names = [item.name for item in session.pending_context]
            ctx_line = f"📎 {', '.join(names)}\n"
            self.view.run_command("append", {"characters": ctx_line})

        self.view.run_command("append", {"characters": self._input_marker})
        self._input_start = self.view.size()  # After the marker

        # NOW set input mode - after _input_start is correctly positioned
        # This ensures on_modified won't save wrong content as draft
        self._input_mode = True
        self.view.settings().set(INPUT_MODE_SETTING, True)

        # Move cursor to input position
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(self._input_start, self._input_start))
        self.view.show(self._input_start)

    def exit_input_mode(self, keep_text: bool = False) -> str:
        """Exit input mode and return the input text."""
        if not self.view or not self._input_mode:
            return ""

        # Get the input text
        input_text = self.get_input_text()

        if not keep_text:
            # Remove entire input area (context + marker + text)
            start = getattr(self, '_input_area_start', self._input_start - len(self._input_marker))
            if start > 0:
                start -= 1  # Include preceding newline
            self.view.run_command("claude_replace", {
                "start": max(0, start),
                "end": self.view.size(),
                "text": ""
            })

        self._input_mode = False
        self.view.settings().set(INPUT_MODE_SETTING, False)
        self.view.set_read_only(True)
        return input_text

    def get_input_text(self) -> str:
        """Get current text in input region."""
        if not self.view or not self._input_mode:
            return ""
        return self.view.substr(sublime.Region(self._input_start, self.view.size()))

    def is_input_mode(self) -> bool:
        """Check if currently in input mode."""
        return self._input_mode

    def reset_input_mode(self) -> None:
        """Force reset input mode state - use when state gets corrupted."""
        if not self.view:
            return

        # Try to clean up leftover input markers in view content
        # Input markers are EXACTLY "◎ " (the marker) possibly followed by user text
        # Prompt lines are "◎ ... ▶" (have the arrow indicator)
        content = self.view.substr(sublime.Region(0, self.view.size()))
        cleanup_start = -1

        # Find input area at end - must be input marker (not prompt) or context line
        lines = content.split('\n')
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            # Input marker line: starts with "◎ " but does NOT contain " ▶" (which prompts have)
            is_input_marker = line.startswith(self._input_marker) and ' ▶' not in line
            is_context_line = line.startswith('📎 ')
            if is_input_marker or is_context_line:
                # Found input area - calculate position to remove
                cleanup_start = len('\n'.join(lines[:i]))
                if i > 0:
                    cleanup_start += 1  # Account for newline before this line
                # Continue checking for context lines above
                continue
            elif line.strip():
                # Non-empty line that's not input area - stop looking
                break

        if cleanup_start >= 0 and cleanup_start < self.view.size():
            self.view.set_read_only(False)
            self.view.run_command("claude_replace", {
                "start": cleanup_start,
                "end": self.view.size(),
                "text": ""
            })
            self.view.set_read_only(True)

        self._input_mode = False
        self._input_start = 0
        self._input_area_start = 0
        self.view.settings().set(INPUT_MODE_SETTING, False)
        self.view.set_read_only(True)
        # Also clear any pending regions that might be stale
        self._pending_context_region = (0, 0)

        # Re-enter input mode after reset to restore a clean, working state
        # Use a timeout to ensure view state is fully reset before re-entering
        sublime.set_timeout(self.enter_input_mode, 10)

    def is_in_input_region(self, point: int) -> bool:
        """Check if a point is within the editable input region."""
        if not self._input_mode:
            return False
        return point >= self._input_start
