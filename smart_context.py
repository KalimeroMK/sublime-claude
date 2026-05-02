"""Smart context provider for intelligent auto-context expansion.

Provides context beyond explicitly added files:
- Git recently modified files
- Symbols from Sublime's index (codebase-wide)
- Current scope (function/class at cursor)
- Open files relevance scoring

Uses Sublime Text's built-in symbol index instead of embeddings,
so it works with any language that Sublime can index (including
PHP via Intelephense, LSP, or built-in syntax definitions).
"""
import os
import re
import subprocess
import time
from typing import List, Dict, Optional, Set, Tuple
import sublime

try:
    from .constants import OUTPUT_VIEW_SETTING
except ImportError:
    OUTPUT_VIEW_SETTING = "claude_output"

# ─── Caches ──────────────────────────────────────────────────────────────────
_GIT_CACHE: Dict[str, Tuple[float, List[str]]] = {}  # cwd -> (timestamp, files)
_GIT_CACHE_TTL = 10.0  # seconds

_FILE_CONTENT_CACHE: Dict[str, Tuple[float, str]] = {}  # path -> (mtime, content)
_FILE_CACHE_MAX_SIZE = 50  # Max entries to prevent unbounded growth

_DEFAULT_MAX_FILE_SIZE = 50_000  # 50KB max per file
_DEFAULT_MAX_CONTENT_LEN = 8_000  # 8K chars max per context item

# Suffixes/basenames that almost never carry semantic meaning for an LLM —
# build artefacts, test caches, scaffolding samples, lock files. Skip these
# even when they show up as recently modified in git.
_NOISE_SUFFIXES = (
    ".cache", ".example", ".lock", ".log",
    ".min.js", ".min.css", ".map",
    ".tmp", ".bak", ".orig", ".swp",
)
_NOISE_BASENAMES = {
    ".env.example", ".env.testing", ".env.staging",
    ".phpunit.result.cache", "phpunit.xml.dist",
    "package-lock.json", "yarn.lock", "composer.lock", "uv.lock", "Cargo.lock",
}


def _is_noise(path: str) -> bool:
    base = os.path.basename(path).lower()
    if base in {b.lower() for b in _NOISE_BASENAMES}:
        return True
    return any(base.endswith(suf) for suf in _NOISE_SUFFIXES)


def get_git_modified_files(cwd: str, max_files: int = 5) -> List[str]:
    """Get recently modified files from git status and recent commits.

    Returns absolute paths to files that have been modified recently.
    Results are cached for 10 seconds to avoid repeated git calls.
    """
    global _GIT_CACHE
    now = time.time()
    cached = _GIT_CACHE.get(cwd)
    if cached and (now - cached[0]) < _GIT_CACHE_TTL:
        return cached[1][:max_files]

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

        # Filter out ignored files (build artifacts, node_modules, etc.)
        if files:
            try:
                check = subprocess.run(
                    ["git", "-C", cwd, "check-ignore", "--no-index", "-z"] + files,
                    capture_output=True, text=True, timeout=5
                )
                ignored = set()
                if check.returncode in (0, 1):  # 0 = some ignored, 1 = none ignored
                    for p in check.stdout.split("\0"):
                        if p:
                            ignored.add(os.path.normpath(p))
                files = [f for f in files if f not in ignored]
            except Exception:
                pass

        files = [f for f in files if not _is_noise(f)]
        result_files = files[:max_files]
        _GIT_CACHE[cwd] = (now, result_files)
        return result_files
    except Exception:
        return []


def _read_file_cached(path: str, max_size: int = _DEFAULT_MAX_FILE_SIZE, max_content: int = _DEFAULT_MAX_CONTENT_LEN) -> Optional[str]:
    """Read file content with mtime-based caching and size limits.

    Returns None if file is too large or cannot be read.
    """
    global _FILE_CONTENT_CACHE
    try:
        mtime = os.path.getmtime(path)
        size = os.path.getsize(path)
        if size > max_size:
            return None

        cached = _FILE_CONTENT_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if len(content) > max_content:
            content = content[:max_content] + "\n\n... [truncated]\n"

        # Prune cache if too large (LRU-style: remove oldest)
        if len(_FILE_CONTENT_CACHE) >= _FILE_CACHE_MAX_SIZE:
            oldest = min(_FILE_CONTENT_CACHE.keys(), key=lambda k: _FILE_CONTENT_CACHE[k][0])
            del _FILE_CONTENT_CACHE[oldest]

        _FILE_CONTENT_CACHE[path] = (mtime, content)
        return content
    except Exception:
        return None


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
        if _is_noise(path):
            continue
        files.append(path)
    return files


