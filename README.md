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

1. Clone this repo into your Sublime Text `Packages` directory:

   ```bash
   # macOS
   cd ~/Library/Application\ Support/Sublime\ Text/Packages
   git clone https://github.com/zoranbogoevskimkd/sublime-claude ClaudeCode

   # Linux
   cd ~/.config/sublime-text/Packages
   git clone https://github.com/zoranbogoevskimkd/sublime-claude ClaudeCode

   # Windows
   cd "%APPDATA%\Sublime Text\Packages"
   git clone https://github.com/zoranbogoevskimkd/sublime-claude ClaudeCode
   ```

   Or symlink an existing clone:

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
| Query | `Cmd+Alt+C` | Send a query to Claude |
| Query Selection | `Cmd+Shift+Alt+C` | Query about selected code |
| Query File | - | Query about current file |
| Add Current File | - | Add file to context (+ auto-related files) |
| Add Selection | - | Add selection to context |
| Add Open Files | - | Add all open files to context |
| Add Current Folder | - | Add folder path to context |
| Clear Context | - | Clear pending context |
| New Session | - | Start a fresh session (auto-detects backend) |
| New Session with Backend... | - | Pick backend manually |
| Configure Settings | - | Open settings file |
| Undo Message | - | Rewind last conversation turn |
| Restart Session | - | Restart current session, keep output view |
| Resume Session... | - | Resume a previous session |
| Switch Session... | - | Switch between active sessions |
| Fork Session | - | Fork current session (branch conversation) |
| Fork Session... | - | Fork from a saved session |
| Rename Session... | - | Name the current session |
| **Tag Session...** | - | Add comma-separated tags to session |
| Stop Session | - | Disconnect and stop |
| Toggle Output | `Cmd+Alt+C` | Show/hide output view |
| Interrupt | `Alt+Escape` | Stop current query |
| **Show Usage Graph** | - | ASCII bar chart of token usage per query |

### Inline Input Mode

The output view features an inline input area (marked with `◎`) where you type prompts directly:

- **Enter** - Submit prompt
- **Shift+Enter** - Insert newline (multiline prompts)
- **@** - Open context menu (add files, selection, folder, or clear context)
- **Alt+Escape** - Interrupt current query

When a permission prompt appears:
- **Y/N** - Allow or deny the tool

### Drag & Drop

Drop files directly onto the **Claude output view**:
- **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`) → automatically added as image context
- **Regular files** → automatically added as file context

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
- `bypassPermissions` - Skip all permission checks

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

### Smart Context

When you add a file, related files are automatically included (up to 5):

- **Test/sibling files** — `user.py` → `user_test.py`, `test_user.py`
- **Imported modules** — parsed from `import` / `from` / `require` / `use` statements in the first 30 lines
- **Convention-based paths** — `User.php` → `controllers/UserController.php`

Supported: Python, JavaScript/TypeScript, PHP, Go.

Disable by removing the `_add_related_files` call in `session.py` if you prefer manual context only.

## Sessions

Sessions are automatically saved and can be resumed later. Each session tracks:
- Session name (auto-generated from first prompt, or manually set)
- **Tags** — comma-separated labels for organization (e.g. `bugfix, refactor`)
- Project directory
- Cumulative cost
- Per-query token usage history (up to 100 queries)

**Multiple sessions per window** - Each "New Session" creates a separate output view. Switch between them like normal tabs.

Use **Claude: Resume Session...** to pick and continue a previous conversation.

After Sublime restarts, orphaned output views are registered as sleeping sessions. Press Enter or use **Wake Session** to reconnect.

### Session Tags

Tag sessions for organization:
1. **Claude: Tag Session...** — enter comma-separated tags
2. Tags appear in status bar as `[tag1,tag2]`
3. Tags are persisted in `.sessions.json` and restored on reconnect

### Token Usage Graph

**Claude: Show Usage Graph** displays an ASCII bar chart of token usage per query:
```
Q  1: in [██████░░░░░░░░░░░░░░] 5,000
      out [▓░░░░░░░░░░░░░░░░░░░] 1,200
Q  2: in [██████████░░░░░░░░░░] 8,000
      out [▓▓▓▓░░░░░░░░░░░░░░░░] 3,000
...
**Total: 40,000 in + 13,200 out = 53,200 tokens**
**Queries: 4 | Est. cost: $0.0234**
```

Tracks up to 100 queries per session, persisted across restarts.

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

### Context Window Gauge

Status bar shows a visual gauge of context window utilization:
```
Claude: ready, effort:high, sonnet.4.5, ctx:45k, 🟡 ████████░░ 75%
```

- **10-segment bar** (`█` = filled, `░` = empty)
- **Color coding:** 🟢 <70%, 🟡 70-90%, 🔴 >90%
- **Model-aware limits:** 200K Claude, 128K GPT-4o, 64K DeepSeek, 32K Mistral

## MCP Tools (Sublime Integration)

Allow Claude to query Sublime Text's editor state via MCP (Model Context Protocol).

### Setup

1. MCP config is loaded from `~/.claude.json` (global), then project `.claude/settings.json`, then `.mcp.json`
2. Start a new session - status bar shows `ready (MCP: sublime)`

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

## Tests

Run the test suite from the project root:

```bash
cd ~/PhpstormProjects/sublime-claude
python3 -m unittest discover tests/ -v
```

**151 tests** covering all core utilities:
- Context window gauge, session tags, drag-drop, usage graph
- Constants, error handling, logging, prompt building
- Command parsing, context parsing, session state machine
- JSON-RPC client, tool routing, settings merging

All tests run in ~0.02s without requiring Sublime Text to be open (uses mock API).

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
└── Utilities:
    ├── constants.py       # Config & magic strings
    ├── context_parser.py  # Context menus & @ picker
    ├── error_handler.py   # Error handling decorators
    ├── logger.py          # File-based logging
    ├── prompt_builder.py  # Prompt construction
    ├── command_parser.py  # Slash command parsing
    ├── session_state.py   # Session state machine
    ├── settings.py        # Settings loading & merging
    └── tool_router.py     # MCP tool dispatch
```

All bridges emit identical JSON-RPC notifications to Sublime, so the output view, permissions, and MCP tools work the same regardless of backend.

## License

VCL (Vibe-Coded License) - see LICENSE
