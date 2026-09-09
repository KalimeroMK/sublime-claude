"""MCP socket server for Sublime Text integration."""
import json
import os
import socket
import threading
import time

import sublime
import sublime_plugin

from .settings import load_profiles_and_checkpoints
from .constants import (
    MCP_SOCKET_PATH, USER_PROFILES_DIR, PROFILES_FILE,
    OUTPUT_VIEW_SETTING, ACTIVE_VIEW_SETTING,
)
from . import lsp_tools

SOCKET_PATH = MCP_SOCKET_PATH
USER_PROFILES_PATH = str(USER_PROFILES_DIR / PROFILES_FILE)

_server = None


def _get_project_profiles_path() -> str:
    """Get project-level profiles path."""
    window = sublime.active_window()
    if window and window.folders():
        return os.path.join(window.folders()[0], ".claude", "profiles.json")
    return ""


def _save_checkpoint(name: str, session_id: str, description: str, to_project: bool = True) -> bool:
    """Save a checkpoint to profiles.json."""
    if to_project:
        path = _get_project_profiles_path()
        if not path:
            return False
    else:
        path = USER_PROFILES_PATH

    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Load existing
    data = {"profiles": {}, "checkpoints": {}}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Claude MCP] Error loading checkpoint data: {e}")

    # Add checkpoint
    if "checkpoints" not in data:
        data["checkpoints"] = {}
    data["checkpoints"][name] = {
        "session_id": session_id,
        "description": description,
    }

    # Save
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Claude MCP] Error saving checkpoint: {e}")
        return False


def start():
    """Start the MCP socket server."""
    global _server
    if _server:
        return
    _server = MCPSocketServer()
    _server.start()


def stop():
    """Stop the MCP socket server."""
    global _server
    if _server:
        _server.stop()
        _server = None


