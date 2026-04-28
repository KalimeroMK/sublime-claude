#!/usr/bin/env python3
"""
Bridge for OpenAI-compatible APIs (Ollama, vLLM, OpenAI, Groq, etc.).
Communicates via JSON-RPC over stdio, talks to API via HTTP.
Supports function calling for tools: Read, Write, Edit, Bash, Glob, Grep.
Auto-detects Ollama and uses its native /api/chat endpoint for better tool support.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from typing import Any, Optional

# Import shared utilities
sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__)) + "/.."))
from settings import load_project_settings
from logger import get_bridge_logger

_logger = get_bridge_logger()

from rpc_helpers import send, send_error, send_result, send_notification
from base import BaseBridge, run_bridge


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file (create or overwrite).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Replace old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["command", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for text in files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
]

OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file (create or overwrite).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Replace old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["command", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for text in files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

def _tool_Read(args: dict, cwd: str) -> str:
    path = args.get("file_path", "")
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def _tool_Write(args: dict, cwd: str) -> str:
    path = args.get("file_path", "")
    content = args.get("content", "")
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File written successfully: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _tool_Edit(args: dict, cwd: str) -> str:
    path = args.get("file_path", "")
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if old not in text:
            return f"Error: old_string not found in {path}"
        text = text.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return f"File edited successfully: {path}"
    except Exception as e:
        return f"Error editing file: {e}"


def _tool_Bash(args: dict, cwd: str) -> str:
    command = args.get("command", "")
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if result.returncode != 0:
            return f"Exit code {result.returncode}:\n{output}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"
    except Exception as e:
        return f"Error running command: {e}"


def _tool_Glob(args: dict, cwd: str) -> str:
    import glob as glob_module
    pattern = args.get("pattern", "")
    if not os.path.isabs(pattern):
        pattern = os.path.join(cwd, pattern)
    try:
        files = glob_module.glob(pattern, recursive=True)
        return "\n".join(files[:50]) or "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def _tool_Grep(args: dict, cwd: str) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", cwd)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            matches = []
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    matches.append(f"{i}: {line.rstrip()}")
            return "\n".join(matches[:50]) or "(no matches)"
        else:
            matches = []
            for root, _dirs, files in os.walk(path):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line):
                                    matches.append(f"{fpath}:{i}: {line.rstrip()}")
                                    if len(matches) >= 50:
                                        break
                        if len(matches) >= 50:
                            break
                    except Exception:
                        pass
                if len(matches) >= 50:
                    break
            return "\n".join(matches) or "(no matches)"
    except Exception as e:
        return f"Error: {e}"


TOOL_DISPATCH = {
    "Read": _tool_Read,
    "Write": _tool_Write,
    "Edit": _tool_Edit,
    "Bash": _tool_Bash,
    "Glob": _tool_Glob,
    "Grep": _tool_Grep,
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_ctx():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_post(url: str, payload: dict, headers: dict) -> dict:
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, context=_make_ctx(), timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class Bridge(BaseBridge):
    def __init__(self):
        super().__init__(name="openai")
        self.base_url: str = ""
        self.api_key: str = ""
        self.model: str = ""
        self.session_id: str = ""
        self._messages: list[dict] = []
        self._system_prompt: str = ""
        self._cwd: str = "."
        self._allowed_tools: list[str] = []
        self._is_ollama = False

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
            elif method == "set_model":
                model = params.get("model")
                if model:
                    self.model = model
                send_result(id, {"ok": True})
            else:
                send_error(id, -32601, f"Method not found: {method}")
        except Exception as e:
            send_error(id, -32000, str(e))

    async def initialize(self, id: int, params: dict) -> None:
        self._cwd = params.get("cwd", ".")
        settings = load_project_settings(self._cwd)

        self._allowed_tools = params.get("allowed_tools", [])

        self.base_url = (settings.get("openai_base_url")
                         or os.environ.get("OPENAI_BASE_URL", "")
                         or os.environ.get("CLAUDE_OPENAI_BASE_URL", "")
                         or params.get("openai_base_url", ""))
        self.api_key = (settings.get("openai_api_key")
                        or os.environ.get("OPENAI_API_KEY", "")
                        or os.environ.get("CLAUDE_OPENAI_API_KEY", "")
                        or params.get("openai_api_key", ""))
        self.model = (settings.get("openai_model")
                      or os.environ.get("OPENAI_MODEL", "")
                      or os.environ.get("CLAUDE_OPENAI_MODEL", "")
                      or params.get("openai_model", ""))

        self.base_url = self.base_url.rstrip("/")

        if params.get("model"):
            self.model = params["model"]

        if params.get("resume"):
            self.session_id = params["resume"]
        else:
            self.session_id = str(uuid.uuid4())

        self._system_prompt = params.get("system_prompt", "")
        self._messages = []
        if self._system_prompt:
            self._messages.append({"role": "system", "content": self._system_prompt})

        # Auto-detect Ollama by checking /api/tags
        self._is_ollama = False
        if self.base_url:
            try:
                import urllib.request
                req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
                with urllib.request.urlopen(req, context=_make_ctx(), timeout=5) as resp:
                    _ = resp.read()
                    self._is_ollama = True
                    _logger.info("Detected Ollama server, using native /api/chat")
            except Exception:
                _logger.info("Using OpenAI-compatible /v1/chat/completions endpoint")

        if not self.base_url:
            send_error(id, -32000, "openai_base_url not configured.")
            return
        if not self.model:
            send_error(id, -32000, "openai_model not configured.")
            return

        _logger.info(f"OpenAI bridge initialized: base_url={self.base_url}, model={self.model}, ollama={self._is_ollama}")
        send_result(id, {
            "status": "initialized",
            "session_id": self.session_id,
            "mcp_servers": [],
            "agents": [],
        })

    async def query(self, id: int, params: dict) -> None:
        prompt = params.get("prompt", "")
        if not prompt:
            send_error(id, -32602, "Missing prompt")
            return

        self.interrupted = False
        self._messages.append({"role": "user", "content": prompt})

        async def run_query():
            try:
                if self._is_ollama:
                    await self._chat_ollama(id)
                else:
                    await self._chat_openai(id)
            except Exception as e:
                _logger.error(f"Query error: {e}")
                import traceback
                _logger.error(traceback.format_exc())
                send_error(id, -32000, f"Query failed: {str(e)}")

        self.current_task = asyncio.create_task(run_query())
        try:
            await self.current_task
        except asyncio.CancelledError:
            send_result(id, {"status": "interrupted"})

    async def _chat_ollama(self, id: int) -> None:
        """Chat using Ollama native /api/chat endpoint."""
        url = f"{self.base_url}/api/chat"
        tools = self._filter_tools(OLLAMA_TOOLS)

        max_turns = 25
        for turn in range(max_turns):
            if self.interrupted:
                break

            payload = {
                "model": self.model,
                "messages": self._messages,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools

            headers = {"Content-Type": "application/json"}
            body = _http_post(url, payload, headers)

            message = body.get("message", {})
            content = message.get("content", "")

            if content:
                send_notification("message", {"type": "text_delta", "text": content})

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                self._messages.append({"role": "assistant", "content": content})
                break

            # Emit tool_use blocks
            for tc in tool_calls:
                func = tc.get("function", {})
                send_notification("message", {
                    "type": "tool_use",
                    "id": tc.get("id", "call_" + uuid.uuid4().hex[:8]),
                    "name": func.get("name", ""),
                    "input": func.get("arguments", {}),
                    "background": False,
                })

            # Build assistant message with tool_calls for history
            assistant_msg = {
                "role": "assistant",
                "content": content,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.get("id", "call_" + uuid.uuid4().hex[:8]),
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"].get("arguments", {}),
                        },
                    }
                    for tc in tool_calls
                ]
            self._messages.append(assistant_msg)

            # Execute tools
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                executor = TOOL_DISPATCH.get(name)
                if executor:
                    result_text = executor(args, self._cwd)
                else:
                    result_text = f"Unknown tool: {name}"

                is_error = result_text.startswith("Error") or result_text.startswith("Exit code")
                tc_id = tc.get("id", "call_" + uuid.uuid4().hex[:8])

                send_notification("message", {
                    "type": "tool_result",
                    "tool_use_id": tc_id,
                    "content": result_text,
                    "is_error": is_error,
                })

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })

        # Send completion
        send_notification("message", {
            "type": "result",
            "session_id": self.session_id,
            "duration_ms": 0,
            "is_error": False,
            "num_turns": turn + 1,
            "total_cost_usd": 0.0,
            "usage": {},
            "stop_reason": "stop",
        })
        send_result(id, {"status": "complete"})

    async def _chat_openai(self, id: int) -> None:
        """Chat using OpenAI-compatible /v1/chat/completions endpoint."""
        url = f"{self.base_url}/v1/chat/completions"
        tools = self._filter_tools(OPENAI_TOOLS)

        max_turns = 25
        for turn in range(max_turns):
            if self.interrupted:
                break

            payload = {
                "model": self.model,
                "messages": self._messages,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            body = _http_post(url, payload, headers)

            choice = body["choices"][0]
            message = choice["message"]
            content = message.get("content", "")

            if content:
                send_notification("message", {"type": "text_delta", "text": content})

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                self._messages.append({"role": "assistant", "content": content})
                break

            for tc in tool_calls:
                func = tc["function"]
                send_notification("message", {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": func["name"],
                    "input": json.loads(func["arguments"]),
                    "background": False,
                })

            assistant_msg = {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            }
            self._messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc["function"]
                name = func["name"]
                args = json.loads(func["arguments"])

                executor = TOOL_DISPATCH.get(name)
                if executor:
                    result_text = executor(args, self._cwd)
                else:
                    result_text = f"Unknown tool: {name}"

                is_error = result_text.startswith("Error") or result_text.startswith("Exit code")

                send_notification("message", {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_text,
                    "is_error": is_error,
                })

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })

        usage = body.get("usage", {})
        send_notification("message", {
            "type": "result",
            "session_id": self.session_id,
            "duration_ms": 0,
            "is_error": False,
            "num_turns": turn + 1,
            "total_cost_usd": 0.0,
            "usage": usage,
            "stop_reason": choice.get("finish_reason"),
        })
        send_result(id, {"status": "complete"})

    def _filter_tools(self, tools: list) -> list:
        if not self._allowed_tools:
            return tools
        allowed = set(self._allowed_tools)
        return [t for t in tools if t["function"]["name"] in allowed]

    async def interrupt(self, id: int) -> None:
        self.interrupted = True
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
        send_result(id, {"status": "interrupted"})

    async def shutdown(self, id: int) -> None:
        self.running = False
        await self.interrupt(id)
        send_result(id, {"status": "shutdown"})

if __name__ == "__main__":
    asyncio.run(run_bridge(Bridge))
