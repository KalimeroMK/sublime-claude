"""Session query orchestration mixin."""
import os
import threading
import time
from typing import Callable

import sublime

from .smart_context import build_smart_context
from .constants import OUTPUT_VIEW_SETTING, MAX_FILE_SIZE_AUTO_ADD, MAX_DIFF_LENGTH
from .memory import get_relevant_memories, format_memory_prompt, extract_memories_from_response
from .session_env import _CONTEXT_LIMITS, _MODEL_CONTEXT_LIMITS

# Module-level cache for CodebaseSearch instances and background index threads
_codebase_instances: dict = {}
_codebase_index_threads: dict = {}


def _get_codebase_search(project_root: str):
    """Get cached CodebaseSearch instance for a project."""
    if project_root not in _codebase_instances:
        from .codebase_search import CodebaseSearch
        _codebase_instances[project_root] = CodebaseSearch(project_root)
    return _codebase_instances[project_root]


def _start_background_index(project_root: str) -> None:
    """Start background indexing for a project if the index is stale."""
    search = _get_codebase_search(project_root)
    if not search.needs_reindex(max_age_hours=24.0):
        return
    if project_root in _codebase_index_threads:
        return  # Already indexing

    def worker():
        try:
            count = search.index_project()
            print(f"[Claude] Background indexed {count} files for {project_root}")
        except Exception as e:
            print(f"[Claude] Background index error for {project_root}: {e}")
        finally:
            _codebase_index_threads.pop(project_root, None)

    t = threading.Thread(target=worker, daemon=True)
    _codebase_index_threads[project_root] = t
    t.start()


