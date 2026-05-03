"""PTY-based terminal manager for persistent shell sessions."""

import asyncio
import os
import pty
import select
import struct
import fcntl
import termios
import threading
import re
from typing import Callable, Optional


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain display."""
    return _ANSI_RE.sub("", text)


class TerminalManager:
    """Manages a persistent PTY shell session.

    Runs the user's shell in a pseudo-terminal so interactive commands
    (git log, htop, npm init) work properly. Output is buffered and can
    be streamed to a callback for real-time display.
    """

    def __init__(
        self,
        shell: Optional[str] = None,
        cwd: Optional[str] = None,
        cols: int = 120,
        rows: int = 30,
        on_output: Optional[Callable[[str], None]] = None,
        max_buffer_chars: int = 50000,
    ):
        self.shell = shell or os.environ.get("SHELL", "/bin/bash")
        self.cwd = cwd or os.getcwd()
        self.cols = cols
        self.rows = rows
        self._on_output = on_output
        self._max_buffer_chars = max_buffer_chars

        self._master_fd: Optional[int] = None
        self._pid: Optional[int] = None
        self._output_buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Fork a shell process inside a PTY."""
        self._master_fd, slave_fd = pty.openpty()
        self._pid = os.fork()
        if self._pid == 0:
            # Child process: become session leader, wire stdio to PTY slave
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if self._master_fd is not None:
                os.close(self._master_fd)
            os.close(slave_fd)
            os.chdir(self.cwd)
            os.execv(self.shell, [self.shell, "-l"])
        else:
            os.close(slave_fd)
            self._set_winsize(self.rows, self.cols)
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

    def stop(self) -> None:
        """Kill the shell and clean up file descriptors."""
        self._running = False
        if self._pid:
            try:
                os.kill(self._pid, 9)
            except ProcessLookupError:
                pass
            self._pid = None
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        # Drain remaining buffered output
        with self._buffer_lock:
            self._output_buffer.clear()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def write(self, data: str) -> None:
        """Write text into the terminal (e.g. user keystrokes or commands)."""
        if self._master_fd is not None and self._running:
            try:
                os.write(self._master_fd, data.encode("utf-8", "replace"))
            except OSError:
                pass

    def read(self, max_chars: Optional[int] = None) -> str:
        """Read the most recent terminal output (tail of buffer)."""
        limit = max_chars or self._max_buffer_chars
        with self._buffer_lock:
            text = "".join(self._output_buffer)
        if len(text) > limit:
            text = text[-limit:]
        return text

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resize(self, rows: int, cols: int) -> None:
        """Update PTY window size (affects programs like vim, htop)."""
        self.rows = rows
        self.cols = cols
        if self._master_fd is not None:
            self._set_winsize(rows, cols)

    def _set_winsize(self, rows: int, cols: int) -> None:
        size = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Background reader
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        """Background thread: read from PTY master and buffer output."""
        while self._running:
            try:
                ready, _, _ = select.select([self._master_fd], [], [], 0.1)
                if not ready:
                    continue
                data = os.read(self._master_fd, 8192)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                with self._buffer_lock:
                    self._output_buffer.append(text)
                    # Trim buffer to max size
                    buf = "".join(self._output_buffer)
                    if len(buf) > self._max_buffer_chars * 2:
                        buf = buf[-self._max_buffer_chars:]
                        self._output_buffer = [buf]
                # Stream to callback if provided
                if self._on_output:
                    try:
                        self._on_output(text)
                    except Exception:
                        pass
            except (OSError, ValueError):
                break
        # EOF or error — signal closure
        if self._on_output:
            try:
                self._on_output("\n[Terminal closed]\n")
            except Exception:
                pass
        self._running = False
