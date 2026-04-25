# Claude Code for Sublime Text

A Sublime Text plugin for [Kimi](https://kimi.ai/), [Claude Code](https://claude.ai/claude-code), [Ollama](https://ollama.com/), [OpenAI](https://openai.com/), [Codex CLI](https://github.com/openai/codex), [GitHub Copilot CLI](https://github.com/features/copilot/cli), and [DeepSeek](https://api-docs.deepseek.com/) integration.

Fork: https://github.com/zoranbogoevskimkd/sublime-claude

## Requirements

- Sublime Text 4
- Python 3.10+ (auto-detected; searches python3.13, 3.12, 3.11, 3.10, uv, pyenv)
- One or more backends:
  - **Kimi/Claude** — `claude` CLI (v2.1+, native binary)
  - **Ollama** — local models (qwen, llama, mistral, etc.)
  - **OpenAI-compatible** — any OpenAI-compatible API server
  - **DeepSeek** — API key only
  - **Codex CLI** — optional
  - **GitHub Copilot CLI** — optional

```bash
# Kimi/Claude (required for claude backend)
claude update   # or install from https://claude.ai/claude-code

# Ollama (optional, for local models)
brew install ollama
ollama pull qwen2.5:7b

# Codex CLI (optional)
npm install -g @openai/codex
```

**Note:** Authenticate your chosen CLI before using this plugin. For Kimi/Claude, run `claude` once to authenticate.

## Installation

1. Clone or symlink this folder to your Sublime Text `Packages` directory:

   ```bash
   # macOS
   ln -s /path/to/sublime-claude ~/Library/Application\ Support/Sublime\ Text/Packages/ClaudeCode

   # Linux
   ln -s /path/to/sublime-claude ~/.config/sublime-text/Packages/ClaudeCode

   # Windows
   mklink /D "%APPDATA%\Sublime Text\Packages\ClaudeCode" C:\path\to\sublime-claude
   ```

2. Configure your backend (see Settings below)

## Backends

The plugin auto-detects which backend to use based on your settings:

| Backend | Trigger | Description |
|---------|---------|-------------|
| **Kimi/Claude** | Default (no `openai_base_url` set) | Cloud API via `claude` CLI |
| **Ollama** | `openai_base_url` is set | Local models via Ollama |
| **OpenAI-compatible** | `openai_base_url` is set | Any OpenAI-compatible server |
| **DeepSeek** | `deepseek_api_key` is set | Anthropic-compatible endpoint |
| **Codex** | `default_backend: "codex"` | OpenAI Codex CLI |

You can also force a backend with `"default_backend": "claude" | "openai" | "deepseek" | "codex"`.

## Usage

### Commands

All commands available via Command Palette (`Cmd+Shift+P`): type "Claude"

| Command | Keybinding | Description |
|---------|------------|-------------|
| Switch Session | `Cmd+Alt+\` | Quick panel: active session, new, or switch |
| Query Selection | `Cmd+Shift+Alt+C` | Query about selected code |
| Query File | - | Query about current file |
| Add Current File | - | Add file to context |
| Add Selection | - | Add selection to context |
| Add Open Files | - | Add all open files to context |
| Add Current Folder | - | Add folder path to context |
| Clear Context | - | Clear pending context |
| New Session | - | Start a fresh session (auto-detects backend) |
| New Session with Backend... | - | Pick backend manually |
| Configure Settings | - | Open settings file |
| Undo Message | - | Rewind last conversation turn |
| Search Sessions | - | Search all sessions by title |
| Clear Notifications | - | List and clear active notifications |
| Restart Session | - | Restart current session, keep output view |
| Resume Session... | - | Resume a previous session |
| Switch Session... | - | Switch between active sessions |
| Fork Session | - | Fork current session (branch conversation) |
| Fork Session... | - | Fork from a saved session |
| Rename Session... | - | Name the current session |
| Sleep Session | - | Put session to sleep (free resources) |
| Wake Session | - | Wake a sleeping session |
| Stop Session | - | Disconnect and stop |
| Toggle Output | `Cmd+Alt+C` | Show/hide output view |
| Clear Output | `Cmd+Ctrl+Alt+C` | Clear output view |
| Interrupt | `Alt+Escape` | Stop current query |
| Permission Mode... | - | Change permission settings |
| Manage Auto-Allowed Tools... | - | Configure tools that skip permission prompts |

### Inline Input Mode

The output view features an inline input area (marked with `◎`) where you type prompts directly:

- **Enter** - Submit prompt
- **Shift+Enter** - Insert newline (multiline prompts)
- **@** - Open context menu (add files, selection, folder, or clear context)
- **Cmd+K** - Clear output
- **Alt+Escape** - Interrupt current query

When a permission prompt appears:
- **Y/N/S/A** - Respond to permission prompts

When viewing plan approval:
- **Y** - Approve plan
- **N** - Reject plan
- **V** - View plan file

### Menu

Tools > Claude Code

### Context Menu

Right-click selected text and choose "Ask Claude" to query about the selection.

## Settings

`Preferences > Package Settings > Claude Code > Settings`

### Backend Selection

The plugin auto-detects the backend from what you configure. You can also force one explicitly.

**Kimi / Claude (default):**
```json
{
    "anthropic_base_url": "https://api.kimi.com/coding/",
    "anthropic_api_key": "sk-ant-api03-...",
    "anthropic_model": "kimi-for-coding"
}
```
If left empty, the plugin uses your global `claude` CLI configuration (`~/.claude/settings.json`).

**Ollama (local):**
```json
{
    "openai_base_url": "http://localhost:11434",
    "openai_model": "qwen2.5:7b"
}
```

**OpenAI-compatible (custom server):**
```json
{
    "openai_base_url": "https://api.example.com/v1",
    "openai_api_key": "sk-...",
    "openai_model": "gpt-4o"
}
```

**DeepSeek:**
```json
{
    "deepseek_api_key": "sk-..."
}
```

**Force a specific backend:**
```json
{
    "default_backend": "claude"
}
```
Options: `"claude"`, `"openai"`, `"deepseek"`, `"codex"`

### General Settings

```json
{
    "python_path": "python3",
    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"],
    "permission_mode": "acceptEdits",
    "effort": "high"
}
```

- **python_path** — Path to Python 3.10+ interpreter. Leave as `"python3"` for auto-detection.
- **allowed_tools** — Tools the AI can use without confirmation
- **permission_mode** — `"default"`, `"acceptEdits"`, `"plan"`, `"bypassPermissions"`
- **effort** — Reasoning effort: `"low"`, `"high"`, `"max"`
- **claude_extra_args** — Extra CLI arguments for `claude` (e.g. `"--max-budget-usd 5 --verbose"`)
- **claude_side_panel** — Show chat in a narrow right-side panel (`true` / `false`). Splits window into 2 columns (78% code, 22% chat) like VS Code. Default: `true`

### Permission Modes

- `default` - Prompt for all tool actions
- `acceptEdits` - Auto-accept file operations
- `auto` - AI classifier auto-approves (Team/Enterprise plan, Sonnet 4.6+)
- `bypassPermissions` - Skip all permission checks

### Permission Prompt

When in `default` mode, tool actions show an inline prompt:

```
⚠ Allow Bash: rm file.txt?
  [Y] Allow  [N] Deny  [S] Allow 30s  [A] Always
```

- **Y** - Allow this action
- **N** - Deny (marks tool as error)
- **S** - Allow same tool for 30 seconds
- **A** - Always allow this tool (saves to project settings)

### Git & SSH Permissions

By default, the AI can run `Bash` commands but may prompt for permission on `git` and `ssh` operations. These permissions **must** be configured in the Claude CLI's own settings file (`~/.claude/settings.json` on macOS) — they cannot be set via the Sublime plugin.

**Location:** `~/.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(ssh *)",
      "Bash(scp *)"
    ]
  }
}
```

This grants the AI automatic permission to run any `git`, `ssh`, or `scp` command without prompting. Restart your Sublime session for changes to take effect.

Alternatively, use **bypassPermissions** mode (see below) to skip all permission checks globally.

### Auto-Allowed Tools

Automatically allow specific tools without permission prompts. Configure via:

**Command:** `Claude: Manage Auto-Allowed Tools...` - UI to add/remove patterns

**Settings:** Add to project `.claude/settings.json` or user `~/.claude/settings.json`:
```json
{
  "autoAllowedMcpTools": [
    "mcp__*__*",        // All MCP tools
    "mcp__plugin_*",    // All plugin MCP tools
    "Read",             // Specific tool
    "Bash"
  ]
}
```

Supports wildcards (`*`) for pattern matching. User-level settings apply to all projects, project settings override.

### Project Settings (.sublime-project)

```json
{
  "settings": {
    "claude_additional_dirs": [
      "/path/to/extra/dir",
      "~/another/dir"
    ],
    "claude_env": {
      "MY_VAR": "value"
    }
  }
}
```

- **claude_additional_dirs** — Extra `--add-dir` paths for CLI access
- **claude_env** — Environment variables passed to bridge

## Context

Add files, selections, or folders as context before your query:

1. Use **Add Current File**, **Add Selection**, etc. to queue context
2. Context shown with 📎 indicator in output view
3. Context is attached to your next query, then cleared

Requires an active session (use **New Session** first).

## Sessions

Sessions are automatically saved and can be resumed later. Each session tracks:
- Session name (auto-generated from first prompt, or manually set)
- Project directory
- Cumulative cost

**Multiple sessions per window** - Each "New Session" creates a separate output view. Switch between them like normal tabs.

Use **Claude: Resume Session...** to pick and continue a previous conversation.

After Sublime restarts, orphaned output views are registered as sleeping sessions. Press Enter or use **Wake Session** to reconnect.

### Sleep/Wake

Sessions can be put to sleep to free bridge subprocess resources while keeping the view:

- **Sleep** — kills the bridge process, view shows `⏸` prefix
- **Wake** — press Enter in a sleeping view, or use **Wake Session** command
- Switch panel shows sleeping sessions with `⏸` indicator
- `auto_sleep_minutes` setting auto-sleeps idle sessions (default: 60, 0 = disabled)

## Output View

The output view shows:

- `◎ prompt ▶` - Your query (multiline supported)
- `⋯` - Working indicator (disappears when done)
- `☐ Tool` - Tool pending
- `✔ Tool` - Tool completed
- `✘ Tool` - Tool error
- Response text with syntax highlighting
- `@done(Xs)` - Completion time

View title shows session status:
- `◉` Active + working
- `◇` Active + idle
- `•` Inactive + working
- `⏸` Sleeping (bridge stopped)
- `❓` Waiting for permission/question response

Non-Claude sessions show backend name in tab title and have distinct background colors:
- **Codex** - Green-tinted background
- **Copilot** - Purple-tinted background
- **DeepSeek** - Default background
- **OpenAI** - Default background

Supports markdown formatting and fenced code blocks with language-specific syntax highlighting.

## MCP Tools (Sublime Integration)

Allow Claude to query Sublime Text's editor state via MCP (Model Context Protocol).

### Setup

1. Run **Claude: Add MCP Tools to Project** from Command Palette
2. This creates `.claude/settings.json` with MCP server config
3. Start a new session - status bar shows `ready (MCP: sublime)`

### Available Tools

Claude gets two MCP tools:

**`sublime_eval`** - Execute Python code in Sublime's context:
```python
# Available helpers:
get_open_files()                    # List open file paths
get_symbols(query, file_path=None)  # Search project symbol index
goto_symbol(query)                  # Navigate to symbol definition
list_tools()                        # List saved tools

