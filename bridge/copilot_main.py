#!/usr/bin/env python3
"""
Bridge between Sublime Text and GitHub Copilot SDK.
Translates our JSON-RPC protocol to Copilot's event-driven SDK.
"""
import asyncio
import json
import os
import sys
import time
from typing import Any, Optional

# Pre-import event types (avoid per-event import overhead)
try:
    from copilot.generated.session_events import SessionEventType
except ImportError:
    SessionEventType = None


from rpc_helpers import send, send_error, send_result, send_notification

def log(msg):
    sys.stderr.write(f"[copilot-bridge] {msg}\n")
    sys.stderr.flush()


class CopilotBridge:
    def __init__(self):
        self.client = None
        self.session = None
        self.running = True
        self.session_id = None
        self._query_req_id = None
        self._turn_start_time = 0
        self._session_config = {}
        self.permission_counter = 0
        self.pending_permissions = {}
        self.pending_questions = {}
        self._got_first_delta = False

    async def handle_request(self, req: dict) -> None:
        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")

        try:
            if method == "initialize":
                await self.handle_initialize(req_id, params)
            elif method == "query":
                await self.handle_query(req_id, params)
            elif method == "interrupt":
                await self.handle_interrupt(req_id)
            elif method == "permission_response":
                await self.handle_permission_response(req_id, params)
            elif method == "question_response":
                await self.handle_question_response(req_id, params)
            elif method == "shutdown":
                await self.handle_shutdown(req_id)
            else:
                send_error(req_id, -32601, f"Unknown method: {method}")
        except Exception as e:
            log(f"Error handling {method}: {e}")
            send_error(req_id, -32000, str(e))

    async def handle_initialize(self, req_id: int, params: dict) -> None:
        from copilot import CopilotClient, PermissionHandler

        cwd = params.get("cwd", os.getcwd())
        model = params.get("model", "gpt-5")
        system_prompt = params.get("system_prompt", "")
        view_id = params.get("view_id", "")
        resume_id = params.get("resume")

        # Map Claude model names to Copilot models
        model_map = {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
        model = model_map.get(model, model)

        self.client = CopilotClient()
        await self.client.start()

        # Build session config
        config = {
            "model": model,
            "streaming": True,
            "on_permission_request": self._handle_permission,
            "working_directory": cwd,
        }
        if system_prompt:
            config["system_message"] = {"content": system_prompt}
        if resume_id:
            config["session_id"] = resume_id

        # MCP server config
        mcp_server_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "mcp", "server.py"
        )
        if os.path.exists(mcp_server_path):
            args = [mcp_server_path]
            if view_id:
                args.append(f"--view-id={view_id}")
            config["mcp_servers"] = {
                "sublime": {"type": "stdio", "command": sys.executable, "args": args, "tools": []}
            }

        self._session_config = config
        log(f"Session config: mcp_servers={'sublime' in config.get('mcp_servers', {})}, model={model}")
        self.session = await self.client.create_session(config)
        self.session.on(self._on_event)
        self.session_id = getattr(self.session, 'session_id', None) or f"copilot-{view_id}"

        log(f"Initialized: model={model}, cwd={cwd}, session_id={self.session_id}")
        send_result(req_id, {
            "session_id": self.session_id,
            "mcp_servers": ["sublime"] if os.path.exists(mcp_server_path) else [],
            "agents": [],
        })

    async def handle_query(self, req_id: int, params: dict) -> None:
        if not self.session:
            send_error(req_id, -32000, "Not initialized")
            return

        prompt = params.get("prompt", "")
        self._query_req_id = req_id
        self._turn_start_time = time.time()
        self._got_first_delta = False

        message_opts = {"prompt": prompt}
        # Images — copilot only supports file attachments, not inline base64
        images = params.get("images", [])
        if images:
            attachments = []
            for img in images:
                if isinstance(img, dict) and img.get("path"):
                    attachments.append({"type": "file", "path": img["path"]})
                elif isinstance(img, str) and img.startswith("/"):
                    attachments.append({"type": "file", "path": img})
                elif isinstance(img, dict) and img.get("data"):
                    # Save base64 to temp file for copilot
                    import base64, tempfile
                    mime = img.get("mime_type", "image/png")
                    ext = mime.split("/")[-1] if "/" in mime else "png"
                    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                        f.write(base64.b64decode(img["data"]))
                        attachments.append({"type": "file", "path": f.name})
            if attachments:
                message_opts["attachments"] = attachments

        await self.session.send(message_opts)

    async def handle_interrupt(self, req_id: int) -> None:
        if self.session:
            try:
                self.session.abort()
            except Exception as e:
                log(f"Interrupt error: {e}")
        send_result(req_id, {"status": "interrupted"})

    async def handle_permission_response(self, req_id: int, params: dict) -> None:
        perm_id = params.get("id")
        allow = params.get("allow", False)
        future = self.pending_permissions.pop(perm_id, None)
        if future and not future.done():
            from copilot import PermissionRequestResult
            future.set_result(PermissionRequestResult(approved=allow))
        send_result(req_id, {"ok": True})

    async def handle_question_response(self, req_id: int, params: dict) -> None:
        q_id = params.get("id")
        answers = params.get("answers")
        future = self.pending_questions.pop(q_id, None)
        if future and not future.done():
            future.set_result(answers)
        send_result(req_id, {"ok": True})

    async def handle_shutdown(self, req_id: int) -> None:
        self.running = False
        if self.session:
            try:
                await self.session.destroy()
            except Exception:
                pass
        if self.client:
            try:
                await self.client.stop()
            except Exception:
                pass
        send_result(req_id, {"ok": True})

    async def _handle_permission(self, request) -> Any:
        """Permission callback — send to Sublime, wait for response."""
        from copilot import PermissionRequestResult

        self.permission_counter += 1
        perm_id = self.permission_counter
        future = asyncio.get_running_loop().create_future()
        self.pending_permissions[perm_id] = future

        # Extract tool info
        tool_name = getattr(request, 'tool_name', '') or str(request)
        tool_input = getattr(request, 'tool_input', {}) or {}

        send_notification("permission_request", {
            "id": perm_id,
            "tool": tool_name,
            "input": tool_input if isinstance(tool_input, dict) else str(tool_input),
        })

        result = await future
        return result

    def _on_event(self, event) -> None:
        """Handle Copilot session events."""
        etype = event.type
        data = event.data

        if etype == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            text = getattr(data, 'delta_content', '') or ''
            if text:
                # Strip leading newlines from first delta of a turn
                if not self._got_first_delta:
                    text = text.lstrip('\n')
                    self._got_first_delta = True
                if text:
                    send_notification("message", {"type": "text_delta", "text": text})

        elif etype == SessionEventType.ASSISTANT_MESSAGE:
            # Text already streamed via ASSISTANT_MESSAGE_DELTA — skip
            pass

        elif etype == SessionEventType.ASSISTANT_REASONING_DELTA:
            text = getattr(data, 'delta_content', '') or ''
            if text:
                send_notification("message", {"type": "thinking", "thinking": text})

        elif etype == SessionEventType.TOOL_EXECUTION_START:
            name = getattr(data, 'tool_name', '') or getattr(data, 'name', '') or 'tool'
            send_notification("message", {"type": "tool_use", "name": name, "input": {}})

        elif etype == SessionEventType.TOOL_EXECUTION_COMPLETE:
            name = getattr(data, 'tool_name', '') or getattr(data, 'name', '') or 'tool'
            is_error = getattr(data, 'is_error', False)
            content = getattr(data, 'result', '') or ''
            send_notification("message", {
                "type": "tool_result",
                "tool_use_id": name,
                "content": str(content)[:500],
                "is_error": is_error,
            })

        elif etype == SessionEventType.SESSION_IDLE:
            if self._query_req_id is not None:
                dur = (time.time() - self._turn_start_time) * 1000
                send_notification("message", {
                    "type": "result",
                    "session_id": self.session_id,
                    "duration_ms": dur,
                    "is_error": False,
                    "num_turns": 1,
                    "total_cost_usd": 0,
                })
                send_result(self._query_req_id, {"status": "complete"})
                self._query_req_id = None

        elif etype == SessionEventType.SESSION_ERROR:
            error = getattr(data, 'message', '') or str(data)
            log(f"Session error: {error}")

        elif etype == SessionEventType.ASSISTANT_USAGE:
            usage = {}
            if hasattr(data, 'input_tokens'):
                usage["input_tokens"] = data.input_tokens
            if hasattr(data, 'output_tokens'):
                usage["output_tokens"] = data.output_tokens
            if usage:
                send_notification("message", {"type": "turn_usage", "usage": usage})


async def main():
    bridge = CopilotBridge()
    log("Bridge started")

    # Read JSON-RPC from stdin (1GB limit to match Claude bridge)
    reader = asyncio.StreamReader(limit=1024 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while bridge.running:
        try:
            line = await reader.readline()
            if not line:
                break
            req = json.loads(line.decode().strip())
            await bridge.handle_request(req)
        except json.JSONDecodeError:
            continue
        except Exception as e:
            log(f"Main loop error: {e}")

    log("Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