def extract_symbol_candidates(text: str) -> List[str]:
    """Extract potential symbol names from prompt text.

    Looks for CamelCase, snake_case, and PascalCase identifiers
    that are likely to be class/function names.
    """
    candidates = set()
    # CamelCase / PascalCase words (2+ consecutive capitalized words)
    for match in re.finditer(r'\b[A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+\b', text):
        candidates.add(match.group())
    # snake_case words that look like functions/classes
    for match in re.finditer(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b', text):
        word = match.group()
        # Exclude common words
        if word not in ("is_valid", "getattr", "hasattr", "isinstance"):
            candidates.add(word)
    # Single Capitalized words (likely class names)
    for match in re.finditer(r'\b[A-Z][a-zA-Z0-9]{2,}\b', text):
        word = match.group()
        if word not in ("True", "False", "None", "HTTP", "URL", "API", "JSON", "XML"):
            candidates.add(word)
    return list(candidates)


def get_view_symbols(view: sublime.View) -> List[Tuple[str, int]]:
    """Get indexed symbols from the current view.

    Returns list of (symbol_name, kind_id) tuples.
    """
    if not view or not view.is_valid():
        return []
    symbols = []
    try:
        # indexed_symbol_regions() returns SymbolRegion objects with .name and .kind
        for sym in view.indexed_symbol_regions():
            symbols.append((sym.name, sym.kind[0] if sym.kind else 0))
    except Exception:
        pass
    return symbols


def get_symbol_related_files(window: sublime.Window, current_file: str, max_symbols: int = 3) -> List[str]:
    """Find definition files for symbols in the current file.

    Uses Sublime Text's symbol index (or Intelephense/LSP if installed)
    to find where symbols defined in current_file are referenced,
    and where symbols referenced in current_file are defined.
    """
    if not window or not current_file:
        return []

    files = []
    try:
        # Find the view for current_file
        current_view = None
        for view in window.views():
            if view.file_name() == current_file:
                current_view = view
                break

        if not current_view or not current_view.is_valid():
            return []

        # Get symbols from current view
        symbols = get_view_symbols(current_view)
        if not symbols:
            return []

        # Prioritize: types/classes first, then functions
        symbols.sort(key=lambda s: 0 if s[1] in (2, 4) else 1)  # KindId.TYPE=2, NAMESPACE=4

        seen = set()
        for sym_name, _ in symbols[:max_symbols]:
            if sym_name in seen:
                continue
            seen.add(sym_name)

            # Look up symbol definitions in project index
            try:
                locations = window.symbol_locations(sym_name)
            except Exception:
                # Fallback to deprecated API
                try:
                    locations = window.lookup_symbol_in_index(sym_name)
                except Exception:
                    continue

            for loc in locations:
                path = loc.path
                if not path or path == current_file:
                    continue
                if os.path.isfile(path) and path not in files:
                    files.append(path)
                    break  # One definition per symbol is enough

            # Also look up references
            try:
                refs = window.lookup_references_in_index(sym_name)
            except Exception:
                refs = []

            for ref in refs[:2]:  # Limit references
                path = ref.path
                if not path or path == current_file:
                    continue
                if os.path.isfile(path) and path not in files:
                    files.append(path)

        return files[:max_symbols]
    except Exception as e:
        print(f"[Claude] Symbol index error: {e}")
        return []


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

    # 2. Symbol-based codebase context (from Sublime's index)
    if current_file:
        sym_files = get_symbol_related_files(window, current_file, max_symbols=3)
        for path in sym_files:
            if os.path.abspath(path) in exclude:
                continue
            if _is_noise(path):
                continue
            content = _read_file_cached(path)
            if content is not None:
                context_items.append({
                    "type": "symbol",
                    "path": path,
                    "content": content,
                    "reason": "symbol_definition",
                })
                exclude.add(os.path.abspath(path))

    # 3. Git recently modified files
    if cwd:
        git_files = get_git_modified_files(cwd, max_files=max_git)
        for path in git_files:
            if os.path.abspath(path) in exclude:
                continue
            content = _read_file_cached(path)
            if content is not None:
                context_items.append({
                    "type": "git",
                    "path": path,
                    "content": content,
                    "reason": "recently_modified",
                })
                exclude.add(os.path.abspath(path))

    # 4. Relevant open files
    open_files = get_open_code_files(window, exclude)
    if current_file:
        scored = [
            (score_file_relevance(path, current_file, open_files), path)
            for path in open_files
        ]
        scored.sort(reverse=True)
        for _, path in scored[:max_open]:
            content = _read_file_cached(path)
            if content is not None:
                context_items.append({
                    "type": "open",
                    "path": path,
                    "content": content,
                    "reason": "open_file",
                })
                exclude.add(os.path.abspath(path))

    return context_items
