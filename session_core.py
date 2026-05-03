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
from .session_services import ServiceAdapter
from .session_context import ContextManager
from .session_bridge import BridgeManager
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
        # External service adapter
        self._services = ServiceAdapter(self)
        # Context manager for pending files/selections/images
        self._context = ContextManager(self)
        # Bridge lifecycle manager
        self._bridge = BridgeManager(self)

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
        self.last_idle_at: float = 0  # set when session enters input mode (truly idle)

        # Plan mode state
        self.plan_mode: bool = False
        self.plan_file: Optional[str] = None

        # Pending retain content (set by compact_boundary, sent after interrupt)
        self._pending_retain: Optional[str] = None

    def start(self, resume_session_at: str = None) -> None:
        """Delegate to BridgeManager."""
        self._bridge.start(resume_session_at)

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


    def add_context_file(self, path: str, content: str) -> None:
        """Delegate to ContextManager."""
        self._context.add_file(path, content)

    def add_context_selection(self, path: str, content: str) -> None:
        """Delegate to ContextManager."""
        self._context.add_selection(path, content)

    def add_context_folder(self, path: str) -> None:
        """Delegate to ContextManager."""
        self._context.add_folder(path)

    def add_context_image(self, image_data: bytes, mime_type: str) -> None:
        """Delegate to ContextManager."""
        self._context.add_image(image_data, mime_type)

    def clear_context(self) -> None:
        """Delegate to ContextManager."""
        self._context.clear()

    def _build_prompt_with_context(self, prompt: str) -> tuple:
        """Delegate to ContextManager."""
        return self._context.build_prompt(prompt)

    def undo_message(self) -> None:
        """Undo last conversation turn by rewinding the CLI session."""
        if not self.session_id:
            return
        if self.working and self.current_tool != "rewinding...":
            return
        rewind_id, undone_prompt = self._find_rewind_point()
        if not rewind_id:
            print(f"[Claude] undo_message: no rewind point found")
            return
        self._apply_undo(rewind_id, undone_prompt)

    def _apply_undo(self, rewind_id: str, undone_prompt: str) -> None:
        """Execute the rewind to rewind_id, restoring undone_prompt as draft."""
        saved_id = self.session_id
        print(f"[Claude] undo: rewinding {saved_id} to {rewind_id}")
        if self.output._input_mode:
            self.output.exit_input_mode(keep_text=False)
        view = self.output.view
        content = view.substr(sublime.Region(0, view.size()))
        import re as _re
        last_prompt = None
        for m in _re.finditer(r'\n◎ .+? ▶', content):
            last_prompt = m
        if not last_prompt and content.startswith("◎ ") and " ▶" in content.split("\n")[0]:
            self.output._replace(0, view.size(), "")
        elif last_prompt:
            self.output._replace(last_prompt.start(), view.size(), "")
        if self.output.current:
            self.output.current = None
        view.erase_regions(CONVERSATION_REGION_KEY)
        if self.client:
            self.client.stop()
            self.client = None
        self.initialized = False
        self.session_id = saved_id
        self.resume_id = saved_id
        self.fork = False
        self.draft_prompt = undone_prompt
        self._input_mode_entered = True
        self._pending_resume_at = rewind_id
        self._save_session()
        self.working = True
        self.current_tool = "rewinding..."
        self._animate()
        self.start(resume_session_at=rewind_id)

    def get_turns_for_undo(self) -> list:
        """Delegate to StateManager."""
        return self._state.get_turns_for_undo()

    def _find_rewind_point(self) -> tuple:
        """Delegate to StateManager."""
        return self._state.find_rewind_point()

    def _find_jsonl_path(self) -> Optional[str]:
        """Delegate to StateManager."""
        return self._state.find_jsonl_path()

    def interrupt(self, break_channel: bool = True) -> None:
        """Delegate to BridgeManager."""
        self._bridge.interrupt(break_channel)

    def stop(self) -> None:
        """Delegate to BridgeManager."""
        self._bridge.stop()

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
        """Delegate to BridgeManager."""
        self._bridge.sleep()

    def _apply_sleep_ui(self) -> None:
        """Delegate to SessionUIHelper."""
        self._ui.apply_sleep()

    def restart(self) -> None:
        """Delegate to BridgeManager."""
        self._bridge.restart()

    def wake(self) -> None:
        """Delegate to BridgeManager."""
        self._bridge.wake()

    # ─── Heartbeat & Auto-Restart ─────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        """Delegate to HeartbeatMonitor."""
        self._heartbeat.start()

    def _stop_heartbeat(self) -> None:
        """Delegate to HeartbeatMonitor."""
        self._heartbeat.stop()

    def _ensure_bridge_alive(self, silent: bool = False) -> bool:
        """Delegate to BridgeManager."""
        return self._bridge.ensure_alive(silent)

    def _auto_restart_bridge(self) -> bool:
        """Delegate to BridgeManager."""
        return self._bridge.auto_restart()

    def _persist_state(self, state: str) -> None:
        """Save session with explicit state override."""
        self._state.persist_state(state)


    def _release_persona(self) -> None:
        """Delegate to BridgeManager."""
        self._bridge.release_persona()

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

    def subscribe_to_service(self, notification_type: str, params: dict, wake_prompt: str) -> dict:
        """Delegate to ServiceAdapter."""
        return self._services.subscribe_to_service(notification_type, params, wake_prompt)

    def register_notification(self, notification_type: str, params: dict, wake_prompt: str,
                               notification_id: Optional[str] = None, callback: Optional[callable] = None) -> None:
        """Delegate to ServiceAdapter."""
        self._services.register_notification(notification_type, params, wake_prompt, notification_id, callback)

    def signal_subsession_complete(self, result_summary: Optional[str] = None, callback: Optional[callable] = None) -> None:
        """Delegate to ServiceAdapter."""
        self._services.signal_subsession_complete(result_summary, callback)

