"""Shared JSON-RPC helpers for bridge subprocesses. Sends to stdout."""
import json
import sys
from typing import Any, Optional


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def send_error(id: Optional[int], code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


def send_result(id: int, result: Any) -> None:
    send({"jsonrpc": "2.0", "id": id, "result": result})


def send_notification(method: str, params: Any) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})