class MCPSocketServer:
    """Unix socket server for MCP eval requests."""

    def __init__(self):
        self.socket = None
        self.running = False
        self.thread = None

    def start(self):
        """Start the server in a background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    def _run(self):
        """Server main loop."""
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass

        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(SOCKET_PATH)
        self.socket.listen(5)
        self.socket.settimeout(1.0)

        print(f"[Claude MCP] Listening on {SOCKET_PATH}")

        while self.running:
            try:
                conn, _ = self.socket.accept()
                self._handle_connection(conn)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Claude MCP] Error: {e}")

    def _handle_connection(self, conn: socket.socket):
        """Handle a single connection."""
        try:
            data = conn.recv(65536).decode()
            if not data:
                return

            request = json.loads(data.strip())
            code = request.get("code", "")
            tool = request.get("tool")
            view_id = request.get("view_id")  # Caller's view_id from mcp/server.py

            result = {"result": None, "error": None}
            done = threading.Event()

            def do_eval():
                try:
                    result["result"] = self._eval(code, tool, caller_view_id=view_id)
                    done.set()
                except Exception as e:
                    result["error"] = str(e)
                    done.set()

            sublime.set_timeout(do_eval, 0)
            timeout = 30
            done.wait(timeout=timeout)

            # Handle spawn_session wait - poll for initialization
            eval_result = result.get("result")
            if isinstance(eval_result, dict) and eval_result.get("_wait_for_init"):
                session = eval_result.pop("_session")
                prompt = eval_result.pop("_prompt")
                wait_for_completion = eval_result.pop("_wait_for_completion", False)
                eval_result.pop("_wait_for_init")

                # Wait for initialization (in this background thread, not main thread)
                import time
                max_wait = 30
                start = time.time()
                while not session.initialized and time.time() - start < max_wait:
                    time.sleep(0.1)

                if not session.initialized:
                    eval_result["error"] = "Session failed to initialize within 30 seconds"
                else:
                    # Send the prompt from main thread
                    def send_prompt():
                        session.query(prompt)
                    sublime.set_timeout(send_prompt, 0)

                    # Optionally wait for completion
                    if wait_for_completion:
                        start = time.time()
                        while session.working and time.time() - start < max_wait:
                            time.sleep(0.1)
                        if session.working:
                            eval_result["warning"] = "Session still processing after 30 seconds"

                    eval_result["working"] = session.working
                    eval_result["initialized"] = True

            # Handle terminal_run wait - blocking capture with PTY terminal
            eval_result = result.get("result")
            if isinstance(eval_result, dict) and eval_result.get("_wait_terminal"):
                from .terminal.terminal import Terminal
                _tag = eval_result.pop("_wait_tag")
                _cmd = eval_result.pop("_wait_cmd")
                _secs = eval_result.pop("_wait_secs")
                _wid = eval_result.pop("_wait_window_id", None)
                eval_result.pop("_wait_terminal")

                # Get terminal or open a new one
                _terminal = Terminal.from_tag(_tag)
                _opened_new = _terminal is None
                if _opened_new:
                    def _do_open():
                        for _w in sublime.windows():
                            if _w.id() == _wid:
                                _w.run_command("claude_terminal_open", {"tag": _tag})
                                return
                        sublime.active_window().run_command("claude_terminal_open", {"tag": _tag})
                    sublime.set_timeout(_do_open, 0)

                    _dl = time.time() + 5.0
                    while time.time() < _dl:
                        _terminal = Terminal.from_tag(_tag)
                        if _terminal:
                            break
                        time.sleep(0.2)

                if not _terminal:
                    result["result"] = {"error": "Terminal failed to open"}
                else:
                    if _opened_new:
                        time.sleep(3.5)  # shell startup

                    _terminal.start_capture()
                    _terminal.send_string(_cmd)
                    _timed_out = not _terminal._capture_event.wait(timeout=_secs)
                    _output, _timed_out = _terminal.stop_capture()
                    _suffix = "\n[timed out]" if _timed_out else ""
                    result["result"] = _output.strip() + _suffix if _output.strip() else "(no output)" + _suffix

            conn.sendall((json.dumps(result) + "\n").encode())

        except Exception as e:
            import traceback
            print(f"[Claude MCP] _handle_connection error: {e}\n{traceback.format_exc()}")
            try:
                conn.sendall((json.dumps({"error": str(e)}) + "\n").encode())
            except OSError:
                pass
        finally:
            conn.close()

    def _get_window(self):
        """Get the window for the calling session, falling back to active window."""
        # Cache per-eval invocation (caller_view_id doesn't change within one tool call)
        cached = getattr(self, '_cached_window', None)
        cached_vid = getattr(self, '_cached_window_vid', None)
        if cached and cached_vid == self._caller_view_id and cached.is_valid():
            return cached
        if self._caller_view_id:
            for w in sublime.windows():
                for v in w.views():
                    if v.id() == self._caller_view_id:
                        self._cached_window = w
                        self._cached_window_vid = self._caller_view_id
                        return w
        return sublime.active_window()

    def _eval(self, code: str, tool: str = None, caller_view_id: int = None):
        """Execute code in Sublime's context.

        Args:
            code: Python code to execute
            tool: Named tool to load and execute
            caller_view_id: View ID of the calling session (from MCP server)
        """
        # Store caller_view_id for _get_session_for_tool to use
        self._caller_view_id = caller_view_id

        # Load saved tool if specified
        if tool:
            window = self._get_window()
            if window and window.folders():
                tool_path = os.path.join(window.folders()[0], ".claude", "sublime_tools", f"{tool}.py")
                if os.path.exists(tool_path):
                    with open(tool_path, "r") as f:
                        code = f.read()
                else:
                    raise FileNotFoundError(f"Tool not found: {tool_path}")
            else:
                raise RuntimeError("No project folder open")

        exec_globals = {
            "sublime": sublime,
            "sublime_plugin": sublime_plugin,
            "get_open_files": self._get_open_files,
            "get_window_summary": self._get_window_summary,
            "find_file": self._find_file,
            "get_symbols": self._get_symbols,
            "goto_symbol": self._goto_symbol,
            "read_view": self._read_view,
            "terminal_run": self._terminal_run,
            "list_tools": self._list_tools,
            # Session tools
            "list_profiles": self._list_profiles,
            "list_personas": self._list_personas,
            "spawn_session": self._spawn_session,
            "send_to_session": self._send_to_session,
            "list_sessions": self._list_sessions,
            "read_session_output": self._read_session_output,
            "list_profile_docs": self._list_profile_docs,
            "read_profile_doc": self._read_profile_doc,
            # Terminal tools (embedded PTY)
            "terminal_list": self._terminal_list,
            "terminal_send": self._terminal_send,
            "terminal_read": self._terminal_read,
            "terminal_close": self._terminal_close,
            # Notification tools (notalone2)
            "register_notification": self._register_notification,
            "subscribe_to_service": self._subscribe_to_service,
            "signal_subsession_complete": self._signal_subsession_complete,
            "list_notifications": self._list_notifications,
            "discover_services": self._discover_services,
            # LSP tools
            "lsp_hover": lambda f, l, c: lsp_tools.hover(self._get_window(), f, l, c),
            "lsp_definition": lambda f, l, c: lsp_tools.definition(self._get_window(), f, l, c),
            "lsp_references": lambda f, l, c: lsp_tools.references(self._get_window(), f, l, c),
            "lsp_symbols": lambda f: lsp_tools.symbols(self._get_window(), f),
            "lsp_workspace_symbols": lambda q: lsp_tools.workspace_symbols(self._get_window(), q),
            "lsp_diagnostics": lambda f=None: lsp_tools.diagnostics(self._get_window(), f),
            "lsp_completion": lambda f, l, c, prefix="", detailed=False: lsp_tools.completion(
                self._get_window(), f, l, c, prefix, detailed),
            "lsp_signature_help": lambda f, l, c: lsp_tools.signature_help(
                self._get_window(), f, l, c),
            "lsp_type_definition": lambda f, l, c: lsp_tools.type_definition(
                self._get_window(), f, l, c),
            "lsp_implementation": lambda f, l, c: lsp_tools.implementation(
                self._get_window(), f, l, c),
            "lsp_call_hierarchy": lambda f, l, c, direction="incoming": lsp_tools.call_hierarchy(
                self._get_window(), f, l, c, direction),
            "lsp_inlay_hint": lambda f, s_, e: lsp_tools.inlay_hint(self._get_window(), f, s_, e),
            "lsp_rename": lambda f, l, c, new_name, apply=False: lsp_tools.rename(
                self._get_window(), f, l, c, new_name, apply),
            "lsp_code_action": lambda f, l, c, apply_index=None: lsp_tools.code_action(
                self._get_window(), f, l, c, apply_index),
        }

        # Add context variables
        window = self._get_window()
        exec_globals["cwd"] = window.folders()[0] if window and window.folders() else None
        exec_globals["AGENT_ID"] = str(caller_view_id) if caller_view_id else None

        # Handle return statements
        if "return " in code:
            lines = code.split("\n")
            new_lines = []
            for line in lines:
                stripped = line.lstrip()
                if stripped.startswith("return "):
                    indent = line[:len(line) - len(stripped)]
                    new_lines.append(f"{indent}__result__ = {stripped[7:]}")
                else:
                    new_lines.append(line)
            code = "__result__ = None\n" + "\n".join(new_lines)
        else:
            code = f"__result__ = None\n{code}"

        exec(code, exec_globals)
        return exec_globals.get("__result__")

    def _get_open_files(self) -> list:
        """Get list of open files."""
        window = self._get_window()
        if not window:
            return []
        return [v.file_name() for v in window.views() if v.file_name()]

    def _get_window_summary(self) -> dict:
        """Get summary of current window state (formatted for reduced context)."""
        window = self._get_window()
        if not window:
            return {"error": "No window"}

        # Build formatted output
        lines = []

        # Project folders
        folders = window.folders()
        if folders:
            lines.append(f"Project: {folders[0]}")
            for f in folders[1:]:
                lines.append(f"  + {f}")

        # Active file
        active_view = window.active_view()
        if active_view and active_view.file_name():
            row, col = active_view.rowcol(active_view.sel()[0].begin()) if active_view.sel() else (0, 0)
            lines.append(f"Active: {active_view.file_name()}:{row+1}:{col+1}")

        # Open files (compact list)
        all_views = window.views()
        open_files = [v.file_name() for v in all_views if v.file_name()]
        dirty_files = [v.file_name() for v in all_views if v.file_name() and v.is_dirty()]

        lines.append(f"Open files ({len(open_files)}):")
        for f in open_files[:20]:  # Limit to 20 files
            marker = " *" if f in dirty_files else ""
            lines.append(f"  • {os.path.basename(f)}{marker}")
        if len(open_files) > 20:
            lines.append(f"  ... and {len(open_files) - 20} more")

        return {"summary": "\n".join(lines), "open_count": len(open_files), "dirty_count": len(dirty_files)}

    def _find_file(self, query: str, pattern: str = None, limit: int = 20) -> list:
        """Fuzzy find files by name, optionally filtered by glob pattern."""
        import fnmatch

        window = self._get_window()
        if not window:
            return []

        folders = window.folders()
        if not folders:
            return []

        # Directories to skip
        skip_dirs = {'.git', 'node_modules', '__pycache__', 'venv', '.venv',
                     'env', '.env', 'dist', 'build', '.cache', '.tox'}

        all_files = []
        root_folder = folders[0]

        for folder in folders:
            for dirpath, dirnames, filenames in os.walk(folder):
                dirnames[:] = [d for d in dirnames
                               if not d.startswith('.') and d not in skip_dirs]

                for filename in filenames:
                    if filename.startswith('.'):
                        continue

                    full_path = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(full_path, root_folder)

                    # Apply pattern filter if provided
                    if pattern:
                        if '**' in pattern:
                            if not fnmatch.fnmatch(rel_path, pattern):
                                continue
                        elif not (fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern)):
                            continue

                    all_files.append(rel_path)

        if not all_files:
            return []

        query_lower = query.lower()

        # Score each file - fuzzy matching
        scored = []
        for path in all_files:
            filename = os.path.basename(path).lower()
            path_lower = path.lower()

            if filename == query_lower:
                scored.append((0, path))
            elif filename.startswith(query_lower):
                scored.append((1, path))
            elif query_lower in filename:
                scored.append((2, path))
            elif query_lower in path_lower:
                scored.append((3, path))
            else:
                idx = 0
                for char in query_lower:
                    idx = path_lower.find(char, idx)
                    if idx == -1:
                        break
                    idx += 1
                else:
                    scored.append((4, path))

        scored.sort(key=lambda x: (x[0], x[1]))
        return [path for _, path in scored[:limit]]

    def _get_symbols(self, query, file_path: str = None, limit: int = 10) -> dict:
        """Batch lookup symbols in project index.

        Args:
            query: Single symbol (str), comma-separated, or JSON array
            file_path: Optional file to limit search to
            limit: Max results per symbol (default 10)
        """
        window = self._get_window()
        if not window:
            return {"success": False, "error": "No window"}

        # Normalize query to list
        if isinstance(query, str):
            query = query.strip()
            if query.startswith('['):
                try:
                    symbols = json.loads(query)
                except json.JSONDecodeError:
                    symbols = [query]
            elif ',' in query:
                symbols = [s.strip() for s in query.split(',') if s.strip()]
            else:
                symbols = [query]
        elif isinstance(query, list):
            symbols = [str(s).strip() for s in query if str(s).strip()]
        else:
            symbols = []

        if not symbols:
            return {"success": False, "error": "No symbols provided"}

        # Collect and format results
        lines = []
        all_locations = []

        for sym in symbols:
            locations = window.lookup_symbol_in_index(sym)

            # Filter by file_path if provided
            if file_path:
                locations = [loc for loc in locations if loc[0] == file_path]

            if not locations:
                lines.append(f"'{sym}': not found")
                continue

            lines.append(f"'{sym}' ({len(locations)} matches):")
            for loc in locations[:limit] if limit > 0 else locations:
                fp, display_name, (row, col) = loc[0], loc[1], loc[2]
                lines.append(f"  • {os.path.basename(fp)}:{row}:{col} - {display_name}")
                all_locations.append({"symbol": sym, "file": fp, "row": row, "col": col})

            if len(locations) > limit:
                lines.append(f"  ... and {len(locations) - limit} more")

        return {"summary": "\n".join(lines), "locations": all_locations[:50]}

    def _list_tools(self) -> list:
        """List available saved tools."""
        window = self._get_window()
        if not window or not window.folders():
            return []

        tools_dir = os.path.join(window.folders()[0], ".claude", "sublime_tools")
        if not os.path.exists(tools_dir):
            return []

        tools = []
        for filename in os.listdir(tools_dir):
            if not filename.endswith('.py'):
                continue

            name = filename[:-3]  # strip .py
            tool_path = os.path.join(tools_dir, filename)

            # Extract docstring as description
            try:
                with open(tool_path, 'r') as f:
                    code = f.read()
                # Simple docstring extraction - first triple-quoted string
                desc = "No description"
                if code.startswith('"""'):
                    end = code.find('"""', 3)
                    if end > 0:
                        desc = code[3:end].strip()
                elif code.startswith("'''"):
                    end = code.find("'''", 3)
                    if end > 0:
                        desc = code[3:end].strip()

                tools.append({"name": name, "description": desc})
            except (ValueError, IndexError):
                tools.append({"name": name, "description": "No description"})

        return tools

    def _goto_symbol(self, query: str) -> dict:
        """Navigate to a symbol definition. Returns the symbol info or error."""
        window = self._get_window()
        if not window:
            return {"error": "No window"}

        locations = window.lookup_symbol_in_index(query)
        if not locations:
            return {"error": f"Symbol '{query}' not found"}

        # Use first match
        loc = locations[0]
        path, name, (row, col) = loc[0], loc[1], loc[2]
        view = window.open_file(f"{path}:{row}:{col}", sublime.ENCODED_POSITION)
        return {"file": path, "name": name, "row": row, "col": col}

    def _read_view(self, file_path: str = None, view_name: str = None, head: int = None, tail: int = None, grep: str = None, grep_i: str = None, max_chars: int = 50000) -> dict:
        """Read content from any view by file path or view name with head/tail/grep filtering.

        Args:
            max_chars: Maximum characters to return (default 50000). Use -1 for unlimited.
        """
        import os
        import re
        window = self._get_window()
        if not window:
            return {"error": "No window"}

        view = None
        identifier = None

        # Search by view name (for scratch buffers)
        if view_name:
            for v in window.views():
                if v.name() == view_name:
                    view = v
                    identifier = view_name
                    break
            if not view:
                return {"error": f"View not found: {view_name}"}

        # Search by file path
        elif file_path:
            # Resolve file path (handle relative paths)
            if not os.path.isabs(file_path):
                # Try relative to project folders
                for folder in window.folders():
                    full_path = os.path.join(folder, file_path)
                    if os.path.exists(full_path):
                        file_path = full_path
                        break

            # Normalize path
            file_path = os.path.normpath(file_path)
            identifier = file_path

            # Find existing view with this file
            for v in window.views():
                if v.file_name() and os.path.normpath(v.file_name()) == file_path:
                    view = v
                    break

            # If not found, try to open it (won't focus, just load)
            if not view:
                if os.path.exists(file_path):
                    view = window.open_file(file_path, sublime.TRANSIENT)
                    # Wait a bit for file to load
                    import time
                    max_wait = 2.0
                    start = time.time()
                    while view.is_loading() and time.time() - start < max_wait:
                        time.sleep(0.05)
                else:
                    return {"error": f"File not found: {file_path}"}

        else:
            return {"error": "Must provide either file_path or view_name"}

        if not view:
            return {"error": f"Could not open view for: {identifier}"}

        # Read content
        content = view.substr(sublime.Region(0, view.size()))
        all_lines = content.split('\n')
        original_line_count = len(all_lines)

        # Apply grep filter first
        if grep or grep_i:
            pattern = grep if grep else grep_i
            flags = re.IGNORECASE if grep_i else 0
            try:
                regex = re.compile(pattern, flags)
                all_lines = [line for line in all_lines if regex.search(line)]
            except re.error as e:
                return {"error": f"Invalid regex pattern: {e}"}

        # Apply head/tail filter
        if head is not None and tail is not None:
            return {"error": "Cannot specify both head and tail"}
        elif head is not None:
            all_lines = all_lines[:head]
        elif tail is not None:
            all_lines = all_lines[-tail:] if tail < len(all_lines) else all_lines

        content = '\n'.join(all_lines)

        # Truncate if content exceeds max_chars
        truncated = False
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        result = {
            "content": content,
            "size": len(content),
            "line_count": len(all_lines),
            "original_line_count": original_line_count,
            "truncated": truncated,
        }

        # Include identifier in response
        if file_path:
            result["file_path"] = file_path
        if view_name:
            result["view_name"] = view_name

        # Include filter info if applied
        if grep or grep_i:
            result["grep_pattern"] = grep if grep else grep_i
            result["grep_case_insensitive"] = bool(grep_i)
        if head is not None:
            result["head"] = head
        if tail is not None:
            result["tail"] = tail

        return result

    # ─── Session Spawn ────────────────────────────────────────────────────

    def _list_profiles(self) -> dict:
        """List available profiles and checkpoints (formatted)."""
        project_path = _get_project_profiles_path()
        profiles, checkpoints = load_profiles_and_checkpoints(project_path)

        lines = []
        profile_names = []
        checkpoint_names = []

        if profiles:
            lines.append("Profiles:")
            for name, config in profiles.items():
                model = config.get("model", "default")
                desc = config.get("description", "")
                desc_short = f" - {desc[:40]}..." if len(desc) > 40 else f" - {desc}" if desc else ""
                lines.append(f"  • {name} ({model}){desc_short}")
                profile_names.append(name)

        if checkpoints:
            lines.append("Checkpoints:")
            for name, config in checkpoints.items():
                desc = config.get("description", "")
                desc_short = f" - {desc[:40]}..." if len(desc) > 40 else f" - {desc}" if desc else ""
                lines.append(f"  • {name}{desc_short}")
                checkpoint_names.append(name)

        if not lines:
            lines.append("No profiles or checkpoints configured")

        return {"summary": "\n".join(lines), "profiles": profile_names, "checkpoints": checkpoint_names}

    def _list_personas(self) -> dict:
        """List available personas from the persona server."""
        from .persona_client import list_personas as _list_personas
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        persona_url = settings.get("persona_url", "http://localhost:5002/personas")
        personas = _list_personas(persona_url)
        if not personas:
            return {"error": "Failed to fetch personas or none available"}
        lines = []
        for p in personas:
            alias = p.get("alias", "?")
            pid = p.get("id", "?")
            locked = p.get("is_locked", False)
            locked_by = p.get("locked_by_session", "")
            tags = ", ".join(p.get("tags", []))
            status = f"🔒 {locked_by}" if locked else "available"
            line = f"  [{pid}] {alias} ({status})"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        if not lines:
            return {"summary": "No personas available", "personas": []}
        return {
            "summary": f"Personas ({len(lines)}):\n" + "\n".join(lines),
            "personas": [{"id": p.get("id"), "alias": p.get("alias"), "is_locked": p.get("is_locked", False)} for p in personas]
        }

    def _spawn_session(self, prompt: str, name: str = None, profile: str = None, checkpoint: str = None, persona_id: int = None, fork_current: bool = False, wait_for_completion: bool = False, backend: str = "claude", _caller_view_id: int = None) -> dict:
        """Spawn a new Claude session with the given prompt. Returns with _wait_for_init flag.

        Args:
            _caller_view_id: The view_id of the calling session. If provided, used as parent_view_id.
                             This ensures subsession signals go to the correct parent.
        """
        from .core import create_session, get_active_session
        import uuid

        window = self._get_window()
        if not window:
            return {"error": "No window"}

        project_path = _get_project_profiles_path()
        profiles, checkpoints = load_profiles_and_checkpoints(project_path)
        profile_config = None
        resume_id = None
        fork = False

        # Load profile config if specified
        if profile:
            if profile not in profiles:
                return {"error": f"Profile '{profile}' not found"}
            profile_config = profiles[profile].copy()
            profile_config["_name"] = profile  # Store name for status bar

        # Load persona config if specified (overrides profile)
        if persona_id:
            from .persona_client import get_persona
            settings = sublime.load_settings("ClaudeCode.sublime-settings")
            persona_url = settings.get("persona_url", "http://localhost:5002/personas")
            persona = get_persona(persona_id, persona_url)
            if not persona:
                return {"error": f"Failed to fetch persona {persona_id}"}
            # Get system_prompt from ability_version or persona top-level
            ability_version = persona.get("ability_version") or {}
            profile_config = {
                "model": ability_version.get("model") or "sonnet",
                "system_prompt": ability_version.get("system_prompt") or persona.get("system_prompt") or "",
            }
            if not name:
                name = persona.get("alias", f"persona-{persona_id}")

        # Fork from caller session if requested
        if fork_current:
            caller_session = sublime._claude_sessions.get(_caller_view_id) if _caller_view_id else None
            if not caller_session:
                caller_session = get_active_session(window)
            current_session = caller_session
            if current_session and current_session.session_id:
                # Session IDs aren't portable across backends — codex thread IDs
                # can't be resumed by the Claude bridge, etc. Only allow fork
                # within the same backend family (claude+deepseek share the Claude
                # bridge's local storage, but codex/copilot live in their own).
                same_family = current_session.backend == backend or (
                    current_session.backend in ("claude", "deepseek") and backend in ("claude", "deepseek")
                )
                if not same_family:
                    return {"error": f"Cannot fork {current_session.backend!r} session into {backend!r} backend; session IDs are not portable. Spawn fresh (fork_current=False)."}
                resume_id = current_session.session_id
                fork = True
            else:
                return {"error": "Cannot fork: current session has no session_id"}

        # Load checkpoint if specified (overrides fork_current)
        if checkpoint:
            if checkpoint not in checkpoints:
                return {"error": f"Checkpoint '{checkpoint}' not found"}
            resume_id = checkpoints[checkpoint].get("session_id")
            fork = True

        # Generate unique subsession ID for notalone2 completion tracking
        subsession_id = f"subsession-{uuid.uuid4().hex[:8]}"

        # Get parent view_id - prefer explicit _caller_view_id, fall back to inference
        if _caller_view_id:
            parent_view_id = _caller_view_id
        else:
            # Fall back to inferring from execution context (less reliable with multiple sessions)
            current_session, _ = self._get_session_for_tool()
            parent_view_id = current_session.output.view.id() if current_session and current_session.output.view else None

        # Prepare initial context for subsession
        initial_context = {
            "subsession_id": subsession_id,
            "parent_view_id": parent_view_id,
        }

        # Create new session with initial context
        print(f"[MCP spawn] backend={backend} fork_current={fork_current} "
              f"resume_id={resume_id!r} fork={fork} "
              f"profile={profile!r} checkpoint={checkpoint!r} persona_id={persona_id} "
              f"caller_view={_caller_view_id} subsession_id={subsession_id}")
        session = create_session(window, resume_id=resume_id, fork=fork, profile=profile_config, initial_context=initial_context, backend=backend)
        print(f"[MCP spawn] created view_id={session.output.view.id() if session.output and session.output.view else None} "
              f"backend={session.backend} prompt_preview={prompt[:80]!r}")
        if name:
            session.name = name
            session.output.set_name(name)

        view_id = session.output.view.id() if session.output.view else None

        # Return with flags for background thread to handle waiting
        return {
            "_wait_for_init": True,  # Signal to wait for initialization
            "_session": session,  # Session object for polling
            "_prompt": prompt,  # Prompt to send after init
            "_wait_for_completion": wait_for_completion,  # Whether to also wait for completion
            "spawned": True,
            "name": name or "(unnamed)",
            "view_id": view_id,
            "subsession_id": subsession_id,  # Return subsession_id for parent to track
            "profile": profile,
            "checkpoint": checkpoint,
        }

    def _send_to_session(self, view_id: int, prompt: str) -> dict:
        """Send a message to an existing session."""

        session = sublime._claude_sessions.get(view_id)
        if not session:
            return {"error": f"Session not found for view_id {view_id}"}

        if session.working:
            return {"error": "Session is busy", "view_id": view_id}

        if not session.initialized:
            return {"error": "Session not initialized", "view_id": view_id}

        session.query(prompt)
        return {
            "sent": True,
            "view_id": view_id,
            "name": session.name or "(unnamed)",
        }

    def _list_sessions(self) -> dict:
        """List subsessions only (spawned via spawn_session)."""
        caller_id = self._caller_view_id
        sessions = []
        lines = []
        for view_id, session in sublime._claude_sessions.items():
            # Skip the calling session itself
            if view_id == caller_id:
                continue
            # Only show subsessions (spawned sessions have a parent_view_id)
            if not getattr(session, 'parent_view_id', None):
                continue
            status = "⏳" if session.working else "✓"
            cost = f"${session.total_cost:.4f}" if session.total_cost else ""
            name = session.name or "(unnamed)"
            lines.append(f"{status} [{view_id}] {name} ({session.query_count} queries) {cost}")
            sessions.append({"view_id": view_id, "name": name, "working": session.working})

        if not lines:
            return {"summary": "No subsessions", "sessions": []}
        return {"summary": "\n".join(lines), "sessions": sessions, "count": len(sessions)}

    def _read_session_output(self, view_id: int, lines: int = None, max_chars: int = 30000) -> dict:
        """Read conversation output from a session's view.

        Args:
            lines: Limit to last N lines
            max_chars: Maximum characters to return (default 30000). Use -1 for unlimited.
                       Smart truncation preserves message boundaries.
        """
        # Debug: log all session view_ids
        all_view_ids = list(sublime._claude_sessions.keys())
        print(f"[Claude] read_session_output: looking for {view_id}, _sessions={id(sublime._claude_sessions)}, available: {all_view_ids}")

        session = sublime._claude_sessions.get(view_id)
        if not session:
            return {
                "error": f"Session not found for view_id {view_id}",
                "available_sessions": all_view_ids,
            }

        if not session.output or not session.output.view:
            return {"error": "Session output view not found", "view_id": view_id}

        # Read text content from the output view
        view = session.output.view
        content = view.substr(sublime.Region(0, view.size()))

        # Optionally limit to last N lines
        if lines:
            all_lines = content.split('\n')
            if len(all_lines) > lines:
                content = '\n'.join(all_lines[-lines:])

        # Smart truncation: preserve message boundaries
        truncated = False
        skipped_messages = 0
        if max_chars > 0 and len(content) > max_chars:
            # Split by message separator (─── or blank lines between messages)
            import re
            # Messages are typically separated by horizontal lines or double newlines
            message_pattern = r'\n(?=───|╭|▸|⚠|✓|✗|\n\n)'
            parts = re.split(message_pattern, content)

            # Keep messages from the end until we exceed max_chars
            kept_parts = []
            total_len = 0
            for part in reversed(parts):
                if total_len + len(part) > max_chars and kept_parts:
                    skipped_messages += 1
                    continue
                kept_parts.insert(0, part)
                total_len += len(part) + 1  # +1 for separator

            content = '\n'.join(kept_parts)
            truncated = True

            # Add truncation notice at the beginning
            if skipped_messages > 0:
                content = f"[... {skipped_messages} earlier messages truncated ...]\n\n{content}"

        return {
            "view_id": view_id,
            "name": session.name or "(unnamed)",
            "working": session.working,
            "output": content,
            "line_count": content.count('\n') + 1 if content else 0,
            "truncated": truncated,
        }

    def _list_profile_docs(self) -> dict:
        """List documentation files available from current session's profile."""
        window = self._get_window()
        if not window:
            return {"error": "No active window"}

        # Get active session
        active_view_id = window.settings().get(ACTIVE_VIEW_SETTING)
        if not active_view_id or active_view_id not in sublime._claude_sessions:
            return {"error": "No active Claude session"}

        session = sublime._claude_sessions[active_view_id]

        if not session.profile_docs:
            return {
                "docs": [],
                "count": 0,
                "note": "No profile docs configured for this session"
            }

        return {
            "docs": session.profile_docs,
            "count": len(session.profile_docs),
            "profile": session.profile.get("description", "") if session.profile else ""
        }

    def _read_profile_doc(self, path: str) -> dict:
        """Read a documentation file from current session's profile docset."""
        window = self._get_window()
        if not window:
            return {"error": "No active window"}

        # Get active session
        active_view_id = window.settings().get(ACTIVE_VIEW_SETTING)
        if not active_view_id or active_view_id not in sublime._claude_sessions:
            return {"error": "No active Claude session"}

        session = sublime._claude_sessions[active_view_id]

        if path not in session.profile_docs:
            return {
                "error": f"File '{path}' not in profile docset",
                "available": session.profile_docs[:10],  # Show first 10
                "total": len(session.profile_docs)
            }

        # Read the file
        import os
        cwd = session._cwd()
        full_path = os.path.join(cwd, path)

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Ensure content is JSON-serializable by replacing problematic characters
            # This shouldn't be necessary since json.dumps handles escaping,
            # but we ensure clean UTF-8 just in case
            import json
            # Test that it can be serialized
            try:
                json.dumps(content)
            except (TypeError, ValueError) as e:
                return {"error": f"Content not JSON-serializable: {str(e)}"}

            return {
                "path": path,
                "content": content,
                "size": len(content),
            }
        except Exception as e:
            return {"error": f"Failed to read {path}: {str(e)}"}

    # ─── Terminal Tools (embedded PTY terminal) ───────────────────────────

    def _resolve_terminal_tag(self, tag: str = None, target_id: str = None, index: int = None) -> str:
        if index is not None:
            from .terminal.terminal import Terminal
            for t in Terminal.list_all():
                if getattr(t, 'index', None) == index:
                    return t.tag
        if target_id:
            return f"claude-agent-{target_id}"
        if tag:
            return tag
        window = self._get_window()
        active_view_id = window.settings().get(ACTIVE_VIEW_SETTING) if window else None
        if active_view_id and active_view_id in sublime._claude_sessions:
            return f"claude-agent-{active_view_id}"
        return f"claude-agent-{window.id() if window else 0}"

    def _terminal_list(self) -> list:
        from .terminal.terminal import Terminal
        import re
        result = []
        for t in Terminal.list_all():
            alive = t.is_alive()
            state = "exited"
            if alive:
                content = "".join(
                    "".join(t.screen.buffer[row][col].data
                            for col in sorted(t.screen.buffer[row].keys()))
                    for row in range(t.screen.lines)
                )
                last = next((l for l in reversed(content.splitlines()) if l.strip()), "")
                state = "idle" if re.search(r'[$%#>❯]\s*$', last) else "running"
            result.append({
                "index": getattr(t, 'index', None),
                "tag": t.tag,
                "view_id": t.view.id() if t.view else None,
                "title": t.view.name() if t.view else "(unnamed)",
                "state": state,
            })
        return result

    def _terminal_run(self, command: str, tag: str = None, wait: float = 30, target_id: str = None, index: int = None) -> dict:
        tag = self._resolve_terminal_tag(tag, target_id, index)
        cmd = command.rstrip('\n') + '\n'
        window = self._get_window()

        if not wait or wait <= 0:
            from .terminal.terminal import Terminal
            t = Terminal.from_tag(tag)
            if not t:
                if window:
                    window.run_command("claude_terminal_open", {"tag": tag})
                return {"sent": False, "info": "Terminal opening, retry in a moment"}
            t.send_string(cmd)
            return {"sent": True, "tag": tag}

        return {
            "_wait_terminal": True,
            "_wait_tag": tag,
            "_wait_cmd": cmd,
            "_wait_secs": float(wait),
            "_wait_window_id": window.id() if window else None,
        }

    def _terminal_send(self, text: str, tag: str = None, target_id: str = None, index: int = None) -> dict:
        from .terminal.terminal import Terminal
        tag = self._resolve_terminal_tag(tag, target_id, index)
        t = Terminal.from_tag(tag)
        if not t:
            return {"error": f"No terminal with tag '{tag}'"}
        t.send_string(text)
        return {"sent": True, "tag": tag}

    def _terminal_read(self, tag: str = None, lines: int = 100, target_id: str = None, index: int = None) -> dict:
        from .terminal.terminal import Terminal
        tag = self._resolve_terminal_tag(tag, target_id, index)
        t = Terminal.from_tag(tag)
        if not t:
            return {"error": f"No terminal with tag '{tag}'"}
        screen = t.screen
        content_lines = []
        for row in range(screen.lines):
            line_buf = screen.buffer.get(row, {})
            text = "".join(line_buf[col].data for col in sorted(line_buf.keys()))
            content_lines.append(text.rstrip())
        # drop trailing blank lines
        while content_lines and not content_lines[-1]:
            content_lines.pop()
        if lines and len(content_lines) > lines:
            content_lines = content_lines[-lines:]
        return "\n".join(content_lines) or "(empty)"

    def _terminal_close(self, tag: str = None, target_id: str = None, index: int = None) -> dict:
        from .terminal.terminal import Terminal
        tag = self._resolve_terminal_tag(tag, target_id, index)
        t = Terminal.from_tag(tag)
        if not t:
            return {"error": f"No terminal with tag '{tag}'"}
        t.close()
        return {"closed": True, "tag": tag}

    # ─── Session Helpers ──────────────────────────────────────────────────

    def _get_session_for_tool(self, session_id: int = None):
        """Get the Claude session for tool execution.

        Args:
            session_id: Optional specific session to use. If not provided,
                        uses claude_executing_view (set during internal tool execution).

        Returns:
            Tuple of (session, error_dict)
        """
        # If session_id provided, use it directly
        if session_id is not None:
            if session_id not in sublime._claude_sessions:
                available = list(sublime._claude_sessions.keys())
                return None, {
                    "error": f"Session not found: {session_id}",
                    "available_sessions": available
                }
            return sublime._claude_sessions[session_id], None

        # Try to find session from execution context
        window = self._get_window()
        if not window:
            return None, {"error": "No active window"}

        # First try caller_view_id from MCP request (most reliable for subsessions)
        view_id = getattr(self, '_caller_view_id', None)

        # Fall back to claude_executing_view (set during active query)
        if not view_id or view_id not in sublime._claude_sessions:
            view_id = window.settings().get("claude_executing_view")

        # Fall back to claude_active_view (last active session)
        if not view_id or view_id not in sublime._claude_sessions:
            view_id = window.settings().get(ACTIVE_VIEW_SETTING)

        # Last resort: if only one session exists, use it
        if not view_id or view_id not in sublime._claude_sessions:
            available = list(sublime._claude_sessions.keys())
            if len(available) == 1:
                view_id = available[0]
            else:
                return None, {
                    "error": "No session context available",
                    "hint": "Multiple sessions active. Focus the target session window.",
                    "available_sessions": available
                }

        return sublime._claude_sessions[view_id], None

    # ─── Notification Tools (notalone2) ────────────────────────────────
    # Uses notalone2 daemon for timer and subsession notifications

    def _register_notification(self, notification_type: str, params: dict, wake_prompt: str) -> dict:
        """Register a notification via notalone2 daemon (direct sync socket).

        Args:
            notification_type: 'timer', 'subsession_complete', or service type
            params: Type-specific parameters (e.g., {'seconds': 30} for timer)
            wake_prompt: Prompt to inject when notification fires

        Returns:
            {notification_id: str, status: "registered"}
        """
        session, error = self._get_session_for_tool()
        if error:
            return error

        # Get view_id for session_id
        view_id = session.output.view.id() if session.output and session.output.view else None
        if not view_id:
            return {"error": "Session has no view"}

        # Direct sync socket call to daemon (like hive does)
        import socket
        from pathlib import Path

        socket_path = str(Path.home() / ".notalone" / "notalone.sock")
        session_id = f"sublime.{view_id}"

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({
                "method": "register",
                "session_id": session_id,
                "type": notification_type,
                "params": params,
                "wake_prompt": wake_prompt
            }) + "\n").encode())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk

            sock.close()
            resp = json.loads(data.decode().strip())

            if resp.get("notification_id"):
                return {
                    "notification_id": resp["notification_id"],
                    "status": "registered",
                    "session_id": session_id
                }
            else:
                error_msg = resp.get("error", "Registration failed")
                # Fetch available services to help agent
                try:
                    services_resp = self._discover_services()
                    available = services_resp.get("services", {})
                    service_types = []
                    for svc, types in available.items():
                        for t in types:
                            service_types.append(f"{svc}.{t}")
                except (AttributeError, TypeError):
                    service_types = []

                return {
                    "error": error_msg,
                    "hint": f"Invalid type '{notification_type}'. Use discover_services() or try one of these.",
                    "builtin_types": ["timer", "subsession"],
                    "service_types": service_types
                }

        except FileNotFoundError:
            return {"error": "notalone2 daemon not running"}
        except Exception as e:
            return {"error": str(e)}

    def _subscribe_to_service(self, notification_type: str, params: dict, wake_prompt: str) -> dict:
        """Subscribe to a service - handles HTTP endpoints for channel services.

        For channel-type services with HTTP endpoints, POSTs to the endpoint first,
        then registers with notalone daemon.
        """
        import socket
        import urllib.request
        from pathlib import Path

        session, error = self._get_session_for_tool()
        if error:
            return error

        view_id = session.output.view.id() if session.output and session.output.view else None
        if not view_id:
            return {"error": "Session has no view"}

        socket_path = str(Path.home() / ".notalone" / "notalone.sock")
        session_id = f"sublime.{view_id}"

        # Get services list to check if this is a channel service
        services = []
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({"method": "services"}) + "\n").encode())
            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()
            services_data = json.loads(data.decode().strip())
            services = services_data.get("services", [])
        except Exception as e:
            print(f"[Claude MCP] Failed to get services: {e}")

        # Check if this is a channel service with an endpoint
        endpoint = None
        mode = None
        for svc in services:
            if svc.get("type") == notification_type:
                endpoint = svc.get("endpoint")
                mode = svc.get("mode")
                break

        # Only POST to endpoint for channel-mode services (not notify-mode)
        if endpoint and mode == "channel":
            try:
                # Include session_id in params for the endpoint
                post_data = dict(params) if params else {}
                post_data["session_id"] = session_id
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(post_data).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result = resp.read().decode()
                    print(f"[Claude MCP] Subscribed to {notification_type}: {result}")
            except Exception as e:
                print(f"[Claude MCP] Failed to POST to {notification_type}: {e}")
                return {"error": f"Failed to subscribe to service endpoint: {e}"}

        # Now register with notalone daemon
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({
                "method": "register",
                "session_id": session_id,
                "type": notification_type,
                "params": params,
                "wake_prompt": wake_prompt
            }) + "\n").encode())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk

            sock.close()
            resp = json.loads(data.decode().strip())

            if resp.get("notification_id"):
                return {
                    "notification_id": resp["notification_id"],
                    "status": "registered",
                    "session_id": session_id
                }
            else:
                return {"error": resp.get("error", "Registration failed")}

        except FileNotFoundError:
            return {"error": "notalone2 daemon not running"}
        except Exception as e:
            return {"error": str(e)}

    def _signal_subsession_complete(self, session_id: int = None, result_summary: str = None) -> dict:
        """Signal that this subsession has completed.

        Directly injects result_summary into parent session's prompt queue.

        Args:
            session_id: The subsession's view_id (required to identify caller)
            result_summary: Optional summary of what was accomplished

        Returns:
            {status: "signaled", subsession_id: str}
        """
        # Look up the calling session by session_id
        if session_id is None:
            return {"error": "session_id is required - pass your view_id from spawn result"}

        session = sublime._claude_sessions.get(session_id)
        if not session:
            available = list(sublime._claude_sessions.keys())
            return {"error": f"Session {session_id} not found", "available": available}

        # Get parent_view_id from this subsession
        parent_view_id = getattr(session, 'parent_view_id', None)
        subsession_id = getattr(session, 'subsession_id', None)

        if not parent_view_id:
            return {"error": f"Session {session_id} is not a subsession - no parent_view_id"}

        # Look up parent session directly in Sublime
        parent_session = sublime._claude_sessions.get(parent_view_id)
        if not parent_session:
            available = list(sublime._claude_sessions.keys())
            return {"error": f"Parent session not found: {parent_view_id}", "available": available}

        # Check if parent session is ready to receive
        if not parent_session.client:
            return {"error": f"Parent session {parent_view_id} has no client connection"}
        if not parent_session.initialized:
            return {"error": f"Parent session {parent_view_id} not initialized"}

        # Build wake prompt
        wake_prompt = f"✅ Subsession {subsession_id} completed"
        if result_summary:
            wake_prompt += f":\n{result_summary}"

        print(f"[Claude] signal_complete: queuing for parent {parent_view_id}: {wake_prompt[:50]}...")

        # Queue injection with retry if parent is busy
        def try_inject():
            if not parent_session.working:
                print(f"[Claude] signal_complete: injecting now to {parent_view_id}")
                parent_session.query(wake_prompt, display_prompt=f"📬 Subsession complete")
            else:
                # Parent still busy, retry in 500ms
                print(f"[Claude] signal_complete: parent {parent_view_id} busy, retrying...")
                sublime.set_timeout(try_inject, 500)

        sublime.set_timeout(try_inject, 0)

        return {"status": "signaled", "subsession_id": subsession_id, "parent_view_id": parent_view_id, "result_summary": result_summary}

    def _list_notifications(self) -> dict:
        """List active notifications for this session (direct sync socket)."""
        session, error = self._get_session_for_tool()
        if error:
            return {"notifications": [], "error": str(error)}

        # Get view_id for session_id
        view_id = session.output.view.id() if session.output and session.output.view else None
        if not view_id:
            return {"notifications": [], "error": "Session has no view"}

        # Direct sync socket call to daemon
        import socket
        from pathlib import Path

        socket_path = str(Path.home() / ".notalone" / "notalone.sock")
        session_id = f"sublime.{view_id}"

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({
                "method": "list",
                "session_id": session_id
            }) + "\n").encode())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk

            sock.close()
            resp = json.loads(data.decode().strip())
            return {"notifications": resp.get("notifications", [])}

        except FileNotFoundError:
            return {"notifications": [], "error": "notalone2 daemon not running"}
        except Exception as e:
            return {"notifications": [], "error": str(e)}

    def _discover_services(self) -> dict:
        """Discover available notification services from notalone2 daemon."""
        import socket
        import json
        from pathlib import Path

        # Builtin types with descriptions
        services = [
            {
                "type": "timer",
                "mode": "builtin",
                "description": "Wake after N seconds",
                "params": {"seconds": "int"}
            },
            {
                "type": "subsession",
                "mode": "builtin",
                "description": "Wake when subsession completes",
                "params": {"subsession_id": "string"}
            }
        ]

        # Query daemon for external services
        socket_path = str(Path.home() / ".notalone" / "notalone.sock")
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(socket_path)
            sock.sendall((json.dumps({"method": "services"}) + "\n").encode())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk

            sock.close()
            resp = json.loads(data.decode().strip())

            # Transform daemon response to flat list
            daemon_services = resp.get("services", {})

            # Handle both dict format and list format from daemon
            if isinstance(daemon_services, dict):
                # Format: {"service-name": {"type.name": {"mode": "...", "description": "..."}}}
                for service_name, types in daemon_services.items():
                    if not isinstance(types, dict):
                        continue
                    endpoint = types.get("_endpoint")
                    for type_name, type_info in types.items():
                        if type_name.startswith("_") or not isinstance(type_info, dict):
                            continue
                        entry = {
                            "type": type_name,
                            "mode": type_info.get("mode", "notify"),
                            "description": type_info.get("description", ""),
                            "service": service_name
                        }
                        if endpoint:
                            entry["endpoint"] = endpoint
                        services.append(entry)
            elif isinstance(daemon_services, list):
                # Already flat list format from daemon
                for svc in daemon_services:
                    if isinstance(svc, dict) and "type" in svc:
                        services.append(svc)

            return {"services": services}

        except FileNotFoundError:
            return {"services": services, "error": "notalone2 daemon not running"}
        except Exception as e:
            return {"services": services, "error": str(e)}

