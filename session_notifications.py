"""Bridge notification dispatcher for Session."""
import os
import time

import sublime


class NotificationHandler:
    """Dispatches JSON-RPC notifications from the bridge process."""

    def __init__(self, session):
        self._s = session

    def handle(self, method: str, params: dict) -> None:
        """Dispatch a notification from the bridge."""
        s = self._s
        # Track stream activity for stall detection
        s.last_activity = time.time()
        s._heartbeat.reset_stall_warning()

        if method == "permission_request":
            s._handle_permission_request(params)
            return
        if method == "question_request":
            s._handle_question_request(params)
            return
        if method == "plan_mode_enter":
            s._handle_plan_mode_enter(params)
            return
        if method == "plan_mode_exit":
            s._handle_plan_mode_exit(params)
            return
        if method == "plan_response":
            # Response handled via pending_plan_approvals in bridge
            return
        if method == "queued_inject":
            self._handle_queued_inject(params)
            return
        if method == "terminal_output":
            s._terminal.handle_output(params.get("text", ""))
            return
        if method == "notification_wake":
            self._handle_notification_wake(params)
            return
        if method != "message":
            return

        t = params.get("type")
        if t == "tool_use":
            self._handle_tool_use(params)
        elif t == "tool_result":
            self._handle_tool_result(params)
        elif t in ("text_delta", "text"):
            s.output.text(params.get("text", ""))
        elif t == "turn_usage":
            self._handle_turn_usage(params)
        elif t == "result":
            self._handle_result(params)
        elif t == "system":
            self._handle_system(params)

    def _handle_queued_inject(self, params: dict) -> None:
        message = params.get("message", "")
        if message:
            self._s._inject_pending = False
            self._s.working = True
            self._s.query(message)

    def _handle_notification_wake(self, params: dict) -> None:
        s = self._s
        wake_prompt = params.get("wake_prompt", "")
        display_message = params.get("display_message", "")

        if display_message:
            user_message = display_message
        else:
            first_line = wake_prompt.split("\n")[0].strip() if wake_prompt else ""
            user_message = first_line if first_line else "🔔 Notification received"

        if s.working:
            def start_wake_query():
                if not s.working:
                    try:
                        s.query(wake_prompt, display_prompt=user_message)
                    except Exception as e:
                        print(f"[Claude] deferred wake query error: {e}")
                else:
                    sublime.set_timeout(start_wake_query, 500)
            sublime.set_timeout(start_wake_query, 500)
            return

        try:
            s.query(wake_prompt, display_prompt=user_message)
        except Exception as e:
            print(f"[Claude] wake query error: {e}")

    def _handle_tool_use(self, params: dict) -> None:
        s = self._s
        name = params.get("name", "")
        tool_input = params.get("input", {})
        background = params.get("background", False)
        tool_id = params.get("id")

        if not name or not name.strip():
            return

        # Snapshot file content before Write/Edit for diff preview / undo
        snapshot = None
        if name in ("Write", "Edit"):
            file_path = tool_input.get("file_path", "")
            if file_path:
                try:
                    if os.path.exists(file_path):
                        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                            snapshot = f.read()
                    else:
                        snapshot = ""
                except Exception:
                    pass

        if background:
            s.output.tool(name, tool_input, tool_id=tool_id, background=True, snapshot=snapshot)
            s._update_status_bar()
            return

        # Foreground: mark previous tool done, take over as current
        if s.current_tool and s.current_tool.strip():
            s.output.tool_done(s.current_tool)
        s.current_tool = name
        s.output.tool(name, tool_input, tool_id=tool_id, background=False, snapshot=snapshot)

    def _handle_tool_result(self, params: dict) -> None:
        s = self._s
        tool_use_id = params.get("tool_use_id")
        content = params.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(c) for c in content)
        if len(content) > 10000:
            content = content[:10000]
        is_error = params.get("is_error")

        matched = s.output.find_tool_by_id(tool_use_id) if tool_use_id else None
        was_background = matched is not None and matched.status == "background"
        tool_name = matched.name if matched else s.current_tool

        if not tool_name or not str(tool_name).strip():
            s.current_tool = None
            return

        if was_background:
            return

        # Compute diff for Write/Edit tools
        if tool_name in ("Write", "Edit") and matched:
            file_path = matched.tool_input.get("file_path", "")
            snapshot = getattr(matched, "snapshot", None)
            if file_path and snapshot is not None:
                try:
                    import difflib
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        current = f.read()
                    old_lines = snapshot.splitlines(keepends=True)
                    new_lines = current.splitlines(keepends=True)
                    if old_lines and not old_lines[-1].endswith("\n"):
                        old_lines[-1] += "\n"
                    if new_lines and not new_lines[-1].endswith("\n"):
                        new_lines[-1] += "\n"
                    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=file_path, tofile=file_path, lineterm=""))
                    if diff:
                        matched.diff = "".join(diff)
                except Exception:
                    pass

        if is_error:
            s.output.tool_error(tool_name, content, tool_id=tool_use_id)
        else:
            s.output.tool_done(tool_name, content, tool_id=tool_use_id)

        if tool_name == s.current_tool:
            s.current_tool = None
        s._update_status_bar()

    def _handle_turn_usage(self, params: dict) -> None:
        s = self._s
        usage = params.get("usage", {})
        if usage:
            s.context_usage = usage
            s._update_status_bar()

    def _handle_result(self, params: dict) -> None:
        s = self._s
        if params.get("session_id"):
            s.session_id = params["session_id"]
            s._save_session()
        cost = params.get("total_cost_usd") or 0
        s.total_cost += cost
        dur = params.get("duration_ms", 0) / 1000
        usage = params.get("usage")
        if usage:
            s.context_usage = usage
            hist_entry = {
                "q": s.query_count,
                "t": time.time(),
                "in": usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
                "out": usage.get("output_tokens", 0),
            }
            s._usage_history.append(hist_entry)
            if len(s._usage_history) > 100:
                s._usage_history = s._usage_history[-100:]
        print(f"[Claude] [{dur:.1f}s, ${cost:.4f}]" if cost else f"[Claude] [{dur:.1f}s]")
        if usage:
            print(f"[Claude] usage: {usage}")
        s.output.meta(dur, cost, usage=usage)
        s._update_status_bar()

    def _handle_system(self, params: dict) -> None:
        s = self._s
        subtype = params.get("subtype", "")
        data = params.get("data", {})

        if subtype == "init":
            if data.get("model"):
                s.sdk_model = data["model"]
                s._update_status_bar()
        elif subtype == "compact_boundary":
            s.context_usage = None
            s._update_status_bar()
            s._inject_retain_midquery()
        elif subtype == "task_started":
            task_id = data.get("task_id", "")
            tool_use_id = data.get("tool_use_id", "")
            if task_id and tool_use_id:
                s._task_tool_map[task_id] = tool_use_id
        elif subtype == "task_updated":
            task_id = data.get("task_id", "")
            patch = data.get("patch", {})
            if patch.get("is_backgrounded"):
                tool_use_id = s._task_tool_map.get(task_id)
                if tool_use_id:
                    tool = s.output.find_tool_by_id(tool_use_id)
                    if tool and tool.status != "background":
                        from .output import BACKGROUND
                        tool.status = BACKGROUND
                        if s.output._is_in_current(tool):
                            s.output._render_current()
                        else:
                            s.output._patch_tool_symbol(tool, "pending")
        elif subtype == "task_notification":
            task_id = data.get("task_id", "")
            status = data.get("status", "")
            tool_use_id = s._task_tool_map.pop(task_id, None)
            if tool_use_id and status == "completed":
                tool = s.output.find_tool_by_id(tool_use_id)
                if tool and tool.status == "background":
                    from .output import DONE
                    old_status = tool.status
                    tool.status = DONE
                    s.output._patch_tool_symbol(tool, old_status)
                    output = ""
                    output_file = data.get("output_file", "")
                    if output_file:
                        try:
                            with open(output_file, "r") as f:
                                output = f.read().strip()
                        except Exception:
                            pass
                    summary = data.get("summary", "")
                    wake_prompt = f"<task-notification>{summary}\n{output}</task-notification>" if output else f"<task-notification>{summary}</task-notification>"
                    if s.working:
                        s._queued_prompts.append(wake_prompt)
                    else:
                        s.query(wake_prompt, display_prompt=f"⚙ {summary}", silent=True)