class SessionQueryMixin:
    @staticmethod
    def _is_synthetic_turn(prompt: str) -> bool:
        """Detect prompts that aren't real user messages (bg-task wakes, retain
        injections, interruption markers, channel/subsession events, …)."""
        if not prompt:
            return True
        first = prompt.lstrip().split("\n", 1)[0]
        if first.startswith("<") and ">" in first:
            tag = first[1:first.index(">")].split()[0].lstrip("/")
            if tag in {"task-notification", "channel", "subsession", "wake", "inject", "timer", "notification", "retain"}:
                return True
        synthetic_brackets = ("[Request interrupted", "[retain context]", "[Loop]")
        if any(first.startswith(p) for p in synthetic_brackets):
            return True
        return False

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

        # --- Auto-compact: if context window is near full, compact first ---
        if not silent and prompt != "/compact" and self._should_auto_compact():
            self._queued_prompts.append(prompt)
            sublime.status_message("Claude: Auto-compacting context...")
            print(f"[Claude] Auto-compact triggered ({self._context_pct()}% context usage)")
            self.query("/compact", display_prompt="⚙ Auto-compacting context...")
            return

        self.working = True
        self.last_activity = time.time()  # Reset stall watchdog for the new query
        self._stall_warning_shown = False  # Reset 30s "still waiting" hint
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

        # --- Auto-add current file if no explicit context provided ---
        if settings.get("auto_add_current_file", True) and not self.pending_context:
            self._auto_add_current_file()

        # --- @-commands: @codebase, @web, @file ---
        prompt = self._expand_at_commands(prompt)

        # --- Persistent Memory: inject relevant memories ---
        try:
            cwd = self._cwd() if hasattr(self, '_cwd') else None
            relevant = get_relevant_memories(cwd, prompt, max_memories=5, min_score=0.15)
            if relevant:
                memory_text = format_memory_prompt(relevant)
                prompt = memory_text + "\n\n" + prompt
                # Update use counts
                import time as _time
                for mem in relevant:
                    mem["use_count"] = mem.get("use_count", 0) + 1
                    mem["last_used"] = _time.time()
        except Exception as e:
            print(f"[Claude] Memory injection error: {e}")

        # Build prompt with context (may include images)
        full_prompt, images = self._build_prompt_with_context(prompt)
        context_names = [item.name for item in self.pending_context]
        self.pending_context = []  # Clear after use
        if hasattr(self, '_context') and self._context:
            self._context._update_display()

        # Store images for RPC call
        self._pending_images = images

        # Use display_prompt for UI if provided, otherwise use full prompt
        ui_prompt = display_prompt if display_prompt else prompt

        # Check if bridge is alive before sending; auto-restart if dead
        if not self._ensure_bridge_alive(silent=silent):
            self._status("error: bridge died")
            if not silent:
                self.output.text("\n\n*Bridge process died and auto-restart failed. Please use `Claude: Restart Session` (Cmd+Shift+R).*\n")
            return

        if not silent:
            self.output.show()
            # Auto-name session from first prompt if not already named
            if not self.name:
                self._set_name(ui_prompt[:30].strip() + ("..." if len(ui_prompt) > 30 else ""))
            self.output.prompt(ui_prompt, context_names)
        # Always show busy indicator: flip tab title now and start the spinner
        # loop. Silent queries (bg-task wakes, retain injects, …) still need a
        # visible cue that the session is processing, even though the user
        # prompt itself isn't rendered.
        self.output._update_title()
        self._animate()
        # --- Auto-extract memories from previous response ---
        try:
            if self.output.current and self.output.current.events:
                # Get last text chunk from previous turn
                last_text = ""
                for event in reversed(self.output.current.events):
                    if isinstance(event, str):
                        last_text = event
                        break
                if last_text:
                    cwd = self._cwd() if hasattr(self, '_cwd') else None
                    extract_memories_from_response(last_text, cwd)
        except Exception as e:
            print(f"[Claude] Memory extraction error: {e}")

        query_params = {"prompt": full_prompt}
        if hasattr(self, '_pending_images') and self._pending_images:
            query_params["images"] = self._pending_images
            self._pending_images = []
        prompt_preview = (full_prompt[:60] + "…") if len(full_prompt) > 60 else full_prompt
        prompt_preview = prompt_preview.replace("\n", " ")
        print(f"[Claude] query: {prompt_preview!r} (len={len(full_prompt)})")
        if not self.client.send("query", query_params, self._on_done):
            self._status("error: bridge died")
            self.working = False
            self.output.text("\n\n*Failed to send query. Bridge process died.*\n")

    def _auto_add_current_file(self) -> None:
        """Automatically add the current file to context if none provided.

        This ensures the AI always sees the file the user is working on,
        matching the behavior of Cursor, Copilot, and Continue.dev.
        """
        from .session_core import ContextItem

        try:
            active_view = self.window.active_view()
            if not active_view or not active_view.is_valid():
                return
            path = active_view.file_name()
            if not path:
                return
            # Skip if it's the output view itself
            if active_view.settings().get(OUTPUT_VIEW_SETTING):
                return
            # Skip very large files (>100KB)
            size = active_view.size()
            if size > MAX_FILE_SIZE_AUTO_ADD:
                return
            content = active_view.substr(sublime.Region(0, size))
            if not content.strip():
                return
            # Add to pending context
            self.pending_context.append(ContextItem(
                kind="file",
                name=path,
                content=f"File: {path}\n```\n{content}\n```",
            ))
            print(f"[Claude] Auto-added current file: {path}")
        except Exception as e:
            print(f"[Claude] Auto-add current file error: {e}")

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

    def _expand_at_commands(self, prompt: str) -> str:
        """Expand @-commands in prompt and add results to pending_context.

        Supported:
            @codebase <query>  -- search project for relevant code (TF-IDF)
            @file:<path>       -- inline file reference
            @web <query>       -- web search via DuckDuckGo (no API key)
            @model <Name>      -- Laravel model: real columns, casts, relations
            @routes            -- routes parsed from the project (modules too)
            @module <Name>     -- one module's models, actions, requests, routes
            @artisan <sub>     -- ask the running app (route:list, db:table, ...)
            @quality [path]    -- the project's own Pint/PHPStan verdict

        Returns the prompt with @-markers removed.
        """
        import re
        from .session_core import ContextItem

        # @codebase <query> -- search codebase
        def replace_codebase(match):
            query_text = match.group(1).strip()
            if not query_text:
                return ""

            project_root = self.window.folders()[0] if self.window.folders() else None
            if not project_root:
                return ""

            try:
                search = _get_codebase_search(project_root)
                # Index on first use if needed — run in thread to avoid blocking UI
                if search.needs_reindex(max_age_hours=24.0):
                    print(f"[Claude] Indexing codebase for @codebase...")
                    sublime.status_message("Claude: Indexing codebase...")
                    indexed_count = [0]

                    def _index_worker():
                        indexed_count[0] = search.index_project()

                    t = threading.Thread(target=_index_worker, daemon=True)
                    t.start()
                    # Poll with short timeouts; actual work is off-main-thread
                    while t.is_alive():
                        t.join(timeout=0.05)
                    print(f"[Claude] Indexed {indexed_count[0]} files")
                    sublime.status_message(f"Claude: Indexed {indexed_count[0]} files")

                results = search.search(query_text, top_k=5)
                if results:
                    for r in results:
                        display_path = r["path"].replace(os.path.expanduser("~"), "~")
                        self.pending_context.append(ContextItem(
                            kind="file",
                            name=display_path,
                            content=f"[codebase] {display_path}:{r['line_start']}\n```\n{r['chunk']}\n```",
                        ))
                    print(f"[Claude] @codebase: added {len(results)} files")
                else:
                    print(f"[Claude] @codebase: no results for '{query_text}'")
            except Exception as e:
                print(f"[Claude] @codebase error: {e}")
            return query_text

        prompt = re.sub(r'@codebase\s+([^@\n]+)', replace_codebase, prompt)

        # @model <Name> -- read the model source; no artisan, no booting the app
        def replace_model(match):
            name = match.group(1).strip()
            root = _framework_root(self.window)
            if not (name and root):
                return ""
            try:
                from . import framework_nav
                path = framework_nav.find_model(root, name)
                if not path:
                    print("[Claude] @model: no model named {}".format(name))
                    return ""
                info = framework_nav.model_summary(path)
                # $fillable is a mass-assignment allowlist, not the table — the
                # migrations are the only source for the real column set.
                try:
                    table = framework_nav.table_name_for(info)
                    if table:
                        info["columns"] = framework_nav.table_columns(root, table)
                except Exception as ce:
                    print("[Claude] @model columns unavailable: {}".format(ce))
            except Exception as e:
                print("[Claude] @model error: {}".format(e))
                return ""
            self.pending_context.append(ContextItem(
                kind="file",
                name="@model {}".format(name),
                content=_format_model(info, root),
            ))
            print("[Claude] @model: added {}".format(name))
            return ""

        prompt = re.sub(r'@model\s+([A-Za-z_]\w*)', replace_model, prompt)

        # @routes [filter] -- parsed from the project source, so it works on a
        # broken app too. A modular project has hundreds of routes; unfiltered
        # they would crowd everything else out of the context window.
        def replace_routes(match):
            raw = (match.group(1) or "").strip()
            keep = "" if _looks_like_route_filter(raw) else raw
            needle = raw.lower() if _looks_like_route_filter(raw) else ""
            root = _framework_root(self.window)
            if not root:
                return keep
            try:
                from . import framework_nav
                routes = framework_nav.route_summary(root)
            except Exception as e:
                print("[Claude] @routes error: {}".format(e))
                return keep
            total = len(routes)
            if needle:
                routes = _filter_routes(routes, needle)
            cap = _setting("routes_max", 150)
            capped = False
            if cap and len(routes) > cap:
                routes, capped = routes[:cap], True
            if not routes:
                print("[Claude] @routes: nothing matched{}".format(
                    " '{}'".format(needle) if needle else ""))
                return keep
            body = _format_routes(routes)
            if capped:
                body += "\n... {} more not shown — narrow it with @routes <filter>".format(
                    total - cap)
            label = "@routes {}".format(needle) if needle else "@routes"
            self.pending_context.append(ContextItem(
                kind="file",
                name="{} ({}/{})".format(label, len(routes), total),
                content=body,
            ))
            print("[Claude] @routes: added {} of {} routes".format(len(routes), total))
            return keep

        prompt = re.sub(r'@routes(?:\s+([^\s@]+))?', replace_routes, prompt)

        # @module <Name> -- the whole vertical slice, grouped by layer
        def replace_module(match):
            name = match.group(1).strip()
            root = _framework_root(self.window)
            if not (name and root):
                return ""
            try:
                from . import framework_nav
                info = framework_nav.module_summary(root, name)
            except Exception as e:
                print("[Claude] @module error: {}".format(e))
                return ""
            if not info:
                try:
                    known = ", ".join(framework_nav.list_modules(root)[:20])
                except Exception:
                    known = ""
                print("[Claude] @module: no module named {}{}".format(
                    name, " (have: {})".format(known) if known else ""))
                return ""
            self.pending_context.append(ContextItem(
                kind="file",
                name="@module {}".format(name),
                content=_format_module(info, root),
            ))
            print("[Claude] @module: added {}".format(name))
            return ""

        prompt = re.sub(r'@module\s+([A-Za-z_]\w*)', replace_module, prompt)

        # @artisan <sub> -- ground truth from the running app; the static
        # parsers above stay the default because they work on a broken app
        def replace_artisan(match):
            sub = (match.group(1) or "").strip()
            arg = (match.group(2) or "").strip()
            root = _framework_root(self.window)
            if not root:
                return ""
            try:
                import json
                from . import laravel_artisan
                if not laravel_artisan.artisan_available(root):
                    print("[Claude] @artisan: no artisan in {}".format(root))
                    return ""
                command = _setting("artisan_command", "php artisan")
                timeout = _setting("artisan_timeout", laravel_artisan.DEFAULT_TIMEOUT)
                if sub in ("routes", "route", "route:list"):
                    data, err = laravel_artisan.route_list(root, command, timeout)
                    body = _format_routes(data) if data else ""
                elif sub in ("table", "db", "db:table"):
                    data, err = laravel_artisan.db_table(root, arg, command, timeout)
                    body = _format_db_table(arg, data) if data else ""
                elif sub in ("model", "model:show"):
                    data, err = laravel_artisan.model_show(root, arg, command, timeout)
                    body = json.dumps(data, indent=2)[:8000] if data else ""
                elif sub == "about":
                    data, err = laravel_artisan.about(root, command, timeout)
                    body = json.dumps(data, indent=2)[:4000] if data else ""
                else:
                    ok, out, errtext = laravel_artisan.run(
                        root, ([sub] + arg.split()) if arg else [sub], command, timeout)
                    data, err, body = (out if ok else None), ("" if ok else errtext), out
            except Exception as e:
                print("[Claude] @artisan error: {}".format(e))
                return ""
            if not data:
                print("[Claude] @artisan {}: {}".format(sub, err or "no output"))
                return ""
            self.pending_context.append(ContextItem(
                kind="file",
                name="@artisan {}".format(" ".join(x for x in (sub, arg) if x)),
                content=body,
            ))
            print("[Claude] @artisan {}: added".format(sub))
            return ""

        prompt = re.sub(r'@artisan\s+([\w:]+)(?:\s+([\w.\-]+))?', replace_artisan, prompt)

        # @quality [path] -- what the project's own Pint/PHPStan say about the
        # code. LSP diagnostics come from intelephense and know nothing about
        # the configured PHPStan level or the project's Pint ruleset.
        def replace_quality(match):
            raw = (match.group(1) or "").strip()
            arg = raw if _looks_like_path(raw) else ""
            keep = "" if arg else raw
            root = _framework_root(self.window)
            if not root:
                return keep
            targets = []
            if arg:
                targets = [arg]
            else:
                view = self.window.active_view() if self.window else None
                current = view.file_name() if view else None
                if current and current.endswith(".php"):
                    targets = [current]
            try:
                from . import php_quality
                settings = {
                    "php_pint": _setting("php_pint", True),
                    "php_phpstan": _setting("php_phpstan", True),
                    "php_pint_command": _setting("php_pint_command"),
                    "php_phpstan_command": _setting("php_phpstan_command"),
                    "php_phpstan_level": _setting("php_phpstan_level"),
                    "php_phpstan_memory_limit": _setting("php_phpstan_memory_limit", "512M"),
                    "php_timeout": _setting("php_timeout", 120),
                }
                result = php_quality.check(root, targets, settings)
                body = php_quality.format_report(result, root)
            except Exception as e:
                print("[Claude] @quality error: {}".format(e))
                return keep
            self.pending_context.append(ContextItem(
                kind="file",
                name="@quality {}".format(os.path.basename(targets[0]) if targets else "project"),
                content=body,
            ))
            print("[Claude] @quality: {}".format(body.splitlines()[0] if body else "no output"))
            return keep

        prompt = re.sub(r'@quality(?:\s+([^\s@]+))?', replace_quality, prompt)

        # @file:<path> -- inline file reference
        def replace_file(match):
            path = match.group(1).strip()
            # Resolve relative to project root
            if not os.path.isabs(path) and self.window.folders():
                for root in self.window.folders():
                    full = os.path.join(root, path)
                    if os.path.isfile(full):
                        path = full
                        break
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    display_path = path.replace(os.path.expanduser("~"), "~")
                    self.pending_context.append(ContextItem(
                        kind="file",
                        name=display_path,
                        content=f"[file] {display_path}\n```\n{content}\n```",
                    ))
                except Exception as e:
                    print(f"[Claude] @file error: {e}")
            else:
                print(f"[Claude] @file: not found: {path}")
            return ""

        prompt = re.sub(r'@file:(\S+)', replace_file, prompt)

        # @web <query> -- DuckDuckGo search
        def replace_web(match):
            query_text = match.group(1).strip()
            if not query_text:
                return ""
            try:
                from .web_search import search as web_search
                results = web_search(query_text, top_k=5)
                if results:
                    lines = [f"[web search: '{query_text}']"]
                    for i, r in enumerate(results, 1):
                        lines.append(f"\n{i}. {r['title']}")
                        lines.append(f"   URL: {r['url']}")
                        if r.get('snippet'):
                            snippet = r['snippet'][:200] + "..." if len(r['snippet']) > 200 else r['snippet']
                            lines.append(f"   {snippet}")
                    self.pending_context.append(ContextItem(
                        kind="note",
                        name=f"web:{query_text[:30]}",
                        content="\n".join(lines),
                    ))
                    print(f"[Claude] @web: added {len(results)} results for '{query_text}'")
                else:
                    print(f"[Claude] @web: no results for '{query_text}'")
            except Exception as e:
                print(f"[Claude] @web error: {e}")
            return query_text

        prompt = re.sub(r'@web\s+([^@\n]+)', replace_web, prompt)

        # @terminal -- add terminal output as context
        if "@terminal" in prompt:
            try:
                if self.client and self.client.is_alive():
                    result = self.client.send_wait("terminal_read", {"max_chars": 10000}, timeout=5.0)
                    if "error" not in result:
                        text = result.get("text", "")
                        if text:
                            if len(text) > 10000:
                                text = text[:10000] + "\n\n... [truncated]\n"
                            self.pending_context.append(ContextItem(
                                kind="note",
                                name="terminal",
                                content=f"[terminal output]\n```\n{text}\n```",
                            ))
                            print(f"[Claude] @terminal: added {len(text)} chars")
                        else:
                            print("[Claude] @terminal: no output")
                    else:
                        print(f"[Claude] @terminal: error reading terminal")
                else:
                    print("[Claude] @terminal: bridge not available")
            except Exception as e:
                print(f"[Claude] @terminal error: {e}")
            prompt = prompt.replace("@terminal", "").strip()

        # @git -- add git diff --staged as context
        if "@git" in prompt:
            try:
                import subprocess
                project_root = self.window.folders()[0] if self.window.folders() else None
                if project_root:
                    result = subprocess.run(
                        ["git", "-C", project_root, "diff", "--staged"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        diff = result.stdout.strip()
                        if len(diff) > MAX_DIFF_LENGTH:
                            diff = diff[:MAX_DIFF_LENGTH] + "\n\n... [truncated]\n"
                        self.pending_context.append(ContextItem(
                            kind="note",
                            name="git:staged",
                            content=f"[git diff --staged]\n```diff\n{diff}\n```",
                        ))
                        print(f"[Claude] @git: added staged diff ({len(diff)} chars)")
                    else:
                        result = subprocess.run(
                            ["git", "-C", project_root, "diff"],
                            capture_output=True, text=True, timeout=10
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            diff = result.stdout.strip()
                            if len(diff) > 20000:
                                diff = diff[:20000] + "\n\n... [truncated]\n"
                            self.pending_context.append(ContextItem(
                                kind="note",
                                name="git:unstaged",
                                content=f"[git diff]\n```diff\n{diff}\n```",
                            ))
                            print(f"[Claude] @git: added unstaged diff ({len(diff)} chars)")
                        else:
                            print("[Claude] @git: no changes to diff")
                else:
                    print("[Claude] @git: no project root")
            except Exception as e:
                print(f"[Claude] @git error: {e}")
            prompt = prompt.replace("@git", "").strip()

        # Clean up any remaining standalone @-commands without args
        prompt = re.sub(r'@codebase\b', '', prompt)
        prompt = re.sub(r'@file\b', '', prompt)
        prompt = re.sub(r'@web\b', '', prompt)
        prompt = re.sub(r'@terminal\b', '', prompt)

        return prompt.strip()

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
            # If bridge died (e.g. Broken pipe), auto-restart with resume
            if self.client and not self.client.is_alive():
                self.output.text("\n*Bridge process died. Auto-restarting...*\n")
                if self._auto_restart_bridge():
                    self.working = False
                    self._clear_deferred_state()
                    # Re-enter input mode so user can continue
                    sublime.set_timeout(lambda: self._enter_input_with_draft() if not self.working else None, 200)
                    return
                # Auto-restart failed
                self._apply_sleep_ui()
                self.working = False
                self._clear_deferred_state()
                return
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
            # If bridge was already torn down (e.g. by heartbeat auto-restart),
            # _on_init will handle input mode — skip here to avoid race.
            if self.client:
                sublime.set_timeout(lambda: self._enter_input_with_draft() if not self.working else None, 100)
            return

        # 5. Process queued prompts (keep working=True, animation continues)
        if self._queued_prompts:
            prompt = self._queued_prompts.pop(0)
            # Synthetic prompts (bg-task wakes, retain injects, etc.) should
            # never be rendered as user input — fire them silently with a
            # short status-bar/background hint.
            if self._is_synthetic_turn(prompt):
                first = prompt.lstrip().split("\n", 1)[0][:60]
                display = f"⚙ {first}"
                self.query(prompt, display_prompt=display, silent=True)
            else:
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
        self._pending_bg_notifications.clear()
        self._bg_flush_scheduled = False
        self._inject_pending = False
        self._pending_retain = None
        self._input_mode_entered = False  # Allow re-entry to input mode

    def _enter_input_with_draft(self) -> None:
        """Enter input mode and restore draft with cursor at end."""
        # Skip if already in input mode or session is working
        if self.output.is_input_mode() or self.working:
            if self.working:
                print(f"[Claude] _enter_input_with_draft skipped: working={self.working}")
            return

        # Skip if we've already entered input mode after the last query
        # This prevents duplicate entries from multiple callers (on_activated, _on_done, etc.)
        # BUT: reset if input mode was exited externally (e.g. sleep) without our knowledge
        if self._input_mode_entered:
            if not self.output.is_input_mode():
                self._input_mode_entered = False
            else:
                return

        self.output.enter_input_mode()

        # Check if enter_input_mode actually succeeded (might have deferred due to render pending)
        if not self.output.is_input_mode():
            # enter_input_mode may have scheduled its own retry — schedule ours too
            sublime.set_timeout(self._enter_input_with_draft, 50)
            return

        self._input_mode_entered = True
        self.last_idle_at = time.time()
        print("[Claude] entered input mode")

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

    def _context_pct(self) -> int:
        """Calculate current context window utilization as percentage."""
        if not self.context_usage:
            return 0
        u = self.context_usage
        used = (u.get("input_tokens", 0)
                + u.get("cache_read_input_tokens", 0)
                + u.get("cache_creation_input_tokens", 0))
        if not used:
            return 0

        max_ctx = None
        model_id = self.sdk_model or ""
        if model_id:
            for suffix, tokens in _CONTEXT_LIMITS.items():
                if model_id.endswith(suffix):
                    max_ctx = tokens
                    break
            if max_ctx is None:
                for family, tokens in _MODEL_CONTEXT_LIMITS.items():
                    if family in model_id.lower():
                        max_ctx = tokens
                        break
        if max_ctx is None:
            max_ctx = 200000 if self.backend in ("claude", "kimi", "default", "") else 128000

        return min(100, int(used / max_ctx * 100))

    def _should_auto_compact(self) -> bool:
        """Check if context usage exceeds auto-compact threshold."""
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        threshold = settings.get("auto_compact_threshold", 70)
        if threshold <= 0:
            return False
        return self._context_pct() >= threshold


# ─── @model / @routes formatting ────────────────────────────────────────────

def _framework_root(window):
    """Framework root for the open project, or None."""
    from . import framework_nav
    folders = window.folders() if window else []
    for folder in folders:
        if framework_nav.detect_framework(folder):
            return folder
    return folders[0] if folders else None


def _format_model(info, root=""):
    """Render a model summary compactly — this goes into the prompt."""
    import os as _os
    if not info:
        return "[model] (unreadable)"
    path = info.get("path", "")
    rel = _os.path.relpath(path, root) if root and path else path
    lines = ["[model] {}".format(info.get("class") or rel), "path: {}".format(rel)]
    if info.get("extends"):
        lines.append("extends: {}".format(info["extends"]))
    for key in ("table", "connection"):
        if info.get(key):
            lines.append("{}: {}".format(key, info[key]))
    for key in ("fillable", "hidden", "guarded", "appends", "dates"):
        if info.get(key):
            lines.append("{}: {}".format(key, ", ".join(info[key])))
    casts = info.get("casts")
    if casts:
        # the regex yields a flat key,value,key,value list; an odd tail means the
        # source did not parse cleanly, so drop the line rather than print "casts:"
        pairs = ["{} => {}".format(casts[i], casts[i + 1])
                 for i in range(0, len(casts) - 1, 2)]
        if pairs:
            lines.append("casts: {}".format(", ".join(pairs)))
    cols = info.get("columns") or []
    if cols:
        lines.append("columns ({}):".format(len(cols)))
        for c in cols:
            flags = [k for k in ("pk", "unique", "index", "nullable") if c.get(k)]
            if c.get("fk"):
                flags.append("FK->{}".format(c["fk"]))
            if c.get("default") is not None:
                flags.append("default={}".format(c["default"]))
            lines.append("  {:24} {:18} {}".format(
                c["name"], c.get("type", ""), " ".join(flags)).rstrip())
    props = info.get("properties") or []
    if props:
        lines.append("properties:")
        lines.extend("  ${} : {}".format(p["name"], p["type"]) for p in props)
    rels = info.get("relations") or []
    if rels:
        lines.append("relations:")
        lines.extend("  {}() {} {}".format(r["name"], r["kind"], r["target"]).rstrip()
                     for r in rels)
    return "\n".join(lines)


def _setting(key, default=None):
    """One ClaudeCode setting, with a default when Sublime is unavailable."""
    try:
        return sublime.load_settings("ClaudeCode.sublime-settings").get(key, default)
    except Exception:
        return default


def _format_db_table(table, columns):
    """Live schema for one table — the database's answer, not the migrations'."""
    if not columns:
        return "[db:table {}] no columns".format(table)
    lines = ["[db:table] {} ({} columns)".format(table, len(columns))]
    for c in columns:
        flags = []
        if c.get("nullable"):
            flags.append("nullable")
        if c.get("default") is not None:
            flags.append("default={}".format(c["default"]))
        lines.append("  {:26} {:20} {}".format(
            c.get("name", ""), c.get("type", ""), " ".join(flags)).rstrip())
    return "\n".join(lines)


def _format_module(info, root=""):
    """Render a module as a layered outline — the shape, not the source."""
    import os as _os
    if not info:
        return "[module] (not found)"
    path = info.get("path", "")
    rel = _os.path.relpath(path, root) if root and path else path
    lines = ["[module] {}".format(info.get("name", "")), "path: {}".format(rel)]
    for layer, items in info.get("layers", {}).items():
        lines.append("{} ({}):".format(layer, len(items)))
        for it in items:
            label = it.get("class") or it.get("file")
            extra = ""
            if it.get("methods"):
                extra = " — " + ", ".join(it["methods"])
            elif it.get("table"):
                extra = " — table {}".format(it["table"])
                if it.get("relations"):
                    extra += "; " + ", ".join(
                        "{}() {}".format(r["name"], r["kind"]) for r in it["relations"])
            lines.append("  {}{}".format(label, extra))
            for field, rule in (it.get("rules") or {}).items():
                lines.append("      {:24} {}".format(field, rule))
    return "\n".join(lines)


def _looks_like_path(word):
    """Only treat a trailing word as a path when it actually looks like one.

    "@quality fix this" must not read "fix" as a file to analyse.
    """
    if not word:
        return False
    return word.endswith(".php") or "/" in word or os.sep in word


def _looks_like_route_filter(word):
    """Whether a trailing word is a route filter rather than prose.

    "@routes please review this" would otherwise filter on "please" and report
    nothing. Module names are capitalised, URIs contain a slash, verbs are
    upper case — prose is none of those.
    """
    if not word:
        return False
    if "/" in word or "." in word or "::" in word:
        return True
    if word.isupper():
        return True
    return word[:1].isupper()


def _filter_routes(routes, needle):
    """Routes whose module, uri, name or action contains `needle`."""
    out = []
    for r in routes:
        haystack = " ".join(str(r.get(k, "")) for k in
                            ("module", "uri", "name", "action", "verb", "file")).lower()
        if needle in haystack:
            out.append(r)
    return out


def _format_routes(routes):
    """Render routes as an aligned table — compact enough for a prompt."""
    if not routes:
        return "[routes] none found"
    # route_summary already folds group prefixes into uri
    show_module = any(r.get("module") for r in routes)
    rows = []
    for r in routes:
        uri = r.get("uri", "")
        prefix = (r.get("prefix") or "").strip("/")
        # route_summary already folds the prefix in; this only fires for entries
        # built by hand or by an older caller
        if prefix and not uri.startswith("/" + prefix):
            uri = "/{}{}".format(prefix, uri if uri.startswith("/") else "/" + uri)
        row = [r.get("verb", ""), uri, r.get("name", ""),
               r.get("action", ""), "{}:{}".format(r.get("file", ""), r.get("line", ""))]
        if show_module:
            row.insert(0, r.get("module", ""))
        rows.append(row)
    n = len(rows[0])
    header = ["VERB", "URI", "NAME", "ACTION"]
    if show_module:
        header.insert(0, "MODULE")
    # the header can be wider than every value in its column
    w = [max([len(row[i]) for row in rows] + [len(header[i])]) for i in range(n - 1)]
    out = ["[routes] {} found".format(len(rows)),
           "  ".join(h.ljust(w[i]) for i, h in enumerate(header))]
    for row in rows:
        out.append("  ".join(
            (cell.ljust(w[i]) if i < n - 1 else cell) for i, cell in enumerate(row)))
    return "\n".join(out)