# ============================================================================
# Chatroom functions
# ============================================================================

def _chatroom_command(req: dict) -> dict:
    """Send chatroom command to daemon."""
    socket_path = str(Path.home() / ".notalone" / "notalone.sock")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(socket_path)
        sock.sendall((json.dumps(req) + "\n").encode())

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        sock.close()
        return json.loads(data.decode().strip())
    except Exception as e:
        return {"error": str(e)}


def chatroom_list() -> dict:
    """List all chatrooms."""
    return _chatroom_command({"method": "chatroom_list"})


def chatroom_rooms_for_session(view_id: int) -> dict:
    """List rooms a session has joined."""
    return _chatroom_command({
        "method": "chatroom_rooms_for_session",
        "session_id": f"sublime.{view_id}"
    })


def chatroom_create(room_id: str = None, name: str = None, max_chars: int = 1000, prompt_hint: int = 500) -> dict:
    """Create a new chatroom."""
    req = {"method": "chatroom_create", "max_chars": max_chars, "prompt_hint": prompt_hint}
    if room_id:
        req["room_id"] = room_id
    if name:
        req["name"] = name
    return _chatroom_command(req)


def chatroom_join(view_id: int, room_id: str, role: str = "agent") -> dict:
    """Join a chatroom."""
    return _chatroom_command({
        "method": "chatroom_join",
        "room_id": room_id,
        "session_id": f"sublime.{view_id}",
        "role": role
    })


def chatroom_leave(view_id: int, room_id: str) -> dict:
    """Leave a chatroom."""
    return _chatroom_command({
        "method": "chatroom_leave",
        "room_id": room_id,
        "session_id": f"sublime.{view_id}"
    })


def chatroom_post(view_id: int, room_id: str, content: str) -> dict:
    """Post a message to a chatroom."""
    return _chatroom_command({
        "method": "chatroom_post",
        "room_id": room_id,
        "session_id": f"sublime.{view_id}",
        "content": content
    })


def chatroom_history(room_id: str, limit: int = 50, before_id: int = 0) -> dict:
    """Get chat history."""
    req = {"method": "chatroom_history", "room_id": room_id, "limit": limit}
    if before_id > 0:
        req["before_id"] = before_id
    return _chatroom_command(req)


