"""Codebase semantic search without embeddings.

Uses TF-IDF over SQLite to find relevant code files based on query keywords.
Falls back to grep-like content search when no index exists.
Works with any language; no additional API or model required.
"""
import os
import re
import sqlite3
from typing import List, Dict, Optional, Set


# File extensions to index
INDEX_EXTENSIONS = (
    ".php", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".java", ".kt", ".swift",
    ".c", ".cpp", ".h", ".hpp",
    ".rb", ".scala", ".clj",
)

# Directories to skip
SKIP_DIRS = {
    "vendor", "node_modules", ".git", "__pycache__",
    "dist", "build", ".claude", ".idea", ".vscode",
    "storage", "cache", "tmp", "temp",
}

# Common English stopwords + programming keywords to ignore
STOPWORDS = {
    "how", "does", "the", "work", "what", "is", "are", "and", "or",
    "do", "to", "a", "an", "in", "of", "for", "with", "this", "that",
    "it", "be", "has", "have", "had", "was", "were", "will", "would",
    "can", "could", "should", "may", "might", "must", "shall",
    "using", "use", "used", "get", "set", "make", "create", "new",
    "from", "into", "out", "up", "down", "on", "off", "over", "under",
    "then", "when", "where", "who", "which", "why", "how",
    "class", "def", "function", "return", "if", "else", "for", "while",
    "import", "from", "var", "let", "const", "public", "private",
}

# Minimum word length
MIN_WORD_LEN = 3


