"""Shared permission pattern matching logic.

Used by both the bridge (can_use_tool / guardrails) and the Sublime output view
(session auto-allow, "Always" button).
"""
import fnmatch
import os
import re
import shlex
from typing import List, Optional, Tuple


# Pre-compile regex for performance
_bash_split_re = re.compile(r'\s*(?:&&|\|\||\|&|[;&|\n])\s*')
_bash_env_var_re = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+')
_bash_subshell_re = re.compile(r'^\$\(|\)$|^`|`$')


# Process wrappers to strip from bash commands
_PROCESS_WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf"}

# Trivial bash commands that should be skipped when making auto-allow patterns
_TRIVIAL_COMMANDS = {"cd", "pushd", "popd", "export", "set", "unset", "source", ".", "true", "false"}


def parse_permission_pattern(pattern: str) -> Tuple[str, Optional[str]]:
    """Parse permission pattern into (tool_name, specifier).

    Formats:
        "Bash" -> ("Bash", None)
        "Bash(git:*)" -> ("Bash", "git:*")
        "Read(/src/**)" -> ("Read", "/src/**")
    """
    if '(' in pattern and pattern.endswith(')'):
        paren_idx = pattern.index('(')
        tool_name = pattern[:paren_idx]
        specifier = pattern[paren_idx + 1:-1]
        return tool_name, specifier
    return pattern, None


def extract_bash_commands(command: str) -> List[str]:
    """Extract individual command names from a bash command string.

    Handles:
    - Command chains: cmd1 && cmd2, cmd1 || cmd2, cmd1 ; cmd2
    - Pipes: cmd1 | cmd2, cmd1 |& cmd2
    - Background: cmd1 & cmd2
    - Newlines
    - Environment variables: FOO=bar cmd
    - Subshells: $(cmd), `cmd`
    - Process wrappers: timeout, time, nice, nohup, stdbuf
    - Bare xargs

    Returns list of command names (e.g., ["cd", "git", "npm"])
    """
    commands = []
    parts = _bash_split_re.split(command)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Skip subshell wrappers
        part = _bash_subshell_re.sub('', part).strip()
        if not part:
            continue

        # Skip leading environment variable assignments (VAR=value)
        while part and _bash_env_var_re.match(part):
            part = _bash_env_var_re.sub('', part).strip()

        if not part:
            continue

        # Try shlex first, fall back to simple split
        try:
            tokens = shlex.split(part)
        except ValueError:
            tokens = part.split()

        if not tokens:
            continue

        idx = 0
        # Skip env var assignments (shlex handles some, but check again)
        while idx < len(tokens) and '=' in tokens[idx] and not tokens[idx].startswith('-'):
            idx += 1
        if idx >= len(tokens):
            continue

        # Strip process wrappers
        while idx < len(tokens) and tokens[idx] in _PROCESS_WRAPPERS:
            idx += 1
            # Skip wrapper's numeric/flag args
            while idx < len(tokens) and (tokens[idx].startswith('-') or tokens[idx].replace('.', '').isdigit()):
                idx += 1
        if idx >= len(tokens):
            continue

        # Strip bare xargs (no flags)
        if tokens[idx] == "xargs" and (idx + 1 >= len(tokens) or not tokens[idx + 1].startswith('-')):
            idx += 1
        if idx >= len(tokens):
            continue

        cmd = tokens[idx]
        # Handle path prefixes like /usr/bin/git -> git
        if '/' in cmd:
            cmd = cmd.split('/')[-1]
        commands.append(cmd)

    return commands


def make_auto_allow_pattern(tool: str, tool_input: dict) -> str:
    """Create a fine-grained auto-allow pattern from tool and input.

    For Bash: extracts command prefix (first word) -> "Bash(git:*)"
    For Read/Write/Edit: uses directory path -> "Read(/src/)"
    For Skill: uses skill name -> "Skill(skill-name)"
    For other tools: returns tool name unchanged.
    """
    if not tool_input:
        return tool

    if tool == "Bash":
        command = tool_input.get("command", "")
        if command:
            cmd_names = extract_bash_commands(command)
            best = None
            for cmd in cmd_names:
                if cmd not in _TRIVIAL_COMMANDS:
                    best = cmd
                    break
            if not best and cmd_names:
                best = cmd_names[0]
            if best:
                return f"Bash({best}:*)"
    elif tool in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            dir_path = os.path.dirname(file_path)
            if dir_path:
                return f"{tool}({dir_path}/)"
    elif tool == "Skill":
        skill_name = tool_input.get("skill", "")
        if skill_name:
            return f"Skill({skill_name})"
    # For other tools, just use the tool name
    return tool


