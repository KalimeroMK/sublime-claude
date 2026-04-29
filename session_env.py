"""Session environment and configuration utilities.

Pure functions for Python detection, model resolution, session persistence,
and environment variable loading. No Sublime Text or Session dependencies.
"""
import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional


# ─── Python Detection Cache ───────────────────────────────────────────────────
_PYTHON_310_CACHE: Optional[str] = None


def _find_python_310_plus() -> str:
    """Auto-detect a Python 3.10+ interpreter for the bridge process.

    Searches in order:
    1. python3.13, python3.12, python3.11, python3.10 on PATH
    2. uv-managed python installations
    3. pyenv shims
    4. Fallback to 'python3' (bridge will fail with clear message if < 3.10)

    Result is cached after first successful detection.
    """
    global _PYTHON_310_CACHE
    if _PYTHON_310_CACHE is not None:
        return _PYTHON_310_CACHE

    # 1. Check explicit versioned binaries on PATH
    for binary in ("python3.13", "python3.12", "python3.11", "python3.10"):
        path = shutil.which(binary)
        if path:
            try:
                out = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if out.returncode == 0 and "3." in out.stdout:
                    _PYTHON_310_CACHE = path
                    return path
            except Exception:
                pass

    # 2. Check if python3 itself is 3.10+
    path = shutil.which("python3")
    if path:
        try:
            out = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                ver = out.stdout.strip() or out.stderr.strip()
                parts = ver.replace("Python ", "").split(".")
                if len(parts) >= 2:
                    try:
                        major, minor = int(parts[0]), int(parts[1])
                        if major >= 3 and minor >= 10:
                            _PYTHON_310_CACHE = path
                            return path
                    except ValueError:
                        pass
        except Exception:
            pass

    # 3. Search uv-managed python installations
    uv_home = os.path.expanduser("~/.local/share/uv/python")
    if os.path.isdir(uv_home):
        for entry in sorted(os.listdir(uv_home), reverse=True):
            if entry.startswith("cpython-3."):
                bin_dir = os.path.join(uv_home, entry, "bin")
                for binary in ("python3.13", "python3.12", "python3.11", "python3.10"):
                    candidate = os.path.join(bin_dir, binary)
                    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                        _PYTHON_310_CACHE = candidate
                        return candidate

    # 4. pyenv shims
    pyenv_shim = shutil.which("pyenv")
    if pyenv_shim:
        for binary in ("python3.13", "python3.12", "python3.11", "python3.10"):
            try:
                out = subprocess.run(
                    [pyenv_shim, "which", binary],
                    capture_output=True, text=True, timeout=5
                )
                if out.returncode == 0:
                    path = out.stdout.strip()
                    if path and os.path.isfile(path):
                        _PYTHON_310_CACHE = path
                        return path
            except Exception:
                pass

    _PYTHON_310_CACHE = "python3"
    return _PYTHON_310_CACHE


# ─── Model Resolution ─────────────────────────────────────────────────────────

_CONTEXT_LIMITS = {
    "@400k": 400000,
    "@200k": 200000,
}

_MODEL_CONTEXT_LIMITS = {
    # Claude models
    "claude-opus-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-haiku-4": 200000,
    "opus": 200000,
    "sonnet": 200000,
    "haiku": 200000,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3-5-sonnet": 200000,
    # OpenAI models
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "o3-mini": 200000,
    "o1": 200000,
    "o1-mini": 128000,
    # Ollama models (typical)
    "qwen2.5": 128000,
    "llama3.1": 128000,
    "llama3.2": 128000,
    "mistral": 32000,
    "phi4": 16000,
    "deepseek": 64000,
    "deepseek-v4": 64000,
    # Codex
    "gpt-5.5": 200000,
    "gpt-5.4": 200000,
    "gpt-5.3": 200000,
    "o3": 200000,
}


def _resolve_model_id(model_id: str):
    """Resolve virtual model ID. Returns (real_model_id, max_context_tokens or None)."""
    if not model_id:
        return model_id, None
    for suffix, tokens in _CONTEXT_LIMITS.items():
        if model_id.endswith(suffix):
            return model_id[:-len(suffix)], tokens
    return model_id, None


# ─── Session Persistence ──────────────────────────────────────────────────────

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), ".sessions.json")

_SAVED_SESSIONS_CACHE: Optional[List[Dict]] = None
_SAVED_SESSIONS_MTIME: float = 0.0


def load_saved_sessions(force_reload: bool = False) -> List[Dict]:
    """Load saved sessions from disk with in-memory caching."""
    global _SAVED_SESSIONS_CACHE, _SAVED_SESSIONS_MTIME

    if not force_reload and _SAVED_SESSIONS_CACHE is not None:
        try:
            mtime = os.path.getmtime(SESSIONS_FILE)
            if mtime == _SAVED_SESSIONS_MTIME:
                return _SAVED_SESSIONS_CACHE
        except OSError:
            pass

    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
            _SAVED_SESSIONS_CACHE = data
            _SAVED_SESSIONS_MTIME = os.path.getmtime(SESSIONS_FILE)
            return data
        except Exception:
            pass

    _SAVED_SESSIONS_CACHE = []
    _SAVED_SESSIONS_MTIME = 0.0
    return []


def save_sessions(sessions: List[Dict]) -> None:
    """Save sessions to disk and invalidate cache."""
    global _SAVED_SESSIONS_CACHE, _SAVED_SESSIONS_MTIME
    try:
        with open(SESSIONS_FILE, "w") as f:
            json.dump(sessions, f, indent=2)
        _SAVED_SESSIONS_CACHE = sessions
        _SAVED_SESSIONS_MTIME = os.path.getmtime(SESSIONS_FILE)
    except Exception as e:
        print(f"[Claude] Failed to save sessions: {e}")
