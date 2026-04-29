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


class ClaudeSelectEffortCommand(sublime_plugin.WindowCommand):
    """Change reasoning effort for current session (persists via settings, applied on next restart)."""
    LEVELS = ["low", "medium", "high", "max"]

    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session")
            return
        if s.backend != "claude":
            sublime.status_message("Effort only supported for claude backend")
            return

        def on_select(idx):
            if idx < 0:
                return
            level = self.LEVELS[idx]
            settings = sublime.load_settings("ClaudeCode.sublime-settings")
            settings.set("effort", level)
            sublime.save_settings("ClaudeCode.sublime-settings")
            sublime.status_message(f"Effort set to {level} — takes effect on next session restart")

        self.window.show_quick_panel(self.LEVELS, on_select)

    def is_enabled(self):
        s = get_active_session(self.window)
        return s is not None and s.backend == "claude"



class ClaudeSelectModelCommand(sublime_plugin.WindowCommand):
    """Quick panel to select model for current session."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            sublime.error_message("No active Claude session")
            return
        if s.working:
            sublime.error_message("Session is busy — wait for the current request to finish")
            return
        backend = s.backend
        models = self._get_models(backend)
        if not models:
            sublime.error_message(f"No models for {backend}.\nRun 'Claude: Refresh Models' first.")
            return
        items = []
        model_ids = []
        for m in models:
            if isinstance(m, str):
                mid, mname = m, m
            elif isinstance(m, list) and len(m) >= 2:
                mid, mname = m[0], m[1]
            else:
                continue
            items.append([mname, mid])
            model_ids.append(mid)

        def on_select(idx):
            if idx < 0:
                return
            mid = model_ids[idx]
            from .session import _resolve_model_id
            real_model, ctx = _resolve_model_id(mid)
            if ctx:
                if sublime.ok_cancel_dialog(
                    f"Context limit ({ctx // 1000}K) requires session restart.\n\nRestart session with {mid}?",
                    "Restart"
                ):
                    settings = sublime.load_settings("ClaudeCode.sublime-settings")
                    default_models = settings.get("default_models", {})
                    default_models[s.backend] = mid
                    settings.set("default_models", default_models)
                    sublime.save_settings("ClaudeCode.sublime-settings")
                    s.restart()
                return
            if s.client:
                s.client.send("set_model", {"model": real_model})
            sublime.status_message(f"Model: {mid}")

        self.window.show_quick_panel(items, on_select)

    def _get_models(self, backend):
        import os
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        all_models = settings.get("models", {})
        # Merge cached
        cached_file = os.path.expanduser("~/.claude/sublime_cached_models.json")
        if os.path.exists(cached_file):
            try:
                import json as _json
                with open(cached_file) as f:
                    cached = _json.load(f)
                for b, models in cached.items():
                    if b not in all_models:
                        all_models[b] = models
            except Exception:
                pass
        if backend not in all_models:
            all_models[backend] = DEFAULT_MODELS.get(backend, [])
        return all_models.get(backend, [])



class ClaudeSetDefaultModelCommand(sublime_plugin.WindowCommand):
    """Set default model per backend in settings."""
    def run(self) -> None:
        backends = ["claude", "codex", "copilot"]
        items = [[b.title(), f"Set default model for {b}"] for b in backends]

        def on_backend(idx):
            if idx < 0:
                return
            backend = backends[idx]
            models = ClaudeSelectModelCommand._get_models(None, backend)
            if not models:
                sublime.status_message(f"No models for {backend}. Run Claude: Refresh Models first.")
                return
            model_items = []
            model_ids = []
            for m in models:
                if isinstance(m, str):
                    mid, mname = m, m
                elif isinstance(m, list) and len(m) >= 2:
                    mid, mname = m[0], m[1]
                else:
                    continue
                model_items.append([mname, mid])
                model_ids.append(mid)

            def on_model(midx):
                if midx < 0:
                    return
                mid = model_ids[midx]
                settings = sublime.load_settings("ClaudeCode.sublime-settings")
                defaults = settings.get("default_models", {})
                defaults[backend] = mid
                settings.set("default_models", defaults)
                # Also set legacy default_model for claude
                if backend == "claude":
                    settings.set("default_model", mid)
                sublime.save_settings("ClaudeCode.sublime-settings")
                sublime.status_message(f"Default {backend} model: {mid}")

            self.window.show_quick_panel(model_items, on_model)

        self.window.show_quick_panel(items, on_backend)



class ClaudeRefreshModelsCommand(sublime_plugin.WindowCommand):
    """Fetch available models from backends and cache them."""
    def run(self) -> None:
        import threading

        def fetch():
            import os, json as _json
            cached = {}

            # Claude models (from Anthropic API)
            try:
                import urllib.request
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if api_key:
                    req = urllib.request.Request(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = _json.loads(resp.read().decode())
                    result = []
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        name = m.get("display_name", mid)
                        result.append([mid, name])
                    if result:
                        cached["claude"] = result
            except Exception as e:
                print(f"[Claude] refresh models claude error: {e}")

            # Copilot models (live from SDK)
            try:
                import asyncio
                from copilot import CopilotClient

                async def get_copilot_models():
                    client = CopilotClient()
                    await client.start()
                    models = await client.list_models()
                    result = []
                    for m in models:
                        mid = getattr(m, 'id', '')
                        name = getattr(m, 'name', '')
                        billing = getattr(m, 'billing', None)
                        mult = getattr(billing, 'multiplier', 1) if billing else 1
                        label = f"{name} ({mult}x)" if mult != 1 else name
                        result.append([mid, label])
                    await client.stop()
                    return result

                cached["copilot"] = asyncio.run(get_copilot_models())
            except Exception as e:
                print(f"[Claude] refresh models copilot error: {e}")

            # Fallback for backends without list API
            for backend_name, fallback_models in DEFAULT_MODELS.items():
                if backend_name not in cached:
                    cached[backend_name] = fallback_models

            # Write cache
            cache_path = os.path.expanduser("~/.claude/sublime_cached_models.json")
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                _json.dump(cached, f, indent=2)

            count = sum(len(v) for v in cached.values())
            sublime.set_timeout(lambda: sublime.status_message(f"Cached {count} models"), 0)

        sublime.status_message("Fetching models...")
        threading.Thread(target=fetch, daemon=True).start()



class ClaudeSearchSessionsCommand(sublime_plugin.WindowCommand):
    """Search all Claude sessions by title/summary."""
    def run(self) -> None:
        self.window.show_input_panel("Search sessions:", "", self._on_done, None, None)

    def _on_done(self, query: str) -> None:
        if not query.strip():
            return
        import threading
        q = query.lower()

        def search():
            import os, json, time
            from .session import load_saved_sessions

            # Build lookup of sublime-claude session names by session_id
            saved = {s["session_id"]: s.get("name", "") for s in load_saved_sessions() if s.get("session_id")}

            projects_dir = os.path.expanduser("~/.claude/projects")
            results = []  # [(session_id, title, mtime, proj_key)]
            if not os.path.isdir(projects_dir):
                return

            for proj_key in os.listdir(projects_dir):
                proj_path = os.path.join(projects_dir, proj_key)
                if not os.path.isdir(proj_path):
                    continue
                for fname in os.listdir(proj_path):
                    if not fname.endswith(".jsonl"):
                        continue
                    fpath = os.path.join(proj_path, fname)
                    sid = fname[:-6]  # strip .jsonl
                    # Check sublime-claude saved name first
                    saved_name = saved.get(sid, "")
                    # Read first few lines to find JSONL title
                    jsonl_title = None
                    try:
                        with open(fpath, "r") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                entry = json.loads(line)
                                if entry.get("type") == "custom-title":
                                    jsonl_title = entry.get("title", "")
                                    break
                                # First real user prompt as fallback
                                if entry.get("type") == "user" and not entry.get("isSidechain"):
                                    msg = entry.get("message", {})
                                    content = msg.get("content", [])
                                    if isinstance(content, list):
                                        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                                        if has_tool_result:
                                            continue
                                        for b in content:
                                            if isinstance(b, dict) and b.get("type") == "text":
                                                t = b.get("text", "")
                                                if t and not t.startswith("[Request interrupted"):
                                                    jsonl_title = t[:80]
                                                    break
                                    elif isinstance(content, str) and not content.startswith("[Request interrupted"):
                                        jsonl_title = content[:80]
                                    if jsonl_title:
                                        break
                    except Exception:
                        continue
                    # Match against both saved name and JSONL title
                    searchable = f"{saved_name} {jsonl_title or ''}".lower()
                    if q not in searchable:
                        continue
                    # Use saved name as display title if available
                    title = saved_name or jsonl_title or "untitled"
                    mtime = os.path.getmtime(fpath)
                    results.append((sid, title, mtime, proj_key))

            results.sort(key=lambda x: x[2], reverse=True)
            results = results[:50]

            if not results:
                sublime.set_timeout(lambda: sublime.status_message(f"No sessions matching '{query}'"), 0)
                return

            items = []
            for sid, title, mtime, proj_key in results:
                ts = time.strftime("%m/%d %H:%M", time.localtime(mtime))
                proj_short = proj_key.rsplit("-", 1)[-1] if "-" in proj_key else proj_key
                items.append([title, f"{proj_short} | {ts} | {sid[:8]}..."])

            def show_panel():
                from .core import create_session

                def on_select(idx):
                    if idx < 0:
                        return
                    sid = results[idx][0]
                    # Look up backend from saved sessions
                    saved_backend = "claude"
                    for saved in load_saved_sessions():
                        if saved.get("session_id") == sid:
                            saved_backend = saved.get("backend", "claude")
                            break
                    create_session(self.window, resume_id=sid, fork=True, backend=saved_backend)

                self.window.show_quick_panel(items, on_select)

            sublime.set_timeout(show_panel, 0)

        threading.Thread(target=search, daemon=True).start()



class ClaudeCodeViewHistoryCommand(sublime_plugin.WindowCommand):
    """View session history from Claude's stored conversation."""
    def run(self) -> None:
        import os
        from .session import load_saved_sessions
        sessions = load_saved_sessions()
        if not sessions:
            sublime.status_message("No saved sessions")
            return

        # Build quick panel items
        items = []
        for s in sessions:
            name = s.get("name", "Unnamed")[:40]
            sid = s.get("session_id", "")[:8]
            cost = s.get("total_cost", 0)
            queries = s.get("query_count", 0)
            project = os.path.basename(s.get("project", ""))
            items.append([f"{name}", f"{project} | {queries} queries | ${cost:.2f} | {sid}..."])

        def on_select(idx: int) -> None:
            if idx < 0:
                return
            session = sessions[idx]
            self._show_history(session)

        self.window.show_quick_panel(items, on_select)

    def _show_history(self, session: dict) -> None:
        """Extract and display user messages from session history."""
        import json, os

        sid = session.get("session_id", "")
        project = session.get("project", "")
        # Convert project path to Claude's format
        project_key = project.replace("/", "-").lstrip("-")
        history_file = os.path.expanduser(f"~/.claude/projects/{project_key}/{sid}.jsonl")

        if not os.path.exists(history_file):
            sublime.status_message(f"History file not found: {history_file}")
            return

        # Extract user messages
        messages = []
        with open(history_file, "r") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("type") == "user":
                        msg = d.get("message", {})
                        content = msg.get("content", [])
                        if isinstance(content, str):
                            messages.append(content)
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    text = c.get("text", "")
                                    if text and not text.startswith("[Request interrupted"):
                                        messages.append(text)
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    print(f"[Claude] Error parsing history message: {e}")

        # Create output view
        view = self.window.new_file()
        view.set_name(f"History: {session.get('name', sid[:8])}")
        view.set_scratch(True)
        view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")

        # Format output
        output = f"# Session: {session.get('name', 'Unnamed')}\n"
        output += f"**ID:** {sid}\n"
        output += f"**Project:** {project}\n"
        output += f"**Queries:** {session.get('query_count', 0)} | **Cost:** ${session.get('total_cost', 0):.2f}\n\n"
        output += "---\n\n"

        for i, msg in enumerate(messages, 1):
            output += f"## [{i}]\n{msg}\n\n"

        view.run_command("append", {"characters": output})



