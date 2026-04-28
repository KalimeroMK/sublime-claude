"""Claude Code commands for Sublime Text."""
import json
import os
import sublime
import sublime_plugin
import platform

from .core import get_active_session, get_session_for_view, create_session
from .session import Session, load_saved_sessions
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



class OpenaiSettingsCommand(sublime_plugin.WindowCommand):
    """Open ClaudeCode settings file for editing."""
    def run(self) -> None:
        self.window.run_command("edit_settings", {
            "base_file": "${packages}/ClaudeCode/ClaudeCode.sublime-settings",
            "default": (
                "{\n"
                '    // OpenAI / Ollama settings\n'
                '    "openai_base_url": "http://localhost:11434",\n'
                '    "openai_model": "qwen2.5:7b",\n'
                '    "openai_api_key": "",\n'
                "\n"
                '    // Claude / Kimi settings\n'
                '    "default_model": "kimi-for-coding",\n'
                '    "anthropic_api_key": "",\n'
                '    "claude_extra_args": "",\n'
                "\n"
                '    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],\n'
                '    "permission_mode": "acceptEdits"\n'
                "}\n"
            )
        })



class ClaudeSettingsCommand(sublime_plugin.WindowCommand):
    """Open ClaudeCode settings file for editing."""
    def run(self) -> None:
        self.window.run_command("edit_settings", {
            "base_file": "${packages}/ClaudeCode/ClaudeCode.sublime-settings",
            "default": (
                "{\n"
                '    // Claude / Kimi settings\n'
                '    "default_model": "kimi-for-coding",\n'
                '    "anthropic_api_key": "",\n'
                '    "claude_extra_args": "",\n'
                "\n"
                '    // OpenAI / Ollama settings\n'
                '    "openai_base_url": "http://localhost:11434",\n'
                '    "openai_model": "qwen2.5:7b",\n'
                '    "openai_api_key": "",\n'
                "\n"
                '    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],\n'
                '    "permission_mode": "acceptEdits"\n'
                "}\n"
            )
        })



class ClaudeCodeStartWithBackendCommand(sublime_plugin.WindowCommand):
    """Start a new session with explicit backend/model picker."""
    def run(self) -> None:
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        self._settings = settings

        # Build list of available backends
        items = [
            ["Kimi (Claude CLI)", "Default cloud model — fastest for coding"],
            ["Claude Opus", "Most capable model for complex tasks"],
            ["Claude Sonnet", "Balanced speed and capability"],
            ["Claude Haiku", "Fastest, good for simple tasks"],
        ]
        self._backends = [
            ("claude", "kimi-for-coding"),
            ("claude", "opus"),
            ("claude", "sonnet"),
            ("claude", "haiku"),
        ]

        # Add Ollama models if available
        oai_url = settings.get("openai_base_url") or ""
        oai_model = settings.get("openai_model") or ""
        if oai_url:
            items.append([f"Ollama: {oai_model or 'default'}", f"Local @ {oai_url}"])
            self._backends.append(("openai", None))

        # Add DeepSeek if configured
        ds_key = settings.get("deepseek_api_key")
        if ds_key:
            items.append(["DeepSeek", "Anthropic-compatible API"])
            self._backends.append(("deepseek", None))

        # Add Codex if available
        import shutil
        if shutil.which("codex"):
            items.append(["OpenAI Codex", "OpenAI's Codex CLI"])
            self._backends.append(("codex", None))

        self.window.show_quick_panel(items, self._on_select)

    def _on_select(self, idx: int) -> None:
        if idx < 0:
            return
        backend, model = self._backends[idx]
        if backend == "openai":
            create_session(self.window, backend="openai")
        elif backend == "deepseek":
            create_session(self.window, backend="deepseek")
        elif backend == "codex":
            create_session(self.window, backend="codex")
        else:
            # Claude backend with specific model override
            if model:
                # Create a temporary profile with this model
                profile = {"model": model}
                create_session(self.window, backend="claude", profile=profile)
            else:
                create_session(self.window, backend="claude")



class ClaudeCodeQueryCommand(sublime_plugin.WindowCommand):
    """Open input for query (focuses output and enters input mode)."""
    def run(self) -> None:
        s = get_active_session(self.window) or create_session(self.window)
        s.output.show()
        s._enter_input_with_draft()



class ClaudeCodeRestartCommand(sublime_plugin.WindowCommand):
    """Restart session, keeping the output view."""
    def run(self) -> None:

        old_session = get_active_session(self.window)
        old_view = None

        if old_session:
            old_view = old_session.output.view
            old_session.stop()
            if old_view and old_view.id() in sublime._claude_sessions:
                del sublime._claude_sessions[old_view.id()]

        # Create new session
        new_session = Session(self.window)

        # Reuse existing view if available
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
        sublime.status_message("Session restarted")



class ClaudeCodeQuerySelectionCommand(sublime_plugin.TextCommand):
    def run(self, edit: sublime.Edit) -> None:
        sel = self.view.sel()
        if not sel or sel[0].empty():
            return

        text = self.view.substr(sel[0])
        fname = self.view.file_name() or "untitled"

        self.view.window().show_input_panel(
            "Ask about selection:",
            "",
            lambda p: self._done(p, text, fname),
            None, None
        )

    def _done(self, prompt: str, selection: str, fname: str) -> None:
        if not prompt.strip():
            return
        window = self.view.window()
        s = get_active_session(window)
        if not s:
            s = create_session(window)
        q = PromptBuilder.selection_query(prompt, fname, selection)
        s.output.show()
        s.output._move_cursor_to_end()
        if s.initialized:
            s.query(q)
        else:
            sublime.set_timeout(lambda: s.query(q), 500)



class ClaudeCodeQueryFileCommand(sublime_plugin.WindowCommand):
    """Send current file as prompt."""
    def run(self) -> None:
        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file to send")
            return

        s = get_active_session(self.window)
        if not s:
            s = create_session(self.window)
        content = view.substr(sublime.Region(0, view.size()))
        fname = view.file_name()

        self.window.show_input_panel(
            "Ask about file:",
            "",
            lambda p: self._done(p, content, fname),
            None, None
        )

    def _done(self, prompt: str, content: str, fname: str) -> None:
        if not prompt.strip():
            return
        s = get_active_session(self.window)
        if not s:
            return
        q = PromptBuilder.file_query(prompt, fname, content)
        s.output.show()
        s.output._move_cursor_to_end()
        if s.initialized:
            s.query(q)
        else:
            sublime.set_timeout(lambda: s.query(q), 500)



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


