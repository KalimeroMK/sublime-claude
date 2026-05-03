"""Claude Code session management."""
import json
import os
import shlex
import time
from typing import Optional, List, Dict, Callable

import sublime

from .rpc import JsonRpcClient
from .output import OutputView
from .session_query import SessionQueryMixin
from .session_permissions import SessionPermissionsMixin
from .session_heartbeat import HeartbeatMonitor
from .session_terminal import TerminalAdapter
from .session_state import StateManager
from .session_ui import SessionUIHelper
from .session_status import StatusManager
from .session_notifications import NotificationHandler
from .constants import CONVERSATION_REGION_KEY, MAX_RELATED_FILES
from .session_env import (
    _find_python_310_plus,
    _resolve_model_id,
    load_saved_sessions,
    _CONTEXT_LIMITS,
    _MODEL_CONTEXT_LIMITS,
)


BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "main.py")
CODEX_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "codex_main.py")
COPILOT_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "copilot_main.py")
OPENAI_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "openai_main.py")


class ContextItem:
    """A pending context item to attach to next query."""
    def __init__(self, kind: str, name: str, content: str):
        self.kind = kind  # "file", "selection"
        self.name = name  # Display name
        self.content = content  # Actual content


class Session(SessionQueryMixin, SessionPermissionsMixin):
    def __init__(self, window: sublime.Window, resume_id: Optional[str] = None, fork: bool = False, profile: Optional[Dict] = None, initial_context: Optional[Dict] = None, backend: str = "claude"):
        self.window = window
        self.backend = backend
        self.client: Optional[JsonRpcClient] = None
        self.output = OutputView(window)
        self.initialized = False
        self.working = False
        self.current_tool: Optional[str] = None
        self.spinner_frame = 0
        # Session identity
        # When resuming (not forking), use resume_id as session_id immediately
        # so renames/saves work before first query completes
        self.session_id: Optional[str] = resume_id if resume_id and not fork else None
        self.resume_id: Optional[str] = resume_id  # ID to resume from
        self.fork: bool = fork  # Fork from resume_id instead of continuing it
        self.profile: Optional[Dict] = profile  # Profile config (model, betas, system_prompt, preload_docs)
        self.profile_name: Optional[str] = profile.get("_name") if profile else None  # Profile name for status bar
        self.initial_context: Optional[Dict] = initial_context  # Initial context (subsession_id, parent_view_id, etc.)
        self.name: Optional[str] = None
        self.sdk_model: Optional[str] = None  # Model from SDK SystemMessage init
        self.total_cost: float = 0.0
        self.query_count: int = 0
        self.context_usage: Optional[Dict] = None  # Latest usage/context stats
        self.tags: List[str] = []  # Session tags for organization
        self._usage_history: List[Dict] = []  # Per-query token usage history
        # Pending context for next query
        self.pending_context: List[ContextItem] = []
        # Profile docs available for reading (paths only, not content)
        self.profile_docs: List[str] = []
        # Draft prompt (persists across input panel open/close)
        self.draft_prompt: str = ""
        self._pending_resume_at: Optional[str] = None  # Set by undo, consumed by next query
        # Background task tracking: task_id → tool_use_id
        self._task_tool_map: Dict[str, str] = {}
        # Track if we've entered input mode after last query
        self._input_mode_entered: bool = False
        # Callback for channel mode responses
        self._response_callback: Optional[Callable[[str], None]] = None
        # Queue of prompts to send after current query completes
        self._queued_prompts: List[str] = []
        # Heartbeat monitor for auto-detecting dead bridges
        self._heartbeat = HeartbeatMonitor(self)
        # Track if inject was sent (to skip "done" status until inject query completes)
        self._inject_pending: bool = False

        # Terminal adapter for persistent shell session
        self._terminal = TerminalAdapter(self)
        # State manager for persistence
        self._state = StateManager(self)
        # UI overlay helper
        self._ui = SessionUIHelper(self)
        # Status bar and spinner manager
        self._status_mgr = StatusManager(self)
        # Bridge notification dispatcher
        self._notifications = NotificationHandler(self)

        # Extract subsession_id and parent_view_id if provided
        if initial_context:
            self.subsession_id = initial_context.get("subsession_id")
            self.parent_view_id = initial_context.get("parent_view_id")
        else:
            self.subsession_id = None
            self.parent_view_id = None

        # Persona info (for release on close)
        if profile:
            self.persona_id = profile.get("persona_id")
            self.persona_session_id = profile.get("persona_session_id")
            self.persona_url = profile.get("persona_url")
        else:
            self.persona_id = None
            self.persona_session_id = None
            self.persona_url = None

        # Activity tracking for auto-sleep
        self.last_activity: float = time.time()

        # Plan mode state
        self.plan_mode: bool = False
        self.plan_file: Optional[str] = None

        # Pending retain content (set by compact_boundary, sent after interrupt)
        self._pending_retain: Optional[str] = None

    def start(self, resume_session_at: str = None) -> None:
        self._ui.show_connecting()

        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        python_path = settings.get("python_path", "python3")
        if python_path == "python3":
            detected = _find_python_310_plus()
            if detected != python_path:
                print(f"[Claude] Auto-detected Python 3.10+: {detected}")
                python_path = detected

        # Build profile docs list early (before init) so we can add to system prompt
        self._build_profile_docs_list()

        # Load environment variables from settings and profile
        env = self._load_env(settings)

        # Resolve virtual model ID (e.g. @400k suffix) → real model + context limit
        default_models = settings.get("default_models", {})
        _backend_fallback_models = {"deepseek": "deepseek-v4-pro", "codex": "gpt-5.5"}
        default_model = default_models.get(self.backend) or _backend_fallback_models.get(self.backend) or settings.get("default_model")
        model_for_env = (self.profile.get("model") if self.profile else None) or default_model
        if model_for_env:
            _, ctx = _resolve_model_id(model_for_env)
            if ctx:
                env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(ctx)

        # Sync sublime project retain content to file for hook
        self._sync_project_retain()

        # Claude/Kimi API settings from Sublime config → passed as env vars to claude CLI
        if self.backend in ("claude", "kimi", "default", ""):
            api_key = settings.get("anthropic_api_key")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            base_url = settings.get("anthropic_base_url")
            if base_url:
                env["ANTHROPIC_BASE_URL"] = base_url
            model = settings.get("anthropic_model")
            if model:
                env["ANTHROPIC_MODEL"] = model

        # DeepSeek uses the Claude bridge with Anthropic-compatible endpoint
        if self.backend == "deepseek":
            ds_key = settings.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
            env["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
            if ds_key:
                env["ANTHROPIC_AUTH_TOKEN"] = ds_key
            env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
            env.setdefault("CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK", "1")

        if self.backend == "openai":
            oai_url = settings.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")
            oai_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            oai_model = settings.get("openai_model") or os.environ.get("OPENAI_MODEL", "")
            if oai_url:
                env["OPENAI_BASE_URL"] = oai_url
            if oai_key:
                env["OPENAI_API_KEY"] = oai_key
            if oai_model:
                env["OPENAI_MODEL"] = oai_model

        if self.backend == "codex":
            bridge_script = CODEX_BRIDGE_SCRIPT
        elif self.backend == "copilot":
            bridge_script = COPILOT_BRIDGE_SCRIPT
        elif self.backend == "openai":
            bridge_script = OPENAI_BRIDGE_SCRIPT
        else:
            bridge_script = BRIDGE_SCRIPT
        self.client = JsonRpcClient(self._on_notification)
        self.client.start([python_path, bridge_script], env=env)
        self._status("connecting...")

        permission_mode = settings.get("permission_mode", "acceptEdits")
        # In default mode, don't auto-allow any tools - prompt for all
        if permission_mode == "default":
            allowed_tools = []
        else:
            allowed_tools = settings.get("allowed_tools", [])

        print(f"[Claude] initialize: permission_mode={permission_mode}, allowed_tools={allowed_tools}, resume={self.resume_id}, fork={self.fork}, profile={self.profile}, default_model={default_model}, subsession_id={getattr(self, 'subsession_id', None)}")
        # Get additional working directories from project folders + project settings
        additional_dirs = self.window.folders()[1:] if len(self.window.folders()) > 1 else []
        project_data = self.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        extra_dirs = project_settings.get("claude_additional_dirs", [])
        if extra_dirs:
            expanded = [os.path.expanduser(d) for d in extra_dirs]
            additional_dirs = additional_dirs + expanded
            print(f"[Claude] extra additional_dirs from project: {expanded}")
        init_params = {
            "cwd": self._cwd(),
            "additional_dirs": additional_dirs,
            "allowed_tools": allowed_tools,
            "permission_mode": permission_mode,
            "view_id": str(self.output.view.id()) if self.output and self.output.view else None,
        }
        if self.resume_id:
            init_params["resume"] = self.resume_id
            if self.fork:
                init_params["fork_session"] = True
            # Use saved session's project dir as cwd (session may belong to different project)
            for saved in load_saved_sessions():
                if saved.get("session_id") == self.resume_id:
                    saved_project = saved.get("project", "")
                    if saved_project and saved_project != init_params["cwd"]:
                        print(f"[Claude] resume: using saved project {saved_project}")
                        init_params["cwd"] = saved_project
                    break
            if resume_session_at:
                init_params["resume_session_at"] = resume_session_at
        # Pass subsession_id if this is a subsession
        if hasattr(self, 'subsession_id') and self.subsession_id:
            init_params["subsession_id"] = self.subsession_id
        # Effort setting — only apply on fresh session (resume keeps CLI's saved value)
        if not self.resume_id:
            effort = settings.get("effort", "high")
            if self.profile and self.profile.get("effort"):
                effort = self.profile["effort"]
            init_params["effort"] = effort
        elif self.profile and self.profile.get("effort"):
            # Profile explicitly sets effort — honor it even on resume
            init_params["effort"] = self.profile["effort"]

        # Apply profile config or default model
        if self.profile:
            if self.profile.get("model"):
                real_model, _ = _resolve_model_id(self.profile["model"])
                init_params["model"] = real_model
            if self.profile.get("betas"):
                init_params["betas"] = self.profile["betas"]
            if self.profile.get("pre_compact_prompt"):
                init_params["pre_compact_prompt"] = self.profile["pre_compact_prompt"]
            # Build system prompt with profile docs info
            system_prompt = self.profile.get("system_prompt", "")
            if self.profile_docs:
                docs_info = f"\n\nProfile Documentation: {len(self.profile_docs)} files available. Use list_profile_docs to see them and read_profile_doc(path) to read their contents."
                system_prompt = system_prompt + docs_info if system_prompt else docs_info.strip()
            if system_prompt:
                init_params["system_prompt"] = system_prompt
        else:
            # No profile - use default_model setting if available
            if default_model:
                real_model, _ = _resolve_model_id(default_model)
                init_params["model"] = real_model

        # Parse extra CLI args from settings (e.g. "--max-budget-usd 5 --effort high")
        extra_args_str = settings.get("claude_extra_args", "")
        if extra_args_str:
            try:
                parsed = shlex.split(extra_args_str)
                extra_dict = {}
                it = iter(parsed)
                for arg in it:
                    key = arg.lstrip("-").replace("-", "_")
                    val = next(it, "")
                    extra_dict[key] = val
                if extra_dict:
                    init_params["extra_args"] = extra_dict
            except Exception as e:
                print(f"[Claude] Failed to parse claude_extra_args: {e}")

        self.client.send("initialize", init_params, self._on_init)

    def _cwd(self) -> str:
        if self.window.folders():
            return self.window.folders()[0]
        view = self.window.active_view()
        if view and view.file_name():
            return os.path.dirname(view.file_name())
        # Fallback: use ~/.claude/scratch for sessions without a project
        # This ensures consistent cwd for session resume
        scratch_dir = os.path.expanduser("~/.claude/scratch")
        os.makedirs(scratch_dir, exist_ok=True)
        return scratch_dir

    def _on_init(self, result: dict) -> None:
        if "error" in result:
            self._ui.clear_overlay()
            error_msg = result['error'].get('message', str(result['error']))
            print(f"[Claude] init error: {error_msg}")
            self._status("error")

            # Show user-friendly message in view
            is_session_error = (
                "No conversation found" in error_msg or
                "Command failed" in error_msg
            )
            if is_session_error:
                self.output.text("\n*Session expired or not found.*\n\nUse `Claude: Restart Session` (Cmd+Shift+R) to start fresh.\n")
            else:
                self.output.text(f"\n*Failed to connect: {error_msg}*\n\nTry `Claude: Restart Session` (Cmd+Shift+R).\n")
            return
        self._ui.clear_overlay()
        self.initialized = True
        self.working = False
        self.current_tool = None
        self.last_activity = time.time()
        # Keep _pending_resume_at alive for consecutive undo support
        self._input_mode_entered = False  # Reset for fresh start after init
        # Capture session_id from initialize response (set via --session-id CLI arg)
        if result.get("session_id"):
            self.session_id = result["session_id"]
            print(f"[Claude] session_id={self.session_id}")
        # Show loaded MCP servers and agents
        mcp_servers = result.get("mcp_servers", [])
        agents = result.get("agents", [])
        parts = []
        if mcp_servers:
            print(f"[Claude] MCP servers: {mcp_servers}")
            parts.append(f"MCP: {', '.join(mcp_servers)}")
        if agents:
            print(f"[Claude] Agents: {agents}")
            parts.append(f"agents: {', '.join(agents)}")
        if parts:
            self._status(f"ready ({'; '.join(parts)})")
        else:
            self._status("ready")
        # Persist "open" state (so plugin_loaded can track which sessions had views)
        self._save_session()
        # Start heartbeat to monitor bridge health
        self._start_heartbeat()
        # Auto-enter input mode when ready
        self._enter_input_with_draft()

    def _load_env(self, settings) -> dict:
        """Load environment variables from settings and project profile."""
        import os
        env = {}
        # From user settings (ClaudeCode.sublime-settings)
        settings_env = settings.get("env", {})
        if isinstance(settings_env, dict):
            env.update(settings_env)
        # From sublime project settings (.sublime-project -> settings -> claude_env)
        project_data = self.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        project_env = project_settings.get("claude_env", {})
        if isinstance(project_env, dict):
            env.update(project_env)
        # From project .claude/settings.json
        cwd = self._cwd()
        if cwd:
            project_settings_path = os.path.join(cwd, ".claude", "settings.json")
            if os.path.exists(project_settings_path):
                try:
                    with open(project_settings_path, "r") as f:
                        import json
                        project_settings = json.load(f)
                    claude_env = project_settings.get("env", {})
                    if isinstance(claude_env, dict):
                        env.update(claude_env)
                except Exception as e:
                    print(f"[Claude] Failed to load project env: {e}")
        # From profile (highest priority)
        if self.profile:
            profile_env = self.profile.get("env", {})
            if isinstance(profile_env, dict):
                env.update(profile_env)
        if env:
            print(f"[Claude] Custom env vars: {env}")
        return env

    def _sync_project_retain(self):
        """Delegate to StateManager."""
        project_data = self.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        retain_content = project_settings.get("claude_retain", "")
        self._state.sync_project_retain(retain_content)

    def _get_retain_path(self) -> Optional[str]:
        """Get path to session's dynamic retain file."""
        return self._state.get_retain_path()


    def retain(self, content: str = None, append: bool = False) -> Optional[str]:
        """Write to or read session's retain file for compaction.

        Args:
            content: Content to write (None to read current)
            append: If True, append to existing content

        Returns:
            Current retain content if reading, None if writing
        """
        return self._state.retain(content, append)


    def clear_retain(self):
        """Clear session's retain file."""
        self._state.clear_retain()


    def _strip_comment_only_content(self, content: str) -> str:
        """Strip lines that are only comments or whitespace."""
        return self._state._strip_comment_only_content(content)


    def _gather_retain_content(self) -> Optional[str]:
        """Gather all retain content from various sources.

        Returns combined retain content string, or None if no content found.
        """
        return self._state.gather_retain_content()


    def _inject_retain_midquery(self) -> None:
        """Inject retain content by interrupting and restarting with retain prompt."""
        self._state.inject_retain_midquery()


    def _build_profile_docs_list(self) -> None:
        """Build list of available docs from profile preload_docs patterns (no reading yet)."""
        if not self.profile or not self.profile.get("preload_docs"):
            return

        import glob as glob_module

        patterns = self.profile["preload_docs"]
        if isinstance(patterns, str):
            patterns = [patterns]

        cwd = self._cwd()

        try:
            for pattern in patterns:
                # Make pattern relative to cwd
                full_pattern = os.path.join(cwd, pattern)
                for filepath in glob_module.glob(full_pattern, recursive=True):
                    if os.path.isfile(filepath):
                        rel_path = os.path.relpath(filepath, cwd)
                        self.profile_docs.append(rel_path)

            if self.profile_docs:
                print(f"[Claude] Profile docs available: {len(self.profile_docs)} files")
        except Exception as e:
            print(f"[Claude] preload_docs error: {e}")

    def add_context_file(self, path: str, content: str) -> None:
        """Add a file to pending context, plus auto-detect related files."""
        name = os.path.basename(path)
        self.pending_context.append(ContextItem("file", name, f"File: {path}\n```\n{content}\n```"))
        self._add_related_files(path, content)
        self._update_context_display()

    def _add_related_files(self, path: str, content: str) -> None:
        """Auto-detect and add related files (tests, imports, siblings) to context.

        Limits to 5 related files to avoid context bloat.
        Only adds files that exist and aren't already in pending context.
        """
        import re

        dirname = os.path.dirname(path)
        basename = os.path.basename(path)
        name_no_ext = os.path.splitext(basename)[0]
        ext = os.path.splitext(basename)[1]

        # Collect candidate paths
        candidates = set()

        # --- Naming convention siblings ---
        suffix_variants = ["_test", "_spec", "Test", "Spec", ".test", ".spec"]
        prefix_variants = ["test_", "spec_"]
        for suffix in suffix_variants:
            candidates.add(os.path.join(dirname, name_no_ext + suffix + ext))
        for prefix in prefix_variants:
            candidates.add(os.path.join(dirname, prefix + name_no_ext + ext))

        # Also check for same-named files in parent/child folders (e.g. controllers)
        if dirname:
            parent = os.path.dirname(dirname)
            if parent:
                # e.g. User.php -> ../controllers/UserController.php
                candidates.add(os.path.join(parent, "controllers", name_no_ext + "Controller" + ext))
                candidates.add(os.path.join(parent, "models", name_no_ext + ext))
                candidates.add(os.path.join(parent, "views", name_no_ext + ext))

        # --- Parse imports from first 30 lines ---
        lines = content.split("\n")[:30]
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # Python: from x.y import z  or  import x.y
            if line.startswith("from ") and " import " in line:
                mod = line.split()[1].replace(".", "/")
                candidates.add(os.path.join(dirname, mod + ".py"))
                for folder in self.window.folders():
                    candidates.add(os.path.join(folder, mod + ".py"))
                    candidates.add(os.path.join(folder, mod, "__init__.py"))
            elif line.startswith("import "):
                mod = line.split()[1].split(".")[0]
                candidates.add(os.path.join(dirname, mod + ".py"))
                for folder in self.window.folders():
                    candidates.add(os.path.join(folder, mod + ".py"))

            # JS/TS: import ... from './relative' or require('./relative')
            elif ("from '" in line or 'from "' in line) or "require(" in line:
                m = re.search(r"[from\srequire]\s*['\"]([^'\"]+)['\"]", line)
                if m:
                    rel = m.group(1)
                    if rel.startswith("."):
                        resolved = os.path.normpath(os.path.join(dirname, rel))
                        candidates.add(resolved)
                        # Also try with .js, .ts, .jsx, .tsx extensions
                        for e in (".js", ".ts", ".jsx", ".tsx", ".vue"):
                            candidates.add(resolved + e)
                            if not resolved.endswith(ext):
                                candidates.add(os.path.join(resolved, "index" + e))

            # PHP: use Namespace\Class;  or  require/include 'path'
            elif line.startswith("use ") and "\\" in line:
                ns = line[4:].rstrip(";").strip()
                parts = ns.split("\\")
                # Try mapping last segment to file
                for folder in self.window.folders():
                    candidates.add(os.path.join(folder, *parts) + ".php")
                    candidates.add(os.path.join(folder, "src", *parts) + ".php")
            elif line.startswith("require") or line.startswith("include"):
                m = re.search(r"['\"]([^'\"]+)['\"]", line)
                if m:
                    rel = m.group(1)
                    if not rel.startswith("http"):
                        candidates.add(os.path.normpath(os.path.join(dirname, rel)))

            # Go: import "package/path"
            elif line.startswith('import "') or line.startswith("import '"):
                m = re.search(r'["\']([^"\']+)["\']', line)
                if m:
                    pkg = m.group(1).split("/")[-1]
                    candidates.add(os.path.join(dirname, pkg + ".go"))
                    for folder in self.window.folders():
                        candidates.add(os.path.join(folder, pkg + ".go"))

        # Filter: must exist, be a file, not self, not already in pending context
        already = set()
        for item in self.pending_context:
            if item.content.startswith("File: ") or item.content.startswith("Related file: "):
                first_line = item.content.split("\n")[0]
                if first_line.startswith("File: "):
                    already.add(os.path.abspath(first_line[6:]))
                elif first_line.startswith("Related file: "):
                    already.add(os.path.abspath(first_line[14:]))

        added = 0
        for cand in candidates:
            if added >= MAX_RELATED_FILES:
                break
            if not cand or cand == path:
                continue
            if not os.path.isfile(cand):
                continue
            abs_cand = os.path.abspath(cand)
            if abs_cand in already:
                continue
            # Skip common build/vendor folders
            if "/node_modules/" in abs_cand or "/vendor/" in abs_cand or "/__pycache__/" in abs_cand:
                continue
            try:
                with open(cand, "r", encoding="utf-8", errors="ignore") as f:
                    related_content = f.read()
                rel_name = os.path.basename(cand)
                self.pending_context.append(ContextItem(
                    "file",
                    rel_name,
                    f"Related file: {cand}\n```\n{related_content}\n```"
                ))
                already.add(abs_cand)
                added += 1
            except Exception:
                continue

        if added:
            print(f"[Claude] Smart Context: added {added} related file(s) for {basename}")

    def add_context_selection(self, path: str, content: str) -> None:
        """Add a selection to pending context."""
        name = os.path.basename(path) if path else "selection"
        self.pending_context.append(ContextItem("selection", name, f"Selection from {path}:\n```\n{content}\n```"))
        self._update_context_display()

    def add_context_folder(self, path: str) -> None:
        """Add a folder path to pending context."""
        name = os.path.basename(path) + "/"
        self.pending_context.append(ContextItem("folder", name, f"Folder: {path}"))
        self._update_context_display()

    def add_context_image(self, image_data: bytes, mime_type: str) -> None:
        """Add an image to pending context."""
        import base64
        import tempfile

        # Save to temp file for reference
        ext = ".png" if "png" in mime_type else ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".img"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(image_data)
            temp_path = f.name

        # Store base64 encoded image
        encoded = base64.b64encode(image_data).decode('utf-8')
        # Use special format that query() will detect
        name = f"image{ext}"
        self.pending_context.append(ContextItem(
            "image",
            name,
            f"__IMAGE__:{mime_type}:{encoded}"  # Special marker for image data
        ))
        print(f"[Claude] Added image to context: {name} ({len(image_data)} bytes, saved to {temp_path})")
        self._update_context_display()

    def clear_context(self) -> None:
        """Clear pending context."""
        self.pending_context = []
        self._update_context_display()

    def _update_context_display(self) -> None:
        """Update output view with pending context."""
        self.output.set_pending_context(self.pending_context)

    def _build_prompt_with_context(self, prompt: str) -> tuple:
        """Build full prompt with pending context.

        Returns:
            (full_prompt, images) where images is list of {"mime_type": str, "data": str}
        """
        if not self.pending_context:
            return prompt, []

        parts = []
        images = []
        for item in self.pending_context:
            if item.content.startswith("__IMAGE__:"):
                # Extract image data: __IMAGE__:mime_type:base64data
                _, mime_type, data = item.content.split(":", 2)
                images.append({"mime_type": mime_type, "data": data})
            else:
                parts.append(item.content)
        parts.append(prompt)
        return "\n\n".join(parts), images

    def undo_message(self) -> None:
        """Undo last conversation turn by rewinding the CLI session."""
        if not self.session_id:
            return
        # Allow undo even while "working" (bridge reconnecting from previous undo)
        if self.working and self.current_tool != "rewinding...":
            return
        rewind_id, undone_prompt = self._find_rewind_point()
        if not rewind_id:
            print(f"[Claude] undo_message: no rewind point found")
            return
        saved_id = self.session_id
        print(f"[Claude] undo_message: rewinding {saved_id} to {rewind_id}")
        # Exit input mode
        if self.output._input_mode:
            self.output.exit_input_mode(keep_text=False)
        # Erase last prompt turn from view (prompt = "◎ ... ▶", not input marker "◎ ")
        view = self.output.view
        content = view.substr(sublime.Region(0, view.size()))
        # Find last prompt line (contains " ▶")
        import re as _re
        last_prompt = None
        for m in _re.finditer(r'\n◎ .+? ▶', content):
            last_prompt = m
        if not last_prompt and content.startswith("◎ ") and " ▶" in content.split("\n")[0]:
            print(f"[Claude] undo: erasing entire view (first turn)")
            self.output._replace(0, view.size(), "")
        elif last_prompt:
            erase_from = last_prompt.start()
            print(f"[Claude] undo: erasing from {erase_from} to {view.size()}, matched={last_prompt.group()[:40]!r}")
            self.output._replace(erase_from, view.size(), "")
        else:
            print(f"[Claude] undo: no prompt found to erase")
        # Update conversation state
        if self.output.current:
            self.output.current = None
        view.erase_regions(CONVERSATION_REGION_KEY)
        # Kill bridge synchronously (may already be dead from previous undo)
        if self.client:
            self.client.stop()
            self.client = None
        self.initialized = False
        # Restart bridge with rewind
        self.session_id = saved_id
        self.resume_id = saved_id
        self.fork = False
        self.draft_prompt = undone_prompt
        self._input_mode_entered = True  # Block auto input mode until bridge ready
        self._pending_resume_at = rewind_id
        self._save_session()  # Persist rewind point for restart survival
        self.working = True
        self.current_tool = "rewinding..."
        self._animate()
        self.start(resume_session_at=rewind_id)
        # _on_init will reset _input_mode_entered and call _enter_input_with_draft

    def _find_rewind_point(self) -> tuple:
        """Delegate to StateManager."""
        return self._state.find_rewind_point()

    def _find_jsonl_path(self) -> Optional[str]:
        """Delegate to StateManager."""
        return self._state.find_jsonl_path()

    def interrupt(self, break_channel: bool = True) -> None:
        """Interrupt current query.

        Args:
            break_channel: If True, also breaks any active channel connection.
                          Set to False when interrupt is from channel message.
        """
        if self.client:
            sent = self.client.send("interrupt", {})
            self._status("interrupting...")
            # Don't set working=False here — wait for _on_done to confirm
            # the bridge actually stopped. This prevents input mode race.
            self._queued_prompts.clear()
            # If bridge is dead, _on_done won't fire — force cleanup
            if not sent:
                self.working = False
                self._status("error: bridge died")
                self.output.text("\n\n*Bridge process died. Please restart the session.*\n")
                self._enter_input_with_draft()

        # Break any active channel connection (only for user-initiated interrupts)
        if break_channel and self.output.view:
            from . import notalone
            notalone.interrupt_channel(self.output.view.id())

    def stop(self) -> None:
        # Persist closed state before cleanup
        self._persist_state("closed")
        # Stop heartbeat
        self._stop_heartbeat()
        # Release persona if acquired
        if self.persona_session_id and self.persona_url:
            self._release_persona()

        if self.client:
            client = self.client
            client.send("shutdown", {}, lambda _: client.stop())
        self._clear_status()

        # Release accumulated state
        if self.output:
            self.output.conversations.clear()
        self.pending_context.clear()
        self._queued_prompts.clear()

    @property
    def is_sleeping(self) -> bool:
        return bool(self.session_id) and self.client is None and not self.initialized

    @property
    def display_name(self) -> str:
        base = self.name or "Claude"
        # Strip any stale sleep prefixes from name
        import re
        base = re.sub(r'^[◉◇•❓⏸⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*', '', base) or "Claude"
        return base

    def sleep(self) -> None:
        """Put session to sleep — kill bridge, keep view."""
        if not self.session_id:
            return
        if self.working:
            self.interrupt()
            sublime.set_timeout(self.sleep, 500)
            return
        self._stop_heartbeat()
        if self.client:
            client = self.client
            self.client = None
            client.send("shutdown", {}, lambda _: client.stop())
        self.initialized = False
        self._persist_state("sleeping")
        self._apply_sleep_ui()

    def _apply_sleep_ui(self) -> None:
        """Apply sleeping state to view UI."""
        if not self.output or not self.output.view:
            return
        if not self.session_id:
            return
        view = self.output.view
        view.settings().set("claude_sleeping", True)
        self.output.set_name(self.display_name)
        self._status("sleeping")
        if self.output.is_input_mode():
            self.draft_prompt = self.output.get_input_text().strip()
            self.output.exit_input_mode(keep_text=False)
            self._input_mode_entered = False
        else:
            # Clean stale input marker from view content (e.g. after restart)
            # Only remove if the last non-empty line is exactly the marker
            content = view.substr(sublime.Region(0, view.size()))
            lines = content.rstrip("\n").split("\n")
            if lines and lines[-1].strip() == "\u25ce":
                # Find the start of this last marker line
                erase_from = content.rstrip("\n").rfind("\n" + lines[-1])
                if erase_from >= 0:
                    view.set_read_only(False)
                    view.run_command("claude_replace", {"start": erase_from, "end": view.size(), "text": ""})
                    view.set_read_only(True)
        self._ui.show_overlay("\u23f8 Session paused \u2014 press Enter to wake", color="var(--yellowish)")

    def restart(self) -> None:
        """Restart session — sleep then immediately wake."""
        def do_wake():
            if self.output and self.output.view and self.output.view.settings().get("claude_sleeping"):
                self.wake()
        self.sleep()
        sublime.set_timeout(do_wake, 600)

    def wake(self) -> None:
        """Wake a sleeping session — re-spawn bridge with resume."""
        if self.client or self.initialized:
            return
        if not self.session_id:
            return
        self._ui.clear_overlay()
        if self.output and self.output.view:
            view = self.output.view
            view.settings().erase("claude_sleeping")
            end = view.size()
            view.sel().clear()
            view.sel().add(end)
            view.show(end)
        self.resume_id = self.session_id
        self.fork = False
        resume_at = self._pending_resume_at
        self.current_tool = "waking..."
        self.start(resume_session_at=resume_at)
        self._persist_state("open")
        if self.output and self.output.view:
            self.output.set_name(self.display_name)

    # ─── Heartbeat & Auto-Restart ─────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        """Delegate to HeartbeatMonitor."""
        self._heartbeat.start()

    def _stop_heartbeat(self) -> None:
        """Delegate to HeartbeatMonitor."""
        self._heartbeat.stop()

    def _ensure_bridge_alive(self, silent: bool = False) -> bool:
        """Check bridge health; auto-restart if dead. Returns True if alive."""
        if self.client and self.client.is_alive() and self.initialized:
            return True
        # Bridge is dead or not initialized — try auto-restart
        if not silent:
            self.output.text("\n*Bridge process died. Auto-restarting...*\n")
        return self._auto_restart_bridge()

    def _auto_restart_bridge(self) -> bool:
        """Kill dead bridge and restart with resume. Returns True on success."""
        # Clean up dead bridge
        if self.client:
            try:
                self.client.stop()
            except Exception:
                pass
            self.client = None
        self.initialized = False
        self.working = False
        self._clear_deferred_state()

        if not self.session_id:
            # No session to resume — can't auto-restart
            return False

        # Restart with resume
        self.resume_id = self.session_id
        self.fork = False
        resume_at = self._pending_resume_at
        self.current_tool = "reconnecting..."
        self._status("reconnecting...")
        try:
            self.start(resume_session_at=resume_at)
            self._persist_state("open")
            return True
        except Exception as e:
            print(f"[Claude] Auto-restart failed: {e}")
            self._status("error: restart failed")
            return False

    def _persist_state(self, state: str) -> None:
        """Save session with explicit state override."""
        self._state.persist_state(state)


    def _release_persona(self) -> None:
        """Release acquired persona."""
        import threading
        from . import persona_client

        session_id = self.persona_session_id
        persona_url = self.persona_url

        def release():
            result = persona_client.release_persona(session_id, base_url=persona_url)
            if "error" not in result:
                print(f"[Claude] Released persona for session {session_id}")

        threading.Thread(target=release, daemon=True).start()

    # ─── Notification Tools ───────────────────────────────────────────────
    # Notification tools are provided by dedicated MCP servers:
    # - notalone2 daemon: timers, session completion, list/unregister
    # - vibekanban MCP server: watch_kanban for ticket state changes

    def _on_notification(self, method: str, params: dict) -> None:
        """Delegate to NotificationHandler."""
        self._notifications.handle(method, params)

    @property
    def terminal_view(self):
        """Backward-compat property for external access to terminal view."""
        return self._terminal.terminal_view

    def toggle_terminal(self) -> None:
        """Toggle the integrated terminal panel."""
        self._terminal.toggle()

    def _set_name(self, name: str) -> None:
        """Set session name and update UI."""
        self.name = name
        self.output.set_name(name)
        self._update_status_bar()
        self._save_session()

    def _save_session(self) -> None:
        """Save session info to disk for later resume."""
        self._state.save()


    def _status(self, text: str) -> None:
        """Delegate to StatusManager."""
        self._status_mgr.status(text)

    def _update_status_bar(self) -> None:
        """Delegate to StatusManager."""
        self._status_mgr.update_status_bar()

    def _clear_status(self) -> None:
        """Delegate to StatusManager."""
        self._status_mgr.clear()

    def _animate(self) -> None:
        """Delegate to StatusManager."""
        self._status_mgr.animate()

    def subscribe_to_service(
        self,
        notification_type: str,
        params: dict,
        wake_prompt: str
    ) -> dict:
        """Subscribe to a service - handles HTTP endpoints for channel services.

        This is synchronous and returns a result dict.
        """
        import urllib.request
        import json as json_mod
        import socket as sock_mod

        # First, get services list synchronously from notalone
        try:
            sock = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(os.path.expanduser("~/.notalone/notalone.sock"))
            sock.sendall((json_mod.dumps({"method": "services"}) + "\n").encode())
            response = sock.recv(65536).decode().strip()
            sock.close()
            services_data = json_mod.loads(response)
            services = services_data.get("services", [])
        except Exception as e:
            print(f"[Claude] Failed to get services: {e}")
            services = []

        # Check if this is a channel service with an endpoint
        endpoint = None
        for svc in services:
            if svc.get("type") == notification_type and svc.get("endpoint"):
                endpoint = svc.get("endpoint")
                break

        # If it has an endpoint, POST to it first
        if endpoint:
            view_id = self.output.view.id() if self.output and self.output.view else 0
            session_id = params.get("session_id", f"sublime.{view_id}")
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=json_mod.dumps({"session_id": session_id}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result = resp.read().decode()
                    print(f"[Claude] Subscribed to {notification_type}: {result}")
            except Exception as e:
                print(f"[Claude] Failed to subscribe to {notification_type}: {e}")
                return {"error": str(e)}

        # Now register with notalone daemon (simple version, no callback)
        if self.client:
            self.client.send("register_notification", {
                "notification_type": notification_type,
                "params": params,
                "wake_prompt": wake_prompt
            })
        view_id = self.output.view.id() if self.output and self.output.view else 0
        return {"ok": True, "notification_type": notification_type, "session_id": params.get("session_id", f"sublime.{view_id}")}

    def register_notification(
        self,
        notification_type: str,
        params: dict,
        wake_prompt: str,
        notification_id: Optional[str] = None,
        callback: Optional[callable] = None
    ) -> None:
        """Register a notification via notalone2 daemon.

        Args:
            notification_type: 'timer', 'subsession_complete', 'ticket_update', 'channel'
            params: Type-specific parameters
            wake_prompt: Prompt to inject when notification fires
            notification_id: Optional custom notification ID
            callback: Optional callback for result
        """
        if not self.client:
            return

        self.client.send("register_notification", {
            "notification_type": notification_type,
            "params": params,
            "wake_prompt": wake_prompt,
            "notification_id": notification_id
        }, callback)

    def signal_subsession_complete(
        self,
        result_summary: Optional[str] = None,
        callback: Optional[callable] = None
    ) -> None:
        """Signal that this subsession has completed.

        Args:
            result_summary: Optional summary of what was accomplished
            callback: Optional callback for result
        """
        if not self.client:
            return

        self.client.send("signal_subsession_complete", {
            "result_summary": result_summary
        }, callback)