class ClaudeCodeSwarmMonitorCommand(sublime_plugin.WindowCommand):
    """Show dashboard of all active sessions (swarm monitor)."""
    def run(self) -> None:
        if not hasattr(sublime, '_claude_sessions') or not sublime._claude_sessions:
            sublime.status_message("Нема активни сесии")
            return

        lines = ["# 🤖 Agent Swarm Monitor", ""]
        lines.append("| Статус | Име | Backend | Queries | Трошок | Родител | Тагови |")
        lines.append("|--------|-----|---------|---------|--------|---------|--------|")

        window_sessions = []
        for view_id, session in sublime._claude_sessions.items():
            # Only show sessions in this window
            if session.window != self.window:
                continue
            window_sessions.append(session)

        if not window_sessions:
            sublime.status_message("Нема активни сесии во овој прозорец")
            return

        # Sort: subsessions last, then by name
        window_sessions.sort(key=lambda s: (s.parent_view_id is None, s.display_name.lower()))

        for session in window_sessions:
            status = self._status_icon(session)
            name = session.display_name or "(unnamed)"
            backend = session.backend or "claude"
            queries = session.query_count
            cost = f"${session.total_cost:.4f}" if session.total_cost else "$0.0000"
            parent = "—"
            if session.parent_view_id:
                parent_session = sublime._claude_sessions.get(session.parent_view_id)
                parent = parent_session.display_name if parent_session else f"#{session.parent_view_id}"
            tags = ", ".join(session.tags) if session.tags else "—"

            lines.append(f"| {status} | {name} | {backend} | {queries} | {cost} | {parent} | {tags} |")

        lines.append("")
        lines.append(f"**Вкупно сесии: {len(window_sessions)}**")

        # Subsession summary
        subsessions = [s for s in window_sessions if s.parent_view_id]
        if subsessions:
            lines.append(f"**Subsessions: {len(subsessions)}**")

        panel = self.window.create_output_panel("claude_swarm")
        panel.run_command("append", {"characters": "\n".join(lines)})
        panel.set_syntax_file("Packages/Markdown/Markdown.sublime-syntax")
        self.window.run_command("show_panel", {"panel": "output.claude_swarm"})

    def _status_icon(self, session) -> str:
        if session.working:
            return "🟢 Working"
        elif session.is_sleeping:
            return "💤 Sleeping"
        elif not session.initialized:
            return "🟡 Connecting"
        else:
            return "⏸ Idle"

    def is_enabled(self):
        return hasattr(sublime, '_claude_sessions') and bool(sublime._claude_sessions)



