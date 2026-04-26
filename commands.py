"""Claude Code commands for Sublime Text."""
import sublime
import sublime_plugin
import platform

from .core import get_active_session, get_session_for_view, create_session
from .session import Session, load_saved_sessions

# Fallback model lists per backend (used when no cache/settings available)
DEFAULT_MODELS = {
    "claude": [
        ["opus", "Opus 4.7"],
        ["opus@400k", "Opus 4.7 (400K context)"],
        ["claude-opus-4-6[1m]", "Opus 4.6 (1M context)"],
        ["claude-opus-4-6[1m]@400k", "Opus 4.6 (400K context)"],
        ["claude-opus-4-6", "Opus 4.6"],
        ["sonnet", "Sonnet 4.6"],
        ["haiku", "Haiku 4.5"],
        ["claude-opus-4-5", "Opus 4.5"],
        ["claude-sonnet-4-5", "Sonnet 4.5"],
    ],
    "copilot": [
        ["claude-sonnet-4-6", "Sonnet 4.6"],
        ["claude-opus-4-6", "Opus 4.6"],
        ["gpt-5.3-codex", "GPT-5.3 Codex"],
        ["gpt-5-mini", "GPT-5 Mini (free)"],
    ],
    "codex": [
        ["gpt-5.5", "GPT-5.5"],
        ["gpt-5.4", "GPT-5.4"],
        ["gpt-5.4-mini", "GPT-5.4 Mini"],
        ["gpt-5.3-codex", "GPT-5.3 Codex"],
        ["o3", "O3"],
    ],
    "deepseek": [
        ["deepseek-v4-pro", "DeepSeek V4 Pro"],
        ["deepseek-v4-flash", "DeepSeek V4 Flash"],
    ],
    "openai": [
        ["gpt-4o", "GPT-4o"],
        ["gpt-4o-mini", "GPT-4o Mini"],
        ["gpt-4-turbo", "GPT-4 Turbo"],
        ["o3-mini", "O3 Mini"],
        ["llama3.1", "Ollama: Llama 3.1"],
        ["qwen2.5", "Ollama: Qwen 2.5"],
        ["mistral", "Ollama: Mistral"],
        ["phi4", "Ollama: Phi-4"],
    ],
}

