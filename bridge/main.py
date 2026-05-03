#!/usr/bin/env python3
"""
Bridge process between Sublime Text (Python 3.8) and Claude Agent SDK (Python 3.10+).
Communicates via JSON-RPC over stdio.
"""
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent))
from settings import load_project_settings
from logger import get_bridge_logger, ContextLogger

from terminal import TerminalManager, strip_ansi


# Import notalone2 client for daemon-based notifications
# notalone2 client removed - using global client in plugin instead


# Initialize logger
_logger = get_bridge_logger()

# Bridge debug log — auto-rotates at 2MB to prevent unbounded growth
_BRIDGE_LOG_PATH = "/tmp/claude_bridge.log"
_BRIDGE_LOG_MAX_BYTES = 2 * 1024 * 1024


def _bridge_log(message: str) -> None:
    """Append a line to the bridge debug log, rotating if too large."""
    try:
        if os.path.exists(_BRIDGE_LOG_PATH):
            size = os.path.getsize(_BRIDGE_LOG_PATH)
            if size > _BRIDGE_LOG_MAX_BYTES:
                # Rotate: keep last 10% of log
                with open(_BRIDGE_LOG_PATH, "r") as f:
                    content = f.read()
                keep_from = len(content) // 10
                with open(_BRIDGE_LOG_PATH, "w") as f:
                    f.write("[log rotated]\n")
                    f.write(content[keep_from:])
        with open(_BRIDGE_LOG_PATH, "a") as f:
            f.write(message + "\n")
    except Exception:
        pass


# Set env var so child processes (bash commands) can detect they're running under Claude agent
os.environ["CLAUDE_AGENT"] = "1"

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
    PermissionResultAllow,
    PermissionResultDeny,
)


def serialize(obj: Any) -> Any:
    """Serialize SDK objects to JSON-compatible dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    return obj


from rpc_helpers import send, send_error, send_result, send_notification


class Bridge:
    def __init__(self):
        self.client: Optional[ClaudeSDKClient] = None
        self.options: Optional[ClaudeAgentOptions] = None
        self.running = True
        self.current_task: Optional[asyncio.Task] = None
        self.pending_permissions: Dict[int, asyncio.Future] = {}
        self.pending_questions: Dict[int, asyncio.Future] = {}  # For AskUserQuestion
        self.pending_plan_approvals: Dict[int, asyncio.Future] = {}  # For plan mode
        self.permission_id = 0
        self.question_id = 0
        self.plan_id = 0
        self.interrupted = False  # Set by interrupt(), checked by query()
        self.query_id: Optional[int] = None  # Track active query for inject_message
        self.cwd: Optional[str] = None  # Current working directory (set by initialize)

        # Queue for injected prompts that arrive when query completes
        self.pending_injects: List[str] = []

        # Track active background tasks
        self._pending_bg_tasks: set[str] = set()
        self._bg_tool_use_ids: set[str] = set()

        # Persistent terminal session
        self.terminal: Optional[TerminalManager] = None

        # Notification system (notalone2)
        # notalone handled by global client in plugin

    async def handle_request(self, req: dict) -> None:
        id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        try:
            if method == "initialize":
                await self.initialize(id, params)
            elif method == "query":
                await self.query(id, params)
            elif method == "interrupt":
                await self.interrupt(id)
            elif method == "shutdown":
                await self.shutdown(id)
            elif method == "permission_response":
                await self.handle_permission_response(id, params)
            elif method == "question_response":
                await self.handle_question_response(id, params)
            elif method == "plan_response":
                await self.handle_plan_response(id, params)
            elif method == "cancel_pending":
                await self.cancel_pending(id)
            elif method == "inject_message":
                await self.inject_message(id, params)
            elif method == "get_history":
                await self.get_history(id)
            elif method == "register_notification":
                result = await self.register_notification(
                    notification_type=params.get("notification_type"),
                    params=params.get("params", {}),
                    wake_prompt=params.get("wake_prompt"),
                    notification_id=params.get("notification_id")
                )
                send_result(id, result)
            elif method == "signal_subsession_complete":
                result = await self.signal_subsession_complete(
                    subsession_id=None,  # Will use self._subsession_id
                    result_summary=params.get("result_summary")
                )
                send_result(id, result)
            elif method == "subsession_complete":
                # Notification: no response needed
                subsession_id = params.get("subsession_id")
                if subsession_id:
                    await self.signal_subsession_complete(subsession_id)
            elif method == "list_notifications":
                result = await self.list_notifications()
                send_result(id, result)
            elif method == "discover_services":
                result = await self.discover_services()
                send_result(id, result)
            elif method == "set_model":
                model = params.get("model")
                if model and self.client:
                    await self.client.set_model(model)
                max_ctx = params.get("max_context_tokens")
                if max_ctx:
                    os.environ["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(max_ctx)
                send_result(id, {"ok": True})
            elif method == "terminal_start":
                await self.terminal_start(id, params)
            elif method == "terminal_stop":
                await self.terminal_stop(id, params)
            elif method == "terminal_write":
                await self.terminal_write(id, params)
            elif method == "terminal_read":
                await self.terminal_read(id, params)
            elif method == "terminal_resize":
                await self.terminal_resize(id, params)
            else:
                send_error(id, -32601, f"Method not found: {method}")
        except Exception as e:
            send_error(id, -32000, str(e))

    async def initialize(self, id: int, params: dict) -> None:
        """Initialize the Claude SDK client."""
        resume_id = params.get("resume")
        fork_session = params.get("fork_session", False)
        cwd = params.get("cwd")
        view_id = params.get("view_id")
        self.cwd = cwd  # Store for later use (e.g., in can_use_tool)
        self._view_id = view_id  # Store for spawn_session to pass to subsessions

        # Generate a proper UUID for Claude CLI (--session-id requires valid UUID format)
        # view_id is Sublime's view ID (integer), not suitable for Claude's session_id
        # For fresh sessions, generate new UUID; for resume, use existing resume_id
        if resume_id:
            session_id = resume_id
        else:
            session_id = str(uuid.uuid4())
        self._session_id = session_id

        # notalone2 handled by global client in plugin (not per-bridge)

        # Change to project directory so SDK finds CLAUDE.md etc.
        if cwd and os.path.isdir(cwd):
            os.chdir(cwd)

        # Load MCP servers, agents, and plugins from project settings
        mcp_servers = self._load_mcp_servers(cwd)
        agents = self._load_agents(cwd)
        plugins = self._load_plugins(cwd)
        settings = load_project_settings(cwd)

        # Load kanban base URL for notalone remote notifications
        self.kanban_base_url = settings.get("kanban_base_url", "http://localhost:5050")
        _logger.info(f"Kanban base URL: {self.kanban_base_url}")

        _logger.info(f"initialize: params={params}")
        _logger.info(f"  resume_id={resume_id}, fork={fork_session}, resume_session_at={params.get('resume_session_at')}, cwd={cwd}, actual_cwd={os.getcwd()}")
        _logger.info(f"  mcp_servers={list(mcp_servers.keys()) if mcp_servers else None}")
        _logger.info(f"  agents={list(agents.keys()) if agents else None}")
        _logger.info(f"  plugins={plugins}")

        # Build system prompt with project addon
        system_prompt = params.get("system_prompt", "")
        addon = settings.get("system_prompt_addon")
        if addon:
            system_prompt = (system_prompt + "\n\n" + addon) if system_prompt else addon

        # Add session info to system prompt
        session_id_info = f"sublime.{session_id}"
        view_id_info = view_id or session_id
        session_guide = f"""

