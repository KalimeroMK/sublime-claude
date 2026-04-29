"""Persistent memory for Claude Code sessions.

Stores key facts, preferences, and decisions across sessions.
Uses project-level `.claude/memory.json` with optional global fallback.
"""
import json
import os
import re
import time
import uuid
from typing import List, Dict, Optional, Any


DEFAULT_MAX_MEMORIES = 50
MEMORY_FILE = "memory.json"


def _get_memory_path(cwd: Optional[str]) -> str:
    """Get path to memory file: project first, then global fallback."""
    if cwd and os.path.isdir(cwd):
        project_path = os.path.join(cwd, ".claude", MEMORY_FILE)
        if os.path.isfile(project_path):
            return project_path
    # Global fallback
    global_dir = os.path.expanduser("~/.claude")
    os.makedirs(global_dir, exist_ok=True)
    return os.path.join(global_dir, MEMORY_FILE)


def _load_memories(cwd: Optional[str]) -> List[Dict[str, Any]]:
    """Load memories from disk."""
    path = _get_memory_path(cwd)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("memories", [])
    except Exception:
        return []


def _save_memories(cwd: Optional[str], memories: List[Dict[str, Any]]) -> None:
    """Save memories to disk, pruning if over limit."""
    path = _get_memory_path(cwd)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Sort by relevance score (descending) and prune
    memories.sort(key=lambda m: m.get("relevance_score", 0), reverse=True)
    memories = memories[:DEFAULT_MAX_MEMORIES]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "memories": memories}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Claude] Memory save error: {e}")


def _score_relevance(memory: Dict[str, Any], query: str) -> float:
    """Score how relevant a memory is to the current query (0.0 - 1.0)."""
    fact = memory.get("fact", "").lower()
    query_lower = query.lower()
    category = memory.get("category", "")

    score = 0.0

    # Exact keyword matches
    query_words = set(re.findall(r'[a-zA-Z0-9_]{3,}', query_lower))
    fact_words = set(re.findall(r'[a-zA-Z0-9_]{3,}', fact))
    if query_words and fact_words:
        overlap = len(query_words & fact_words)
        score += min(0.6, overlap * 0.15)

    # Contains query substring
    if query_lower in fact or any(w in fact for w in query_words if len(w) > 4):
        score += 0.2

    # Category boosts
    category_boosts = {
        "coding_style": 0.1,
        "architecture": 0.1,
        "preferences": 0.1,
        "stack": 0.15,
        "conventions": 0.1,
    }
    score += category_boosts.get(category, 0.0)

    # Use count bonus (memories used more often are more relevant)
    use_count = memory.get("use_count", 0)
    score += min(0.1, use_count * 0.02)

    return min(1.0, score)


def get_relevant_memories(cwd: Optional[str], query: str, max_memories: int = 5, min_score: float = 0.15) -> List[Dict[str, Any]]:
    """Get memories relevant to the current query, sorted by score."""
    memories = _load_memories(cwd)
    if not memories:
        return []

    scored = []
    for mem in memories:
        score = _score_relevance(mem, query)
        if score >= min_score:
            mem_copy = dict(mem)
            mem_copy["_score"] = score
            scored.append((score, mem_copy))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_memories]]


def format_memory_prompt(memories: List[Dict[str, Any]]) -> str:
    """Format memories as a system prompt snippet."""
    if not memories:
        return ""
    lines = ["\n<memories>"]
    for mem in memories:
        cat = mem.get("category", "note")
        fact = mem.get("fact", "")
        lines.append(f"  [{cat}] {fact}")
    lines.append("</memories>")
    return "\n".join(lines)


def add_memory(cwd: Optional[str], fact: str, category: str = "note") -> bool:
    """Add a new memory."""
    if not fact or len(fact) < 5:
        return False
    memories = _load_memories(cwd)
    # Deduplicate: skip if very similar memory exists
    for mem in memories:
        if mem.get("fact", "").lower() == fact.lower():
            mem["use_count"] = mem.get("use_count", 0) + 1
            mem["last_used"] = time.time()
            _save_memories(cwd, memories)
            return True

    memories.append({
        "id": str(uuid.uuid4())[:8],
        "fact": fact,
        "category": category,
        "created": time.time(),
        "last_used": time.time(),
        "use_count": 1,
        "relevance_score": 0.5,
    })
    _save_memories(cwd, memories)
    return True


def delete_memory(cwd: Optional[str], memory_id: str) -> bool:
    """Delete a memory by ID."""
    memories = _load_memories(cwd)
    filtered = [m for m in memories if m.get("id") != memory_id]
    if len(filtered) < len(memories):
        _save_memories(cwd, filtered)
        return True
    return False


def list_memories(cwd: Optional[str]) -> List[Dict[str, Any]]:
    """List all memories."""
    return _load_memories(cwd)


def extract_memories_from_response(response: str, cwd: Optional[str]) -> int:
    """Auto-extract memories from AI response.

    Looks for patterns like:
    - "I will use X approach" -> coding_style
    - "Remember to Y" -> preferences
    - "From now on, Z" -> conventions
    """
    patterns = [
        (r'\b(?:from now on|going forward|always)\b[^.\n]{10,200}[.\n]', "conventions"),
        (r'\b(?:use|prefer)\s+[a-zA-Z_]+\s+(?:for|when)[^.\n]{5,150}[.\n]', "coding_style"),
        (r'\b(?:remember to|don\'t forget)\b[^.\n]{10,200}[.\n]', "preferences"),
        (r'\b(?:architecture|pattern|design)\b[^.\n]{10,200}[.\n]', "architecture"),
        (r'\b(?:stack|framework|library|version)\b[^.\n]{10,200}[.\n]', "stack"),
    ]

    added = 0
    seen = set()
    for pattern, category in patterns:
        for match in re.finditer(pattern, response, re.IGNORECASE):
            fact = match.group().strip()
            # Clean up
            fact = re.sub(r'^(?:[AI]\s+)?(?:will|should|could|would)\s+', '', fact, flags=re.I)
            fact = fact.strip()
            if len(fact) > 15 and fact.lower() not in seen:
                seen.add(fact.lower())
                if add_memory(cwd, fact, category):
                    added += 1

    return added
