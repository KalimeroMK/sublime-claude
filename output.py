"""Structured output view with region tracking."""
import re
import sublime
import sublime_plugin
from typing import List, Optional

from .constants import (
    SPINNER_FRAMES,
    INPUT_MODE_SETTING,
    CONVERSATION_REGION_KEY,
    PERMISSION_REGION_KEY,
    PLAN_REGION_KEY,
    QUESTION_REGION_KEY,
    UNDO_BUTTON_REGION_KEY,
    DIFF_HIGHLIGHT_REGION_KEY,
)
from .output_format import format_tool_detail

from .output_plan import PlanUIRendererMixin
from .output_input import InputModeControllerMixin
from .output_permissions import PermissionUIRendererMixin
from .output_question import QuestionUIRendererMixin
from .output_models import (
    PENDING, DONE, ERROR, BACKGROUND,
    PlanApproval, PermissionRequest, QuestionRequest,
    ToolCall, TodoItem, Conversation,
)


IN_PROGRESS = "in_progress"


class OutputView(PlanUIRendererMixin, PermissionUIRendererMixin, QuestionUIRendererMixin, InputModeControllerMixin):
    """Structured output view - readonly, plugin-controlled."""

    SYMBOLS = {
        "pending": "○",
        "done": "●",
        "error": "●",
        "background": "⚙",
    }

    def __init__(self, window: sublime.Window):
        self.window = window
        self.view: Optional[sublime.View] = None
        self.conversations: List[Conversation] = []
        self.current: Optional[Conversation] = None
        self.pending_permission: Optional[PermissionRequest] = None
        self._permission_queue: List[PermissionRequest] = []  # Queue for multiple requests
        self._batch_allow_active: bool = False  # True when [B] Batch Allow is active for current query
        self._batch_allow_edits_only: bool = True  # Only batch Write/Edit, or all tools
        self.pending_plan: Optional[PlanApproval] = None
        self.pending_question: Optional[QuestionRequest] = None
        self.auto_allow_tools: set = self._load_persisted_auto_allow()  # Tools auto-allowed for this session
        self._last_allowed_tool: Optional[str] = None  # Track last tool we allowed
        self._last_allowed_time: float = 0  # Timestamp of last allow
        self._pending_context_region: tuple = (0, 0)  # Region for context display
        self._cleared_content: Optional[str] = None  # For undo clear
        self._render_pending: bool = False  # Debounce flag for rendering
        self._render_queued_changes: int = 0  # Count of pending changes to batch
        self._last_rendered_events_len: int = 0  # Track events length at last render
        self._last_rendered_text_len: int = 0  # Track total text length at last render
        self._last_rendered_last_event_len: int = 0  # Track last event text length at last render
        self._incremental_render: bool = False  # Whether to use incremental append
        # Inline input state
        self._input_mode: bool = False  # True when user can type in input region
        self._input_start: int = 0  # Start position of editable input region
        self._input_area_start: int = 0  # Start of entire input area (context + marker)
        self._input_marker: str = "◎ "  # Marker for input line
        self._spinner_frame: int = 0  # Current spinner animation frame
        self._spinner_region_key: str = "claude_spinner"  # For in-place spinner updates
        # Undo button tracking: list of (region_start, region_end, file_path, snapshot)
        self._undo_buttons: List[tuple] = []

    def show(self, focus: bool = True) -> None:
        # If we already have a view, optionally focus it
        if self.view and self.view.is_valid():
            if focus:
                self.window.focus_view(self.view)
            return

        # Create new view
        self.view = self.window.new_file()

        # Optional: show in side panel (narrow right column) like VS Code
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        if settings.get("claude_side_panel", False):
            # Ensure 2-column layout exists (editor wide, chat narrow)
            if self.window.num_groups() == 1:
                self.window.set_layout({
                    "cols": [0.0, 0.78, 1.0],
                    "rows": [0.0, 1.0],
                    "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
                })
            # Move view to right group (group 1)
            self.window.set_view_index(self.view, 1, 0)
            # Focus back to left group so new files open on the left
            self.window.focus_group(0)

        self.view.set_name("Claude")
        self.view.set_scratch(True)
        self.view.set_read_only(True)
        self.view.settings().set("claude_output", True)
        self.view.settings().set("auto_indent", False)
        self.view.settings().set("drag_text", True)
        self._apply_output_settings()
        sublime.load_settings("ClaudeOutput.sublime-settings").add_on_change(
            f"claude_output_{self.view.id()}", self._apply_output_settings
        )
        try:
            self.view.assign_syntax("Packages/ClaudeCode/ClaudeOutput.sublime-syntax")
            self.view.settings().set("color_scheme", "Packages/ClaudeCode/ClaudeOutput.hidden-tmTheme")
        except Exception as e:
            print(f"[Claude] Error setting syntax/theme: {e}")

        # Initialize cursor position to enable mouse selection
        # CRITICAL: Sublime requires a valid cursor for mouse interaction
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(0, 0))

        # Ensure view can receive mouse events
        self.view.settings().set("is_widget", False)

        if focus:
            self.window.focus_view(self.view)

    def set_name(self, name: str) -> None:
        """Update the output view title."""
        self._name = name  # Store for refresh_title
        self._update_title()

    def _update_title(self) -> None:
        """Refresh the view title based on current state."""
        if not self.view or not self.view.is_valid():
            return
        name = getattr(self, '_name', 'Claude')
        # Check if this is the active Claude view
        window = self.view.window()
        is_active = window and window.settings().get("claude_active_view") == self.view.id()
        # ◉ = working, ◇ = idle, • = inactive+working, ❓ = questioning, ⏸ = sleeping
        from . import claude_code
        session = claude_code.get_session_for_view(self.view)
        is_sleeping = session and session.is_sleeping
        is_questioning = bool(
            (self.pending_permission and self.pending_permission.callback) or
            (self.pending_question and self.pending_question.callback) or
            (self.pending_plan and self.pending_plan.callback)
        )
        is_working = self.current and self.current.working
        if is_sleeping:
            prefix = "⏸ "
        elif is_questioning:
            prefix = "❓"
        elif is_active:
            prefix = "◉ " if is_working else "◇ "
        else:
            prefix = "• " if is_working else "◇ "
        # Show backend for non-claude sessions
        backend = self.view.settings().get("claude_backend")
        if backend:
            name = f"[{backend}] {name}"
        # Truncate to keep tab bar usable
        if len(name) > 24:
            from .constants import MAX_SESSION_NAME_LENGTH
            name = name[:MAX_SESSION_NAME_LENGTH] + "…"
        self.view.set_name(f"{prefix}{name}")

    @staticmethod
    def _tool_icon(name: str) -> str:
        """Get icon for tool type."""
        icons = {
            "Read": "📄",
            "Edit": "✎",
            "Write": "✍",
            "Bash": "⚡",
            "Glob": "🔍",
            "Grep": "🔍",
            "WebSearch": "🌐",
            "WebFetch": "🌐",
            "Task": "⚙",
            "TodoWrite": "📋",
            "Skill": "🎯",
            "NotebookEdit": "📓",
            "ask_user": "❓",
        }
        return icons.get(name, "")

    def _highlight_diff_blocks(self, start: int, end: int) -> None:
        """Scan conversation region for diff lines and add colored scopes.

        Diff lines are indented 4 spaces (no fence markers).
        We match lines starting with 4+ spaces followed by + / - / @@.
        """
        if not self.view or not self.view.is_valid():
            return

        try:
            # Erase old diff highlights (base + suffixed keys)
            self.view.erase_regions(DIFF_HIGHLIGHT_REGION_KEY)
            self.view.erase_regions(f"{DIFF_HIGHLIGHT_REGION_KEY}_inserted")
            self.view.erase_regions(f"{DIFF_HIGHLIGHT_REGION_KEY}_deleted")
            self.view.erase_regions(f"{DIFF_HIGHLIGHT_REGION_KEY}_range")

            text = self.view.substr(sublime.Region(start, end))
            inserted = []   # + lines (green)
            deleted = []    # - lines (red)
            ranges = []     # @@ lines (purple)

            line_start = start

            for i, ch in enumerate(text):
                if ch == '\n':
                    line_end = start + i
                    line_text = text[line_start - start:line_end - start]
                    # Match new diff format: "    │ + │ content" or "    │ - │ content"
                    # Also keep backward compat with old format: "    + content"
                    if len(line_text) >= 6 and line_text[:4] == '    ':
                        stripped = line_text.lstrip()
                        if '│ + │' in line_text or stripped.startswith('+'):
                            inserted.append(sublime.Region(line_start, line_end))
                        elif '│ - │' in line_text or stripped.startswith('-'):
                            deleted.append(sublime.Region(line_start, line_end))
                        elif stripped.startswith('@@'):
                            ranges.append(sublime.Region(line_start, line_end))

                    line_start = line_end + 1

            # Handle last line if text doesn't end with newline
            if line_start < end:
                line_text = text[line_start - start:]
                if len(line_text) >= 6 and line_text[:4] == '    ':
                    stripped = line_text.lstrip()
                    if '│ + │' in line_text or stripped.startswith('+'):
                        inserted.append(sublime.Region(line_start, end))
                    elif '│ - │' in line_text or stripped.startswith('-'):
                        deleted.append(sublime.Region(line_start, end))
                    elif stripped.startswith('@@'):
                        ranges.append(sublime.Region(line_start, end))

            # Add regions with scopes (theme already defines colors for these)
            if inserted:
                self.view.add_regions(
                    f"{DIFF_HIGHLIGHT_REGION_KEY}_inserted",
                    inserted,
                    "markup.inserted.diff",
                    "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE,
                )
            if deleted:
                self.view.add_regions(
                    f"{DIFF_HIGHLIGHT_REGION_KEY}_deleted",
                    deleted,
                    "markup.deleted.diff",
                    "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE,
                )
            if ranges:
                self.view.add_regions(
                    f"{DIFF_HIGHLIGHT_REGION_KEY}_range",
                    ranges,
                    "meta.diff.range",
                    "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE,
                )
        except Exception as e:
            # Never let diff highlighting break the render
            print(f"[Claude] _highlight_diff_blocks error: {e}")

    def _highlight_tool_status(self, start: int, end: int) -> None:
        """Add colored scopes to tool status symbols (● green=done, ● red=error, ○ gray=pending)."""
        if not self.view or not self.view.is_valid():
            return
        try:
            self.view.erase_regions("claude_status_done")
            self.view.erase_regions("claude_status_error")
            self.view.erase_regions("claude_status_pending")
            text = self.view.substr(sublime.Region(start, end))
            done_regs = []
            error_regs = []
            pending_regs = []
            # Find lines with status symbols: "  ● tool..." or "  ○ tool..."
            for m in re.finditer(r'^  (●|○) ', text, re.MULTILINE):
                sym = m.group(1)
                abs_start = start + m.start(1)
                abs_end = start + m.end(1)
                region = sublime.Region(abs_start, abs_end)
                if sym == "●":
                    # Distinguish done vs error by looking at tool name line
                    line_end = text.find('\n', m.end())
                    line = text[m.end():line_end if line_end != -1 else len(text)]
                    if "✘" in line or "error" in line.lower():
                        error_regs.append(region)
                    else:
                        done_regs.append(region)
                else:
                    pending_regs.append(region)
            if done_regs:
                self.view.add_regions("claude_status_done", done_regs, "markup.inserted.diff", "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)
            if error_regs:
                self.view.add_regions("claude_status_error", error_regs, "markup.deleted.diff", "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)
            if pending_regs:
                self.view.add_regions("claude_status_pending", pending_regs, "comment", "", sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)
        except Exception as e:
            print(f"[Claude] _highlight_tool_status error: {e}")

    def _write(self, text: str, pos: Optional[int] = None) -> int:
        """Write text at position (or end). Returns end position."""
        if not self.view or not self.view.is_valid():
            return 0

        self.view.set_read_only(False)
        if pos is None:
            pos = self.view.size()
        self.view.run_command("claude_insert", {"pos": pos, "text": text})
        self.view.set_read_only(True)
        return pos + len(text)

    def _replace(self, start: int, end: int, text: str) -> int:
        """Replace region with text. Returns new end position."""
        if not self.view or not self.view.is_valid():
            return end

        old_size = self.view.size()
        self.view.set_read_only(False)
        self.view.run_command("claude_replace", {"start": start, "end": end, "text": text})
        self.view.set_read_only(True)
        # Calculate actual new end from view size delta (more reliable than len())
        new_size = self.view.size()
        return end + (new_size - old_size)

    def _scroll_to_end(self, force: bool = False) -> None:
        """Scroll to end. Sticky behavior: always tracks the bottom so the
        input prompt stays visible without manual scrolling.

        Args:
            force: kept for API compatibility; currently every call scrolls.
        """
        if not self.view or not self.view.is_valid():
            return

        # In input mode, always keep input visible
        if self._input_mode:
            self.view.show(self._input_start, keep_to_left=False, animate=False)
            return

        # Sticky scroll: always pin to the bottom on every render
        end = self.view.size()
        self.view.show(end, keep_to_left=False, animate=False)

    # --- Inline Input ---

    # --- Input mode (delegated to InputModeControllerMixin) ---

    # --- Public API ---

    def set_pending_context(self, context_items: list) -> None:
        """Show pending context - integrated with input mode if active."""
        if not self.view or not self.view.is_valid():
            return

        # If in input mode, re-render the whole input area with new context
        if self._input_mode:
            # Save current input text, re-render input area with new context
            input_text = self.get_input_text()
            # Clear draft to prevent on_activated from re-filling it
            from . import claude_code
            session = claude_code.get_session_for_view(self.view)
            if session:
                session.draft_prompt = ""
            self.exit_input_mode(keep_text=False)
            self.enter_input_mode()
            # Restore input text
            if input_text:
                self.view.run_command("append", {"characters": input_text})
                end = self.view.size()
                self.view.sel().clear()
                self.view.sel().add(sublime.Region(end, end))
            return

        # Not in input mode - show context at end of view
        # Remove old context display
        start, end = self._pending_context_region
        if end > start:
            self._replace(start, end, "")

        if not context_items:
            self._pending_context_region = (0, 0)
            return

        # Build context display
        names = [item.name for item in context_items]
        text = f"\n📎 {', '.join(names)} ({len(names)} file{'s' if len(names) > 1 else ''})\n"

        # Write at end
        start = self.view.size()
        end = self._write(text)
        self._pending_context_region = (start, end)
        self._scroll_to_end()

    def prompt(self, text: str, context_names: List[str] = None) -> None:
        """Start a new conversation with a prompt."""
        self.show()

        # Cancel any pending render - we're starting fresh
        self._render_pending = False

        # Exit input mode if active (query is starting)
        # Save any typed text as draft so it's not lost
        if self._input_mode:
            # Get session to save draft
            from . import claude_code
            session = claude_code.get_session_for_view(self.view)
            if session:
                session.draft_prompt = self.get_input_text()
            self.exit_input_mode(keep_text=False)
        else:
            # Not in input mode, but check for stale input markers
            # This can happen after restart or if state got corrupted
            content = self.view.substr(sublime.Region(0, self.view.size()))
            lines = content.split('\n')
            # Check if last non-empty lines look like input area (marker without ▶, context, or queued line)
            for line in reversed(lines[-5:]):  # Check last 5 lines
                if not line.strip():
                    continue
                is_input_marker = line.startswith(self._input_marker) and ' ▶' not in line
                is_context_line = line.startswith('📎 ')
                is_queued_line = line.startswith('⏳ ')
                if is_input_marker or is_context_line or is_queued_line:
                    # Found stale input marker - clean it up
                    self.reset_input_mode()
                break  # Only check the last non-empty line

        # Clear pending context display
        start, end = self._pending_context_region
        if end > start:
            self._replace(start, end, "")
            self._pending_context_region = (0, 0)

        # Finalize and save previous conversation
        prev_todos = []
        if self.current:
            # Ensure previous conversation is marked as done
            if self.current.working:
                self.current.working = False
                self._render_current()
            self.conversations.append(self.current)
            if len(self.conversations) > 20:
                self.conversations = self.conversations[-20:]
            # Carry todos forward only if not all completed
            if not self.current.todos_all_done:
                prev_todos = self.current.todos

        # Start new
        self.current = Conversation(prompt=text, todos=prev_todos, context_names=context_names or [])
        self._update_title()  # Show working indicator

        # Render prompt with optional context indicator
        start = self.view.size()
        prefix = "\n" if start > 0 else ""
        # Indent continuation lines to align with first line after ◎
        lines = text.split("\n")
        if len(lines) > 1:
            indented = lines[0] + "\n" + "\n".join("  " + l for l in lines[1:])
        else:
            indented = text
        if context_names:
            context_str = ", ".join(context_names)
            line = f"{prefix}◎ {indented} ▶\n  📎 {context_str}\n"
        else:
            line = f"{prefix}◎ {indented} ▶\n"
        line += "  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
        end = self._write(line)
        self.current.region = (start, end)
        # Track with Sublime region so it auto-adjusts when view content shifts
        self.view.add_regions(
            CONVERSATION_REGION_KEY,
            [sublime.Region(start, end)],
            "", "", sublime.HIDDEN,
        )
        self._scroll_to_end()

    def tool(self, name: str, tool_input: dict = None, tool_id: str = None, background: bool = False, snapshot: str = None) -> None:
        """Add a pending tool."""
        if not self.current:
            return

        tool_input = tool_input or {}
        status = BACKGROUND if background else PENDING
        tool_call = ToolCall(name=name, tool_input=tool_input, status=status, id=tool_id, snapshot=snapshot)
        self.current.events.append(tool_call)

        # Capture TodoWrite state
        if name == "TodoWrite" and "todos" in tool_input:
            self.current.todos = [
                TodoItem(content=t.get("content", ""), status=t.get("status", "pending"))
                for t in tool_input["todos"]
            ]

        self._render_current()

    def _find_pending_or_background_by_id(self, tool_id: str) -> Optional[ToolCall]:
        """Find a ToolCall by id across ALL conversations including current."""
        if not tool_id:
            return None
        if self.current:
            for event in self.current.events:
                if isinstance(event, ToolCall) and event.id == tool_id:
                    return event
        for conv in self.conversations:
            for event in conv.events:
                if isinstance(event, ToolCall) and event.id == tool_id:
                    return event
        return None

    def find_tool_by_id(self, tool_id: str) -> Optional[ToolCall]:
        return self._find_pending_or_background_by_id(tool_id)

    def active_background_tools(self) -> list:
        """Get all currently running background tools."""
        result = []
        for conv in self.conversations:
            for event in conv.events:
                if isinstance(event, ToolCall) and event.status == BACKGROUND:
                    result.append(event)
        if self.current:
            for event in self.current.events:
                if isinstance(event, ToolCall) and event.status == BACKGROUND:
                    result.append(event)
        return result

    def _is_in_current(self, target: ToolCall) -> bool:
        """Check if a tool call belongs to the current conversation."""
        if not self.current:
            return False
        return any(e is target for e in self.current.events)

    def _patch_tool_symbol(self, target: ToolCall, old_status: str) -> None:
        """Patch a tool's symbol in-place in the view (for previous conversations)."""
        if not self.view:
            return
        old_sym = self.SYMBOLS.get(old_status, "☐")
        new_sym = self.SYMBOLS.get(target.status, "☐")
        if old_sym == new_sym:
            return
        content = self.view.substr(sublime.Region(0, self.view.size()))
        # Find the tool line: "  ⚙ ToolName: ..." and replace the symbol
        import re
        pattern = re.escape(f"  {old_sym} {target.name}")
        for m in re.finditer(pattern, content):
            self._replace(m.start() + 2, m.start() + 2 + len(old_sym), new_sym)
            return

    def tool_done(self, name: str, result: str = None, tool_id: str = None) -> None:
        """Mark tool as done. Prefer tool_id match, fall back to name+PENDING."""
        target = self._find_pending_or_background_by_id(tool_id)
        if target is None and self.current:
            for event in reversed(self.current.events):
                if isinstance(event, ToolCall) and event.name == name and event.status == PENDING:
                    target = event
                    break
        if target is None:
            if self.current:
                self.current.events.append(ToolCall(name=name, tool_input={}, status=DONE, result=result, id=tool_id))
                self._render_current()
            return
        old_status = target.status
        target.status = DONE
        target.result = result
        if self._is_in_current(target):
            self._render_current()
        else:
            self._patch_tool_symbol(target, old_status)

    def tool_error(self, name: str, result: str = None, tool_id: str = None) -> None:
        """Mark tool as error. Prefer tool_id match, fall back to name+PENDING."""
        target = self._find_pending_or_background_by_id(tool_id)
        if target is None and self.current:
            for event in reversed(self.current.events):
                if isinstance(event, ToolCall) and event.name == name and event.status == PENDING:
                    target = event
                    break
        if target is None:
            if self.current:
                self.current.events.append(ToolCall(name=name, tool_input={}, status=ERROR, result=result, id=tool_id))
                self._render_current()
            return
        old_status = target.status
        target.status = ERROR
        target.result = result
        if self._is_in_current(target):
            self._render_current()
        else:
            self._patch_tool_symbol(target, old_status)

    def text(self, content: str) -> None:
        """Add response text."""
        if not self.current:
            return

        # Merge with previous text event to avoid per-token line breaks
        if self.current.events and isinstance(self.current.events[-1], str):
            self.current.events[-1] += content
        else:
            self.current.events.append(content)
        self._render_current()

    def meta(self, duration: float, cost: float = None, usage: dict = None) -> None:
        """Set completion meta - marks conversation as done."""
        if not self.current:
            return

        self.current.duration = duration
        self.current.usage = usage
        self.current.working = False
        self._render_current()

    def interrupted(self) -> None:
        """Show interrupted indicator."""
        if not self.current:
            return
        self.current.working = False
        # Mark any pending/background tools as error
        for event in self.current.events:
            if isinstance(event, ToolCall) and event.status in (PENDING, BACKGROUND):
                event.status = ERROR
        # Clear any pending permission prompt
        if self.pending_permission:
            self._remove_permission_block()
            self.pending_permission = None
        # Clear any pending plan approval
        if self.pending_plan:
            self._clear_plan_approval()
            self.pending_plan = None
        # Clear any pending question
        if self.pending_question:
            callback = self.pending_question.callback
            self._clear_question()
            self.pending_question = None
            if callback:
                callback(None)
        # Append interrupted text
        self.current.events.append("\n\n*[interrupted]*\n")
        self._render_current()

    def clear(self) -> None:
        """Clear all output (can undo with Cmd+Z)."""
        # Remember if we were in input mode
        was_input_mode = self._input_mode
        # Check if agent is currently working (before we clear state)
        was_working = self.current and self.current.working

        if self._input_mode:
            self.exit_input_mode(keep_text=False)
        if self.view and self.view.is_valid():
            # Save content for undo
            self._cleared_content = self.view.substr(sublime.Region(0, self.view.size()))
            self.view.set_read_only(False)
            self.view.run_command("claude_clear_all")
            self.view.set_read_only(True)
            # Reset view settings that might be stale from old session
            self.view.settings().set(INPUT_MODE_SETTING, False)
        self.conversations = []
        self.current = None
        self.pending_permission = None
        self._permission_queue.clear()
        self.pending_plan = None
        self.pending_question = None
        self.auto_allow_tools.clear()
        self._pending_context_region = (0, 0)
        self._input_mode = False
        self._input_start = 0
        self._input_area_start = 0
        # Clean up any tracked permission region
        if self.view:
            self.view.erase_regions(PERMISSION_REGION_KEY)

        # If agent was working, create a stub conversation to receive further output
        # This prevents output from being silently discarded after clear
        if was_working:
            self.current = Conversation(prompt="(continued)", working=True)
            self.current.region = (0, 0)  # Will be set on first render
            self._update_title()  # Show working indicator
            return  # Don't enter input mode while working

        # Re-enter input mode if we were in it
        if was_input_mode:
            self.enter_input_mode()

    def undo_clear(self) -> None:
        """Restore content from last clear."""
        if self._cleared_content and self.view and self.view.is_valid():
            self._write(self._cleared_content)
            self._cleared_content = None
            self._scroll_to_end()

    def reset_active_states(self) -> None:
        """Reset active states when reconnecting after Sublime restart.

        Clears pending permissions, marks pending tools as interrupted,
        resets input mode, and resets the view title to remove any stale spinner.
        """
        # Reset input mode state (view settings may persist across restart)
        self.reset_input_mode()

        # Clear permission state
        if self.pending_permission:
            self._remove_permission_block()
            self.pending_permission = None
        self._permission_queue.clear()

        # Reset any stale working state from previous bridge
        if self.current:
            self.current.working = False
            had_pending = False
            for event in self.current.events:
                if isinstance(event, ToolCall) and event.status in (PENDING, BACKGROUND):
                    event.status = ERROR
                    had_pending = True
            if had_pending:
                self.current.events.append("\n\n*[session reconnected]*\n")
                self._render_current()

    # --- Permission UI (delegated to PermissionUIRendererMixin) ---

    def _move_cursor_to_end(self) -> None:
        """Move cursor to end of view."""
        if self.view and self.view.is_valid():
            end = self.view.size()
            self.view.sel().clear()
            self.view.sel().add(sublime.Region(end, end))
            self.view.show(end)

    # --- Question UI (delegated to QuestionUIRendererMixin) ---

    def handle_undo_click(self, point: int) -> bool:
        """Handle click on an [Undo] button. Returns True if handled."""
        if not self.view:
            return False
        # Check if point is within any undo button region
        for start, end, file_path, snapshot in self._undo_buttons:
            if start <= point < end and file_path and snapshot is not None:
                try:
                    # Ensure directory exists
                    import os
                    dir_path = os.path.dirname(file_path)
                    if dir_path and not os.path.exists(dir_path):
                        os.makedirs(dir_path, exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(snapshot)
                    sublime.status_message(f"Claude: undone edit to {os.path.basename(file_path)}")
                    # Remove snapshot from the tool so [Undo] disappears
                    for conv in self.conversations + ([self.current] if self.current else []):
                        for event in conv.events:
                            if isinstance(event, ToolCall):
                                if event.tool_input.get("file_path") == file_path and getattr(event, "snapshot", None) is not None:
                                    event.snapshot = None
                                    event.diff = None
                    self._render_current()
                    return True
                except Exception as e:
                    sublime.status_message(f"Claude: undo failed: {e}")
                    return True
        return False

    def find_undoable_at_cursor(self, point: int) -> Optional[tuple]:
        """Find the nearest undoable edit at or before point. Returns (file_path, snapshot) or None."""
        if not self.view or not self.current:
            return None
        # Search backward from point for a tool line with [Undo]
        content = self.view.substr(sublime.Region(0, point))
        # Find last occurrence of tool line pattern with [Undo]
        import re
        for m in reversed(list(re.finditer(r'^  [✔✘] (Write|Edit): (.+?)\s+\[Undo\]', content, re.MULTILINE))):
            file_path = m.group(2).strip()
            # Find matching ToolCall
            for conv in self.conversations + ([self.current] if self.current else []):
                for event in conv.events:
                    if isinstance(event, ToolCall) and event.name in ("Write", "Edit"):
                        if event.tool_input.get("file_path") == file_path:
                            snapshot = getattr(event, "snapshot", None)
                            if snapshot is not None:
                                return (file_path, snapshot)
            # If no snapshot on that exact tool, keep searching
        return None

    def _render_current(self, auto_scroll: bool = True) -> None:
        """Re-render current conversation in place (debounced)."""
        if not self.current or not self.view:
            return

        # Debounce: accumulate changes instead of queuing multiple renders
        self._render_queued_changes += 1
        if self._render_pending:
            return
        self._render_pending = True
        self._auto_scroll = auto_scroll  # Store for _do_render

        # Adaptive debounce: longer during active streaming to batch more chunks
        is_streaming = self.current and self.current.working and self._render_queued_changes > 1
        debounce_ms = 50 if is_streaming else 16  # 50ms for streaming, ~1 frame otherwise
        sublime.set_timeout(self._do_render, debounce_ms)

    def advance_spinner(self) -> None:
        """Advance spinner animation frame and re-render if working."""
        if not self.current or not self.current.working or not self.view:
            return
        self._spinner_frame += 1
        # Try in-place spinner update to avoid expensive full re-render
        regions = self.view.get_regions(self._spinner_region_key)
        if regions and regions[0].size() > 0:
            symbol = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
            self._replace(regions[0].begin(), regions[0].end(), symbol)
            # Update tracked region for next frame (region auto-adjusts, but be explicit)
            self.view.add_regions(
                self._spinner_region_key,
                [sublime.Region(regions[0].begin(), regions[0].begin() + len(symbol))],
                "", "", sublime.HIDDEN,
            )
        else:
            # Fallback to full render if spinner region not tracked
            self._render_current(auto_scroll=False)
        # Periodically clear undo history to prevent memory bloat
        if self._spinner_frame % 50 == 0:
            try:
                self.view.clear_undo_stack()
            except AttributeError:
                pass  # Not available in older Sublime builds

    def _do_render(self) -> None:
        """Actually perform the render."""
        self._render_pending = False
        queued_changes = self._render_queued_changes
        self._render_queued_changes = 0
        if not self.current or not self.view:
            return

        # Don't render while in input mode - it would corrupt the input region
        if self._input_mode:
            return

        # --- Incremental render optimization ---
        # If only text was added (no tool changes, no meta, still working),
        # just append new text instead of rebuilding the whole conversation.
        current_events_len = len(self.current.events)
        current_text_len = sum(
            len(e) for e in self.current.events if isinstance(e, str)
        )
        can_incremental = (
            self.current.working
            and queued_changes > 0
            and current_events_len == self._last_rendered_events_len
            and current_text_len > self._last_rendered_text_len
            and not any(
                isinstance(e, ToolCall) and e.status == PENDING
                for e in self.current.events
            )
        )
        if can_incremental:
            # Only append new text delta since last render
            last_event = self.current.events[-1] if self.current.events and isinstance(self.current.events[-1], str) else ""
            if last_event and len(last_event) > self._last_rendered_last_event_len:
                delta = last_event[self._last_rendered_last_event_len:]
                self._write(delta, pos=self.view.size())
                self._last_rendered_text_len = current_text_len
                self._last_rendered_last_event_len = len(last_event)
                self._scroll_to_end()
                self._update_title()
                return

        # Read region from Sublime's tracked region (auto-adjusts when view shifts)
        view_size = self.view.size()
        tracked = self.view.get_regions(CONVERSATION_REGION_KEY)
        if tracked and tracked[0].size() > 0:
            start, end = tracked[0].begin(), tracked[0].end()
        else:
            # Fallback to tuple
            start, end = self.current.region
        if start > view_size or end > view_size:
            # Region is invalid - recalculate from view content
            content = self.view.substr(sublime.Region(0, view_size))
            prompt_marker = f"◎ {self.current.prompt[:20]}"
            last_pos = content.rfind(prompt_marker)
            if last_pos >= 0:
                start = last_pos
                end = view_size
            else:
                return

        # Build the full text for this conversation
        lines = []

        # Prompt (newline before only if not at start)
        prefix = "\n" if self.current.region[0] > 0 else ""
        # Indent continuation lines
        prompt_lines = self.current.prompt.split("\n")
        if len(prompt_lines) > 1:
            indented_prompt = prompt_lines[0] + "\n" + "\n".join("  " + l for l in prompt_lines[1:])
        else:
            indented_prompt = self.current.prompt
        # Include context indicator if present
        if self.current.context_names:
            context_str = ", ".join(self.current.context_names)
            lines.append(f"{prefix}◎ {indented_prompt} ▶\n")
            lines.append(f"  📎 {context_str}\n")
        else:
            lines.append(f"{prefix}◎ {indented_prompt} ▶\n")
        # Thin separator after prompt header
        lines.append("  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n")

        # Events in time order (text chunks and tools interleaved)
        # Find the last pending tool to animate it when working
        last_pending_idx = None
        if self.current.working:
            for idx, event in enumerate(self.current.events):
                if isinstance(event, ToolCall) and event.status == PENDING:
                    last_pending_idx = idx

        # Collect undo button positions during render
        undo_buttons = []
        # Compute prompt text length once, then track incrementally (avoids O(n²))
        running_offset = len("".join(lines))

        if self.current.events:
            lines.append("\n")
            running_offset += 1
            for idx, event in enumerate(self.current.events):
                if isinstance(event, str):
                    # Text chunk
                    lines.append(event)
                    running_offset += len(event)
                    if not event.endswith("\n"):
                        lines.append("\n")
                        running_offset += 1
                elif isinstance(event, ToolCall):
                    # Tool call
                    if idx == last_pending_idx:
                        # Animate the currently-executing tool
                        symbol = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
                    else:
                        symbol = self.SYMBOLS[event.status]
                    detail = format_tool_detail(event)
                    # Tool icon based on type (skip for file tools — file icon is in detail)
                    if event.name in ("Read", "Edit", "Write"):
                        line = f"  {symbol} {event.name}{detail}\n"
                    else:
                        tool_icon = self._tool_icon(event.name)
                        line = f"  {symbol} {tool_icon} {event.name}{detail}\n"
                    # Track [Undo] button position using running offset (O(1) per tool)
                    if getattr(event, "snapshot", None) is not None and event.status == DONE:
                        undo_idx = line.find("[Undo]")
                        if undo_idx >= 0:
                            undo_buttons.append((running_offset + undo_idx, running_offset + undo_idx + len("[Undo]"), event))
                    # Track spinner position for in-place updates during animation
                    if idx == last_pending_idx:
                        spinner_start = start + running_offset + 2  # +2 for "  "
                        spinner_end = spinner_start + len(symbol)
                        self.view.add_regions(
                            self._spinner_region_key,
                            [sublime.Region(spinner_start, spinner_end)],
                            "", "", sublime.HIDDEN,
                        )
                    lines.append(line)
                    running_offset += len(line)

        # Working indicator at bottom (animated) — only show when no pending tools
        if self.current.working and last_pending_idx is None:
            spinner = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
            line = f"  {spinner}\n"
            spinner_start = start + running_offset + 2  # +2 for "  "
            spinner_end = spinner_start + len(spinner)
            self.view.add_regions(
                self._spinner_region_key,
                [sublime.Region(spinner_start, spinner_end)],
                "", "", sublime.HIDDEN,
            )
            lines.append(line)
            running_offset += len(line)

        # Todo list (if any)
        if self.current.todos:
            lines.append("\n  ───── Tasks ─────\n")
            for todo in self.current.todos:
                if todo.status == "completed":
                    icon = "✓"
                elif todo.status == "in_progress":
                    icon = "▸"
                else:
                    icon = "○"
                lines.append(f"  {icon} {todo.content}\n")
            # Mark as done so next conversation starts fresh
            if all(t.status == "completed" for t in self.current.todos):
                self.current.todos_all_done = True

        # Meta
        if self.current.duration > 0:
            meta_parts = [f"{self.current.duration:.1f}s"]
            if self.current.usage:
                u = self.current.usage
                input_t = (u.get("input_tokens", 0)
                         + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0))
                if input_t:
                    if input_t >= 1000:
                        meta_parts.append(f"{input_t // 1000}k ctx")
                    else:
                        meta_parts.append(f"{input_t} ctx")
            lines.append(f"\n  ── ✓ {' · '.join(meta_parts)} ──\n")

        text = "".join(lines)

        # Re-read view size (may have changed during text building)
        view_size = self.view.size()
        # If there's content after our region, extend end to clean it up
        # This handles race conditions where content was orphaned from previous renders
        # BUT: Don't extend if there's a permission block - that's intentional content after the region
        rerender_ui = False
        has_trailing_ui = (
            (self.pending_permission and self.pending_permission.callback) or
            (self.pending_plan and self.pending_plan.callback) or
            (self.pending_question and self.pending_question.callback)
        )
        if has_trailing_ui:
            # Clamp end to not eat the trailing UI block
            if self.pending_permission and self.pending_permission.callback:
                ui_key = PERMISSION_REGION_KEY
            elif self.pending_plan and self.pending_plan.callback:
                ui_key = PLAN_REGION_KEY
            else:
                ui_key = QUESTION_REGION_KEY
            ui_region = self.view.get_regions(ui_key)
            if ui_region and ui_region[0].size() > 0:
                end = min(end, ui_region[0].begin())
            else:
                # UI block tracked region lost — extend to clean up, then re-render UI
                end = view_size
                rerender_ui = True
        elif end < view_size:
            end = view_size
        new_end = self._replace(start, end, text)
        self.current.region = (start, new_end)
        self.view.add_regions(
            CONVERSATION_REGION_KEY,
            [sublime.Region(start, new_end)],
            "", "", sublime.HIDDEN,
        )

        # Set up undo button regions
        self.view.erase_regions(UNDO_BUTTON_REGION_KEY)
        self._undo_buttons = []
        if undo_buttons:
            regions = []
            for u_start, u_end, tool in undo_buttons:
                abs_start = start + u_start
                abs_end = start + u_end
                regions.append(sublime.Region(abs_start, abs_end))
                self._undo_buttons.append((abs_start, abs_end, tool.tool_input.get("file_path", ""), tool.snapshot))
            self.view.add_regions(
                UNDO_BUTTON_REGION_KEY,
                regions,
                "claude.permission.button.allow",
                "", sublime.DRAW_NO_OUTLINE,
            )

        # Highlight diff blocks with colors
        self._highlight_diff_blocks(start, new_end)
        # Highlight tool status symbols
        self._highlight_tool_status(start, new_end)

        # Update title to reflect working state
        self._update_title()

        # Re-render UI blocks only if their tracked regions were lost
        if rerender_ui:
            if self.pending_permission and self.pending_permission.callback:
                self._render_permission()
            if self.pending_question and self.pending_question.callback:
                self._render_question()

        # Scroll after render completes (only if auto_scroll is enabled)
        if getattr(self, '_auto_scroll', True):
            self._scroll_to_end()

        # Track render state for incremental optimization
        self._last_rendered_events_len = len(self.current.events)
        self._last_rendered_text_len = sum(
            len(e) for e in self.current.events if isinstance(e, str)
        )
        if self.current.events and isinstance(self.current.events[-1], str):
            self._last_rendered_last_event_len = len(self.current.events[-1])
        else:
            self._last_rendered_last_event_len = 0



    def _apply_output_settings(self) -> None:
        if not self.view:
            return
        s = sublime.load_settings("ClaudeOutput.sublime-settings")
        for key in ("font_size", "line_numbers", "gutter", "word_wrap", "margin",
                    "draw_indent_guides", "highlight_line", "fold_buttons", "fade_fold_buttons"):
            val = s.get(key)
            if val is not None:
                self.view.settings().set(key, val)


# --- Helper commands for text manipulation ---

class ClaudeInsertCommand(sublime_plugin.TextCommand):
    """Insert text at position."""
    def run(self, edit, pos: int, text: str):
        self.view.insert(edit, pos, text)


class ClaudeReplaceCommand(sublime_plugin.TextCommand):
    """Replace region with text."""
    def run(self, edit, start: int, end: int, text: str):
        region = sublime.Region(start, end)
        self.view.replace(edit, region, text)


class ClaudeClearAllCommand(sublime_plugin.TextCommand):
    """Clear all text (undoable)."""
    def run(self, edit):
        region = sublime.Region(0, self.view.size())
        self.view.erase(edit, region)


class ClaudeUndoClearCommand(sublime_plugin.TextCommand):
    """Undo clear - restore saved content."""
    def run(self, edit):
        # Get the OutputView instance from claude_code module
        from .core import get_active_session
        window = self.view.window()
        if window:
            session = get_active_session(window)
            if session:
                session.output.undo_clear()
