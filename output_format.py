"""Tool result formatting — pure functions, no view dependencies."""
import os
import re
import json
import codecs
import difflib

from .constants import TOOL_STATUS_DONE as DONE, TOOL_STATUS_ERROR as ERROR, TOOL_STATUS_BACKGROUND as BACKGROUND


def format_bash_result(result: str) -> str:
    """Format Bash command output with box-drawing style."""
    if not result or not result.strip():
        return ""
    lines = result.strip().split("\n")
    max_head = 3
    max_tail = 5
    max_width = 80

    def truncate(line):
        return line[:max_width] + "…" if len(line) > max_width else line

    # Box drawing style like VS Code terminal
    output_lines = ["    ┌─ OUT ─────────────────────────────────────────"]
    if len(lines) <= max_head + max_tail:
        for line in lines:
            output_lines.append(f"    │ {truncate(line)}")
    else:
        for line in lines[:max_head]:
            output_lines.append(f"    │ {truncate(line)}")
        omitted = len(lines) - max_head - max_tail
        output_lines.append(f"    │ ... ({omitted} more lines)")
        for line in lines[-max_tail:]:
            output_lines.append(f"    │ {truncate(line)}")
    output_lines.append("    └───────────────────────────────────────────────")

    return "\n" + "\n".join(output_lines)


def format_glob_result(result: str) -> str:
    """Format Glob result as file count."""
    if not result or not result.strip():
        return " → 0 files"
    lines = [l for l in result.strip().split("\n") if l.strip()]
    return f" → {len(lines)} files"


def format_grep_result(result: str) -> str:
    """Format Grep result as match count."""
    if not result or not result.strip():
        return " → 0 matches"
    lines = [l for l in result.strip().split("\n") if l.strip()]
    files = set()
    for line in lines:
        if ":" in line:
            files.add(line.split(":")[0])
    if files:
        return f" → {len(lines)} matches in {len(files)} files"
    return f" → {len(lines)} matches"


def format_read_result(result: str) -> str:
    """Format Read result as line count."""
    if not result or not result.strip():
        return " → 0 lines"
    lines = result.strip().split("\n")
    return f" → {len(lines)} lines"


def format_mcp_result(result: str) -> str:
    """Format generic MCP tool result."""
    try:
        match = re.search(r"'text':\s*'((?:[^'\\]|\\.)*)'", result)
        if not match:
            match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', result)
        if match:
            text = match.group(1)
            text = text.replace('\\n', '\n').replace("\\'", "'").replace('\\"', '"')
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    compact = json.dumps(data, ensure_ascii=False)
                    if len(compact) < 60:
                        return f" → {compact}"
                    lines = []
                    for k, v in list(data.items())[:5]:
                        v_str = str(v)[:50]
                        lines.append(f"    │ {k}: {v_str}")
                    if len(data) > 5:
                        lines.append(f"    │ ... ({len(data) - 5} more)")
                    return "\n" + "\n".join(lines)
                elif isinstance(data, list):
                    return f" → [{len(data)} items]"
            except Exception:
                if len(text) > 60:
                    return f" → {text[:60]}..."
                return f" → {text}" if text else ""
        return ""
    except Exception:
        return ""


def format_ask_user_result(result: str, question: str) -> str:
    """Format ask_user Q&A result."""
    try:
        match = re.search(r'"answer":\s*"((?:[^"\\]|\\.)*)"', result)
        if match:
            answer = match.group(1)
            answer = answer.replace('\\\\u', '\\u')
            answer = codecs.decode(answer, 'unicode_escape')
            return f"\n    → {answer}"
        if '"cancelled": true' in result or '"cancelled":true' in result:
            return "\n    → (cancelled)"
        return ""
    except Exception as e:
        print(f"[Claude] format_ask_user_result error: {e}, result={result[:50]}")
        return ""


def find_line_number(file_path: str, old: str, new: str) -> int:
    """Find the line number where old_string (or new_string) occurs in file."""
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        search = new if new else old
        if not search:
            return None
        pos = content.find(search)
        if pos == -1 and old:
            pos = content.find(old)
        if pos == -1:
            return None
        return content[:pos].count('\n') + 1
    except Exception:
        return None


def format_edit_diff(old: str, new: str, max_lines: int = 30) -> str:
    """Format Edit diff with optional truncation."""
    if not old and not new:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    if old_lines and not old_lines[-1].endswith('\n'):
        old_lines[-1] += '\n'
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
    if not diff:
        return ""
    diff_lines = []
    for line in diff:
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        diff_lines.append(line.rstrip('\n'))
    if not diff_lines:
        return ""
    return _format_diff_block(diff_lines, max_lines=max_lines)


def extract_diff_line_num(unified: str) -> int:
    """Extract the starting line number from the first hunk header of a unified diff."""
    m = re.search(r'^@@\s+-(\d+)', unified, re.MULTILINE)
    if m:
        return int(m.group(1))
    return 0


