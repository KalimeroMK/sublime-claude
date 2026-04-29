"""Skills manager for Claude Code Sublime plugin.

Manages curated skills that can be installed globally (all projects) or per-project.
Skills are injected into CLAUDE.md files which Claude Code CLI reads automatically.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

# Marker comments used to delimit managed skill sections in CLAUDE.md files
SKILLS_START_MARKER = "<!-- [Claude Sublime Skills] START -->"
SKILLS_END_MARKER = "<!-- [Claude Sublime Skills] END -->"

# Directories and files
_SKILLS_BASE_DIR = os.path.expanduser("~/.claude-sublime/skills")
_GLOBAL_MANIFEST_PATH = os.path.join(_SKILLS_BASE_DIR, "global_manifest.json")
_PROJECT_MANIFEST_NAME = ".claude/skills_manifest.json"


def _ensure_dirs() -> None:
    """Create base directories if missing."""
    os.makedirs(_SKILLS_BASE_DIR, exist_ok=True)


def load_marketplace(path: Optional[str] = None) -> Dict[str, dict]:
    """Load curated skills from bundled marketplace JSON."""
    if path is None:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(plugin_dir, "skills_marketplace.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("skills", {})
    except Exception as e:
        print(f"[Claude Skills] Error loading marketplace: {e}")
        return {}


def _load_manifest(manifest_path: str) -> Dict[str, List[str]]:
    """Load a manifest file (list of active skill IDs)."""
    if not os.path.exists(manifest_path):
        return {"active": []}
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("active"), list):
            data["active"] = []
        return data
    except Exception as e:
        print(f"[Claude Skills] Error loading manifest {manifest_path}: {e}")
        return {"active": []}


def _save_manifest(manifest_path: str, data: Dict[str, List[str]]) -> None:
    """Save a manifest file."""
    try:
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Claude Skills] Error saving manifest {manifest_path}: {e}")


def get_active_skills(scope: str, project_root: Optional[str] = None) -> List[str]:
    """Get list of active skill IDs for a scope ('global' or 'project')."""
    if scope == "global":
        manifest = _load_manifest(_GLOBAL_MANIFEST_PATH)
        return manifest.get("active", [])
    elif scope == "project" and project_root:
        manifest_path = os.path.join(project_root, _PROJECT_MANIFEST_NAME)
        manifest = _load_manifest(manifest_path)
        return manifest.get("active", [])
    return []


def is_skill_active(skill_id: str, scope: str, project_root: Optional[str] = None) -> bool:
    """Check if a skill is active in a given scope."""
    return skill_id in get_active_skills(scope, project_root)


def toggle_skill(skill_id: str, scope: str, project_root: Optional[str] = None) -> bool:
    """Toggle a skill on/off in the given scope. Returns new state (True=active)."""
    _ensure_dirs()
    if scope == "global":
        manifest_path = _GLOBAL_MANIFEST_PATH
    elif scope == "project" and project_root:
        manifest_path = os.path.join(project_root, _PROJECT_MANIFEST_NAME)
    else:
        return False

    manifest = _load_manifest(manifest_path)
    active = manifest.get("active", [])

    if skill_id in active:
        active.remove(skill_id)
        new_state = False
    else:
        active.append(skill_id)
        new_state = True

    manifest["active"] = active
    _save_manifest(manifest_path, manifest)
    return new_state


def set_skill_state(skill_id: str, scope: str, enabled: bool, project_root: Optional[str] = None) -> bool:
    """Explicitly set a skill's state. Returns the state after operation."""
    _ensure_dirs()
    if scope == "global":
        manifest_path = _GLOBAL_MANIFEST_PATH
    elif scope == "project" and project_root:
        manifest_path = os.path.join(project_root, _PROJECT_MANIFEST_NAME)
    else:
        return False

    manifest = _load_manifest(manifest_path)
    active = manifest.get("active", [])

    if enabled and skill_id not in active:
        active.append(skill_id)
    elif not enabled and skill_id in active:
        active.remove(skill_id)

    manifest["active"] = active
    _save_manifest(manifest_path, manifest)
    return enabled


