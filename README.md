# Claude Code for Sublime Text — Extended

A Sublime Text plugin for [Kimi](https://kimi.ai/), [Claude Code](https://claude.ai/claude-code), [Ollama](https://ollama.com/), [OpenAI](https://openai.com/), [Codex CLI](https://github.com/openai/codex), [GitHub Copilot CLI](https://github.com/features/copilot/cli), and [DeepSeek](https://api-docs.deepseek.com/) integration.

**Built on top of [tommo/sublime-claude](https://github.com/tommo/sublime-claude)** — extended with additional UI features, monitoring tools, an MCP marketplace, bug fixes, and a comprehensive test suite.

**Repository:** https://github.com/KalimeroMK/sublime-claude

## What's New

This build extends the base project with additional features, bug fixes, and a full test suite.

### Additional Features (not in the original)

| Feature | Description |
|---------|-------------|
| **Context Window Gauge** | Visual 10-segment bar in the status bar showing context usage percentage with color coding (🟢🟡🔴) |
| **Session Tags** | Label sessions with comma-separated tags (e.g. `bugfix, refactor`) — shown in status bar and persisted across restarts |
| **Attach File / Image** | Single command (`Cmd+Shift+F`) for attaching any file or image to context — auto-detects file type and sends images as binary |
| **Drag & Drop** | Drop files or images directly onto the output view — automatically added to context |
| **Token Usage Graph** | `Claude: Show Usage Graph` — ASCII bar chart of token usage per query, 100-query history persisted |
| **Agent Swarm Monitor** | `Claude: Swarm Monitor` — dashboard showing all active sessions, subsessions, statuses, and costs |
| **MCP Marketplace** | `Claude: MCP Marketplace` — browse and install 12 curated MCP servers (fetch, filesystem, github, git, postgres, sqlite, brave-search, puppeteer, sequential-thinking, memory, slack, sentry) with one-click auto-install |
| **Diff Preview & Undo** | Unified diff preview for Write/Edit tools — see changes before approving, with one-click undo after execution |
| **Smart Context** | Auto-adds current scope, git-modified files, relevant open files, and symbol definitions to queries |
| **Comprehensive Test Suite** | 197 unit tests covering all core utilities, running in ~0.03s with a mock Sublime API |

### Bug Fixes

| Issue | Fix |
|-------|-----|
| Import error | Fixed `ClaudeInsertCommand`/`ClaudeReplaceCommand` imported from wrong module |
| Python 3.9 compatibility | Replaced `int \| None`, `dict[]`, `list[]` with `Optional`, `Dict`, `List` for Sublime's Python 3.8 |
| Mouse selection unresponsive | Fixed dynamic `read_only` toggling to allow selection while protecting conversation history |
| Input mode leaks | Blocked typing/pasting outside the input area when in input mode |
| Orphaned view reconnection | Fixed blank lines being added on every reconnect after Sublime restart |
| Reset input mode | Fixed command to properly re-enter input mode after cleanup instead of leaving view in an unusable state |
| Duplicate event handlers | Removed duplicate `on_activated` and non-existent imports that caused runtime errors |
| Dead code cleanup | Removed unused commands and modules that added unnecessary bloat |

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
   git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode

   # Linux
   cd ~/.config/sublime-text/Packages
   git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode

   # Windows
   cd "%APPDATA%\Sublime Text\Packages"
   git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode
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
| **Undo Last Edit** | - | Undo the most recent Write/Edit file change |
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
| **Attach File...** | `Cmd+Shift+F` | Attach any file or image to context (auto-detects type) |
| **Swarm Monitor** | - | Dashboard of all active sessions and subsessions |
| **MCP Marketplace** | - | Browse and install 12+ MCP servers with one click |
| **Generate Commit Message** | - | Generate commit message from `git diff --staged` |
| **Git Status** | - | Show `git status --short` in output view |
| **Voice Input** | `Cmd+Shift+R` | Record audio, transcribe via Whisper API, insert text (macOS only) |

### Inline Input Mode

The output view features an inline input area (marked with `◎`) where you type prompts directly:

- **Enter** - Submit prompt
- **Shift+Enter** - Insert newline (multiline prompts)
- **@** - Open context menu (add files, @codebase, @git, folder, or clear context)
- **Alt+Escape** - Interrupt current query

When a permission prompt appears:
- **Y/N** - Allow or deny the tool
- **S** - Allow same tool for 30 seconds
- **A** - Always allow this tool pattern
- **B** - **Batch Allow** — auto-approves all Write/Edit tools for the current query (useful for multi-file refactoring)

For Write/Edit tools, the permission block shows a **diff preview** so you can see exactly what will change before approving.

### Attach File / Image

**`Claude: Attach File...`** (`Cmd+Shift+F`) — attach any file to the current session:
- **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`) → sent as binary context with correct MIME type
- **Regular files** → sent as text content
- Uses native macOS file picker (or input panel on other platforms)

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
    "effort": "high",
    "smart_context_enabled": true,
    "auto_add_current_file": true
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

### Smart Context (Auto)

The plugin automatically enriches queries with relevant context when no explicit context is provided:

- **Current scope** — function/class at cursor position (via `view.symbols()`)
- **Git-modified files** — staged files + last 3 commits
- **Relevant open files** — same directory, same extension (score-based ranking)
- **Symbol definitions** — uses Sublime's built-in symbol index (`window.symbol_locations()`)

Works with any language server (Intelephense, LSP, etc.) without external dependencies.

**Settings:**
```json
{
    "smart_context_enabled": true,
    "auto_add_current_file": true
}
```

Disable `smart_context_enabled` to skip auto-context injection. Disable `auto_add_current_file` to prevent automatically adding the active file to context.

### @-Commands

Type `@` in the inline input area to trigger the context menu, or type commands directly in your prompt:

| Command | Description |
|---------|-------------|
| `@codebase <query>` | Search entire project for relevant code (TF-IDF, no API needed) |
| `@git` | Add `git diff --staged` (or unstaged) to context |
| `@file:<path>` | Inline reference to a specific file |

**`@codebase`** finds the most relevant files based on your query keywords and adds them to context automatically:

```
◎ @codebase how does authentication work? ▶
```

This will:
1. Index the project (first use only, ~1-10s depending on size)
2. Search for files matching keywords like `auth`, `login`, `authenticate`
3. Add top 5 matching code chunks to your query context

**How it works:** Uses TF-IDF over a local SQLite database — no embeddings API or Ollama required. Indexes are stored in `.claude_codebase.db` inside your project root and auto-refresh every 24 hours.

### Related Files (Manual)

When you explicitly add a file, related files are automatically included (up to 5):

- **Test/sibling files** — `user.py` → `user_test.py`, `test_user.py`
- **Imported modules** — parsed from `import` / `from` / `require` / `use` statements in the first 30 lines
- **Convention-based paths** — `User.php` → `controllers/UserController.php`

Supported: Python, JavaScript/TypeScript, PHP, Go.

Disable by removing the `_add_related_files` call in `session.py` if you prefer manual context only.

## Voice Input

**`Claude: Voice Input`** (`Cmd+Shift+R`) — speak instead of typing (macOS only):

1. Press `Cmd+Shift+R` to start recording
2. Speak your prompt
3. Press `Cmd+Shift+R` again to stop
4. Audio is sent to OpenAI Whisper API and transcribed
5. Text is inserted into the input area

**Requirements:**
- macOS (`afrecord` for audio capture)
- OpenAI API key set in settings: `"openai_api_key": "sk-..."`

**Privacy note:** Audio is sent to OpenAI's Whisper API for transcription. For local-only transcription, use macOS built-in dictation (Fn twice) instead.

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
- `✔ Tool` - Tool completed (with diff preview for Write/Edit)
- `✘ Tool` - Tool error
- Response text with syntax highlighting
- `@done(Xs)` - Completion time

### Diff Preview & Undo

When the AI uses **Write** or **Edit** tools:

1. **Before execution** — the permission block shows a diff preview of the proposed changes
2. **After execution** — the completed tool line shows the actual unified diff with an `[Undo]` button
3. **Hover over `[Undo]`** — shows a popup with a link to revert the file to its original state
4. **Command Palette** — `Claude: Undo Last Edit` to undo the most recent file change

Diffs are computed from the actual file snapshot taken before execution, so undo is accurate even for multiple consecutive edits.

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

### Agent Swarm Monitor

**`Claude: Swarm Monitor`** — dashboard showing all active sessions in the current window:

| Status | Name | Backend | Queries | Cost | Parent | Tags |
|--------|------|---------|---------|------|--------|------|
| 🟢 Working | Main | claude | 5 | $0.1234 | — | bugfix |
| 💤 Sleeping | Worker | openai | 2 | $0.0567 | Main | — |
| ⏸ Idle | Cache | deepseek | 10 | $0.8901 | — | refactor |

- **Status icons:** 🟢 Working / 💤 Sleeping / 🟡 Connecting / ⏸ Idle
- **Subsession tracking** — shows parent session name
- **Window-scoped** — only shows sessions in the current Sublime window

### MCP Marketplace

**`Claude: MCP Marketplace`** — browse and install MCP servers with one click:

Available servers (12 curated):
- **Web Fetch** — fetch any web page for context
- **File System** — read/write files in allowed directories
- **GitHub** — search repos, read issues/PRs
- **Git** — `git log`, `diff`, `blame`
- **PostgreSQL / SQLite** — query databases
- **Brave Search** — web search via API
- **Puppeteer** — browser automation
- **Sequential Thinking** — structured problem-solving
- **Memory** — persistent knowledge graph across sessions
- **Slack** — read channels, send messages
- **Sentry** — read and analyze issues

**How it works:**
1. Select a server from the quick panel
2. Confirm installation (shows required env vars like `GITHUB_PAT`)
3. Automatically updates `.mcp.json` in your project (or `~/.claude.json` globally)
4. Uses `npx -y` — no manual `npm install` needed
5. Template variables auto-resolved: `${project_root}`, `${database_path}`

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

**197 tests** covering all core utilities:
- Context window gauge, session tags, drag-drop, usage graph
- Attach commands (image/file auto-detect, MIME mapping)
- Swarm monitor (status icons, session tracking)
- MCP marketplace (config loading, install logic, template variables)
- Smart context (scope, git, open files, symbol definitions)
- Diff preview and undo logic
- Constants, error handling, logging, prompt building
- Command parsing, context parsing, session state machine
- JSON-RPC client, tool routing, settings merging

All tests run in ~0.03s without requiring Sublime Text to be open (uses mock API).

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
├── session_core.py        # Session class (lifecycle, bridge, notifications)
├── session_query.py       # Query handling (smart context, file attachment)
├── session_permissions.py # Permission/plan/question UI handling
├── session_env.py         # Environment & session persistence helpers
├── output.py              # Output view rendering
├── output_models.py       # Data classes (ToolCall, Conversation, etc.)
├── output_format.py       # Tool result formatting (diffs, etc.)
├── listeners.py           # Event handlers
├── rpc.py                 # JSON-RPC client
├── mcp_server.py          # MCP socket server
├── smart_context.py       # Auto context expansion (git, symbols, scope)
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
