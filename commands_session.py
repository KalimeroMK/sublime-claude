"""Claude Code commands for Sublime Text."""
import json
import os
import sublime
import sublime_plugin
import platform

from .core import get_active_session, get_session_for_view, create_session
from .session import Session, load_saved_sessions
from .constants import OUTPUT_VIEW_SETTING, ACTIVE_VIEW_SETTING
from .prompt_builder import PromptBuilder
from .command_parser import CommandParser

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



class ClaudeCodeClearCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        s = get_active_session(self.window)
        if s:
            s.output.clear()



class ClaudeCodeCopyCommand(sublime_plugin.WindowCommand):
    """Copy entire conversation to clipboard."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if s and s.output.view and s.output.view.is_valid():
            content = s.output.view.substr(sublime.Region(0, s.output.view.size()))
            sublime.set_clipboard(content)
            sublime.status_message("Conversation copied to clipboard")



class ClaudeCodeSaveCheckpointCommand(sublime_plugin.WindowCommand):
    """Save current session as a named checkpoint for future forking."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s or not s.session_id:
            sublime.status_message("No active session with ID to checkpoint")
            return

        def on_done(name: str) -> None:
            name = name.strip()
            if not name:
                return

            from .mcp_server import _save_checkpoint
            if _save_checkpoint(name, s.session_id, s.name or "Checkpoint"):
                sublime.status_message(f"Checkpoint '{name}' saved")
            else:
                sublime.error_message(f"Failed to save checkpoint '{name}'")

        default_name = (s.name or "checkpoint").lower().replace(" ", "-")[:20]
        self.window.show_input_panel("Checkpoint name:", default_name, on_done, None, None)



class ClaudeCodeUsageCommand(sublime_plugin.WindowCommand):
    """Show API usage statistics."""
    def run(self) -> None:
        # Get current session usage
        s = get_active_session(self.window)
        current_usage = []
        if s:
            current_usage = [
                f"## Current Session: {s.name}",
                f"",
                f"Queries: {s.query_count}",
                f"Total Cost: ${s.total_cost:.4f}",
                f"",
            ]

        # Get all saved sessions usage
        sessions = load_saved_sessions()
        total_cost = sum(sess.get("total_cost", 0) for sess in sessions)
        total_queries = sum(sess.get("query_count", 0) for sess in sessions)

        lines = [
            "# API Usage Statistics",
            "",
            f"Total (All Sessions): ${total_cost:.4f} ({total_queries} queries)",
            "",
        ]

        if current_usage:
            lines.extend(current_usage)

        if sessions:
            lines.extend([
                "## Recent Sessions",
                ""
            ])
            for sess in sessions[:10]:  # Show last 10
                name = sess.get("name", "Untitled")
                cost = sess.get("total_cost", 0)
                queries = sess.get("query_count", 0)
                lines.append(f"- {name}: ${cost:.4f} ({queries} queries)")

        # Show in quick panel with monospace font
        content = "\n".join(lines)

        # Create a new output panel to show usage
        panel = self.window.create_output_panel("claude_usage")
        panel.set_read_only(False)
        panel.run_command("append", {"characters": content})
        panel.set_read_only(True)
        panel.settings().set("word_wrap", False)
        panel.settings().set("gutter", False)
        self.window.run_command("show_panel", {"panel": "output.claude_usage"})



class ClaudeCodeResetInputCommand(sublime_plugin.WindowCommand):
    """Force reset input mode state when it gets corrupted."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if s:
            s.output.reset_input_mode()
            sublime.status_message("Input mode reset")



class ClaudeCodeRenameCommand(sublime_plugin.WindowCommand):
    """Rename the current session."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            return
        current = s.name or ""
        self.window.show_input_panel(
            "Session name:",
            current,
            lambda name: self._done(name),
            None, None
        )

    def _done(self, name: str) -> None:
        if name.strip():
            s = get_active_session(self.window)
            if s:
                s._set_name(name.strip())



