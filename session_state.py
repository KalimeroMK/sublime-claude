"""State persistence manager for sessions (sessions.json, retain files, JSONL)."""
import json
import os
from typing import Optional

from .session_env import load_saved_sessions, save_sessions


class StateManager:
    """Manages session persistence: sessions.json, retain files, rewind points."""

    def __init__(self, session):
        self._s = session

    # ─── sessions.json ────────────────────────────────────────────────────

    def save(self) -> None:
        """Save session info to disk for later resume."""
        s = self._s
        if not s.session_id:
            return
        sessions = load_saved_sessions()
        # Update or add this session — always move to front (most recently active)
        entry = None
        for i, existing in enumerate(sessions):
            if existing.get("session_id") == s.session_id:
                entry = sessions.pop(i)
                break
        if not entry:
            entry = {"session_id": s.session_id}
        entry["name"] = s.name
        entry["project"] = s._cwd()
        entry["total_cost"] = s.total_cost
        entry["query_count"] = s.query_count
        entry["backend"] = s.backend
        entry["last_activity"] = s.last_activity
        if s.tags:
            entry["tags"] = s.tags.copy()
        else:
            entry.pop("tags", None)
        if s._usage_history:
            entry["usage_history"] = s._usage_history[-50:]  # Keep last 50 queries
        else:
            entry.pop("usage_history", None)
        # Derive state from current session state
        if s.client is not None and s.initialized:
            entry["state"] = "open"
        elif s.session_id and s.client is None and not s.initialized:
            entry["state"] = "sleeping"
        else:
            entry.setdefault("state", "closed")
        if s._pending_resume_at:
            entry["resume_session_at"] = s._pending_resume_at
        else:
            entry.pop("resume_session_at", None)
        sessions.insert(0, entry)
        from .constants import MAX_SESSIONS
        sessions = sessions[:MAX_SESSIONS]
        save_sessions(sessions)

    def persist_state(self, state: str) -> None:
        """Save session with explicit state override."""
        if not self._s.session_id:
            return
        sessions = load_saved_sessions()
        for i, s in enumerate(sessions):
            if s.get("session_id") == self._s.session_id:
                sessions[i]["state"] = state
                save_sessions(sessions)
                return
        # Entry doesn't exist yet — create it
        self.save()

    # ─── Retain files ─────────────────────────────────────────────────────

    def sync_project_retain(self, retain_content: str = None) -> None:
        """Sync project-level retain content to .claude/sublime_project_retain.md."""
        cwd = self._s._cwd()
        if not cwd:
            return
        retain_path = os.path.join(cwd, ".claude", "sublime_project_retain.md")
        if retain_content:
            os.makedirs(os.path.dirname(retain_path), exist_ok=True)
            with open(retain_path, "w") as f:
                f.write(retain_content)
        elif os.path.exists(retain_path):
            os.remove(retain_path)

    def get_retain_path(self) -> Optional[str]:
        """Get path to session's dynamic retain file."""
        if not self._s.session_id:
            return None
        cwd = self._s._cwd()
        if not cwd:
            return None
        return os.path.join(cwd, ".claude", "sessions", f"{self._s.session_id}_retain.md")

    def retain(self, content: str = None, append: bool = False) -> Optional[str]:
        """Write to or read session's retain file for compaction."""
        path = self.get_retain_path()
        if not path:
            print("[Claude] Cannot access retain file - no session_id yet")
            return None

        if content is None:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return f.read()
            return ""

        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode) as f:
            if append and os.path.exists(path):
                f.write("\n")
            f.write(content)
        print(f"[Claude] Retain file updated: {path}")
        return None

    def clear_retain(self) -> None:
        """Clear session's retain file."""
        path = self.get_retain_path()
        if path and os.path.exists(path):
            os.remove(path)
            print(f"[Claude] Retain file cleared: {path}")

    def _strip_comment_only_content(self, content: str) -> str:
        """Strip lines that are only comments or whitespace."""
        lines = content.split('\n')
        filtered = [line for line in lines if line.strip() and not line.strip().startswith('#')]
        return '\n'.join(filtered).strip()

    def gather_retain_content(self) -> Optional[str]:
        """Gather all retain content from various sources."""
        prompts = []
        cwd = self._s._cwd()

        # 1. Static retain file
        if cwd:
            static_path = os.path.join(cwd, ".claude", "RETAIN.md")
            if os.path.exists(static_path):
                try:
                    with open(static_path, "r") as f:
                        content = self._strip_comment_only_content(f.read())
                    if content:
                        prompts.append(content)
                except Exception as e:
                    print(f"[Claude] Error reading static retain: {e}")

        # 2. Sublime project retain file
        if cwd:
            sublime_retain_path = os.path.join(cwd, ".claude", "sublime_project_retain.md")
            if os.path.exists(sublime_retain_path):
                try:
                    with open(sublime_retain_path, "r") as f:
                        content = self._strip_comment_only_content(f.read())
                    if content:
                        prompts.append(content)
                except Exception as e:
                    print(f"[Claude] Error reading sublime project retain: {e}")

        # 3. Session retain file
        session_retain = self._strip_comment_only_content(self.retain() or "")
        if session_retain:
            prompts.append(session_retain)

        # 4. Profile pre_compact_prompt
        if self._s.profile and self._s.profile.get("pre_compact_prompt"):
            prompts.append(self._s.profile["pre_compact_prompt"])

        if prompts:
            return "\n\n---\n\n".join(prompts)
        return None

    def inject_retain_midquery(self) -> None:
        """Inject retain content by interrupting and restarting with retain prompt."""
        self._s._pending_retain = self.gather_retain_content()
        if self._s._pending_retain:
            self._s.interrupt()

    # ─── JSONL / Rewind ───────────────────────────────────────────────────

    def find_jsonl_path(self) -> Optional[str]:
        """Find the JSONL file for this session."""
        if not self._s.session_id:
            return None
        fname = f"{self._s.session_id}.jsonl"
        projects_dir = os.path.expanduser("~/.claude/projects")
        # Try exact cwd match first
        cwd = self._s._cwd()
        project_key = cwd.replace("/", "-").lstrip("-")
        exact = os.path.join(projects_dir, project_key, fname)
        if os.path.exists(exact):
            return exact
        # Search all project directories
        if os.path.isdir(projects_dir):
            for d in os.listdir(projects_dir):
                candidate = os.path.join(projects_dir, d, fname)
                if os.path.exists(candidate):
                    return candidate
        return None

    def find_rewind_point(self) -> tuple:
        """Find the assistant entry uuid to rewind to.
        Returns (uuid, undone_prompt) or (None, "")."""
        jsonl_path = self.find_jsonl_path()
        if not jsonl_path:
            return None, ""
        turns = []  # [(prompt, prev_assistant_uuid)]
        last_assistant_uuid = None
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("isSidechain") or entry.get("isMeta"):
                        continue
                    etype = entry.get("type")
                    if etype == "assistant":
                        uuid = entry.get("uuid")
                        if uuid:
                            last_assistant_uuid = uuid
                    elif etype == "user":
                        msg = entry.get("message", {})
                        content = msg.get("content", [])
                        has_tool_result = (
                            isinstance(content, list) and
                            any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        )
                        if has_tool_result:
                            continue
                        prompt = ""
                        if isinstance(content, str):
                            prompt = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    prompt += block.get("text", "")
                        turns.append((prompt, last_assistant_uuid))
        except Exception as e:
            print(f"[Claude] _find_rewind_point error: {e}")
            return None, ""

        s = self._s
        if s._pending_resume_at:
            for i, (prompt, asst_uuid) in enumerate(turns):
                if asst_uuid == s._pending_resume_at:
                    if i < 2:
                        return None, ""
                    undone_prompt = turns[i - 1][0]
                    rewind_to = turns[i - 1][1]
                    if not rewind_to:
                        return None, ""
                    return rewind_to, undone_prompt
            return None, ""

        if len(turns) < 2:
            return None, ""
        undone_prompt = turns[-1][0]
        rewind_to = turns[-1][1]
        if not rewind_to:
            return None, ""
        return rewind_to, undone_prompt