# Available modules: sublime, sublime_plugin
# Use 'return' to return values
```

**`sublime_tool`** - Run saved tools from `.claude/sublime_tools/<name>.py`

### Creating Saved Tools

Save reusable tools to `.claude/sublime_tools/`:

```python
# .claude/sublime_tools/find_references.py
"""Find all references to a symbol in the project"""
query = "MyClass"  # or get from context
symbols = get_symbols(query)
return [{"file": s["file"], "line": s["row"]} for s in symbols]
```

Add a docstring at the top - it's shown when calling `list_tools()`.

### Session Spawning

- `spawn_session(prompt, name?, profile?, persona_id?, backend?, fork_current?)` - Spawn a subsession
- `list_sessions()` - List active sessions in current window
- `list_personas()` - List available personas from persona server
- `list_profiles()` - List profiles and checkpoints

### Alarm System (Event-Driven Waiting)

Instead of polling for subsession completion, sessions can set alarms to "sleep" and wake when events occur. This enables efficient async coordination.

**Usage Pattern:**
```python
# Spawn a subsession
result = spawn_session("Run all tests", name="test-runner")
subsession_id = str(result["view_id"])

# Set alarm to wake when subsession completes (via MCP tool)
set_alarm(
    event_type="subsession_complete",
    event_params={"subsession_id": subsession_id},
    wake_prompt="Tests completed. Summarize results from test-runner."
)
# Main session ends query (goes idle), alarm monitors in background
# When subsession completes, alarm fires and injects wake_prompt
```

**Event Types:**
- `subsession_complete` - Wake when subsession finishes: `{subsession_id: str}`
- `time_elapsed` - Wake after N seconds: `{seconds: int}`
- `agent_complete` - Same as subsession_complete: `{agent_id: str}`

**MCP Tools:**
- `set_alarm(event_type, event_params, wake_prompt, alarm_id=None)`
- `cancel_alarm(alarm_id)`

Subsessions automatically notify the bridge when they complete. The alarm fires by injecting the wake_prompt into the main session as a new query.

## Subagents

### Custom Agents

Define additional agents in `.claude/settings.json`:

```json
{
  "agents": {
    "nim-expert": {
      "description": "Use for Nim language questions and idioms",
      "prompt": "You are a Nim expert. Help with Nim-specific patterns and macros.",
      "tools": ["Read", "Grep", "Glob"],
      "model": "haiku"
    },
    "test-runner": {
      "description": "Use to run tests and analyze failures",
      "prompt": "Run tests and analyze results. Focus on failures.",
      "tools": ["Bash", "Read"]
    }
  }
}
```

- **description** - When Claude should use this agent (use "PROACTIVELY" for auto-invocation)
- **prompt** - System prompt for the agent
- **tools** - Restrict available tools (read-only, execute-only, etc.)
- **model** - Use `haiku` for simple tasks, `sonnet`/`opus` for complex

Agents run with separate context, preventing conversation bloat. Custom agents override built-ins with the same name.

## Architecture

```
┌─────────────────┐     JSON-RPC/stdio     ┌─────────────────┐
│  Sublime Text   │ ◄────────────────────► │  bridge/main.py │ (Kimi/Claude)
│  (Python 3.8)   │                        │  (CLI wrapper)  │
│                 │                        └─────────────────┘
│                 │     JSON-RPC/stdio     ┌─────────────────┐
│                 │ ◄────────────────────► │  bridge/openai_ │ (Ollama/OpenAI)
│                 │                        │  main.py        │
│                 │                        └────────┬────────┘
│                 │     JSON-RPC/stdio     ┌────────┴────────┐
│                 │ ◄────────────────────► │  bridge/codex_  │ (Codex)
│                 │                        │  main.py        │
│                 │                        └────────┬────────┘
│                 │     JSON-RPC/stdio     ┌────────┴────────┐
│                 │ ◄────────────────────► │  bridge/copilot_│ (Copilot)
│                 │                        │  main.py        │
└─────────────────┘                        └─────────────────┘
        │
        │ Unix socket
        ▼