## Session Info

Session ID: {session_id_info}
View ID: {view_id_info}
"""
        system_prompt = (system_prompt + session_guide) if system_prompt else session_guide

        # If this is a subsession, store subsession_id and add specific guidance
        subsession_id = params.get("subsession_id")
        self._subsession_id = subsession_id  # Store for signal_complete tool
        if subsession_id:
            subsession_guide = f"""
You are subsession **{subsession_id}**. Call signal_complete(session_id={view_id_info}, result_summary="...") when done.
"""
            system_prompt += subsession_guide

        options_dict = {
            "allowed_tools": params.get("allowed_tools", []),
            "permission_mode": params.get("permission_mode", "default"),
            "cwd": cwd,
            "system_prompt": system_prompt,
            "can_use_tool": self.can_use_tool,
            "resume": resume_id,
            "fork_session": fork_session,
            "setting_sources": ["user", "project"],
            "max_buffer_size": 100 * 1024 * 1024,  # 100MB for large images/files
            "include_partial_messages": True,
            "cli_path": "claude",
        }

        # Profile config: model, betas, effort
        if params.get("model"):
            options_dict["model"] = params["model"]
        if params.get("betas"):
            options_dict["betas"] = params["betas"]
        effort = params.get("effort", "high")
        if effort:
            options_dict["effort"] = effort

        # Sandbox settings from project config
        sandbox = self._load_sandbox_settings(cwd)
        if sandbox:
            options_dict["sandbox"] = sandbox
            _bridge_log(f"  sandbox enabled: {sandbox}\n")
        # Add MCP servers if found
        if mcp_servers:
            options_dict["mcp_servers"] = mcp_servers

        # Add agents if found
        if agents:
            options_dict["agents"] = agents

        # Add plugins if found
        if plugins:
            options_dict["plugins"] = plugins

        # For fresh sessions (not resuming), specify session_id upfront via CLI arg
        # This avoids waiting for first query to get session_id from ResultMessage
        if not resume_id:
            extra_args = {"session-id": session_id}
            # Add additional working directories from Sublime project folders
            additional_dirs = params.get("additional_dirs", [])
            if additional_dirs:
                extra_args["add-dir"] = additional_dirs
            # Merge extra args from settings (e.g. max-budget-usd)
            user_extra = params.get("extra_args")
            if user_extra and isinstance(user_extra, dict):
                extra_args.update(user_extra)
            options_dict["extra_args"] = extra_args
        else:
            # Resume mode — check for rewind point
            resume_session_at = params.get("resume_session_at")
            if resume_session_at:
                options_dict["extra_args"] = {"resume-session-at": resume_session_at}

        self.options = ClaudeAgentOptions(**options_dict)
        self.client = ClaudeSDKClient(options=self.options)

        try:
            await self.client.connect()
        except Exception as e:
            error_msg = str(e)

            # If session not found or command failed during resume, retry without resume
            # The SDK wraps the actual error, so we check for common patterns
            is_session_error = (
                "No conversation found" in error_msg or
                ("Command failed" in error_msg and resume_id)
            )
            if is_session_error and resume_id:
                # If rewind failed, retry resume without rewind point
                if "extra_args" in options_dict and "resume-session-at" in options_dict.get("extra_args", {}):
                    _bridge_log(f"resume-session-at failed, retrying plain resume: {error_msg}\n")
                    del options_dict["extra_args"]["resume-session-at"]
                    if not options_dict["extra_args"]:
                        del options_dict["extra_args"]
                    self.options = ClaudeAgentOptions(**options_dict)
                    self.client = ClaudeSDKClient(options=self.options)
                    await self.client.connect()
                else:
                    raise
            else:
                raise

        send_result(id, {
            "status": "initialized",
            "session_id": session_id,
            "mcp_servers": list(mcp_servers.keys()) if mcp_servers else [],
            "agents": list(agents.keys()) if agents else [],
        })


    def _load_mcp_servers(self, cwd: str) -> dict:
        """Load MCP servers from global config (~/.claude.json), project config,
        and built-in sublime MCP server."""
        servers = {}

        # 1. Global MCP servers from ~/.claude.json (Claude CLI global config)
        global_mcp_path = os.path.expanduser("~/.claude.json")
        if os.path.exists(global_mcp_path):
            try:
                with open(global_mcp_path) as f:
                    global_config = json.load(f)
                global_servers = global_config.get("mcpServers", {})
                servers.update(global_servers)
                _logger.info(f"  Loaded global MCP servers from ~/.claude.json: {list(global_servers.keys())}")
            except Exception as e:
                _logger.warning(f"  Failed to load ~/.claude.json: {e}")

        # 2. Project MCP servers from .claude/settings.json
        if cwd:
            project_settings_path = os.path.join(cwd, ".claude", "settings.json")
            if os.path.exists(project_settings_path):
                try:
                    with open(project_settings_path) as f:
                        project_config = json.load(f)
                    project_servers = project_config.get("mcpServers", {})
                    servers.update(project_servers)
                    _logger.info(f"  Loaded project MCP servers from .claude/settings.json: {list(project_servers.keys())}")
                except Exception as e:
                    _logger.warning(f"  Failed to load project settings: {e}")

            # 3. Fallback: .mcp.json in project root
            mcp_fallback_path = os.path.join(cwd, ".mcp.json")
            if os.path.exists(mcp_fallback_path):
                try:
                    with open(mcp_fallback_path) as f:
                        fallback_config = json.load(f)
                    fallback_servers = fallback_config.get("mcpServers", {})
                    servers.update(fallback_servers)
                    _logger.info(f"  Loaded project MCP servers from .mcp.json: {list(fallback_servers.keys())}")
                except Exception as e:
                    _logger.warning(f"  Failed to load .mcp.json: {e}")

        # 4. Always include the built-in sublime MCP server
        bridge_dir = os.path.dirname(os.path.abspath(__file__))
        plugin_dir = os.path.dirname(bridge_dir)
        mcp_server_path = os.path.join(plugin_dir, "mcp", "server.py")

        if os.path.exists(mcp_server_path):
            view_id_arg = f"--view-id={self._view_id}" if self._view_id else ""
            servers["sublime"] = {
                "command": sys.executable,
                "args": [mcp_server_path, view_id_arg] if view_id_arg else [mcp_server_path]
            }

        if servers:
            _bridge_log(f"  injected MCP servers: {list(servers.keys())}\n")
            return servers

    def _load_sandbox_settings(self, cwd: str) -> dict:
        """Load sandbox settings from project config."""
        settings = load_project_settings(cwd)
        sandbox_config = settings.get("sandbox", {})

        if not sandbox_config.get("enabled"):
            return None

        sandbox = {
            "enabled": True,
            "auto_allow_bash_if_sandboxed": sandbox_config.get("autoAllowBashIfSandboxed", False),
        }

        # Excluded commands (bypass sandbox)
        if "excludedCommands" in sandbox_config:
            sandbox["excluded_commands"] = sandbox_config["excludedCommands"]

        # Allow model to request unsandboxed execution
        if sandbox_config.get("allowUnsandboxedCommands"):
            sandbox["allow_unsandboxed_commands"] = True

        # Network settings
        network = sandbox_config.get("network", {})
        if network:
            sandbox["network"] = {}
            if network.get("allowLocalBinding"):
                sandbox["network"]["allow_local_binding"] = True
            if network.get("allowUnixSockets"):
                sandbox["network"]["allow_unix_sockets"] = network["allowUnixSockets"]
            if network.get("allowAllUnixSockets"):
                sandbox["network"]["allow_all_unix_sockets"] = True

        return sandbox

    def _load_agents(self, cwd: str) -> dict:
        """Return empty dict - agents loaded by SDK via setting_sources."""
        # SDK loads agents from ~/.claude/settings.json and .claude/settings.json
        return {}

    def _load_plugins(self, cwd: str) -> list:
        """Return empty list - plugins loaded by SDK via setting_sources.

        SDK loads plugins from ~/.claude/settings.json and .claude/settings.json.
        """
        return []

    def _parse_permission_pattern(self, pattern: str) -> Tuple[str, Optional[str]]:
        """Parse permission pattern into (tool_name, specifier).

        Formats:
            "Bash" -> ("Bash", None)
            "Bash(git:*)" -> ("Bash", "git:*")
            "Read(/src/**)" -> ("Read", "/src/**")
        """
        if '(' in pattern and pattern.endswith(')'):
            paren_idx = pattern.index('(')
            tool_name = pattern[:paren_idx]
            specifier = pattern[paren_idx + 1:-1]
            return tool_name, specifier
        return pattern, None

    def _extract_bash_commands(self, command: str) -> List[str]:
        """Extract individual command names from a bash command string.

        Handles:
        - Command chains: cmd1 && cmd2, cmd1 || cmd2, cmd1 ; cmd2
        - Pipes: cmd1 | cmd2
        - Environment variables: FOO=bar cmd
        - Subshells: $(cmd), `cmd`

        Returns list of command names (e.g., ["cd", "git", "npm"])
        """
        import re
        import shlex

        commands = []

        # Split on command separators: &&, ||, ;, |, but not inside quotes
        # Simple approach: split on these patterns
        parts = re.split(r'\s*(?:&&|\|\||;|\|)\s*', command)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Skip subshell wrappers
            part = re.sub(r'^\$\(|\)$|^`|`$', '', part).strip()

            # Skip leading environment variable assignments (VAR=value)
            while part and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', part):
                part = re.sub(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', '', part)

            if not part:
                continue

            # Extract first word as command name
            try:
                tokens = shlex.split(part)
                if tokens:
                    cmd = tokens[0]
                    # Handle path prefixes like /usr/bin/git -> git
                    if '/' in cmd:
                        cmd = cmd.split('/')[-1]
                    commands.append(cmd)
            except ValueError:
                # shlex parsing failed, try simple split
                words = part.split()
                if words:
                    cmd = words[0]
                    if '/' in cmd:
                        cmd = cmd.split('/')[-1]
                    commands.append(cmd)

        return commands

    def _match_permission_pattern(self, tool_name: str, tool_input: dict, pattern: str) -> bool:
        """Check if tool use matches a permission pattern.

        Supports:
            - Simple tool match: "Bash" matches any Bash command
            - Prefix match: "Bash(git:*)" matches commands starting with "git"
            - Exact match: "Bash(git status)" matches exactly "git status"
            - Glob match: "Read(/src/**/*.py)" matches files under /src/ ending in .py
        """
        import fnmatch

        parsed_tool, specifier = self._parse_permission_pattern(pattern)

        # Tool name must match (supports wildcards like mcp__*__)
        if not fnmatch.fnmatch(tool_name, parsed_tool):
            return False

        # No specifier = match all uses of this tool
        if specifier is None:
            return True

        # Special handling for Bash - extract and match individual commands
        if tool_name == "Bash":
            full_command = tool_input.get("command", "")
            if not full_command:
                return False

            # Extract individual command names from the bash string
            cmd_names = self._extract_bash_commands(full_command)

            # Handle prefix match with :* suffix
            if specifier.endswith(":*"):
                prefix = specifier[:-2]
                # Match if ANY command starts with prefix OR full command starts with prefix
                if full_command.startswith(prefix):
                    return True
                return any(cmd.startswith(prefix) for cmd in cmd_names)

            # Handle glob/fnmatch patterns
            if any(c in specifier for c in ['*', '?', '[']):
                # Match against full command OR any individual command
                if fnmatch.fnmatch(full_command, specifier):
                    return True
                return any(fnmatch.fnmatch(cmd, specifier) for cmd in cmd_names)

            # Exact match - check full command OR any individual command name
            if full_command == specifier:
                return True
            return specifier in cmd_names

        # Special handling for Read/Write/Edit - directory-based permissions
        # Like Claude CLI: permission granted for a file extends to its directory
        if tool_name in ("Read", "Write", "Edit"):
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return False

            # Handle glob patterns (e.g., /src/**/*.py)
            if any(c in specifier for c in ['*', '?', '[']):
                return fnmatch.fnmatch(file_path, specifier)

            # Handle prefix match with :* suffix
            if specifier.endswith(":*"):
                prefix = specifier[:-2]
                return file_path.startswith(prefix)

            # Directory-based permission: if specifier is a file path,
            # allow access to any file in the same directory
            # e.g., pattern "/src/foo.py" allows "/src/bar.py"
            specifier_dir = os.path.dirname(specifier.rstrip('/'))
            file_dir = os.path.dirname(file_path)

            # If specifier looks like a directory (ends with /), match files within
            if specifier.endswith('/'):
                return file_path.startswith(specifier)

            # Same directory = allowed
            if specifier_dir and file_dir == specifier_dir:
                return True

            # Exact match still works
            return file_path == specifier

        # Get the value to match against based on tool type
        match_value = None
        if tool_name in ("Glob", "Grep"):
            match_value = tool_input.get("pattern", "")
        elif tool_name == "WebFetch":
            match_value = tool_input.get("url", "")
        elif tool_name == "Skill":
            match_value = tool_input.get("skill", "")
        else:
            # For other tools, try common field names
            match_value = tool_input.get("command") or tool_input.get("path") or tool_input.get("query", "")

        if not match_value:
            return False

        # Handle prefix match with :* suffix (like Claude Code)
        if specifier.endswith(":*"):
            prefix = specifier[:-2]
            return match_value.startswith(prefix)

        # Handle glob/fnmatch patterns
        if any(c in specifier for c in ['*', '?', '[']):
            return fnmatch.fnmatch(match_value, specifier)

        # Exact match
        return match_value == specifier

    def _load_guardrails(self) -> dict:
        """Load guardrails configuration from project settings."""
        settings = load_project_settings(self.cwd)
        return settings.get("guardrails", {})

    def _validate_bash_command(self, command: str) -> Tuple[bool, str]:
        """Validate bash command for dangerous patterns and guardrails.

        Returns: (is_safe, warning_message)
        """
        import re

        guardrails = self._load_guardrails()
        blocked_patterns = guardrails.get("blocked_commands", [])
        require_approval = guardrails.get("require_approval_for", [])

        # Check blocked commands (always denied)
        for pattern in blocked_patterns:
            if pattern.lower() in command.lower():
                return False, f"Command blocked by guardrail: '{pattern}' is not allowed. " \
                              f"Remove it from 'guardrails.blocked_commands' in .claude/settings.json to allow."

        # Check commands requiring approval (will trigger permission dialog)
        # This is handled in can_use_tool after validation, but we mark them here

        # Check for rm -rf with potentially dangerous paths
        rm_pattern = r'\brm\s+(-[rf]{1,2}\s+|-[a-z]*[rf][a-z]*\s+)'
        if re.search(rm_pattern, command):
            # Extract the path being deleted
            path_match = re.search(rm_pattern + r'([^\s;&|]+)', command)
            if path_match:
                path = path_match.group(2)

                # Dangerous: relative paths that could delete parent dirs
                if '..' in path:
                    return False, f"Dangerous rm command with parent directory reference: {path}"

                # Dangerous: deleting from root or home
                if path.startswith('/') and path.count('/') <= 3:
                    return False, f"Dangerous rm command targeting high-level directory: {path}"

                # Dangerous: wildcards in critical locations
                if '*' in path and path.count('/') <= 4:
                    return False, f"Dangerous rm command with wildcards in shallow path: {path}"

                # Check for deletion of entire project directories
                critical_dirs = ['node', 'src', 'lib', 'app', 'dist', 'build']
                path_parts = path.rstrip('/').split('/')
                if path_parts and path_parts[-1] in critical_dirs and '/' not in path:
                    return False, f"Dangerous: attempting to delete entire '{path_parts[-1]}' directory"

        return True, ""

    def _run_pre_flight_checks(self, command: str) -> Tuple[bool, str]:
        """Run pre-flight checks before allowing certain commands.

        Returns: (passed, message)
        """
        import subprocess

        guardrails = self._load_guardrails()
        checks_config = guardrails.get("pre_flight_checks", {})

        # Find matching check pattern
        checks_to_run = []
        for pattern, checks in checks_config.items():
            if pattern.lower() in command.lower():
                checks_to_run = checks if isinstance(checks, list) else [checks]
                break

        if not checks_to_run:
            return True, ""

        results = []
        for check in checks_to_run:
            try:
                result = subprocess.run(
                    check, shell=True, capture_output=True, text=True,
                    cwd=self.cwd, timeout=120
                )
                if result.returncode != 0:
                    results.append(f"❌ {check} FAILED:\n{result.stdout}\n{result.stderr}")
                else:
                    results.append(f"✅ {check} passed")
            except Exception as e:
                results.append(f"❌ {check} ERROR: {e}")

        failures = [r for r in results if r.startswith("❌")]
        if failures:
            return False, "Pre-flight checks failed:\n\n" + "\n\n".join(failures)

        return True, "\n".join(results)

    async def can_use_tool(self, tool_name: str, tool_input: dict, context=None):
        """Handle permission request - ask Sublime for approval."""
        # Handle AskUserQuestion - show UI and collect answers
        if tool_name == "AskUserQuestion":
            return await self._handle_ask_user_question(tool_input)

        # Handle EnterPlanMode - notify Sublime and auto-allow
        if tool_name == "EnterPlanMode":
            send_notification("plan_mode_enter", {})
            return PermissionResultAllow(updated_input=tool_input)

        # Handle ExitPlanMode - wait for user approval
        if tool_name == "ExitPlanMode":
            return await self._handle_exit_plan_mode(tool_input)

        # Auto-allow built-in sublime MCP tools
        if tool_name.startswith("mcp__sublime__"):
            return PermissionResultAllow(updated_input=tool_input)

        # Validate Bash commands for dangerous patterns and guardrails
        if tool_name == "Bash" and "command" in tool_input:
            is_safe, warning = self._validate_bash_command(tool_input["command"])
            if not is_safe:
                _bridge_log(f"BLOCKED dangerous Bash command: {warning}\n")
                _bridge_log(f"  Command: {tool_input['command']}\n")
                return PermissionResultDeny(message=f"Blocked dangerous command: {warning}")

            # Run pre-flight checks for commands that require them
            passed, message = self._run_pre_flight_checks(tool_input["command"])
            if not passed:
                _bridge_log(f"PRE-FLIGHT CHECKS FAILED: {message}\n")
                return PermissionResultDeny(message=f"Pre-flight checks failed:\n{message}")

            # Check guardrails requiring approval
            guardrails = self._load_guardrails()
            require_approval = guardrails.get("require_approval_for", [])
            _guardrail_requires_approval = any(
                pattern.lower() in tool_input["command"].lower()
                for pattern in require_approval
            )
            if _guardrail_requires_approval:
                _bridge_log(f"GUARDRAIL: Requiring approval for command matching guardrail pattern\n")
                # Fall through to permission dialog below
            else:
                # Check auto-allowed tools from settings
                settings = load_project_settings(self.cwd)
                auto_allowed = settings.get("autoAllowedMcpTools", [])

                # Check if tool matches any auto-allow pattern (supports fine-grained patterns)
                for pattern in auto_allowed:
                    if self._match_permission_pattern(tool_name, tool_input, pattern):
                        _bridge_log(f"can_use_tool: auto-allowed {tool_name} (matched pattern: {pattern})\n")
                        return PermissionResultAllow(updated_input=tool_input)

                # No auto-allow match, fall through to permission dialog below

        # For non-Bash tools: check auto-allowed tools from settings
        if tool_name != "Bash":
            settings = load_project_settings(self.cwd)
            auto_allowed = settings.get("autoAllowedMcpTools", [])

            # Check if tool matches any auto-allow pattern (supports fine-grained patterns)
            for pattern in auto_allowed:
                if self._match_permission_pattern(tool_name, tool_input, pattern):
                    _bridge_log(f"can_use_tool: auto-allowed {tool_name} (matched pattern: {pattern})\n")
                    return PermissionResultAllow(updated_input=tool_input)

        self.permission_id += 1
        pid = self.permission_id

        _bridge_log(f"can_use_tool: tool={tool_name}, pid={pid}, input={str(tool_input)[:100]}\n")
        # Create a future to wait for the response
        future = asyncio.get_event_loop().create_future()
        self.pending_permissions[pid] = future

        # Send permission request to Sublime
        send_notification("permission_request", {
            "id": pid,
            "tool": tool_name,
            "input": tool_input,
        })

        # Wait for response from Sublime
        try:
            allowed = await asyncio.wait_for(future, timeout=3600)  # 1 hour timeout
            _bridge_log(f"can_use_tool returning: pid={pid}, allowed={allowed}\n")
            if allowed:
                return PermissionResultAllow(updated_input=tool_input)
            else:
                return PermissionResultDeny(message="User denied permission")
        except asyncio.TimeoutError:
            return PermissionResultDeny(message="Permission request timed out")
        finally:
            self.pending_permissions.pop(pid, None)

    async def handle_permission_response(self, id: int, params: dict) -> None:
        """Handle permission response from Sublime."""
        pid = params.get("id")
        allow = params.get("allow", False)

        _bridge_log(f"permission_response: pid={pid}, allow={allow}\n")
        if pid in self.pending_permissions:
            future = self.pending_permissions[pid]
            future.set_result(allow)
        else:
            _bridge_log(f"  -> WARNING: pid {pid} not found in pending!\n")
        send_result(id, {"status": "ok"})

    async def _handle_ask_user_question(self, tool_input: dict):
        """Handle AskUserQuestion tool - show UI and collect answers."""
        questions = tool_input.get("questions", [])
        if not questions:
            return PermissionResultAllow(updated_input=tool_input)

        self.permission_id += 1
        qid = self.permission_id

        _bridge_log(f"AskUserQuestion: qid={qid}, questions={len(questions)}\n")
        future = asyncio.get_event_loop().create_future()
        self.pending_questions[qid] = future

        send_notification("question_request", {
            "id": qid,
            "questions": questions,
        })

        try:
            answers = await future
            _bridge_log(f"AskUserQuestion response: qid={qid}, answers={answers}\n")
            if answers is None:
                return PermissionResultDeny(message="User cancelled")

            updated_input = {"questions": questions, "answers": answers}
            return PermissionResultAllow(updated_input=updated_input)
        finally:
            self.pending_questions.pop(qid, None)

    async def handle_question_response(self, id: int, params: dict) -> None:
        """Handle question response from Sublime."""
        qid = params.get("id")
        answers = params.get("answers")

        _bridge_log(f"question_response: qid={qid}, answers={answers}\n")
        if qid in self.pending_questions:
            self.pending_questions[qid].set_result(answers)
        else:
            _bridge_log(f"  -> WARNING: qid {qid} not found!\n")
        send_result(id, {"status": "ok"})

    async def _handle_exit_plan_mode(self, tool_input: dict):
        """Handle ExitPlanMode - show plan approval UI and wait for response."""
        self.plan_id += 1
        pid = self.plan_id

        _bridge_log(f"ExitPlanMode: pid={pid}, input={str(tool_input)[:200]}\n")
        future = asyncio.get_event_loop().create_future()
        self.pending_plan_approvals[pid] = future

        # Send notification to Sublime with plan details
        send_notification("plan_mode_exit", {
            "id": pid,
            "tool_input": tool_input,
        })

        try:
            result = await asyncio.wait_for(future, timeout=3600)  # 1 hour timeout
            _bridge_log(f"ExitPlanMode response: pid={pid}, approved={result}\n")
            if result is True:
                # Approved - allow the tool
                return PermissionResultAllow(updated_input=tool_input)
            elif result is False:
                # Rejected - deny and stop
                return PermissionResultDeny(message="Plan rejected by user")
            else:
                # None = continue planning - deny but with continue message
                return PermissionResultDeny(message="User wants to continue planning")
        except asyncio.TimeoutError:
            return PermissionResultDeny(message="Plan approval timed out")
        finally:
            self.pending_plan_approvals.pop(pid, None)

    async def handle_plan_response(self, id: int, params: dict) -> None:
        """Handle plan approval response from Sublime."""
        pid = params.get("id")
        approved = params.get("approved")  # True, False, or None (continue)

        _bridge_log(f"plan_response: pid={pid}, approved={approved}\n")
        if pid in self.pending_plan_approvals:
            self.pending_plan_approvals[pid].set_result(approved)
        else:
            _bridge_log(f"  -> WARNING: pid {pid} not found!\n")
        send_result(id, {"status": "ok"})

    def _build_content_with_images(self, prompt: str, images: list) -> list:
        """Build Claude content array with text and images.

        Args:
            prompt: Text prompt
            images: List of {"mime_type": str, "data": str} dicts

        Returns:
            Content array for Claude API
        """
        content = []
        # Add images first (Claude prefers images before text)
        for img in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["mime_type"],
                    "data": img["data"]
                }
            })
        # Add text
        content.append({"type": "text", "text": prompt})
        return content

    async def query(self, id: int, params: dict) -> None:
        """Send a query and stream responses."""
        if not self.client:
            send_error(id, -32002, "Not initialized")
            return

        prompt = params.get("prompt", "")
        images = params.get("images", [])

        # Cancel any still-running previous query (e.g. after interrupt)
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            try:
                await self.current_task
            except (asyncio.CancelledError, Exception):
                pass

        # Kill lingering CLI process so the next one can acquire the session lock
        if self.client:
            try:
                await self.client.interrupt()
            except Exception:
                pass

        self.interrupted = False  # Reset at start of query
        self._got_first_delta = False
        self.query_id = id  # Store for inject_message to know query is active

        async def run_query():
            if images:
                # Build multimodal content
                content = self._build_content_with_images(prompt, images)
                # Yield as user message stream
                async def message_stream():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content},
                        "parent_tool_use_id": None,
                    }
                await self.client.query(message_stream())
            else:
                await self.client.query(prompt)
            turn_done = False
            async for message in self.client.receive_messages():
                # Track background tasks
                if isinstance(message, SystemMessage):
                    data = message.data or {}
                    if message.subtype == "task_started":
                        tool_use_id = data.get("tool_use_id", "")
                        task_id = data.get("task_id", "")
                        if tool_use_id in self._bg_tool_use_ids:
                            self._pending_bg_tasks.add(task_id)
                    elif message.subtype == "task_updated" and (data.get("patch") or {}).get("is_backgrounded"):
                        self._pending_bg_tasks.add(data.get("task_id", ""))
                    elif message.subtype == "task_notification":
                        self._pending_bg_tasks.discard(data.get("task_id", ""))
                if not turn_done:
                    if self.interrupted and not isinstance(message, ResultMessage):
                        continue
                    await self.emit_message(message)
                    if isinstance(message, ResultMessage):
                        status = "interrupted" if self.interrupted else "complete"
                        send_result(id, {"status": status})
                        turn_done = True
                        if not self._pending_bg_tasks:
                            break
                else:
                    # Post-turn: forward system messages for background task updates
                    if isinstance(message, SystemMessage):
                        await self.emit_message(message)
                    if not self._pending_bg_tasks:
                        break

        self.current_task = asyncio.create_task(run_query())
        result_sent = False
        try:
            await self.current_task
        except asyncio.CancelledError:
            send_result(id, {"status": "interrupted"})
            result_sent = True
        except Exception as e:
            error_msg = str(e)
            _bridge_log(f"query error: {error_msg}\n")
            # Check for session-related errors
            is_session_error = (
                "No conversation found" in error_msg or
                "Command failed" in error_msg or
                "exit code" in error_msg
            )
            if is_session_error:
                send_error(id, -32003, f"Session error: {error_msg}. Try restarting the session.")
            else:
                send_result(id, {"status": "error", "error": error_msg})
            result_sent = True
        finally:
            # Safety net: if run_query() finished without sending a result
            # (e.g. receive_messages() ended unexpectedly), send one now so
            # the session doesn't hang forever.
            if not result_sent:
                status = "interrupted" if self.interrupted else "complete"
                _bridge_log(f"query: safety-net result status={status}\n")
                send_result(id, {"status": status})
            self.query_id = None
            # Process any pending injects that arrived during query
            if self.pending_injects:
                _bridge_log(f"query ended with {len(self.pending_injects)} pending injects\n")
                # Send notification to Sublime to submit the queued prompts
                for inject in self.pending_injects:
                    send_notification("queued_inject", {"message": inject})
                self.pending_injects.clear()

    async def emit_message(self, message: Any) -> None:
        """Emit a message notification."""
        if isinstance(message, StreamEvent):
            event = message.event
            etype = event.get("type")
            if etype == "content_block_start":
                self._got_first_delta = False
            elif etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta["text"]
                    if not self._got_first_delta:
                        text = text.lstrip('\n')
                        self._got_first_delta = True
                    if text:
                        send_notification("message", {
                            "type": "text_delta",
                            "text": text,
                        })
            return

        if isinstance(message, AssistantMessage):
            _bridge_log(f"  blocks: {[type(b).__name__ for b in message.content]}\n")
            if message.usage:
                send_notification("message", {
                    "type": "turn_usage",
                    "usage": message.usage,
                })
            for block in message.content:
                if isinstance(block, TextBlock):
                    # Text was already streamed via StreamEvent text_deltas — skip
                    pass
                elif isinstance(block, ToolUseBlock):
                    tool_input = block.input or {}
                    is_bg = bool(tool_input.get("run_in_background") if isinstance(tool_input, dict) else False)
                    if is_bg:
                        self._bg_tool_use_ids.add(block.id)
                    send_notification("message", {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": tool_input,
                        "background": is_bg,
                    })
                elif isinstance(block, ToolResultBlock):
                    _bridge_log(f"tool_result: id={block.tool_use_id}, is_error={block.is_error}, content={str(block.content)[:200]}\n")
                    send_notification("message", {
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    })
                elif isinstance(block, ThinkingBlock):
                    send_notification("message", {
                        "type": "thinking",
                        "thinking": block.thinking,
                    })
        elif isinstance(message, UserMessage):
            # UserMessage contains tool results
            content = message.content
            if isinstance(content, list):
                _bridge_log(f"  UserMessage blocks: {[type(b).__name__ for b in content]}\n")
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        _bridge_log(f"tool_result: id={block.tool_use_id}, is_error={block.is_error}\n")
                        send_notification("message", {
                            "type": "tool_result",
                            "tool_use_id": block.tool_use_id,
                            "content": block.content if hasattr(block, 'content') else None,
                            "is_error": block.is_error,
                        })
        elif isinstance(message, ResultMessage):
            result_params = {
                "type": "result",
                "session_id": message.session_id,
                "duration_ms": message.duration_ms,
                "is_error": message.is_error,
                "num_turns": message.num_turns,
                "total_cost_usd": message.total_cost_usd,
            }
            if message.usage:
                result_params["usage"] = message.usage
            if message.stop_reason:
                result_params["stop_reason"] = message.stop_reason
            send_notification("message", result_params)
        elif isinstance(message, SystemMessage):
            _bridge_log(f"SystemMessage: subtype={message.subtype}, data={message.data}\n")
            send_notification("message", {
                "type": "system",
                "subtype": message.subtype,
                "data": message.data,
            })

    async def interrupt(self, id: int) -> None:
        """Interrupt current query and drain pending messages."""
        has_task = self.current_task is not None and not self.current_task.done()
        _bridge_log(f"interrupt: called, has_task={has_task}\n")
        # Always signal the SDK to interrupt — even if our task tracking thinks
        # it's done, the underlying claude CLI process may still be running.
        if self.client:
            _bridge_log(f"interrupt: sending to SDK\n")
            try:
                await self.client.interrupt()
            except Exception as e:
                _bridge_log(f"interrupt: SDK interrupt error: {e}\n")
        if has_task:
            self.interrupted = True  # Signal to query() that we were interrupted
            # Cancel any pending permission requests
            for pid, future in list(self.pending_permissions.items()):
                if not future.done():
                    future.set_result(False)  # Deny pending permissions
            self.pending_permissions.clear()
            # Don't cancel task - let it drain naturally after interrupt
            # Wait for the task to complete (it should finish quickly after interrupt)
            _bridge_log(f"interrupt: waiting for task to drain\n")
            try:
                await asyncio.wait_for(self.current_task, timeout=5.0)
            except asyncio.TimeoutError:
                _bridge_log(f"interrupt: drain timeout, cancelling\n")
                self.current_task.cancel()
                try:
                    await self.current_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                _bridge_log(f"interrupt: drain error: {e}\n")
                send_result(id, {"status": "interrupted"})

    async def cancel_pending(self, id: int) -> None:
        """Cancel all pending permission/question requests."""
        count = 0
        for pid, future in list(self.pending_permissions.items()):
            if not future.done():
                future.set_result(False)  # Deny
                count += 1
        self.pending_permissions.clear()

        for qid, future in list(self.pending_questions.items()):
            if not future.done():
                future.set_result(None)  # Cancel
                count += 1
        self.pending_questions.clear()

        _bridge_log(f"cancel_pending: cancelled {count} requests\n")
        send_result(id, {"status": "ok", "cancelled": count})

    # _on_notalone_inject removed - handled by global client in plugin

    async def inject_message(self, id: int, params: dict) -> None:
        """Inject a user message into the current conversation mid-query."""
        message = params.get("message", "")
        if not message:
            send_error(id, -32602, "Missing message parameter")
            return

        _bridge_log(f"inject_message: {message[:60]}...\n")
        # If no active query, queue the message to be sent when query ends
        if not self.query_id:
            _bridge_log(f"  no active query, queuing inject\n")
            self.pending_injects.append(message)
            send_result(id, {"status": "queued"})
            return

        # Try to inject immediately via client.query()
        try:
            await self.client.query(message)
            send_result(id, {"status": "ok"})
        except Exception as e:
            # If injection fails (e.g., query completed), queue it
            _bridge_log(f"  inject failed: {e}, queuing\n")
            self.pending_injects.append(message)
            send_result(id, {"status": "queued"})

    async def get_history(self, id: int) -> None:
        """Get conversation history from the SDK."""
        if not self.client:
            send_error(id, -32002, "Client not initialized")
            return

        try:
            # Try to access SDK's internal conversation state
            # The SDK stores messages internally for context
            messages = []

            # Check if client has a messages/history attribute
            if hasattr(self.client, '_messages'):
                messages = serialize(self.client._messages)
            elif hasattr(self.client, 'messages'):
                messages = serialize(self.client.messages)
            elif hasattr(self.client, 'conversation'):
                messages = serialize(self.client.conversation)
            else:
                # Fallback: return what we know
                send_result(id, {
                    "messages": [],
                    "note": "SDK conversation history not accessible via standard API"
                })
                return

            send_result(id, {"messages": messages})
        except Exception as e:
            send_error(id, -32000, f"Failed to get history: {str(e)}")

    # ─── Subsession signaling ────────────────────────────────────────────
    # Notification registration handled by MCP tools directly to daemon

    async def signal_subsession_complete(self, subsession_id: str = None, result_summary: str = None) -> dict:
        """Signal that a subsession has completed (direct socket to daemon)."""
        import socket
        from pathlib import Path

        if subsession_id is None:
            subsession_id = getattr(self, '_subsession_id', None)

        if not subsession_id:
            return {"error": "Not a subsession - no subsession_id available"}

        socket_path = str(Path.home() / ".notalone" / "notalone.sock")
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({
                "method": "signal_complete",
                "subsession_id": subsession_id,
                "result_summary": result_summary
            }) + "\n").encode())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk

            sock.close()
            resp = json.loads(data.decode().strip())
            success = resp.get("ok", False)
            _logger.info(f"Subsession {subsession_id} completed - signaled: {success}")
            return {
                "status": "signaled" if success else "failed",
                "subsession_id": subsession_id,
                "result_summary": result_summary
            }
        except Exception as e:
            _logger.error(f"Error signaling subsession complete: {e}")
            return {"error": str(e)}

    async def _ensure_terminal(self, cwd: str) -> TerminalManager:
        """Lazy-start the terminal if not running."""
        if self.terminal is None:
            loop = asyncio.get_running_loop()

            def on_output(text: str) -> None:
                # Called from background thread — schedule on event loop
                try:
                    loop.call_soon_threadsafe(
                        lambda: send_notification("terminal_output", {"text": text})
                    )
                except Exception:
                    pass

            self.terminal = TerminalManager(
                cwd=cwd,
                on_output=on_output,
            )
            self.terminal.start()
            _bridge_log("Terminal started\n")
        return self.terminal

    async def terminal_start(self, id: int, params: dict) -> None:
        """Start the terminal shell."""
        cwd = params.get("cwd", self.cwd or os.getcwd())
        await self._ensure_terminal(cwd)
        send_result(id, {"status": "started"})

    async def terminal_stop(self, id: int, params: dict) -> None:
        """Stop the terminal shell."""
        if self.terminal:
            self.terminal.stop()
            self.terminal = None
            _bridge_log("Terminal stopped\n")
        send_result(id, {"status": "stopped"})

    async def terminal_write(self, id: int, params: dict) -> None:
        """Write text to the terminal."""
        cwd = params.get("cwd", self.cwd or os.getcwd())
        term = await self._ensure_terminal(cwd)
        text = params.get("text", "")
        if text:
            term.write(text)
        send_result(id, {"status": "ok"})

    async def terminal_read(self, id: int, params: dict) -> None:
        """Read recent terminal output."""
        if self.terminal:
            max_chars = params.get("max_chars", 10000)
            text = self.terminal.read(max_chars)
            send_result(id, {"status": "ok", "text": text})
        else:
            send_result(id, {"status": "ok", "text": ""})

    async def terminal_resize(self, id: int, params: dict) -> None:
        """Resize the terminal."""
        if self.terminal:
            rows = params.get("rows", 30)
            cols = params.get("cols", 120)
            self.terminal.resize(rows, cols)
        send_result(id, {"status": "ok"})

    async def shutdown(self, id: int) -> None:
        """Shutdown the bridge."""
        if self.terminal:
            self.terminal.stop()
            self.terminal = None
        if self.client:
            await self.client.disconnect()

        send_result(id, {"status": "shutdown"})
        self.running = False

    async def run(self) -> None:
        """Main loop - read JSON-RPC from stdin."""
        # Immediate startup log
        sys.stderr.write("=== BRIDGE STARTING WITH 1GB BUFFER ===\n")
        sys.stderr.flush()

        loop = asyncio.get_running_loop()
        # Increase buffer limit to 1GB to handle large tool results (e.g., images)
        buffer_limit = 1024 * 1024 * 1024
        reader = asyncio.StreamReader(limit=buffer_limit)
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        # Log to verify this code is running
        _bridge_log("Bridge started with 1GB buffer limit\n")
        sys.stderr.write(f"=== StreamReader limit set to {reader._limit} bytes ===\n")
        sys.stderr.flush()

        while self.running:
            try:
                line = await reader.readline()
                if not line:
                    break
                req = json.loads(line.decode())
                # Don't await - handle requests concurrently so permission responses
                # can be processed while a query is running
                asyncio.create_task(self.handle_request(req))
            except asyncio.LimitOverrunError as e:
                send_error(None, -32000, f"Message too large: {e}")
                sys.stderr.write(f"!!! LIMIT OVERRUN ERROR: {e} !!!\n")
                sys.stderr.write(f"!!! Reader limit: {reader._limit} !!!\n")
                sys.stderr.write(f"!!! Error type: {type(e).__name__} !!!\n")
                sys.stderr.flush()
                # Try to consume the rest of the line to recover
                try:
                    await reader.readuntil(b'\n')
                except (asyncio.LimitOverrunError, asyncio.IncompleteReadError, ValueError):
                    pass
            except json.JSONDecodeError as e:
                send_error(None, -32700, f"Parse error: {e}")
                sys.stderr.write(f"Fatal error in message reader: Failed to decode JSON: {e}\n")
                sys.stderr.flush()
            except Exception as e:
                send_error(None, -32000, f"Internal error: {e}")
                sys.stderr.write(f"!!! EXCEPTION TYPE: {type(e).__module__}.{type(e).__name__} !!!\n")
                sys.stderr.write(f"!!! EXCEPTION MESSAGE: {e} !!!\n")
                sys.stderr.write(f"!!! READER LIMIT: {reader._limit} !!!\n")
                sys.stderr.write(f"Fatal error in message reader: {e}\n")
                sys.stderr.flush()
                import traceback
                traceback.print_exc(file=sys.stderr)


async def main():
    bridge = Bridge()
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