class ClaudeCodeTagSessionCommand(sublime_plugin.WindowCommand):
    """Add or edit tags for the current session."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            return
        current = ", ".join(s.tags) if s.tags else ""
        self.window.show_input_panel(
            "Session tags (comma-separated):",
            current,
            lambda tags: self._done(tags),
            None, None
        )

    def _done(self, tags: str) -> None:
        s = get_active_session(self.window)
        if not s:
            return
        if tags.strip():
            s.tags = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            s.tags = []
        s._update_status_bar()
        s._save_state()
        sublime.status_message(f"Tags: {', '.join(s.tags) if s.tags else 'none'}")



class ClaudeCodeShowUsageGraphCommand(sublime_plugin.WindowCommand):
    """Show token usage graph for the current session."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session")
            return
        if not s._usage_history:
            sublime.status_message("No usage data yet")
            return

        lines = ["# Token Usage Graph", ""]
        hist = s._usage_history
        max_tok = max(max(h["in"], h["out"]) for h in hist) or 1
        bar_width = 20

        for h in hist[-20:]:  # Show last 20 queries
            q = h["q"]
            inp = h["in"]
            out = h["out"]
            in_bar = int(inp / max_tok * bar_width)
            out_bar = int(out / max_tok * bar_width)
            in_str = "█" * in_bar + "░" * (bar_width - in_bar)
            out_str = "▓" * out_bar + "░" * (bar_width - out_bar)
            lines.append(f"Q{q:3d}: in [{in_str}] {inp:,}")
            lines.append(f"      out [{out_str}] {out:,}")
            lines.append("")

        # Totals
        total_in = sum(h["in"] for h in hist)
        total_out = sum(h["out"] for h in hist)
        lines.append(f"**Total: {total_in:,} in + {total_out:,} out = {total_in + total_out:,} tokens**")
        lines.append(f"**Queries: {len(hist)} | Est. cost: ${s.total_cost:.4f}**")

        panel = self.window.create_output_panel("claude_usage_graph")
        panel.run_command("append", {"characters": "\n".join(lines)})
        panel.set_syntax_file("Packages/Markdown/Markdown.sublime-syntax")
        self.window.run_command("show_panel", {"panel": "output.claude_usage_graph"})



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



class ClaudeSleepSessionCommand(sublime_plugin.WindowCommand):
    """Put the active session to sleep."""
    def run(self):
        session = get_active_session(self.window)
        if session and not session.is_sleeping:
            session.sleep()

    def is_enabled(self):
        session = get_active_session(self.window)
        return session is not None and not session.is_sleeping



class ClaudeWakeSessionCommand(sublime_plugin.WindowCommand):
    """Wake a sleeping session."""
    def run(self):
        session = get_active_session(self.window)
        if session and session.is_sleeping:
            session.wake()

    def is_enabled(self):
        session = get_active_session(self.window)
        return session is not None and session.is_sleeping



class ClaudeCodeResumeCommand(sublime_plugin.WindowCommand):
    """Resume a previous session."""
    def run(self) -> None:
        cwd = self.window.folders()[0] if self.window.folders() else ""
        sessions = [s for s in load_saved_sessions() if s.get("project", "") == cwd]
        if not sessions:
            sublime.status_message("No saved sessions to resume")
            return

        # Build quick panel items
        items = []
        for s in sessions:
            name = s.get("name") or "(unnamed)"
            backend = s.get("backend", "claude")
            prefix = f"[{backend}] " if backend != "claude" else ""
            project = s.get("project", "")
            if project:
                project = "  " + project.split("/")[-1]
            cost = s.get("total_cost", 0)
            cost_str = f"  ${cost:.4f}" if cost else ""
            items.append([f"{prefix}{name}", f"{project}{cost_str}"])

        def on_select(idx):
            if idx >= 0:
                session_id = sessions[idx].get("session_id")
                name = sessions[idx].get("name")
                backend = sessions[idx].get("backend", "claude")
                s = create_session(self.window, resume_id=session_id, backend=backend)
                if name:
                    s.name = name
                    s.output.show()
                    s.output.set_name(name)
                    s._update_status_bar()

        self.window.show_quick_panel(items, on_select)