class ClaudeMcpMarketplaceCommand(sublime_plugin.WindowCommand):
    """Browse and install MCP servers from the marketplace."""

    _MARKETPLACE_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "mcp_marketplace.json"
    )

    def run(self) -> None:
        servers = self._load_marketplace()
        if not servers:
            sublime.status_message("MCP Marketplace: нема достапни сервери")
            return

        items = []
        self._server_keys = []
        for key, info in servers.items():
            self._server_keys.append(key)
            name = info.get("name", key)
            desc = info.get("description", "")
            install = info.get("install_type", "npm")
            publisher = info.get("publisher", "unknown")
            items.append([f"{name}  ({install})", f"{publisher} — {desc}"])

        self.window.show_quick_panel(
            items,
            self._on_select,
            placeholder="Избери MCP сервер за инсталација..."
        )

    def _load_marketplace(self) -> dict:
        try:
            if not os.path.isfile(self._MARKETPLACE_PATH):
                return {}
            with open(self._MARKETPLACE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("servers", {})
        except Exception as e:
            print(f"[Claude] MCP Marketplace error: {e}")
            return {}

    def _on_select(self, idx: int) -> None:
        if idx < 0:
            return
        key = self._server_keys[idx]
        servers = self._load_marketplace()
        info = servers.get(key)
        if not info:
            return

        # Show install confirmation with env vars info
        name = info.get("name", key)
        env = info.get("env", {})
        env_note = ""
        if env:
            env_note = "\n\nПотребни env vars:\n" + "\n".join(f"  {k}={v}" for k, v in env.items())

        if sublime.ok_cancel_dialog(
            f"Инсталирај '{name}'?\n\n{info.get('description', '')}{env_note}",
            "Инсталирај"
        ):
            self._install_server(key, info)

    def _install_server(self, key: str, info: dict) -> None:
        """Install MCP server and update config."""
        install_type = info.get("install_type", "npm")
        package = info.get("package", "")
        runtime = info.get("runtime", "npx")
        args_template = info.get("args", [])
        env_vars = info.get("env", {})

        # Resolve template variables in args
        project_root = ""
        if self.window.folders():
            project_root = self.window.folders()[0]

        args = []
        for arg in args_template:
            if arg == "${project_root}":
                args.append(project_root or ".")
            elif arg == "${database_url}":
                args.append("postgresql://localhost/db")
            elif arg == "${database_path}":
                args.append(os.path.join(project_root or ".", "data.db"))
            else:
                args.append(arg)

        # Check if runtime is available
        if runtime in ("npx", "npm"):
            if not self._command_exists("npx"):
                sublime.error_message(
                    "npx не е пронајден.\n\nИнсталирај Node.js од https://nodejs.org"
                )
                return

        # Build server config
        server_config = {
            "command": runtime,
            "args": args,
        }
        if env_vars:
            server_config["env"] = env_vars

        # Update config file
        config_path = self._get_config_path()
        if not config_path:
            sublime.error_message("Не е пронајден проект. Отвори folder прво.")
            return

        try:
            config = {"mcpServers": {}}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

            if "mcpServers" not in config:
                config["mcpServers"] = {}

            config["mcpServers"][key] = server_config

            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

            sublime.status_message(f"✅ MCP сервер '{key}' е инсталиран. Рестартирај го Sublime.")
            print(f"[Claude MCP] Installed {key} to {config_path}")
        except Exception as e:
            sublime.error_message(f"Грешка при инсталација: {e}")
            print(f"[Claude MCP] Install error: {e}")

    def _get_config_path(self) -> str:
        """Get MCP config path. Prefer project .mcp.json, fallback to ~/.claude.json."""
        if self.window.folders():
            project_root = self.window.folders()[0]
            mcp_path = os.path.join(project_root, ".mcp.json")
            return mcp_path
        return os.path.expanduser("~/.claude.json")

    def _command_exists(self, cmd: str) -> bool:
        """Check if a command exists in PATH."""
        try:
            import subprocess
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            return True
        except Exception:
            return False



class ClaudeCodeManageAutoAllowedToolsCommand(sublime_plugin.WindowCommand):
    """Manage auto-allowed MCP tools for the current project."""

    def run(self):
        """Show quick panel to manage auto-allowed tools."""
        import os
        import json

        # Get project settings path
        folders = self.window.folders()
        if not folders:
            sublime.error_message("No project folder open")
            return

        project_dir = folders[0]
        settings_dir = os.path.join(project_dir, ".claude")
        settings_path = os.path.join(settings_dir, "settings.json")

        # Load current settings
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            except Exception as e:
                print(f"[Claude] Error loading settings: {e}")

        auto_allowed = settings.get("autoAllowedMcpTools", [])

        # Build options
        options = []
        options.append(("add", None, "➕ Add new pattern", "Add a new MCP tool pattern to auto-allow"))

        # Show current patterns
        for i, pattern in enumerate(auto_allowed):
            options.append(("remove", i, f"❌ Remove: {pattern}", "Click to remove this pattern"))

        if not auto_allowed:
            options.append(("info", None, "ℹ️  No patterns configured", "Add patterns to auto-allow MCP tools"))

        # Show quick panel
        items = [[opt[2], opt[3]] for opt in options]

        def on_select(idx):
            if idx < 0:
                return

            action, data, _, _ = options[idx]

            if action == "add":
                self.show_add_pattern_input(settings_path, settings, auto_allowed)
            elif action == "remove":
                self.remove_pattern(settings_path, settings, auto_allowed, data)

        self.window.show_quick_panel(items, on_select)

    def show_add_pattern_input(self, settings_path, settings, auto_allowed):
        """Show input panel to add a new pattern."""
        # Build common patterns list
        # Format: "Tool" or "Tool(specifier)" where specifier can be:
        #   - exact match: "Bash(git status)"
        #   - prefix match: "Bash(git:*)" matches commands starting with "git"
        #   - glob pattern: "Read(/src/**/*.py)"
        common_patterns = [
            "mcp__*__*",  # All MCP tools
            "mcp__plugin_*",  # All plugin MCP tools
            "Bash(git:*)",  # Git commands only
            "Bash(ls:*)",  # ls commands
            "Bash(cat:*)",  # cat commands
            "Bash(python:*)",  # python commands
            "Bash(npm:*)",  # npm commands
            "Read",  # All Read
            "Write",  # All Write
        ]

        # Show quick panel with common patterns + custom option
        items = []
        items.append(["✏️ Enter custom pattern", "Type your own pattern"])
        for pattern in common_patterns:
            items.append([f"Add: {pattern}", "Common pattern"])

        def on_select_pattern(idx):
            if idx < 0:
                return

            if idx == 0:
                # Custom pattern
                self.window.show_input_panel(
                    "Enter MCP tool pattern (supports wildcards like mcp__*__):",
                    "",
                    lambda pattern: self.add_pattern(settings_path, settings, auto_allowed, pattern),
                    None,
                    None
                )
            else:
                # Use common pattern
                pattern = common_patterns[idx - 1]
                self.add_pattern(settings_path, settings, auto_allowed, pattern)

        self.window.show_quick_panel(items, on_select_pattern)

    def add_pattern(self, settings_path, settings, auto_allowed, pattern):
        """Add a pattern to auto-allowed tools."""
        import os
        import json

        if not pattern or not pattern.strip():
            return

        pattern = pattern.strip()

        if pattern in auto_allowed:
            sublime.status_message(f"Pattern already exists: {pattern}")
            return

        # Add pattern
        auto_allowed.append(pattern)
        settings["autoAllowedMcpTools"] = auto_allowed

        # Save settings
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        try:
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            sublime.status_message(f"Added auto-allow pattern: {pattern}")
        except Exception as e:
            sublime.error_message(f"Failed to save settings: {e}")

    def remove_pattern(self, settings_path, settings, auto_allowed, index):
        """Remove a pattern from auto-allowed tools."""
        import json

        if 0 <= index < len(auto_allowed):
            pattern = auto_allowed.pop(index)
            settings["autoAllowedMcpTools"] = auto_allowed

            # Save settings
            try:
                with open(settings_path, "w") as f:
                    json.dump(settings, f, indent=2)
                sublime.status_message(f"Removed auto-allow pattern: {pattern}")
            except Exception as e:
                sublime.error_message(f"Failed to save settings: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Skills Marketplace Commands
# ──────────────────────────────────────────────────────────────────────────────

class ClaudeSkillsMarketplaceCommand(sublime_plugin.WindowCommand):
    """Browse and install skills from the curated marketplace."""

    def run(self) -> None:
        from .skills_manager import list_installed_skills

        project_root = self.window.folders()[0] if self.window.folders() else None
        self._skills = list_installed_skills(project_root)

        if not self._skills:
            sublime.status_message("Skills Marketplace: нема достапни skills")
            return

        items = []
        for skill in self._skills:
            name = skill["name"]
            cat = skill["category"]
            desc = skill["description"]
            status = ""
            if skill["global_active"] and skill["project_active"]:
                status = " 🌍📁"
            elif skill["global_active"]:
                status = " 🌍"
            elif skill["project_active"]:
                status = " 📁"
            items.append([f"{name}{status}", f"[{cat}] {desc}"])

        self.window.show_quick_panel(
            items,
            self._on_select,
            placeholder="Избери skill за инсталација..."
        )

    def _on_select(self, idx: int) -> None:
        if idx < 0:
            return
        skill = self._skills[idx]
        self._selected_skill = skill

        # Ask user where to install
        items = [
            ["🌍 Global", "Сите проекти (~/.claude/CLAUDE.md)"],
            ["📁 Project", f"Само тековен проект ({self.window.folders()[0] if self.window.folders() else 'нема'})"],
        ]

        # If already active somewhere, show toggle options
        if skill["global_active"] or skill["project_active"]:
            items.append(["❌ Disable", "Исклучи го skill-от"])

        self.window.show_quick_panel(
            items,
            self._on_scope_select,
            placeholder=f"{skill['name']} — каде да инсталираш?"
        )

    def _on_scope_select(self, idx: int) -> None:
        if idx < 0:
            return
        skill = self._selected_skill
        project_root = self.window.folders()[0] if self.window.folders() else None

        from .skills_manager import (
            set_skill_state,
            rebuild_global_claude_md,
            rebuild_project_claude_md,
        )

        if idx == 0:
            # Global
            set_skill_state(skill["id"], "global", True)
            rebuild_global_claude_md()
            sublime.status_message(f"✅ {skill['name']} е активиран глобално")
        elif idx == 1:
            # Project
            if not project_root:
                sublime.error_message("Нема отворен проект за инсталација.")
                return
            set_skill_state(skill["id"], "project", True, project_root)
            rebuild_project_claude_md(project_root)
            sublime.status_message(f"✅ {skill['name']} е активиран за проектот")
        elif idx == 2:
            # Disable
            if skill["global_active"]:
                set_skill_state(skill["id"], "global", False)
                rebuild_global_claude_md()
            if skill["project_active"] and project_root:
                set_skill_state(skill["id"], "project", False, project_root)
                rebuild_project_claude_md(project_root)
            sublime.status_message(f"❌ {skill['name']} е исклучен")


class ClaudeSkillsListCommand(sublime_plugin.WindowCommand):
    """List all active skills and their scope."""

    def run(self) -> None:
        from .skills_manager import list_installed_skills

        project_root = self.window.folders()[0] if self.window.folders() else None
        skills = list_installed_skills(project_root)

        active = [s for s in skills if s["global_active"] or s["project_active"]]

        if not active:
            sublime.status_message("Нема активни skills")
            return

        lines = ["# 🎯 Active Skills", ""]
        for s in active:
            scopes = []
            if s["global_active"]:
                scopes.append("🌍 Global")
            if s["project_active"]:
                scopes.append("📁 Project")
            lines.append(f"- **{s['name']}** ({s['category']}) — {' + '.join(scopes)}")
            if s["description"]:
                lines.append(f"  {s['description']}")

        view = self.window.new_file()
        view.set_name("Claude Skills")
        view.set_scratch(True)
        view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")
        view.run_command("append", {"characters": "\n".join(lines) + "\n"})


class ClaudeSkillsDisableAllCommand(sublime_plugin.WindowCommand):
    """Disable all skills (global and/or project)."""

    def run(self) -> None:
        items = [
            ["🌍 Disable Global", "Исклучи ги сите глобални skills"],
            ["📁 Disable Project", "Исклучи ги сите project skills"],
            ["❌ Disable All", "Исклучи ги сите (global + project)"],
        ]

        def on_select(idx):
            if idx < 0:
                return
            project_root = self.window.folders()[0] if self.window.folders() else None
            from .skills_manager import (
                get_active_skills,
                set_skill_state,
                rebuild_global_claude_md,
                rebuild_project_claude_md,
            )

            if idx == 0:
                for sid in get_active_skills("global"):
                    set_skill_state(sid, "global", False)
                rebuild_global_claude_md()
                sublime.status_message("Сите глобални skills се исклучени")
            elif idx == 1:
                if project_root:
                    for sid in get_active_skills("project", project_root):
                        set_skill_state(sid, "project", False, project_root)
                    rebuild_project_claude_md(project_root)
                    sublime.status_message("Сите project skills се исклучени")
            elif idx == 2:
                for sid in get_active_skills("global"):
                    set_skill_state(sid, "global", False)
                rebuild_global_claude_md()
                if project_root:
                    for sid in get_active_skills("project", project_root):
                        set_skill_state(sid, "project", False, project_root)
                    rebuild_project_claude_md(project_root)
                sublime.status_message("Сите skills се исклучени")

        self.window.show_quick_panel(items, on_select)