def match_permission_pattern(
    tool_name: str,
    tool_input: dict,
    pattern: str,
) -> bool:
    """Check if tool use matches a permission pattern.

    Supports:
        - Simple tool match: "Bash" matches any Bash command
        - Prefix match: "Bash(git:*)" matches commands starting with "git"
        - Exact match: "Bash(git status)" matches exactly "git status"
        - Glob match: "Read(/src/**/*.py)" matches files under /src/ ending in .py
        - Wildcard tool names: "mcp__*__" matches any MCP tool
        - Directory-based: "Read(/src/foo.py)" allows any file in same directory
    """
    parsed_tool, specifier = parse_permission_pattern(pattern)

    # Tool name must match (supports wildcards like mcp__*__)
    if not fnmatch.fnmatch(tool_name, parsed_tool):
        return False

    # No specifier = match all uses of this tool
    if specifier is None:
        return True

    # Special handling for Bash - extract and match individual commands
    if tool_name == "Bash":
        full_command = tool_input.get("command", "")
        if not full_command:
            return False

        # Extract individual command names from the bash string
        cmd_names = extract_bash_commands(full_command)

        # Handle prefix match with :* suffix
        if specifier.endswith(":*"):
            prefix = specifier[:-2]
            # Match if ANY command starts with prefix OR full command starts with prefix
            if full_command.startswith(prefix):
                return True
            return any(cmd.startswith(prefix) for cmd in cmd_names)

        # Handle glob/fnmatch patterns
        if any(c in specifier for c in ['*', '?', '[']):
            # Match against full command OR any individual command
            if fnmatch.fnmatch(full_command, specifier):
                return True
            return any(fnmatch.fnmatch(cmd, specifier) for cmd in cmd_names)

        # Exact match - check full command OR any individual command name
        if full_command == specifier:
            return True
        return specifier in cmd_names

    # Special handling for Read/Write/Edit - directory-based permissions
    # Like Claude CLI: permission granted for a file extends to its directory
    if tool_name in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return False

        # Handle glob patterns (e.g., /src/**/*.py)
        if any(c in specifier for c in ['*', '?', '[']):
            return fnmatch.fnmatch(file_path, specifier)

        # Handle prefix match with :* suffix
        if specifier.endswith(":*"):
            prefix = specifier[:-2]
            return file_path.startswith(prefix)

        # Directory-based permission: if specifier is a file path,
        # allow access to any file in the same directory
        # e.g., pattern "/src/foo.py" allows "/src/bar.py"
        specifier_dir = os.path.dirname(specifier.rstrip('/'))
        file_dir = os.path.dirname(file_path)

        # If specifier looks like a directory (ends with /), match files within
        if specifier.endswith('/'):
            return file_path.startswith(specifier) or os.path.dirname(file_path) + '/' == specifier

        # Same directory = allowed
        if specifier_dir and file_dir == specifier_dir:
            return True

        # Exact match still works
        return file_path == specifier

    # Get the value to match against based on tool type
    match_value = None
    if tool_name in ("Glob", "Grep"):
        match_value = tool_input.get("pattern", "")
    elif tool_name == "WebFetch":
        match_value = tool_input.get("url", "")
    elif tool_name == "Skill":
        match_value = tool_input.get("skill", "")
    else:
        # For other tools, try common field names
        match_value = tool_input.get("command") or tool_input.get("path") or tool_input.get("query", "")

    if not match_value:
        return False

    # Handle prefix match with :* suffix (like Claude Code)
    if specifier.endswith(":*"):
        prefix = specifier[:-2]
        return match_value.startswith(prefix)

    # Handle glob/fnmatch patterns
    if any(c in specifier for c in ['*', '?', '[']):
        return fnmatch.fnmatch(match_value, specifier)

    # Exact match
    return match_value == specifier