┌─────────────────┐     stdio     ┌─────────────────┐
│  mcp_server.py  │ ◄──────────► │  mcp/server.py  │
│  (socket server)│              │  (MCP server)   │
└─────────────────┘              └─────────────────┘
```

The plugin runs in Sublime's Python 3.8 environment and spawns a separate bridge process using Python 3.10+. Each bridge translates between Sublime's JSON-RPC protocol and the backend CLI:
- **Kimi/Claude**: `bridge/main.py` — Wraps `claude` CLI v2.1+ with `--output-format=stream-json`
- **Ollama/OpenAI**: `bridge/openai_main.py` — Native Ollama `/api/chat` + OpenAI-compatible
- **Codex**: `bridge/codex_main.py` — Codex app-server protocol
- **Copilot**: `bridge/copilot_main.py` — GitHub Copilot SDK
- **DeepSeek**: `bridge/main.py` — Same Claude bridge, Anthropic-compatible endpoint

```
sublime-claude/
├── claude_code.py         # Plugin entry point
├── core.py                # Session lifecycle
├── commands.py            # Plugin commands
├── session.py             # Session class
├── output.py              # Output rendering
├── listeners.py           # Event handlers
├── rpc.py                 # JSON-RPC client
├── mcp_server.py          # MCP socket server
├── bridge/
│   ├── main.py            # Claude bridge (Claude CLI wrapper)
│   ├── openai_main.py     # Ollama/OpenAI bridge
│   ├── codex_main.py      # Codex bridge (app-server)
│   ├── copilot_main.py    # Copilot bridge (Copilot SDK)
│   └── rpc_helpers.py     # Shared JSON-RPC helpers
├── mcp/server.py          # MCP protocol server
│
└── Core Utilities:
    ├── constants.py       # Config & magic strings
    ├── logger.py          # Unified logging
    ├── error_handler.py   # Error handling
    ├── session_state.py   # State machine
    ├── settings.py        # Settings loader
    ├── prompt_builder.py  # Prompt utilities
    ├── tool_router.py     # Tool dispatch
    └── context_parser.py  # Context menus
```

All bridges emit identical JSON-RPC notifications to Sublime, so the output view, permissions, and MCP tools work the same regardless of backend.

## License

VCL (Vibe-Coded License) - see LICENSE
