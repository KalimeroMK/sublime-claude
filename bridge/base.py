"""Base bridge class with shared JSON-RPC loop and utilities.

All backend bridges (Claude, OpenAI, Codex, Copilot) should inherit from
BaseBridge and implement the abstract handle_request method.
"""
import asyncio
import json
import sys
from abc import abstractmethod
from typing import Any, Optional

from rpc_helpers import send_error


class BaseBridge:
    """Base class for JSON-RPC bridges communicating over stdio."""

    def __init__(self, name: str = "bridge", buffer_limit: int = 1024 * 1024 * 1024):
        self.name = name
        self.buffer_limit = buffer_limit
        self.running = True
        self.current_task: Optional[asyncio.Task] = None
        self.interrupted = False

    @abstractmethod
    async def handle_request(self, req: dict) -> None:
        """Handle a single JSON-RPC request.

        Subclasses must implement this method to dispatch requests
        to backend-specific handlers.
        """
        raise NotImplementedError

    async def run(self) -> None:
        """Main loop — read JSON-RPC from stdin and dispatch requests."""
        sys.stderr.write(f"=== {self.name.upper()} STARTING ===\n")
        sys.stderr.flush()

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader(limit=self.buffer_limit, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        sys.stderr.write(f"=== StreamReader limit set to {self.buffer_limit} bytes ===\n")
        sys.stderr.flush()

        while self.running:
            try:
                line = await reader.readline()
                if not line:
                    break
                req = json.loads(line.decode())
                # Don't await — handle requests concurrently so responses
                # can be processed while a long-running query is active
                asyncio.create_task(self._safe_handle(req))
            except asyncio.LimitOverrunError as e:
                send_error(None, -32000, f"Message too large: {e}")
                sys.stderr.write(f"!!! LIMIT OVERRUN: {e} !!!\n")
                sys.stderr.flush()
                try:
                    await reader.readuntil(b'\n')
                except Exception:
                    pass
            except json.JSONDecodeError as e:
                send_error(None, -32700, f"Parse error: {e}")
                sys.stderr.write(f"JSON decode error: {e}\n")
                sys.stderr.flush()
            except Exception as e:
                send_error(None, -32000, f"Internal error: {e}")
                sys.stderr.write(f"Fatal error in reader: {e}\n")
                sys.stderr.flush()

    async def _safe_handle(self, req: dict) -> None:
        """Wrap handle_request with error handling."""
        try:
            await self.handle_request(req)
        except Exception as e:
            req_id = req.get("id")
            send_error(req_id, -32000, str(e))
            sys.stderr.write(f"Request handler error: {e}\n")
            sys.stderr.flush()

    def serialize(self, obj: Any) -> Any:
        """Serialize dataclass objects to JSON-compatible dicts."""
        from dataclasses import asdict, is_dataclass
        if is_dataclass(obj) and not isinstance(obj, type):
            return {k: self.serialize(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [self.serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.serialize(v) for k, v in obj.items()}
        return obj


async def run_bridge(bridge_class: type, **kwargs) -> None:
    """Instantiate and run a bridge class.

    Usage:
        if __name__ == "__main__":
            asyncio.run(run_bridge(MyBridge))
    """
    bridge = bridge_class(**kwargs)
    await bridge.run()