def _build_skills_content(skill_ids: List[str], marketplace: Optional[Dict[str, dict]] = None) -> str:
    """Build markdown content from active skill IDs."""
    if marketplace is None:
        marketplace = load_marketplace()

    parts = [SKILLS_START_MARKER, ""]
    for sid in skill_ids:
        skill = marketplace.get(sid)
        if not skill:
            continue
        content = skill.get("content", "").strip()
        if content:
            parts.append(content)
            parts.append("")
    parts.append(SKILLS_END_MARKER)
    return "\n".join(parts)


def _inject_into_claude_md(file_path: str, skill_ids: List[str], marketplace: Optional[Dict[str, dict]] = None) -> bool:
    """Inject skills content into a CLAUDE.md file, preserving user content."""
    skills_content = _build_skills_content(skill_ids, marketplace)

    existing = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception as e:
            print(f"[Claude Skills] Error reading {file_path}: {e}")
            return False

    # Remove old managed section if present
    start_idx = existing.find(SKILLS_START_MARKER)
    end_idx = existing.find(SKILLS_END_MARKER)
    if start_idx != -1 and end_idx != -1:
        # Remove from start marker through end marker (inclusive)
        after_end = end_idx + len(SKILLS_END_MARKER)
        # Also remove trailing whitespace
        while after_end < len(existing) and existing[after_end] == "\n":
            after_end += 1
        existing = existing[:start_idx] + existing[after_end:]
        # Clean up leading/trailing whitespace
        existing = existing.strip()

    if not skill_ids:
        # No skills to inject; if file exists and is now empty, remove it
        if existing:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(existing)
                    f.write("\n")
            except Exception as e:
                print(f"[Claude Skills] Error writing {file_path}: {e}")
                return False
        else:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return True

    # Build new content
    if existing:
        new_content = existing.rstrip() + "\n\n\n" + skills_content + "\n"
    else:
        new_content = skills_content + "\n"

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"[Claude Skills] Error writing {file_path}: {e}")
        return False


def rebuild_global_claude_md(marketplace: Optional[Dict[str, dict]] = None) -> bool:
    """Rebuild ~/.claude/CLAUDE.md from global active skills."""
    active = get_active_skills("global")
    file_path = os.path.expanduser("~/.claude/CLAUDE.md")
    return _inject_into_claude_md(file_path, active, marketplace)


def rebuild_project_claude_md(project_root: str, marketplace: Optional[Dict[str, dict]] = None) -> bool:
    """Rebuild ./CLAUDE.md from project active skills."""
    active = get_active_skills("project", project_root)
    file_path = os.path.join(project_root, "CLAUDE.md")
    return _inject_into_claude_md(file_path, active, marketplace)


def rebuild_all(project_root: Optional[str] = None, marketplace: Optional[Dict[str, dict]] = None) -> Tuple[bool, bool]:
    """Rebuild both global and project CLAUDE.md files. Returns (global_ok, project_ok)."""
    global_ok = rebuild_global_claude_md(marketplace)
    project_ok = True
    if project_root:
        project_ok = rebuild_project_claude_md(project_root, marketplace)
    return global_ok, project_ok


def get_skill_status(skill_id: str, project_root: Optional[str] = None) -> Dict[str, bool]:
    """Get activation status of a skill in both scopes."""
    return {
        "global": is_skill_active(skill_id, "global"),
        "project": is_skill_active(skill_id, "project", project_root) if project_root else False,
    }


def list_installed_skills(project_root: Optional[str] = None) -> List[Dict[str, any]]:
    """List all marketplace skills with their activation status."""
    marketplace = load_marketplace()
    global_active = set(get_active_skills("global"))
    project_active = set(get_active_skills("project", project_root) if project_root else [])

    result = []
    for sid, info in marketplace.items():
        result.append({
            "id": sid,
            "name": info.get("name", sid),
            "description": info.get("description", ""),
            "category": info.get("category", "general"),
            "global_active": sid in global_active,
            "project_active": sid in project_active,
        })

    # Sort: active first, then by category, then by name
    result.sort(key=lambda s: (
        not (s["global_active"] or s["project_active"]),
        s["category"],
        s["name"].lower(),
    ))
    return result
