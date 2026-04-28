"""Session query orchestration mixin."""
import time
from typing import Optional, Callable

import sublime

from .smart_context import build_smart_context


class SessionQueryMixin:
    def query(self, prompt: str, display_prompt: str = None, silent: bool = False) -> None:
        """
        Start a new query.

        Args:
            prompt: The full prompt to send to the agent
            display_prompt: Optional shorter prompt to display in the UI (defaults to prompt)
            silent: If True, skip UI updates (for channel mode)
        """
        if not self.client or not self.initialized:
            sublime.error_message("Claude not initialized")
            return

        self.working = True
        self.query_count += 1
        self.draft_prompt = ""  # Clear draft — query submitted
        self._pending_resume_at = None  # New query advances past any rewind point
        self._input_mode_entered = False  # Reset so input mode can be entered when query completes

        # Mark this session as the currently executing session for MCP tools
        # MCP tools should operate on the executing session, not the UI-active session
        # Only set if not already set (don't overwrite parent session when spawning subsessions)
        self._is_executing_session = False  # Track if we set the marker
        if self.output.view and not self.window.settings().has("claude_executing_view"):
            self.window.settings().set("claude_executing_view", self.output.view.id())
            self._is_executing_session = True

        # --- Smart Context: auto-add relevant files if enabled ---
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        if settings.get("smart_context_enabled", True):
            self._inject_smart_context()

        # Build prompt with context (may include images)
        full_prompt, images = self._build_prompt_with_context(prompt)
        context_names = [item.name for item in self.pending_context]
        self.pending_context = []  # Clear after use
        self._update_context_display()

        # Store images for RPC call
        self._pending_images = images

        # Use display_prompt for UI if provided, otherwise use full prompt
        ui_prompt = display_prompt if display_prompt else prompt

        # Check if bridge is alive before sending
        if not self.client.is_alive():
            self._status("error: bridge died")
            if not silent:
                self.output.text("\n\n*Bridge process died. Please restart the session.*\n")
            return

        if not silent:
            self.output.show()
            # Auto-name session from first prompt if not already named
            if not self.name:
                self._set_name(ui_prompt[:30].strip() + ("..." if len(ui_prompt) > 30 else ""))
            self.output.prompt(ui_prompt, context_names)
            self._animate()
        query_params = {"prompt": full_prompt}
        if hasattr(self, '_pending_images') and self._pending_images:
            query_params["images"] = self._pending_images
            self._pending_images = []
        if not self.client.send("query", query_params, self._on_done):
            self._status("error: bridge died")
            self.working = False
            self.output.text("\n\n*Failed to send query. Bridge process died.*\n")

    def _inject_smart_context(self) -> None:
        """Auto-add smart context items based on current editor state.

        Adds git-modified files, relevant open files, and current scope info
        to pending_context before the query is sent.
        """
        from .session_core import ContextItem

        try:
            active_view = self.window.active_view()
            current_file = active_view.file_name() if active_view else None

            smart_items = build_smart_context(
                window=self.window,
                current_file=current_file,
                current_view=active_view,
                max_related=3,
                max_git=2,
                max_open=2,
            )

            already = {item.name for item in self.pending_context}
            for item in smart_items:
                path = item.get("path", "")
                if path in already:
                    continue
                content = item.get("content", "")
                reason = item.get("reason", "")
                if not content:
                    continue
                prefix = f"[{reason}] " if reason else ""
                if item.get("type") == "scope":
                    # Scope info goes as a short note, not a full file
                    self.pending_context.append(ContextItem(
                        kind="note",
                        name=f"scope:{path}",
                        content=f"{prefix}{content}",
                    ))
                else:
                    # File content
                    display_path = path.replace(os.path.expanduser("~"), "~")
                    self.pending_context.append(ContextItem(
                        kind="file",
                        name=display_path,
                        content=f"{prefix}File: {display_path}\n```\n{content}\n```",
                    ))
                already.add(path)
        except Exception as e:
            print(f"[Claude] Smart context error: {e}")

    def send_message_with_callback(self, message: str, callback: Callable[[str], None], silent: bool = False, display_prompt: str = None) -> None:
        """Send message and call callback with Claude's response.

        Used by channel mode for sync request-response communication.

        Args:
            message: The message to send to Claude
            callback: Function to call with the response text when complete
            silent: If True, skip UI updates
            display_prompt: Optional display text for UI (ignored if silent=True)
        """
        # Validate session state before setting callback
        if not self.client or not self.initialized:
            print(f"[Claude] send_message_with_callback: session not initialized")
            callback("Error: session not initialized")
            return
        if not self.client.is_alive():
            print(f"[Claude] send_message_with_callback: bridge not running")
            callback("Error: bridge not running")
            return

        print(f"[Claude] send_message_with_callback: sending message")
        self._response_callback = callback
        ui_prompt = display_prompt if display_prompt else (message[:50] + "..." if len(message) > 50 else message)
        self.query(message, display_prompt=ui_prompt, silent=silent)

        # Check if query() failed (working is False if send failed)
        if not self.working and self._response_callback:
            print(f"[Claude] send_message_with_callback: query failed, calling callback with error")
            cb = self._response_callback
            self._response_callback = None
            cb("Error: failed to send query")

    def _on_done(self, result: dict) -> None:
        self.current_tool = None

        # Clear executing session marker - MCP tools should no longer target this session
        if self.output.view and getattr(self, '_is_executing_session', False):
            self.window.settings().erase("claude_executing_view")
            self._is_executing_session = False

        # 1. Determine completion type
        if "error" in result:
            completion = "error"
        elif result.get("status") == "interrupted":
            completion = "interrupted"
        else:
            completion = "success"

        # 2. Handle UI for each completion type
        if completion == "error":
            error_msg = result['error'].get('message', str(result['error'])) if isinstance(result['error'], dict) else str(result['error'])
            self._status("error")
            self.output.text(f"\n\n*Error: {error_msg}*\n")
            if self.output.current:
                self.output.current.working = False
                self.output._render_current()
        elif completion == "interrupted":
            self._status("interrupted")
            self.output.interrupted()
        else:
            self._status("ready")

        self.output.set_name(self.name or "Claude")
        self.output.clear_all_permissions()

        # 3. Response callback fires for ALL completions (channel mode needs to know)
        if self._response_callback:
            callback = self._response_callback
            self._response_callback = None
            response_text = ""
            if self.output.current:
                response_text = "".join(self.output.current.text_chunks)
            try:
                callback(response_text)
            except Exception as e:
                print(f"[Claude] response callback error: {e}")

        # Notify subsession completion (for notalone2)
        if self.output.view:
            view_id = str(self.output.view.id())
            for session in sublime._claude_sessions.values():
                if session.client:
                    session.client.send("subsession_complete", {"subsession_id": view_id})

        # 4. Check for pending retain (interrupt was triggered by compact_boundary)
        if completion == "interrupted" and self._pending_retain:
            retain_content = self._pending_retain
            self._pending_retain = None
            self.output.text(f"\n◎ [retain] ▶\n\n")
            self.query(retain_content, display_prompt="[retain context]")
            return

        # 5. GATE: Only process deferred actions on success
        if completion != "success":
            self.working = False
            self._clear_deferred_state()
            sublime.set_timeout(lambda: self._enter_input_with_draft() if not self.working else None, 100)
            return

        # 5. Process queued prompts (keep working=True, animation continues)
        if self._queued_prompts:
            prompt = self._queued_prompts.pop(0)
            self.output.text(f"\n**[queued]** {prompt}\n\n")
            self.query(prompt)
            return

        # 6. Clear inject_pending - if inject was mid-query, it's done now
        # If inject was queued, queued_inject notification will start new query
        self._inject_pending = False

        # 7. Now set working=False and enter input mode
        self.working = False
        self.last_activity = time.time()
        sublime.set_timeout(lambda: self._enter_input_with_draft() if not self.working else None, 100)

    def _clear_deferred_state(self) -> None:
        """Clear deferred action state. Called on error/interrupt."""
        self._queued_prompts.clear()
        self._inject_pending = False
        self._pending_retain = None
        self._input_mode_entered = False  # Allow re-entry to input mode

    def _enter_input_with_draft(self) -> None:
        """Enter input mode and restore draft with cursor at end."""
        # Skip if already in input mode or session is working
        if self.output.is_input_mode() or self.working:
            return

        # Skip if we've already entered input mode after the last query
        # This prevents duplicate entries from multiple callers (on_activated, _on_done, etc.)
        if self._input_mode_entered:
            return

        self.output.enter_input_mode()

        # Check if enter_input_mode actually succeeded (might have deferred)
        if not self.output.is_input_mode():
            return

        self._input_mode_entered = True

        if self.draft_prompt and self.output.view:
            self.output.view.run_command("append", {"characters": self.draft_prompt})
            end = self.output.view.size()
            self.output.view.sel().clear()
            self.output.view.sel().add(sublime.Region(end, end))


    def queue_prompt(self, prompt: str) -> None:
        """Inject a prompt into the current query stream."""
        self._status(f"injected: {prompt[:30]}...")

        if self.working and self.client:
            # Mid-query: show prompt and inject via bridge
            short = prompt[:100] + "..." if len(prompt) > 100 else prompt
            self.output.text(f"\n◎ [injected] {short} ▶\n\n")
            self._inject_pending = True  # Don't show "done" until inject query completes
            self.client.send("inject_message", {"message": prompt})
        elif self.client:
            # Not working: start query directly (no round-trip delay)
            self.query(prompt)
        else:
            # No client - queue locally for later
            self._queued_prompts.append(prompt)

    def show_queue_input(self) -> None:
        """Show input panel to queue a prompt while session is working."""
        if not self.working:
            # Not working, just enter normal input mode
            self._enter_input_with_draft()
            return

        def on_done(text: str) -> None:
            text = text.strip()
            if text:
                self.queue_prompt(text)

        self.window.show_input_panel(
            "Queue prompt:",
            self.draft_prompt,
            on_done,
            None,  # on_change
            None   # on_cancel
        )

