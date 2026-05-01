# Development Notes

## Architecture

See [README.md](README.md) for full architecture diagram. Key files:

```
Core:
  session.py              # Main Session class (combines all mixins)
  session_core.py         # Lifecycle, bridge, heartbeat, auto-restart
  session_query.py        # Query handling, smart context, @-commands
  session_permissions.py  # Permission/plan/question UI
  session_env.py          # Environment & persistence helpers

Output:
  output.py               # Rendering, incremental updates, input mode
  output_models.py        # ToolCall, Conversation, Todo data classes
  output_format.py        # Tool result formatting, diff rendering, icons

Commands (split by domain):
  commands_core.py        # Core commands (query, interrupt, toggle)
  commands_session.py     # Session commands (new, resume, wake, fork)
  commands_context.py     # Context commands (add file, attach, drag-drop)
  commands_tools.py       # Tool commands (undo edit, MCP marketplace)
  commands_ui.py          # UI commands (usage graph, swarm monitor)
  commands_voice.py       # Voice input (macOS only)

Context & Search:
  smart_context.py        # Auto context expansion (git, symbols, scope)
  codebase_search.py      # TF-IDF @codebase search (SQLite index)
  web_search.py           # DuckDuckGo @web search (no API key)
  context_parser.py       # Context menus & @ picker

Bridge (Python 3.10+ subprocess):
  bridge/
    base.py               # Base bridge class
    main.py               # Claude/Kimi bridge
    openai_main.py        # Ollama/OpenAI bridge
    codex_main.py         # Codex bridge
    copilot_main.py       # Copilot bridge
    rpc_helpers.py        # Shared JSON-RPC helpers
```

Plugin code runs in Sublime's Python 3.8 host. Bridge subprocess auto-detects Python 3.10+.

## Sublime Text Module Caching

- Sublime caches imported modules aggressively
- Touching `claude_code.py` triggers reload of all `.py` files in package root
- Enum classes cause issues when cached — use plain string constants
- Dataclass definitions also get cached

## Output View

- Read-only scratch view controlled by plugin
- Region-based rendering allows in-place updates
- Custom syntax highlighting (ClaudeOutput.sublime-syntax)
- Ayu Mirage theme (ClaudeOutput.hidden-tmTheme)

**Symbols:**
- `○` Tool pending / idle session
- `●` Tool done (green) / error (red)
- `⚙` Background tool
- `◎` Prompt header
- `── time · ctx ──` Completion footer

**Tool icons by type:**
- Read: `📄` (with file-type icon: 🐍 .py, ⚛️ .tsx, ☕ .java)
- Edit: `✎`
- Write: `✍`
- Bash: `⚡` (with box-drawing output borders)
- Glob/Grep: `🔍`
- WebSearch/WebFetch: `🌐`
- Task: `⚙`
- TodoWrite: `📋`
- Skill: `🎯`
- ask_user: `❓`

**File paths:** Shortened with `_shorten_path()` — home dir collapsed, truncated from left.

**Diff format:** VS Code-like aligned columns:
```
│ + │ added line
│ - │ removed line
│   │ context line
```

## Permission UI

Inline permission prompts in output view:
- `[Y] Allow` — one-time allow
- `[N] Deny` — deny (marks tool as error)
- `[S] Allow 30s` — auto-allow same tool for 30 seconds
- `[A] Always` — auto-allow this tool pattern
- `[B] Batch Allow` — auto-approve all Write/Edit for current query

Clickable buttons + keyboard shortcuts (Y/N/S/A/B keys).

**Permission modes:**
| Mode | Behavior | Safest for |
|------|----------|------------|
| `default` | Prompt for all | Production code |
| `acceptEdits` | Auto-accept file ops; prompt Bash/Web | Daily dev |
| `bypassPermissions` | Skip all checks | Quick experiments |

Multiple permission requests are queued — only one shown at a time.

## Session Management

- Sessions keyed by output view id (not window id) — multiple per window
- Sessions saved to `.sessions.json` with name, project, cost, query count, tags
- Resume via `session_id` passed to bridge
- `plugin_loaded` hook reconnects orphaned output views after Sublime restart
- Closing output view stops its session
- **Auto-restart on bridge crash** — heartbeat every 30s, auto-restarts dead bridge

**View title indicators:**
- `◉` Active + working
- `◇` Active + idle
- `•` Inactive + working
- `⏸` Sleeping (bridge stopped)
- `❓` Waiting for permission/question

## MCP Integration

- `mcp_server.py` — Unix socket server in Sublime, handles eval requests
- `mcp/server.py` — MCP stdio server, connects to Sublime socket
- Bridge loads MCP config from `~/.claude.json`, then `.claude/settings.json`, then `.mcp.json`
- Status bar shows `ready (MCP: sublime)` on init

**MCP Tools:**
- Editor: `get_window_summary`, `find_file`, `get_symbols`, `goto_symbol`, `read_view`
- Sessions: `spawn_session`, `list_sessions`
- Alarms: `set_alarm`, `cancel_alarm`
- User: `ask_user` — ask questions via quick panel
- Custom: `sublime_eval`, `sublime_tool`, `list_tools`

## Alarm System (Event-Driven Waiting)

Sessions set alarms to "sleep" and wake when events occur. Alarm fires by injecting `wake_prompt` into the session.

**Event types:**
- `time_elapsed` — fire after N seconds
- `subsession_complete` — fire when subsession finishes
- `agent_complete` — alias for subsession_complete

**Usage:**
```python
set_alarm(
    event_type="subsession_complete",
    event_params={"subsession_id": subsession_id},
    wake_prompt="Tests completed. Summarize results."
)
```

## Subagents

Loaded from `.claude/settings.json` `agents` key. Built-in agents merged with project-defined (project overrides).

**Built-in agents:**
- `planner` — creates implementation plan (haiku)
- `reporter` — updates progress report (haiku)

## Critical Invariants for AI Agents

**Session Resume — MUST pass `resume_id`:**
```python
# CORRECT
session = Session(window, resume_id=saved_session_id)
# WRONG — loses ALL history
session = Session(window)
```

**Red Flags — STOP and Verify:**
1. Removing function parameters — likely breaks callers
2. Changing default values — silent behavior change
3. "Simplifying" by removing steps — those existed for a reason
4. Any change justified by "cleaner" — clean != correct

**Rules:**
1. No silent behavior changes — state old vs new behavior
2. Distrust your own simplifications — check git history first
3. Context loss is the enemy — write decisions immediately
4. Preserve load-bearing code — "unnecessary" code is often critical
