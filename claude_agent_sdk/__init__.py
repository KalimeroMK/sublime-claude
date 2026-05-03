"""
Compatibility wrapper for claude_agent_sdk using Claude Code CLI
(--output-format=stream-json --input-format=stream-json).

This replaces the private claude-agent-sdk Python package which is no longer
available. It wraps the official `claude` CLI binary and converts its JSON
stream events into the same dataclass objects the original SDK produced.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, List, Optional, Union


# ---------------------------------------------------------------------------
# Dataclasses (same interface as original SDK)
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    text: str


@dataclass
class ThinkingBlock:
    thinking: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: Any
    is_error: bool = False


@dataclass
class AssistantMessage:
    content: list
    usage: Optional[dict] = None


@dataclass
class UserMessage:
    content: list


@dataclass
class SystemMessage:
    subtype: str
    data: Optional[dict] = None


@dataclass
class ResultMessage:
    session_id: str
    duration_ms: int
    is_error: bool
    num_turns: int
    total_cost_usd: float
    usage: Optional[dict] = None
    stop_reason: Optional[str] = None


@dataclass
class StreamEvent:
    event: dict


@dataclass
class PermissionResultAllow:
    updated_input: dict


@dataclass
class PermissionResultDeny:
    message: str


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass
class ClaudeAgentOptions:
    allowed_tools: list = field(default_factory=list)
    permission_mode: str = "default"
    cwd: Optional[str] = None
    system_prompt: str = ""
    can_use_tool: Optional[Callable] = None
    resume: Optional[str] = None
    fork_session: bool = False
    setting_sources: list = field(default_factory=list)
    max_buffer_size: int = 100 * 1024 * 1024
    include_partial_messages: bool = True
    cli_path: str = "claude"
    model: Optional[str] = None
    betas: Optional[list] = None
    effort: Optional[str] = None
    sandbox: Optional[dict] = None
    mcp_servers: Optional[dict] = None
    agents: Optional[dict] = None
    plugins: Optional[list] = None
    extra_args: Optional[dict] = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ClaudeSDKClient:
    def __init__(self, options: ClaudeAgentOptions):
        self.options = options
        self._session_id: Optional[str] = options.resume
        self._message_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_file: Optional[Any] = None
        self._interrupted = False
        self._model: Optional[str] = options.model
        self._log_path = "/tmp/claude_bridge.log"

    def _log(self, msg: str) -> None:
        try:
            with open(self._log_path, "a") as f:
                f.write(f"[sdk_wrapper] {msg}\n")
        except Exception:
            pass

    async def connect(self) -> None:
        """Verify CLI availability and set up session."""
        proc = await asyncio.create_subprocess_exec(
            self.options.cli_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI not available: {stderr.decode()}")
        self._log(f"claude CLI OK: {stdout.decode().strip()}")
        # Honor session-id from extra_args (set by bridge for fresh sessions)
        if not self._session_id and self.options.extra_args:
            sid = self.options.extra_args.get("session-id")
            if sid:
                self._session_id = sid
        if not self._session_id:
            self._session_id = str(uuid.uuid4())
        self._log(f"session_id={self._session_id}")

    async def set_model(self, model: str) -> None:
        self._model = model

    async def query(self, prompt: Union[str, AsyncIterator]) -> None:
        """Write the prompt directly to the persistent CLI stdin."""
        await self._ensure_process()

        if isinstance(prompt, str):
            content = [{"type": "text", "text": prompt}]
        else:
            # async generator of messages (multimodal)
            messages = []
            async for msg in prompt:
                messages.append(msg)
            first = messages[0]
            if isinstance(first, dict) and "message" in first:
                msg = first["message"]
                content = msg.get("content", [])
            else:
                content = [{"type": "text", "text": str(messages)}]

        input_msg = {
            "type": "user",
            "message": {"role": "user", "content": content},
        }
        input_line = json.dumps(input_msg) + "\n"
        self._log(f"input={input_line[:200]}")
        self._proc.stdin.write(input_line.encode())
        await self._proc.stdin.drain()

    async def receive_messages(self) -> AsyncIterator[Any]:
        """Yield SDK message objects from the persistent CLI output queue."""
        while True:
            msg = await self._message_queue.get()
            if msg is None:
                break
            yield msg

    async def _ensure_process(self) -> None:
        """Start the persistent CLI process if not already running."""
        proc_alive = self._proc is not None and self._proc.returncode is None
        reader_alive = self._reader_task is not None and not self._reader_task.done()

        if proc_alive and reader_alive:
            return  # Process is healthy

        self._interrupted = False

        # Drain stale queue messages (e.g. None sentinel from dead reader)
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Clean up old process
        if self._proc:
            try:
                if self._proc.returncode is None:
                    self._proc.kill()
            except ProcessLookupError:
                pass
            self._proc = None

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._stderr_file:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

        cmd = [
            self.options.cli_path,
            "-p",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]

        if self.options.permission_mode:
            cmd.extend(["--permission-mode", self.options.permission_mode])

        if self.options.resume:
            cmd.extend(["--resume", self._session_id])
        elif self._session_id:
            cmd.extend(["--session-id", self._session_id])
        else:
            self._session_id = str(uuid.uuid4())
            cmd.extend(["--session-id", self._session_id])

        if self.options.fork_session:
            cmd.append("--fork-session")

        if self._model:
            cmd.extend(["--model", self._model])

        if self.options.allowed_tools:
            tools_str = ",".join(self.options.allowed_tools)
            cmd.extend(["--allowed-tools", tools_str])

        cwd = self.options.cwd or os.getcwd()

        if self.options.system_prompt:
            cmd.extend(["--append-system-prompt", self.options.system_prompt])

        if self.options.effort:
            cmd.extend(["--effort", self.options.effort])

        if self.options.betas:
            for beta in self.options.betas:
                cmd.extend(["--betas", beta])

        if self.options.extra_args:
            for key, val in self.options.extra_args.items():
                arg_name = f"--{key}"
                if isinstance(val, list):
                    for v in val:
                        cmd.extend([arg_name, str(v)])
                else:
                    cmd.extend([arg_name, str(val)])

        if self.options.mcp_servers:
            mcp_path = f"/tmp/claude_mcp_servers_{self._session_id}.json"
            with open(mcp_path, "w") as f:
                json.dump({"mcpServers": self.options.mcp_servers}, f)
            cmd.extend(["--mcp-config", mcp_path])

        if self.options.agents:
            agents_json = json.dumps(self.options.agents)
            cmd.extend(["--agents", agents_json])

        if self.options.plugins:
            for plugin_dir in self.options.plugins:
                cmd.extend(["--plugin-dir", plugin_dir])

        self._log(f"cmd={cmd}")
        self._stderr_file = open(f"/tmp/claude_cli_stderr_{self._session_id}.log", "wb")
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self._stderr_file,
            cwd=cwd,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self) -> None:
        """Read JSON lines from stdout and enqueue SDK objects."""
        try:
            while True:
                if self._interrupted:
                    break
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue
                msg = self._convert_event(data)
                if msg:
                    await self._message_queue.put(msg)
        except Exception as e:
            self._log(f"read_stdout error: {e}")
            if not self._interrupted:
                await self._message_queue.put(SystemMessage("error", {"message": str(e)}))
        finally:
            await self._message_queue.put(None)
            if self._proc:
                try:
                    if self._proc.returncode is None:
                        self._proc.kill()
                except ProcessLookupError:
                    pass
                self._proc = None
            if self._stderr_file:
                try:
                    self._stderr_file.close()
                except Exception:
                    pass
                self._stderr_file = None

    def _convert_event(self, data: dict) -> Any:
        etype = data.get("type")

        if etype == "system":
            subtype = data.get("subtype", "")
            # Capture session_id from init
            if subtype == "init" and data.get("session_id"):
                self._session_id = data["session_id"]
            return SystemMessage(subtype, data)

        if etype == "stream_event":
            return StreamEvent(data.get("event", {}))

        if etype == "assistant":
            msg = data.get("message", {})
            content = []
            for block in msg.get("content", []):
                btype = block.get("type")
                if btype == "text":
                    content.append(TextBlock(text=block.get("text", "")))
                elif btype == "thinking":
                    content.append(ThinkingBlock(thinking=block.get("thinking", "")))
                elif btype == "tool_use":
                    content.append(ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                    ))
            usage = msg.get("usage")
            return AssistantMessage(content=content, usage=usage)

        if etype == "user":
            msg = data.get("message", {})
            content = []
            for block in msg.get("content", []):
                btype = block.get("type")
                if btype == "tool_result":
                    content.append(ToolResultBlock(
                        tool_use_id=block.get("tool_use_id", ""),
                        content=block.get("content"),
                        is_error=block.get("is_error", False),
                    ))
            return UserMessage(content=content)

        if etype == "result":
            # Update session_id from result if present
            if data.get("session_id"):
                self._session_id = data["session_id"]
            return ResultMessage(
                session_id=data.get("session_id", ""),
                duration_ms=data.get("duration_ms", 0),
                is_error=data.get("is_error", False),
                num_turns=data.get("num_turns", 0),
                total_cost_usd=data.get("total_cost_usd", 0.0),
                usage=data.get("usage"),
                stop_reason=data.get("stop_reason"),
            )

        return None

    async def interrupt(self) -> None:
        """Kill the current subprocess."""
        self._interrupted = True
        if self._proc:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    async def disconnect(self) -> None:
        """Clean up resources."""
        await self.interrupt()