class ClaudeCodeSwitchCommand(sublime_plugin.WindowCommand):
    """Switch between active sessions in this window."""
    def run(self, backend: str = "claude") -> None:
        import os
        import shutil
        from .core import create_session

        backend_prefix = f"[{backend}] " if backend != "claude" else ""
        has_codex = bool(shutil.which("codex"))
        has_copilot = os.path.exists(os.path.join(os.path.dirname(__file__), "bridge", "copilot_main.py"))
        has_deepseek = bool(sublime.load_settings("ClaudeCode.sublime-settings").get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY"))

        # Get all sessions in this window
        sessions_in_window = []
        for view_id, session in sublime._claude_sessions.items():
            if session.window == self.window:
                sessions_in_window.append((view_id, session))

        # Build quick panel items
        active_view_id = self.window.settings().get(ACTIVE_VIEW_SETTING)
        items = []
        actions = []  # ("new", None) | ("focus", session)

        # Add active session at top if exists
        active_session = None
        for view_id, s in sessions_in_window:
            if view_id == active_view_id:
                active_session = s
                break

        # Show "Active:" option only when not in a Claude output view (for quick jumping from file view)
        current_view = self.window.active_view()
        in_output_view = current_view and current_view.settings().get(OUTPUT_VIEW_SETTING)
        current_file = current_view.file_name() if current_view else None

        # Add "New Session with This File" option when in a non-session file
        if not in_output_view and current_file:
            filename = os.path.basename(current_file)
            items.append([f"📎 {backend_prefix}New with ctx:{filename}", "Create session with this file as context"])
            actions.append(("new_with_file", current_file))

        if active_session and not in_output_view:
            name = active_session.name or "(unnamed)"
            if active_session.is_sleeping:
                status = "sleeping"
                prefix = "⏸ "
            elif active_session.working:
                status = "working..."
                prefix = "Active: "
            else:
                status = "ready"
                prefix = "Active: "
            cost = f"${active_session.total_cost:.4f}" if active_session.total_cost > 0 else ""
            detail = f"{status}  {cost}  {active_session.query_count}q" if cost else f"{status}  {active_session.query_count}q"
            items.append([f"{prefix}{name}", detail])
            actions.append(("focus", active_session))

        # Add other sessions (not the active one)
        for view_id, s in sessions_in_window:
            if view_id == active_view_id:
                continue  # Already shown at top
            name = s.name or "(unnamed)"
            if s.is_sleeping:
                marker = "⏸ "
                status = "sleeping"
            elif s.working:
                marker = "\u2022 "
                status = "working..."
            else:
                marker = "  "
                status = "ready"
            cost = f"${s.total_cost:.4f}" if s.total_cost > 0 else ""
            detail = f"{status}  {cost}  {s.query_count}q" if cost else f"{status}  {s.query_count}q"
            items.append([f"{marker}{name}", detail])
            actions.append(("focus", s))

        # Add session actions when in a session output view
        if in_output_view and active_session:
            if not active_session.working and active_session.session_id:
                items.append(["↩ Undo Message", "Rewind session to previous turn"])
                actions.append(("undo_message", active_session))
            if active_session and not active_session.is_sleeping:
                items.append(["○ Sleep Session", "Put session to sleep, free resources"])
                actions.append(("sleep", active_session))
            items.append(["🔄 Restart Session", "Restart current session, keep output"])
            actions.append(("restart", active_session))

        # Add profiles and checkpoints
        from .settings import load_profiles_and_checkpoints

        # Get project profiles path
        project_path = None
        if self.window.folders():
            project_path = os.path.join(self.window.folders()[0], ".claude", "profiles.json")

        profiles, checkpoints = load_profiles_and_checkpoints(project_path)

        for name, config in profiles.items():
            desc = config.get("description", f"{config.get('model', 'default')} model")
            items.append([f"😶 {backend_prefix}{name}", desc])
            config_with_name = config.copy()
            config_with_name["_name"] = name
            actions.append(("profile", config_with_name))

        if backend == "claude":
            for name, config in checkpoints.items():
                desc = config.get("description", "Saved checkpoint")
                items.append([f"📍 {backend_prefix}{name}", desc])
                actions.append(("checkpoint", config))

        # Add "From Persona" option
        sublime_settings = sublime.load_settings("ClaudeCode.sublime-settings")
        persona_url = sublime_settings.get("persona_url", "http://localhost:5002/personas")
        items.append(["👤 From Persona...", "Acquire a persona identity"])
        actions.append(("persona", persona_url))

        # Add "New Session" option
        # Add "New Session with Model" option
        items.append([f"🆕 {backend_prefix}New Session", "Start fresh with default settings"])
        actions.append(("new", None))

        # Model selection from settings + cached models
        all_models = sublime_settings.get("models", {})
        # Also read cached models from copilot SDK
        cached_models_file = os.path.expanduser("~/.claude/sublime_cached_models.json")
        if os.path.exists(cached_models_file):
            try:
                import json as _json
                with open(cached_models_file) as f:
                    cached = _json.load(f)
                for b, models in cached.items():
                    if b not in all_models:
                        all_models[b] = models
            except Exception:
                pass
        backend_models = all_models.get(backend, [])
        for m in backend_models:
            if isinstance(m, str):
                model_id, model_name = m, m
            elif isinstance(m, list) and len(m) >= 2:
                model_id, model_name = m[0], m[1]
            else:
                continue
            items.append([f"🆕 {backend_prefix}{model_name}", f"New session with {model_id}"])
            actions.append(("new_model", model_id))

        # Add "Fork Session" option when in a session window
        if in_output_view and active_session:
            items.append(["🍴 Fork Session", "Create new session with copy of history"])
            actions.append(("fork", active_session))

        # Add "Switch Backend" options
        other_backends = []
        if has_codex and backend != "codex":
            other_backends.append("codex")
        if has_copilot and backend != "copilot":
            other_backends.append("copilot")
        if has_deepseek and backend != "deepseek":
            other_backends.append("deepseek")
        if backend != "claude":
            other_backends.append("claude")
        for other in other_backends:
            items.append([f"⇄ Switch to {other}", f"Show {other} options"])
            actions.append(("switch_backend", other))

        def on_select(idx):
            if idx >= 0:
                action, data = actions[idx]
                if action == "switch_backend":
                    # Re-open panel with new backend
                    sublime.set_timeout(lambda: self.run(backend=data), 0)
                    return
                if action == "undo_message" and data:
                    data.undo_message()
                elif action == "restart" and data:
                    # Show profile picker for restart
                    self._show_restart_picker(data, profiles, checkpoints)
                elif action == "new_with_file" and data:
                    # Create new session with current file as context
                    s = create_session(self.window, backend=backend)
                    # Read file content and add to context
                    try:
                        with open(data, "r", encoding="utf-8") as f:
                            content = f.read()
                        s.add_context_file(data, content)
                    except Exception as e:
                        print(f"[Claude] Error adding file context: {e}")
                elif action == "new":
                    create_session(self.window, backend=backend)
                elif action == "new_model":
                    create_session(self.window, profile={"model": data}, backend=backend)
                elif action == "profile":
                    create_session(self.window, profile=data, backend=backend)
                elif action == "checkpoint":
                    session_id = data.get("session_id")
                    if session_id:
                        create_session(self.window, resume_id=session_id, fork=True, backend=backend)
                elif action == "fork" and data:
                    # Fork the current session
                    if data.session_id:
                        create_session(self.window, resume_id=data.session_id, fork=True, backend=data.backend)
                elif action == "persona" and data:
                    # Show persona picker
                    self._show_persona_picker(data, backend=backend)
                elif action == "sleep" and data:
                    data.sleep()
                elif action == "focus" and data:
                    data.output.show()

        self.window.show_quick_panel(items, on_select)

    def _show_persona_picker(self, persona_url: str, backend: str = "claude") -> None:
        """Show list of personas to pick from."""
        from . import persona_client
        from .core import create_session
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

    def _start_with_persona(self, persona_id: int, persona_url: str, backend: str = "claude") -> None:
        """Acquire persona and start session."""
        from . import persona_client
        from .core import create_session
        import threading
        import uuid

        def acquire_and_start():
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
                if handoff_notes:
                    s.output.text(f"\n*Handoff notes:* {handoff_notes}\n")
                sublime.status_message(f"Acquired persona: {persona.get('alias', 'unknown')}")

            sublime.set_timeout(start, 0)

        threading.Thread(target=acquire_and_start, daemon=True).start()

    def _show_restart_picker(self, session, profiles, checkpoints):
        """Show profile/checkpoint picker for restart."""
        from .core import create_session

        items = []
        actions = []

        # Default restart
        items.append(["🆕 Fresh Start", "Restart with default settings"])
        actions.append(("default", None))

        # Profiles
        for name, config in profiles.items():
            desc = config.get("description", f"{config.get('model', 'default')} model")
            items.append([f"📋 {name}", desc])
            config_with_name = config.copy()
            config_with_name["_name"] = name
            actions.append(("profile", config_with_name))

        # Checkpoints
        for name, config in checkpoints.items():
            desc = config.get("description", "Saved checkpoint")
            items.append([f"📍 {name}", desc])
            actions.append(("checkpoint", config))

        def on_select(idx):
            if idx < 0:
                return

            action, data = actions[idx]
            old_view = session.output.view

            # Stop old session
            session.stop()
            if old_view and old_view.id() in sublime._claude_sessions:
                del sublime._claude_sessions[old_view.id()]

            # Create new session with selected config
            if action == "checkpoint":
                session_id = data.get("session_id")
                new_session = Session(self.window, resume_id=session_id, fork=True, backend=session.backend)
            elif action == "profile":
                new_session = Session(self.window, profile=data, backend=session.backend)
            else:
                new_session = Session(self.window, backend=session.backend)

            # Reuse existing view
            if old_view and old_view.is_valid():
                new_session.output.view = old_view
                new_session.output.clear()
                sublime._claude_sessions[old_view.id()] = new_session

            new_session.start()
            if new_session.output.view:
                new_session.output.view.set_name("Claude")
                if new_session.output.view.id() not in sublime._claude_sessions:
                    sublime._claude_sessions[new_session.output.view.id()] = new_session
            new_session.output.show()

        self.window.show_quick_panel(items, on_select)



class ClaudeCodeForkCommand(sublime_plugin.WindowCommand):
    """Fork the current active session."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s or not s.session_id:
            sublime.status_message("No active session to fork")
            return

        # Create forked session
        forked = create_session(self.window, resume_id=s.session_id, fork=True, backend=s.backend)
        forked_name = f"{s.name or 'session'} (fork)"
        forked.name = forked_name
        forked.output.set_name(forked_name)
        sublime.status_message(f"Forked session: {forked_name}")



class ClaudeCodeForkFromCommand(sublime_plugin.WindowCommand):
    """Fork from a session selected from list."""
    def run(self) -> None:

        # Combine active sessions and saved sessions
        items = []
        sources = []

        # Active sessions in this window
        for view_id, session in sublime._claude_sessions.items():
            if session.window == self.window and session.session_id:
                name = session.name or "(unnamed)"
                cost = f"${session.total_cost:.4f}" if session.total_cost > 0 else ""
                items.append([f"● {name}", f"active  {cost}  {session.query_count}q"])
                sources.append(("active", view_id, session.session_id, name, session.backend))

        # Saved sessions
        saved = load_saved_sessions()
        for s in saved:
            session_id = s.get("session_id")
            name = s.get("name") or "(unnamed)"
            if any(src[2] == session_id for src in sources):
                continue
            project = s.get("project", "")
            if project:
                project = project.split("/")[-1]
            cost = s.get("total_cost", 0)
            cost_str = f"${cost:.4f}" if cost else ""
            items.append([name, f"saved  {project}  {cost_str}"])
            sources.append(("saved", None, session_id, name, s.get("backend", "claude")))

        if not items:
            sublime.status_message("No sessions to fork from")
            return

        def on_select(idx):
            if idx >= 0:
                source_type, view_id, session_id, name, src_backend = sources[idx]
                forked = create_session(self.window, resume_id=session_id, fork=True, backend=src_backend)
                forked_name = f"{name} (fork)"
                forked.name = forked_name
                forked.output.set_name(forked_name)
                sublime.status_message(f"Forked session: {forked_name}")

        self.window.show_quick_panel(items, on_select)