def format_unified_diff(unified: str, max_lines: int = 30) -> str:
    """Render a pre-computed unified diff, stripping headers, with optional truncation."""
    if not unified:
        return ""
    lines = []
    for line in unified.splitlines():
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        lines.append(line)
    if not lines:
        return ""
    return _format_diff_block(lines, max_lines=max_lines)


def _format_diff_block(lines: list, max_lines: int = 30) -> str:
    """Format diff lines with VS Code-like style — aligned columns."""
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append(f"... ({omitted} more lines)")

    result = []
    for line in lines:
        if not line:
            continue
        marker = line[0]
        content = line[1:] if len(line) > 1 else ""

        if marker == "+":
            result.append(f"    │ + │ {content}")
        elif marker == "-":
            result.append(f"    │ - │ {content}")
        elif marker == "^":
            result.append(f"    │ ^ │ {content}")
        else:
            result.append(f"    │   │ {content}")

    return "\n" + "\n".join(result)


def format_tool_detail(tool) -> str:
    """Format tool detail string for display.

    Args:
        tool: A ToolCall-like object with name, tool_input, result, status attributes.
    """
    detail = ""
    tool_input = tool.tool_input or {}

    if tool.name == "EnterPlanMode":
        return ": entering plan mode..."
    elif tool.name == "ExitPlanMode":
        allowed = tool_input.get("allowedPrompts", [])
        if allowed:
            return f": {len(allowed)} requested permissions"
        return ": awaiting approval..."

    if tool.name == "Skill" and "skill" in tool_input:
        detail = f": {tool_input['skill']}"
    elif tool.name == "Bash" and "command" in tool_input:
        detail = f": {tool_input['command']}"
        if tool.result and tool.status in (DONE, ERROR):
            detail += format_bash_result(tool.result)
    elif tool.name == "Read" and "file_path" in tool_input:
        detail = f": {tool_input['file_path']}"
        if tool.result and tool.status == DONE:
            detail += format_read_result(tool.result)
    elif tool.name == "Edit" and "file_path" in tool_input:
        file_path = tool_input['file_path']
        # Prefer pre-computed diff from snapshot (actual file changes)
        if getattr(tool, "diff", None):
            diff_str = format_unified_diff(tool.diff)
            line_num = extract_diff_line_num(tool.diff)
            detail = f": {file_path}:{line_num}" if line_num else f": {file_path}"
            if diff_str:
                detail += diff_str
        else:
            old = tool_input.get("old_string", "")
            new = tool_input.get("new_string", "")
            unified = tool_input.get("unified_diff", "")
            if unified:
                diff_str = format_unified_diff(unified)
                line_num = extract_diff_line_num(unified)
                detail = f": {file_path}:{line_num}" if line_num else f": {file_path}"
            else:
                line_num = find_line_number(file_path, old, new)
                diff_str = format_edit_diff(old, new)
                detail = f": {file_path}:{line_num}" if line_num else f": {file_path}"
            if diff_str:
                detail += diff_str
        if getattr(tool, "snapshot", None) is not None and tool.status == DONE:
            detail += "  [Undo]"
    elif tool.name == "Write" and "file_path" in tool_input:
        file_path = tool_input['file_path']
        detail = f": {file_path}"
        if getattr(tool, "diff", None):
            diff_str = format_unified_diff(tool.diff)
            if diff_str:
                detail += diff_str
        if getattr(tool, "snapshot", None) is not None and tool.status == DONE:
            detail += "  [Undo]"
    elif tool.name == "Glob" and "pattern" in tool_input:
        detail = f": {tool_input['pattern']}"
        if tool.result and tool.status == DONE:
            detail += format_glob_result(tool.result)
    elif tool.name == "Grep" and "pattern" in tool_input:
        detail = f": {tool_input['pattern']}"
        if tool.result and tool.status == DONE:
            detail += format_grep_result(tool.result)
    elif tool.name == "WebSearch" and "query" in tool_input:
        detail = f": {tool_input['query']}"
    elif tool.name == "WebFetch" and "url" in tool_input:
        detail = f": {tool_input['url']}"
    elif tool.name == "Task" and "subagent_type" in tool_input:
        subagent = tool_input["subagent_type"]
        desc = tool_input.get("description", "")
        detail = f": {subagent}" + (f" - {desc}" if desc else "")
    elif tool.name == "NotebookEdit" and "notebook_path" in tool_input:
        detail = f": {tool_input['notebook_path']}"
    elif tool.name == "TodoWrite" and "todos" in tool_input:
        todos = tool_input["todos"]
        count = len(todos) if isinstance(todos, list) else "?"
        detail = f": {count} task{'s' if count != 1 else ''}"
    elif tool.name in ("ask_user", "mcp__sublime__ask_user") and "question" in tool_input:
        question = tool_input["question"]
        detail = f": {question}"
        if tool.result and tool.status == DONE:
            detail += format_ask_user_result(tool.result, question)
    elif tool.name.startswith("mcp__sublime__") and tool.result and tool.status == DONE:
        detail += format_mcp_result(tool.result)

    if tool.status == BACKGROUND:
        detail += " (background)"

    return detail