class ClaudeCodeStartCommand(sublime_plugin.WindowCommand):
    """Start a new session. Shows profile picker if profiles are configured."""
    def run(self, profile: str = None, persona_id: int = None, backend: str = None) -> None:
        from .settings import load_profiles_and_checkpoints, load_project_settings
        import os

        # Auto-detect backend from config if not explicitly specified
        if backend is None:
            sublime_settings = sublime.load_settings("ClaudeCode.sublime-settings")
            backend = sublime_settings.get("default_backend")
            if not backend:
                # Auto-detect based on what's configured
                has_openai = bool(sublime_settings.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL"))
                has_deepseek = bool(sublime_settings.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY"))
                if has_openai:
                    backend = "openai"
                elif has_deepseek:
                    backend = "deepseek"
                else:
                    backend = "claude"

        # Validate backend-specific settings
        if backend == "openai":
            base_url = sublime_settings.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")
            model = sublime_settings.get("openai_model") or os.environ.get("OPENAI_MODEL", "")
            if not base_url:
                sublime.error_message("OpenAI base URL not set. Add 'openai_base_url' to ClaudeCode settings.")
                return
            if not model:
                sublime.error_message("OpenAI model not set. Add 'openai_model' to ClaudeCode settings.")
                return
        elif backend == "deepseek":
            if not sublime_settings.get("deepseek_api_key") and not os.environ.get("DEEPSEEK_API_KEY"):
                sublime.error_message("DeepSeek API key not set. Add 'deepseek_api_key' to ClaudeCode settings.")
                return

        # If persona_id specified, acquire and start
        if persona_id:
            self._start_with_persona(persona_id)
            return

        # Get project profiles path
        project_path = None
        cwd = None
        if self.window.folders():
            cwd = self.window.folders()[0]
            project_path = os.path.join(cwd, ".claude", "profiles.json")

        profiles, checkpoints = load_profiles_and_checkpoints(project_path)
        settings = load_project_settings(cwd)

        # If profile specified directly, use it
        if profile:
            profile_config = profiles.get(profile, {}).copy()
            profile_config["_name"] = profile  # Store name for status bar
            create_session(self.window, profile=profile_config, backend=backend)
            return

        # Build options list
        options = []

        # Default option (always available)
        options.append(("default", None, "🆕 New Session", "Start fresh with default settings"))

        # Personas - get URL from sublime settings
        sublime_settings = sublime.load_settings("ClaudeCode.sublime-settings")
        persona_url = sublime_settings.get("persona_url", "http://localhost:5002/personas")
        options.append(("persona", persona_url, "👤 From Persona...", "Acquire a persona identity"))

        # Profiles
        for name, config in profiles.items():
            desc = config.get("description", f"{config.get('model', 'default')} model")
            options.append(("profile", name, f"📋 {name}", desc))

        # Checkpoints (Claude-only, session IDs are backend-specific)
        if backend == "claude":
            for name, config in checkpoints.items():
                desc = config.get("description", "Saved checkpoint")
                options.append(("checkpoint", name, f"📍 {name}", desc))

        if len(options) == 1:
            # Only default, just start
            create_session(self.window, backend=backend)
            return

        # Show quick panel
        items = [[opt[2], opt[3]] for opt in options]

        def on_select(idx):
            if idx < 0:
                return
            opt_type, opt_name, _, _ = options[idx]
            if opt_type == "default":
                create_session(self.window, backend=backend)
            elif opt_type == "persona":
                self._show_persona_picker(opt_name, backend=backend)  # opt_name contains the URL
            elif opt_type == "profile":
                profile_config = profiles.get(opt_name, {}).copy()
                profile_config["_name"] = opt_name  # Store name for status bar
                create_session(self.window, profile=profile_config, backend=backend)
            elif opt_type == "checkpoint":
                checkpoint = checkpoints.get(opt_name, {})
                session_id = checkpoint.get("session_id")
                if session_id:
                    create_session(self.window, resume_id=session_id, fork=True, backend=backend)
                else:
                    sublime.error_message(f"Checkpoint '{opt_name}' has no session_id")

        self.window.show_quick_panel(items, on_select)

    def _show_persona_picker(self, persona_url: str, backend: str = "claude") -> None:
        """Show list of personas to pick from."""
        from . import persona_client
        import threading

        def fetch_and_show():
            personas = persona_client.list_personas(persona_url)
            if not personas:
                sublime.set_timeout(lambda: sublime.status_message("No personas available"), 0)
                return

            # Build options: unlocked first, then locked
            unlocked = [p for p in personas if not p.get("is_locked")]
            locked = [p for p in personas if p.get("is_locked")]

            options = []
            for p in unlocked:
                tags = ", ".join(p.get("tags", [])) if p.get("tags") else ""
                desc = p.get("notes", tags) or "No description"
                options.append((p["id"], f"👤 {p['alias']}", desc[:60]))

            for p in locked:
                locked_by = p.get("locked_by_session", "unknown")
                options.append((p["id"], f"🔒 {p['alias']}", f"Locked by {locked_by}"))

            def show_panel():
                items = [[opt[1], opt[2]] for opt in options]

                def on_select(idx):
                    if idx < 0:
                        return
                    persona_id = options[idx][0]
                    self._start_with_persona(persona_id, persona_url, backend=backend)

                self.window.show_quick_panel(items, on_select)

            sublime.set_timeout(show_panel, 0)

        threading.Thread(target=fetch_and_show, daemon=True).start()

    def _start_with_persona(self, persona_id: int, persona_url: str = None, backend: str = "claude") -> None:
        """Acquire persona and start session."""
        from . import persona_client
        from .settings import load_project_settings
        import threading
        import os

        if not persona_url:
            cwd = self.window.folders()[0] if self.window.folders() else None
            settings = load_project_settings(cwd)
            persona_url = settings.get("persona_url")

        if not persona_url:
            sublime.error_message("persona_url not configured in settings")
            return

        def acquire_and_start():
            # Generate session ID for locking
            import uuid
            session_id = f"sublime-{uuid.uuid4().hex[:8]}"

            result = persona_client.acquire_persona(session_id, persona_id=persona_id, base_url=persona_url)

            if "error" in result:
                sublime.set_timeout(
                    lambda: sublime.error_message(f"Failed to acquire persona: {result['error']}"),
                    0
                )
                return

            persona = result.get("persona", {})
            ability = result.get("ability", {})
            handoff_notes = result.get("handoff_notes")

            # Build profile config from persona (fallback to persona-level fields if ability empty)
            profile_config = {
                "model": ability.get("model") or persona.get("model") or "sonnet",
                "system_prompt": ability.get("system_prompt") or persona.get("system_prompt") or "",
                "persona_id": persona_id,
                "persona_session_id": session_id,
                "persona_url": persona_url,
                "description": f"Persona: {persona.get('alias', 'unknown')}"
            }

            def start():
                s = create_session(self.window, profile=profile_config, backend=backend)
                # Show handoff notes if present
                if handoff_notes:
                    s.output.text(f"\n*Handoff notes:* {handoff_notes}\n")
                sublime.status_message(f"Acquired persona: {persona.get('alias', 'unknown')}")

            sublime.set_timeout(start, 0)

        threading.Thread(target=acquire_and_start, daemon=True).start()



class ClaudeCodeQueryCommand(sublime_plugin.WindowCommand):
    """Open input for query (focuses output and enters input mode)."""
    def run(self) -> None:
        s = get_active_session(self.window) or create_session(self.window)
        s.output.show()
        s._enter_input_with_draft()



class ClaudeCodeAddFileCommand(sublime_plugin.WindowCommand):
    """Add current file to context."""
    def run(self) -> None:
        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file to add")
            return
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return
        content = view.substr(sublime.Region(0, view.size()))
        s.add_context_file(view.file_name(), content)
        name = view.file_name().split("/")[-1]
        sublime.status_message(f"Added: {name}")



class ClaudeCodeAddSelectionCommand(sublime_plugin.WindowCommand):
    """Add selection to context."""
    def run(self) -> None:
        view = self.window.active_view()
        if not view:
            sublime.status_message("No active view")
            return
        sel = view.sel()
        if not sel or sel[0].empty():
            sublime.status_message("No selection")
            return
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return
        content = view.substr(sel[0])
        path = view.file_name() or "untitled"
        s.add_context_selection(path, content)
        name = path.split("/")[-1] if "/" in path else path
        sublime.status_message(f"Added selection from: {name}")



class ClaudeCodeClearContextCommand(sublime_plugin.WindowCommand):
    """Clear pending context."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if s:
            s.clear_context()
            sublime.status_message("Context cleared")



class ClaudeCodeInterruptCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            return
        # If working, always interrupt — don't just clear input
        if s.working:
            s.interrupt()
            return
        # If idle in input mode with text, clear the input
        if s.output.is_input_mode() and s.output.get_input_text().strip():
            view = s.output.view
            start = s.output._input_start
            view.run_command("claude_replace", {
                "start": start,
                "end": view.size(),
                "text": ""
            })
            view.sel().clear()
            view.sel().add(sublime.Region(start, start))
            return
        s.interrupt()



class ClaudeCloseSessionCommand(sublime_plugin.TextCommand):
    """Close Claude session view with confirmation."""
    def run(self, edit):
        view = self.view
        session = sublime._claude_sessions.get(view.id())
        if not session or not (session.initialized or session.is_sleeping):
            view.close()
            return
        # Use set_timeout so the dialog doesn't block the command dispatch loop.
        # Blocking mid-dispatch can cause the next Cmd+W to bypass our keybinding.
        def _ask():
            # Re-check session (may have closed in the meantime)
            s = sublime._claude_sessions.get(view.id())
            if not s or not (s.initialized or s.is_sleeping):
                view.close()
                return
            if sublime.ok_cancel_dialog("Close this Claude session?", "Close"):
                s.stop()
                if view.id() in sublime._claude_sessions:
                    del sublime._claude_sessions[view.id()]
                view.close()
        sublime.set_timeout(_ask, 0)



class ClaudeCodeToggleCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        s = get_active_session(self.window)
        if s and s.output.view and s.output.view.is_valid():
            # View exists - toggle visibility
            group, _ = self.window.get_view_index(s.output.view)
            if group >= 0:
                # Visible - hide it
                self.window.focus_view(s.output.view)
                self.window.run_command("close_file")
            else:
                # Hidden/closed - show it
                s.output.show()
        elif s:
            # No view yet - show it
            s.output.show()



class ClaudeCodeStopCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:

        s = get_active_session(self.window)
        if s and s.output.view:
            view_id = s.output.view.id()
            s.stop()
            if view_id in sublime._claude_sessions:
                del sublime._claude_sessions[view_id]



class ClaudeSubmitInputCommand(sublime_plugin.TextCommand):
    """Handle Enter key in input mode - submit the prompt."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if not s:
            return

        # Wake sleeping session on Enter
        if s.is_sleeping:
            s.wake()
            return

        # Check for question free-text input first
        if s.output.submit_question_input():
            return

        if not s.output.is_input_mode():
            return

        text = s.output.get_input_text().strip()

        # Ignore empty input
        if not text:
            return

        # Check for slash commands
        cmd = CommandParser.parse(text)
        if cmd:
            s.output.exit_input_mode(keep_text=False)
            s.draft_prompt = ""
            self._handle_command(s, cmd)
            return

        s.output.exit_input_mode(keep_text=False)
        s.draft_prompt = ""

        # If session is working, queue the prompt instead
        if s.working:
            s.queue_prompt(text)
        else:
            s.query(text)

    def _handle_command(self, session, cmd):
        """Handle a slash command."""
        if cmd.name == "clear":
            self._cmd_clear(session)
        elif cmd.name == "compact":
            self._cmd_compact(session)
        elif cmd.name == "context":
            self._cmd_context(session)
        else:
            # Unknown command - send as regular prompt to Claude
            session.query(cmd.raw)

    def _cmd_clear(self, session):
        """Clear conversation history."""
        session.output.clear()
        sublime.status_message("Claude: conversation cleared")

    def _cmd_compact(self, session):
        """Send /compact to Claude for context summarization."""
        session.query("/compact", display_prompt="/compact")

    def _cmd_context(self, session):
        """Show pending context items."""
        if not session.pending_context:
            session.output.text("\n*No pending context.*\n")
        else:
            lines = ["\n*Pending context:*"]
            for item in session.pending_context:
                lines.append(f"  📎 {item.name}")
            lines.append("")
            session.output.text("\n".join(lines))
        session.output.enter_input_mode()



class ClaudeInsertCommand(sublime_plugin.TextCommand):
    """Insert text at position in Claude output view."""
    def run(self, edit, pos, text):
        self.view.insert(edit, pos, text)



class ClaudeReplaceCommand(sublime_plugin.TextCommand):
    """Replace region in Claude output view."""
    def run(self, edit, start, end, text):
        self.view.replace(edit, sublime.Region(start, end), text)



class ClaudeReplaceContentCommand(sublime_plugin.TextCommand):
    """Replace entire view content."""
    def run(self, edit, content):
        self.view.replace(edit, sublime.Region(0, self.view.size()), content)



class ClaudeInsertNewlineCommand(sublime_plugin.TextCommand):
    """Insert newline in input mode (Shift+Enter)."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s and s.output.is_input_mode():
            for region in self.view.sel():
                if s.output.is_in_input_region(region.begin()):
                    self.view.insert(edit, region.begin(), "\n")


# --- Permission Commands ---


class ClaudePermissionAllowCommand(sublime_plugin.TextCommand):
    """Handle Y key - allow permission or approve plan."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            if not s.output.handle_plan_key("y"):
                s.output.handle_permission_key("y")



class ClaudePermissionDenyCommand(sublime_plugin.TextCommand):
    """Handle N key - deny permission or reject plan."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            if not s.output.handle_plan_key("n"):
                s.output.handle_permission_key("n")