class CodebaseSearch:
    """TF-IDF based codebase search backed by SQLite."""

    DB_NAME = ".claude_codebase.db"
    CHUNK_LINES = 25  # Lines per result chunk
    CHUNK_CONTEXT = 5  # Lines before/after match

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self.db_path = os.path.join(self.project_root, self.DB_NAME)
        self._init_db()

    def _init_db(self) -> None:
        """Create SQLite tables if not present."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    content TEXT,
                    mtime REAL,
                    size INTEGER
                );
                CREATE TABLE IF NOT EXISTS words (
                    word TEXT,
                    path TEXT,
                    count INTEGER,
                    PRIMARY KEY (word, path)
                );
                CREATE INDEX IF NOT EXISTS idx_word ON words(word);
                CREATE INDEX IF NOT EXISTS idx_path ON words(path);
            """)

    def needs_reindex(self, max_age_hours: float = 24.0) -> bool:
        """Check if index is stale or empty."""
        if not os.path.exists(self.db_path):
            return True
        # Check if any files table entries exist
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            count = cursor.fetchone()[0]
            if count == 0:
                return True
            # Check last index time via mtime of newest file entry
            cursor = conn.execute("SELECT MAX(mtime) FROM files")
            newest = cursor.fetchone()[0]
            if newest is None:
                return True
            import time
            age_hours = (time.time() - newest) / 3600.0
            return age_hours > max_age_hours

    def index_project(
        self,
        extensions: Optional[tuple] = None,
        skip_dirs: Optional[Set[str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> int:
        """Index all matching files in project. Returns number of files indexed."""
        extensions = extensions or INDEX_EXTENSIONS
        skip_dirs = skip_dirs or SKIP_DIRS
        indexed = 0

        for root, dirs, files in os.walk(self.project_root):
            # Filter directories in-place
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            for filename in files:
                if not filename.endswith(extensions):
                    continue
                path = os.path.join(root, filename)
                try:
                    if self._index_file(path):
                        indexed += 1
                        if progress_callback:
                            progress_callback(path)
                except Exception as e:
                    print(f"[Claude] Index error for {path}: {e}")

        return indexed

    def _index_file(self, path: str) -> bool:
        """Index or re-index a single file. Returns True if indexed."""
        try:
            stat = os.stat(path)
            mtime = stat.st_mtime
            size = stat.st_size
        except (OSError, IOError):
            return False

        # Skip files > 500KB
        if size > 512000:
            return False

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except (OSError, IOError):
            return

        # Extract words
        text_lower = content.lower()
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text_lower)
        word_counts: Dict[str, int] = {}
        for w in words:
            if len(w) >= MIN_WORD_LEN and w not in STOPWORDS:
                word_counts[w] = word_counts.get(w, 0) + 1

        # Store in SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM words WHERE path = ?", (path,))
            conn.execute(
                "INSERT OR REPLACE INTO files (path, content, mtime, size) VALUES (?, ?, ?, ?)",
                (path, content, mtime, size),
            )
            for word, count in word_counts.items():
                conn.execute(
                    "INSERT INTO words (word, path, count) VALUES (?, ?, ?)",
                    (word, path, count),
                )
        return True

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract searchable keywords from a natural language query."""
        # Remove code blocks and backticks
        text = re.sub(r'`[^`]*`', ' ', query)
        # Extract words preserving case for CamelCase detection
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text)

        keywords = []
        seen = set()
        for w in words:
            w_lower = w.lower()
            if w_lower in STOPWORDS or len(w_lower) < MIN_WORD_LEN:
                continue
            # Handle CamelCase: AuthController -> auth, controller
            parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', w)
            if len(parts) > 1:
                for part in parts:
                    part_lower = part.lower()
                    if part_lower not in STOPWORDS and len(part_lower) >= MIN_WORD_LEN:
                        if part_lower not in seen:
                            seen.add(part_lower)
                            keywords.append(part_lower)
            if w_lower not in seen:
                seen.add(w_lower)
                keywords.append(w_lower)

        return keywords

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Search codebase for files relevant to query.

        Returns list of dicts with keys:
            path: absolute file path
            chunk: code snippet around match
            line_start: 1-based starting line
            score: relevance score
        """
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        # Check if index exists and has data
        if not os.path.exists(self.db_path):
            return self._fallback_search(query, top_k)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            if cursor.fetchone()[0] == 0:
                return self._fallback_search(query, top_k)

        # Score files by keyword frequency (TF)
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(keywords))
            rows = conn.execute(f"""
                SELECT path, SUM(count) as score
                FROM words
                WHERE word IN ({placeholders})
                GROUP BY path
                ORDER BY score DESC
                LIMIT ?
            """, keywords + [top_k * 3])

            scored_files = [(path, score) for path, score in rows]

        if not scored_files:
            return self._fallback_search(query, top_k)

        # Build results with content chunks
        results = []
        seen_paths = set()

        for path, score in scored_files:
            if path in seen_paths:
                continue
            seen_paths.add(path)

            # Get file content
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT content FROM files WHERE path = ?", (path,)
                ).fetchone()
                if not row:
                    continue
                content = row[0]

            # Find best matching line
            lines = content.split("\n")
            best_line = self._find_best_line(lines, keywords)

            if best_line >= 0:
                start = max(0, best_line - self.CHUNK_CONTEXT)
                end = min(len(lines), best_line + self.CHUNK_LINES - self.CHUNK_CONTEXT)
                chunk = "\n".join(lines[start:end])
                results.append({
                    "path": path,
                    "chunk": chunk,
                    "line_start": start + 1,
                    "score": score,
                })

            if len(results) >= top_k:
                break

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _find_best_line(self, lines: List[str], keywords: List[str]) -> int:
        """Find the line with the most keyword matches."""
        best_score = -1
        best_line = -1
        for i, line in enumerate(lines):
            line_lower = line.lower()
            score = sum(1 for kw in keywords if kw in line_lower)
            # Boost if keyword appears in a function/class definition
            if score > 0:
                stripped = line.strip()
                if any(stripped.startswith(p) for p in ("def ", "function ", "class ", "public ", "private ", "protected ")):
                    score += 3
                if "function(" in stripped or "function " in stripped:
                    score += 2
            if score > best_score:
                best_score = score
                best_line = i
        return best_line

    def _fallback_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Fallback: grep-like search when no index exists."""
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        results = []
        seen = set()

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

            for filename in files:
                if not filename.endswith(INDEX_EXTENSIONS):
                    continue
                path = os.path.join(root, filename)
                if path in seen:
                    continue
                seen.add(path)

                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue

                # Skip large files
                if len(content) > 512000:
                    continue

                text_lower = content.lower()
                score = sum(text_lower.count(kw) for kw in keywords)

                if score > 0:
                    lines = content.split("\n")
                    best_line = self._find_best_line(lines, keywords)
                    if best_line >= 0:
                        start = max(0, best_line - self.CHUNK_CONTEXT)
                        end = min(len(lines), best_line + self.CHUNK_LINES - self.CHUNK_CONTEXT)
                        chunk = "\n".join(lines[start:end])
                        results.append({
                            "path": path,
                            "chunk": chunk,
                            "line_start": start + 1,
                            "score": score,
                        })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def index_if_needed(self, max_age_hours: float = 24.0) -> bool:
        """Re-index project if index is stale or empty. Returns True if indexing was done."""
        if self.needs_reindex(max_age_hours):
            self.index_project()
            return True
        return False
