"""Smart context provider for intelligent auto-context expansion.

Provides context beyond explicitly added files:
- Git recently modified files
- Symbols from Sublime's index
- Current scope (function/class at cursor)
- Open files relevance scoring
"""
import os
import subprocess
from typing import List, Dict, Optional, Set
import sublime

try:
    from .constants import OUTPUT_VIEW_SETTING
except ImportError:
    OUTPUT_VIEW_SETTING = "claude_output"


def get_git_modified_files(cwd: str, max_files: int = 5) -> List[str]:
    """Get recently modified files from git status and recent commits.

    Returns absolute paths to files that have been modified recently.
    """
    files = []
    try:
        # Staged and unstaged changes
        result = subprocess.run(
            ["git", "-C", cwd, "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    files.append(os.path.normpath(os.path.join(cwd, line)))

        # Recently committed files (last 3 commits)
        result = subprocess.run(
            ["git", "-C", cwd, "diff", "--name-only", "HEAD~3", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    path = os.path.normpath(os.path.join(cwd, line))
                    if path not in files:
                        files.append(path)

        return files[:max_files]
    except Exception:
        return []


def get_symbols_in_view(view: sublime.View) -> List[Dict]:
    """Get symbols defined in the current view.

    Uses Sublime's symbol list (functions, classes, etc.)
    """
    if not view or not view.is_valid():
        return []

    symbols = []
    try:
        # view.symbols() returns list of (region, name) tuples
        for region, name in view.symbols():
            symbols.append({
                "name": name,
                "line": view.rowcol(region.begin())[0] + 1,
                "kind": "symbol",
            })
    except Exception:
        pass
    return symbols


def get_current_scope(view: sublime.View) -> Optional[Dict]:
    """Get the current function/class scope at cursor position.

    Returns the symbol that contains the first cursor position.
    """
    if not view or not view.is_valid():
        return None

    try:
        sel = view.sel()
        if not sel:
            return None
        cursor = sel[0].begin()

        # Try to use scope to find function/class boundaries
        scope = view.scope_name(cursor)

        # Look for symbol that contains cursor
        for region, name in view.symbols():
            if region.contains(cursor):
                return {
                    "name": name,
                    "line": view.rowcol(region.begin())[0] + 1,
                    "region": (region.begin(), region.end()),
                }
    except Exception:
        pass
    return None


def score_file_relevance(path: str, current_file: str, open_files: List[str]) -> float:
    """Score how relevant a file is to the current context.

    Higher score = more relevant. Factors:
    - Same directory (+2)
    - Same extension (+1)
    - Open in editor (+3)
    - Recently modified (+2)
    """
    score = 0.0
    current_dir = os.path.dirname(current_file)

    if os.path.dirname(path) == current_dir:
        score += 2.0

    if os.path.splitext(path)[1] == os.path.splitext(current_file)[1]:
        score += 1.0

    if path in open_files:
        score += 3.0

    return score


def get_open_code_files(window: sublime.Window, exclude: Set[str]) -> List[str]:
    """Get list of open files that contain code (not output views, etc.)."""
    files = []
    for view in window.views():
        path = view.file_name()
        if not path:
            continue
        if path in exclude:
            continue
        # Skip Claude output views and scratch buffers
        if view.settings().get(OUTPUT_VIEW_SETTING) or view.is_scratch():
            continue
        files.append(path)
    return files


def build_smart_context(
    window: sublime.Window,
    current_file: Optional[str],
    current_view: Optional[sublime.View],
    max_related: int = 3,
    max_git: int = 3,
    max_open: int = 2,
) -> List[Dict]:
    """Build a list of smart context items for the current session.

    Returns list of dicts with keys: type, path, content, reason
    """
    context_items = []
    if not window:
        return context_items

    exclude = set()
    if current_file:
        exclude.add(os.path.abspath(current_file))

    cwd = window.folders()[0] if window.folders() else None

    # 1. Current scope (function/class at cursor)
    if current_view and current_view.is_valid():
        scope = get_current_scope(current_view)
        if scope:
            context_items.append({
                "type": "scope",
                "path": current_file or "",
                "content": f"Current scope: {scope['name']} (line {scope['line']})",
                "reason": "cursor",
            })

    # 2. Git recently modified files
    if cwd:
        git_files = get_git_modified_files(cwd, max_files=max_git)
        for path in git_files:
            if os.path.abspath(path) in exclude:
                continue
            if os.path.exists(path) and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    context_items.append({
                        "type": "git",
                        "path": path,
                        "content": content,
                        "reason": "recently_modified",
                    })
                    exclude.add(os.path.abspath(path))
                except Exception:
                    pass

    # 3. Relevant open files
    open_files = get_open_code_files(window, exclude)
    if current_file:
        scored = [
            (score_file_relevance(path, current_file, open_files), path)
            for path in open_files
        ]
        scored.sort(reverse=True)
        for _, path in scored[:max_open]:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                context_items.append({
                    "type": "open",
                    "path": path,
                    "content": content,
                    "reason": "open_file",
                })
                exclude.add(os.path.abspath(path))
            except Exception:
                pass

    return context_items
