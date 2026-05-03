# Claude Code for Sublime Text — Extended

A Sublime Text plugin for [Kimi](https://kimi.ai/), [Claude Code](https://claude.ai/claude-code), [Ollama](https://ollama.com/), [OpenAI](https://openai.com/), [Codex CLI](https://github.com/openai/codex), [GitHub Copilot CLI](https://github.com/features/copilot/cli), and [DeepSeek](https://api-docs.deepseek.com/) integration.

**Built on top of [tommo/sublime-claude](https://github.com/tommo/sublime-claude)** — extended with additional UI features, monitoring tools, an MCP marketplace, bug fixes, and a comprehensive test suite.

**Repository:** https://github.com/KalimeroMK/sublime-claude

---

## Table of Contents

- [Quick Start](#quick-start)
- [Comparison with Original](#comparison-with-original)
- [What's New](#whats-new)
- [Requirements](#requirements)
- [Installation](#installation)
- [Backends](#backends)
- [Usage](#usage)
  - [Commands](#commands)
  - [Inline Input Mode](#inline-input-mode)
  - [Attach File / Image](#attach-file--image)
  - [Drag & Drop](#drag--drop)
- [Settings](#settings)
  - [Backend Selection](#backend-selection)
  - [General Settings](#general-settings)
  - [Permission Modes](#permission-modes)
  - [Project Settings](#project-settings-sublime-project)
- [Context](#context)
  - [Smart Context (Auto)](#smart-context-auto)
  - [@-Commands](#-commands)
  - [Related Files (Manual)](#related-files-manual)
- [Voice Input](#voice-input)
- [Terminal Integration](#terminal-integration)
- [Sessions](#sessions)
  - [Auto-Restart on Bridge Crash](#auto-restart-on-bridge-crash)
  - [Session Tags](#session-tags)
  - [Token Usage Graph](#token-usage-graph)
  - [Persistent Memory](#persistent-memory)
- [Output View](#output-view)
  - [Diff Preview & Undo](#diff-preview--undo)
  - [Context Window Gauge](#context-window-gauge)
  - [Agent Swarm Monitor](#agent-swarm-monitor)
  - [Skills Marketplace](#skills-marketplace)
  - [MCP Marketplace](#mcp-marketplace)
- [MCP Tools (Sublime Integration)](#mcp-tools-sublime-integration)
- [Subagents](#subagents)
- [Tests](#tests)
- [Architecture](#architecture)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [License](#license)

---

## Quick Start

Get up and running in 3 minutes:

```bash
# 1. Clone into Sublime Text Packages
# macOS:
cd ~/Library/Application\ Support/Sublime\ Text/Packages
git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode

# Linux:
cd ~/.config/sublime-text/Packages
git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode

# Windows:
cd "%APPDATA%\Sublime Text\Packages"
git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode
```

```json
// 2. Add your API key (Preferences > Package Settings > Claude Code > Settings)
{
    "anthropic_api_key": "sk-ant-api03-...",
    "anthropic_model": "claude-sonnet-4-6"
}
```

```
// 3. Open Command Palette (Cmd+Shift+P) → "Claude: New Session"
// 4. Type your prompt and press Enter
```

**That's it.** The plugin auto-detects your backend, starts the bridge, and opens the output view.

[↑ Back to Top](#table-of-contents)

---

## Comparison with Original

| Feature | tommo/sublime-claude | This Extended Version |
|---------|---------------------|----------------------|
| **Backends** | Claude only | Claude, Kimi, Ollama, DeepSeek, OpenAI, Codex, Copilot |
| **Context Tools** | Manual add only | Smart Context, @codebase TF-IDF search, @web DuckDuckGo, auto-related files |
| **MCP Marketplace** | — | 21 curated MCP servers, one-click install |
| **Skills Marketplace** | — | 27 curated skills (global / per-project) |
| **Monitoring** | — | Swarm Monitor, Token Usage Graph, Context Gauge |
| **Diff Preview** | — | Unified diff with colored lines + one-click undo |
| **Voice Input** | — | macOS voice-to-text via Whisper |
| **Drag & Drop** | — | Drop files/images onto output view |
| **Persistent Memory** | — | AI remembers facts across sessions |
| **Session Tags** | — | Label sessions for organization |
| **Auto-Restart** | — | Heartbeat + auto-restart on bridge crash |
| **Terminal** | — | Embedded PTY terminal with agent blocking, SSH/REPL support |
| **Undo** | Immediate rewind | Selectable rewind target via quick panel |
| **Navigation** | — | Cmd+R jumps between prompts (Symbols) |
| **Session Bookmarks** | — | Star sessions to pin them to top of lists |
| **Live Settings** | — | Output view settings apply without restart |
| **Tests** | Minimal | 284 unit tests, mock Sublime API |

[↑ Back to Top](#table-of-contents)

---

## What's New

This build extends the base project with additional features, bug fixes, and a full test suite.

### Additional Features (not in the original)

| Feature | Description |
|---------|-------------|
| **Context Window Gauge** | Visual 10-segment bar in the status bar showing context usage percentage with color coding (🟢🟡🔴) |
| **Session Tags** | Label sessions with comma-separated tags (e.g. `bugfix, refactor`) — shown in status bar and persisted across restarts |
| **Session Bookmarks** | Star/unstar sessions via Switch Session panel — starred sessions float to the top of resume/switch lists |
| **Undo Quick Panel** | Cmd+Z shows a quick panel listing all undoable turns — select exactly how far to rewind |
| **Symbols Navigation** | Cmd+R (Goto Symbol) jumps between prompt entries in the output view |
| **Attach File / Image** | Single command (`Cmd+Shift+F`) for attaching any file or image to context — auto-detects file type and sends images as binary |
| **Drag & Drop** | Drop files or images directly onto the output view — automatically added to context |
| **Token Usage Graph** | `Claude: Show Usage Graph` — ASCII bar chart of token usage per query, 100-query history persisted |
| **Agent Swarm Monitor** | `Claude: Swarm Monitor` — dashboard showing all active sessions, subsessions, statuses, and costs |
| **MCP Marketplace** | `Claude: MCP Marketplace` — browse and install 21 curated MCP servers with one-click auto-install |
| **Skills Marketplace** | `Claude: Skills Marketplace` — browse and install 27 curated skills (global or per-project). Skills inject into `~/.claude/CLAUDE.md` or `./CLAUDE.md` |
| **Diff Preview & Undo** | Unified diff preview for Write/Edit tools — see changes before approving, with colored diff lines (green/red) and one-click undo |
| **Smart Context** | Auto-adds current scope, git-modified files, relevant open files, and symbol definitions to queries — with caching and `.gitignore` filtering |
| **Persistent Memory** | AI remembers facts, preferences, and decisions across sessions via `.claude/memory.json` |
| **Scroll Respect** | Viewport-aware auto-scroll — doesn't jump to bottom when reading history |
| **Terminal Integration** | Embedded PTY terminal — agent can run interactive commands (`htop`, `vim`, SSH, REPLs) and block until completion |
| **Live Output Settings** | Changes to `ClaudeOutput.sublime-settings` apply live to all open output views |
| **Persistent CLI** | One `claude` subprocess per session (not per-query) — eliminates session lock deadlocks |
| **Comprehensive Test Suite** | 284 unit tests covering all core utilities, running in ~0.03s with a mock Sublime API |

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
| **Stderr pipe deadlock** | `--verbose` filled stderr pipe (~64KB), blocked stdout. Fixed by redirecting stderr to per-session log file |
| **Session lock deadlock** | Per-query CLI spawned new process with `--resume`, but old process held session lock. Fixed by persistent CLI process |
| **Bridge race condition** | `_drain_stale()` 0.05s timeout could cancel `_start_query()` mid-flight, leaving zombie subprocess. Removed |
| **Python 3.13 compat** | Removed deprecated `loop=` kwargs from `asyncio.StreamReader`/`StreamReaderProtocol` |
| **MCP config race** | Per-session temp files for MCP config and stderr logs prevent collisions between parallel sessions |

[↑ Back to Top](#table-of-contents)

---

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

[↑ Back to Top](#table-of-contents)

---

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

2. Configure your backend (see [Settings](#settings))

[↑ Back to Top](#table-of-contents)

---

## Backends

The plugin auto-detects which backend to use based on your settings:

| Backend | Trigger | Description |
|---------|---------|-------------|
| **Kimi/Claude** | Default (no `openai_base_url` set) | Cloud API via `claude` CLI |
| **Ollama** | `openai_base_url` is set | Local models via Ollama |
| **OpenAI-compatible** | `openai_base_url` is set | Any OpenAI-compatible server |
| **DeepSeek** | `deepseek_api_key` is set | Anthropic-compatible endpoint |
| **Codex** | `default_backend: "codex"` | OpenAI Codex CLI |
| **Copilot** | `default_backend: "copilot"` | GitHub Copilot SDK |

You can also force a backend with `"default_backend": "claude" | "openai" | "deepseek" | "codex" | "copilot"`.

[↑ Back to Top](#table-of-contents)

---

## Usage

### Commands

All commands available via Command Palette (`Cmd+Shift+P`): type "Claude"

| Command | Keybinding | Description |
|---------|------------|-------------|
| Query | — | Send a query to Claude |
| Query Selection | — | Query about selected code |
| Query File | — | Query about current file |
| Add Current File | — | Add file to context (+ auto-related files) |
| Add Selection | — | Add selection to context |
| Add Open Files | — | Add all open files to context |
| Add Current Folder | — | Add folder path to context |
| Clear Context | — | Clear pending context |
| New Session | — | Start a fresh session (auto-detects backend) |
| New Session with Backend... | — | Pick backend manually |
| Configure Settings | — | Open settings file |
| Undo Message | `Cmd+Z` | Rewind conversation — shows quick panel to select target turn |
| **Undo Last Edit** | — | Undo the most recent Write/Edit file change |
| **Add Memory** | — | Save a persistent fact/preference for AI to remember |
| **List Memories** | — | Browse and delete stored memories |
| **Clear All Memories** | — | Wipe all stored memories |
| Copy Conversation | — | Copy full conversation to clipboard |
| Save Checkpoint... | — | Save current conversation state |
| View Session History... | — | Browse conversation history |
| Restart Session | — | Restart current session, keep output view |
| Resume Session... | — | Resume a previous session |
| Switch Session... | — | Switch between active sessions |
| Fork Session | — | Fork current session (branch conversation) |
| Fork Session... | — | Fork from a saved session |
| Rename Session... | — | Name the current session |
| **Tag Session...** | — | Add comma-separated tags to session |
| Sleep Session | — | Put session to sleep (disconnect, keep view) |
| Wake Session | — | Reconnect a sleeping session |
| Stop Session | — | Disconnect and stop |
| Toggle Output | `Cmd+Alt+C` | Show/hide output view |
| Interrupt | `Alt+Escape` | Stop current query |
| Queue Prompt | — | Queue a prompt while query is running |
| Reset Input Mode | — | Force re-enter input mode |
| Select Effort | — | Choose reasoning effort (low/high/max) |
| Select Model | — | Switch model for current session |
| Set Default Model | — | Set default model for new sessions |
| Refresh Models | — | Refresh model list from API |
| Search Sessions | — | Search across all saved sessions |
| Clear Notifications | — | Clear all notification badges |
| Permission Mode... | — | Toggle permission mode (default/acceptEdits/bypass) |
| Manage Auto-Allowed Tools... | — | View/remove auto-allowed tool patterns |
| Open Link at Cursor | — | Open URL under cursor in browser |
| **Show Usage** | — | Show token usage for current query |
| **Show Usage Graph** | — | ASCII bar chart of token usage per query |
| **Attach File...** | `Cmd+Shift+F` | Attach any file or image to context (auto-detects type) |
| **Swarm Monitor** | — | Dashboard of all active sessions and subsessions |
| **MCP Marketplace** | — | Browse and install 21 MCP servers with one click |
| **Generate Commit Message** | — | Generate commit message from `git diff --staged` |
| **Git Status** | — | Show `git status --short` in output view |
| **Voice Input** | `Cmd+Shift+R` | Record audio, transcribe via Whisper API, insert text (macOS only) |
| **Open Terminal** | — | Open a new embedded PTY terminal tab |
| **Toggle Terminal** | ``Ctrl+` `` | Show/hide PTY-based terminal panel |
| **Send to Terminal** | ``Ctrl+Shift+` `` | Send command to terminal panel |
| **Output Settings** | — | Edit `ClaudeOutput.sublime-settings` |
| **Skills Marketplace** | — | Browse and install 27 curated skills |
| **List Active Skills** | — | Show currently active skills |
| **Disable All Skills** | — | Disable all active skills |

### Inline Input Mode

The output view features an inline input area (marked with `◎`) where you type prompts directly:

- **Enter** - Submit prompt
- **Shift+Enter** - Insert newline (multiline prompts)
- **@** - Open context menu (add files, `@codebase`, `@git`, `@web`, `@terminal`, folder, or clear context)
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

[↑ Back to Top](#table-of-contents)

---

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
- **permission_mode** — `"default"`, `"acceptEdits"`, `"bypassPermissions"`
- **effort** — Reasoning effort: `"low"`, `"high"`, `"max"`
- **smart_context_enabled** — Auto-expand queries with relevant context (`true` / `false`)
- **auto_add_current_file** — Automatically add active file to context (`true` / `false`)
- **claude_extra_args** — Extra CLI arguments for `claude` (e.g. `"--max-budget-usd 5 --verbose"`)
- **claude_side_panel** — Show chat in a narrow right-side panel (`true` / `false`). Splits window into 2 columns (78% code, 22% chat) like VS Code. Default: `true`

### Permission Modes

| Mode | Behavior | Safest for |
|------|----------|------------|
| `default` | Prompt for all tool actions | Sensitive codebases, production repos |
| `acceptEdits` | Auto-accept Read/Write/Edit; prompt for Bash/Web | Daily development, trusted projects |
| `bypassPermissions` | Skip all permission checks | Local testing, throwaway code |

**Recommendation:** Use `acceptEdits` for normal work — it removes friction for file operations while still confirming destructive commands (`Bash`, `WebSearch`). Use `default` when touching production code. Use `bypassPermissions` only for quick experiments.

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

[↑ Back to Top](#table-of-contents)

---

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
| `@web <query>` | Search the web via DuckDuckGo (no API key) |
| `@terminal` | Inject current terminal output into context |

**`@codebase`** finds the most relevant files based on your query keywords and adds them to context automatically:

```
◎ @codebase how does authentication work? ▶
```

This will:
1. Index the project (first use only, ~1-10s depending on size)
2. Search for files matching keywords like `auth`, `login`, `authenticate`
3. Add top 5 matching code chunks to your query context

**How it works:** Uses TF-IDF over a local SQLite database — no embeddings API or Ollama required. Indexes are stored in `.claude_codebase.db` inside your project root and auto-refresh every 24 hours.

**`@web`** searches DuckDuckGo and adds top results to your query context — no API key required:

```
◎ @web latest python asyncio best practices ▶
```

This will:
1. Query DuckDuckGo Lite via HTTPS
2. Parse title, URL, and snippet from results
3. Add top 5 results as context for your query

**Privacy note:** Searches go directly to DuckDuckGo (not your AI backend). No tracking, no API key needed.

**`@terminal`** injects the current terminal output into your query context:

```
◎ @terminal why is this test failing? ▶
```

This will:
1. Capture the last ~2000 characters of terminal output
2. Add them as a `note` context item for the AI to analyze
3. Useful for debugging build errors, test failures, or server logs

Requires an active terminal session (use **Toggle Terminal** first, or it auto-starts on first `@terminal` use).

### Related Files (Manual)

When you explicitly add a file, related files are automatically included (up to 5):

- **Test/sibling files** — `user.py` → `user_test.py`, `test_user.py`
- **Imported modules** — parsed from `import` / `from` / `require` / `use` statements in the first 30 lines
- **Convention-based paths** — `User.php` → `controllers/UserController.php`

Supported: Python, JavaScript/TypeScript, PHP, Go.

Disable by removing the `_add_related_files` call in `session.py` if you prefer manual context only.

[↑ Back to Top](#table-of-contents)

---

## Voice Input

**`Claude: Voice Input`** (`Cmd+Shift+R`) — speak instead of typing (macOS only):

1. Press `Cmd+Shift+R` to start recording
2. Speak your prompt
3. Press `Cmd+Shift+R` again to stop
4. Audio is sent to OpenAI Whisper API and transcribed
5. Text is inserted into the input area

**Requirements:**
- macOS (`afrecord` for audio capture)
- **Microphone permission** for Sublime Text in System Settings → Privacy & Security → Microphone
- OpenAI API key set in settings: `"openai_api_key": "sk-..."`

**Privacy note:** Audio is sent to OpenAI's Whisper API for transcription. For local-only transcription, use macOS built-in dictation (Fn twice) instead.

[↑ Back to Top](#table-of-contents)

---

## Terminal Integration

A full embedded PTY terminal inside Sublime Text — shared between you and the AI agent. You can type commands interactively; the agent can run commands and **block until they complete**, reading the captured output.

### Keybindings

| Keybinding | Action |
|-----------|--------|
| `Cmd+Shift+P` → "Claude: Open Terminal" | Open a new terminal tab |
| ``Ctrl+` `` | Toggle terminal panel |
| ``Ctrl+Shift+` `` | Send command to terminal |

### Features

- **Real PTY** — `htop`, `vim`, `less`, `npm init`, SSH, and REPLs work correctly
- **Agent blocking** — `terminal_run("npm test", wait=60)` blocks until the shell returns to prompt
- **Multiple tabs** — Each session gets its own terminal; users can open additional tabs
- **Index targeting** — Target any terminal by its `#N` index (shown in tab title)
- **Shell integration** — OSC 133 hooks for zsh/bash/fish give ~50ms prompt detection
- **SSH/REPL support** — 300ms output quiescence fallback for remote shells and interactive programs
- **Session restore** — Terminal tabs reopen after Sublime restart with cwd preserved
- **ANSI rendering** — Full color support via custom color scheme (not stripped)

### Agent MCP Tools

The agent gets four terminal tools via MCP:

- `terminal_run(command, wait=30, index=None)` — Run command and block until done
- `terminal_read(lines=100, index=None)` — Read current screen buffer
- `terminal_send(text, index=None)` — Send keystrokes to a running program
- `terminal_close(index=None)` — Close a terminal tab

See [`docs/terminal.md`](docs/terminal.md) for the full agent guide.

### How It Works

1. The `Terminal` class spawns a real PTY via `ptyprocess`
2. A `pyte` screen emulator parses ANSI sequences into a buffer
3. A render thread syncs the buffer to a Sublime view every ~30ms
4. For agent commands, `start_capture()` records raw output until prompt detection fires (OSC 133 → PGID → quiescence)

[↑ Back to Top](#table-of-contents)

---

## Sessions

Sessions are automatically saved and can be resumed later. Each session tracks:
- Session name (auto-generated from first prompt, or manually set)
- **Tags** — comma-separated labels for organization (e.g. `bugfix, refactor`)
- **Bookmarks** — star sessions to pin them to the top of resume/switch lists
- Project directory
- Cumulative cost
- Per-query token usage history (up to 100 queries)

**Multiple sessions per window** - Each "New Session" creates a separate output view. Switch between them like normal tabs.

Use **Claude: Resume Session...** to pick and continue a previous conversation.

After Sublime restarts, orphaned output views are registered as sleeping sessions. Press Enter or use **Wake Session** to reconnect.

### Undo

**`Cmd+Z`** (Undo Message) shows a quick panel listing all undoable turns, newest first:
```
3 — refactor auth middleware…
2 — add user validation…
1 — initial project setup…
```
Selecting one rewinds the session to before that turn. You can undo multiple steps in one action.

### Auto-Restart on Bridge Crash

If the bridge process dies (OOM, timeout, Broken pipe), the plugin **automatically restarts and resumes** the conversation:

- **Heartbeat monitoring** — 15s interval checks bridge health via JSON-RPC ping
- **Stall detection** — warns at 60s without activity, auto-restarts at 120s
- **Pre-query health check** — auto-restarts before sending if bridge is dead
- **Post-error recovery** — auto-restarts after a crash mid-query
- **Persistent CLI** — the `claude` subprocess lives for the entire session; new prompts are sent as JSON lines on stdin instead of spawning new processes. This eliminates the session lock deadlock that occurred when the old process still held the lock.
- Resume uses the same `session_id`, so Anthropic continues the conversation if still available

You rarely need to manually restart — the agent just keeps working.

### Session Tags

Tag sessions for organization:
1. **Claude: Tag Session...** — enter comma-separated tags
2. Tags appear in status bar as `[tag1,tag2]`
3. Tags are persisted in `.sessions.json` and restored on reconnect

### Session Bookmarks

Star sessions to keep them at the top of the resume/switch panels:
1. **Claude: Switch Session...**
2. Select **☆ Star Session** (or **★ Unstar Session** if already starred)
3. Starred sessions show a `★` prefix and float above unstarred ones

Bookmarks are persisted per-project in `.claude/bookmarks.json`.

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

### Persistent Memory

**Claude: Add Memory** — save facts, preferences, and decisions that AI remembers across sessions:

```bash
# Saved automatically in .claude/memory.json (project-level)
# Or ~/.claude/memory.json (global fallback)
```

**How it works:**
1. Before each query, top 5 relevant memories are injected as context:
   ```
   <memories>
     [coding_style] Use camelCase for JS variables
     [stack] Laravel 12 with PHP 8.3
     [conventions] Always validate user input before DB queries
   </memories>
   ```
2. After each response, AI extracts new memories automatically ("use X approach", "remember to Y")
3. Relevance scoring based on keyword overlap + category boosts

**Commands:**
- **Add Memory** — save a new fact/preference
- **List Memories** — browse and delete stored memories
- **Clear All Memories** — wipe everything

Max 50 memories per project, auto-pruned by relevance score.

[↑ Back to Top](#table-of-contents)

---

## Output View

The output view shows:

- `◎ prompt ▶` - Your query (multiline supported)
- `⋯` - Working indicator (disappears when done)
- `○ Tool` - Tool pending
- `● Tool` - Tool completed (with diff preview for Write/Edit)
- Response text with syntax highlighting
- `── time · ctx ──` - Completion footer

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

### Skills Marketplace

**`Claude: Skills Marketplace`** — browse and install 27 curated skills with one click:

- **TDD Workflow** — RED-GREEN-REFACTOR with 80%+ coverage and git checkpoints
- **Security Review** — OWASP-aligned checklist (secrets, XSS, SQL injection, auth, rate limiting)
- **API Design** — REST patterns: resource naming, status codes, pagination, versioning
- **Search First** — research-before-coding workflow (adopt/extend/build decision matrix)
- **Frontend Patterns** — React, Next.js, state management, performance, forms, accessibility
- **Backend Patterns** — repository/service layers, database optimization, caching, auth
- **Deployment Patterns** — CI/CD, Docker, health checks, rollback strategies
- **Verification Loop** — build, type check, lint, tests, security scan, diff review
- **Laravel Boost** — comprehensive Laravel: architecture, Eloquent, security, TDD with Pest
- **PHP Strict**, **Python Clean**, **TypeScript Strict**, **Rust**, **Go**
- **Domain-Driven Design**, **Microservices**, **Functional Programming**

**How it works:**
1. Select a skill from the quick panel
2. Choose scope: 🌍 **Global** (all projects → `~/.claude/CLAUDE.md`) or 📁 **Project** (current project → `./CLAUDE.md`)
3. Skills are injected between `<!-- [Claude Sublime Skills] START/END -->` markers
4. User content is preserved — only the managed section is updated
5. Additional commands: `Claude: List Active Skills`, `Claude: Disable All Skills`

### MCP Marketplace

**`Claude: MCP Marketplace`** — browse and install MCP servers with one click:

Available servers (21 curated):
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
- **Firecrawl** — scrape any web page to structured markdown
- **Figma** — read designs, extract tokens and component specs
- **Linear** — create issues, search tickets, update status
- **Perplexity** — AI-powered web search with citations
- **Tavily** — AI search engine optimized for LLMs
- **Chrome DevTools** — debug browser from Claude (DOM, console, network)
- **Kubeshark** — Kubernetes network observability
- **Exa** — AI-powered web search and content crawling
- **Spec Workflow** — spec-driven development with dashboard

**How it works:**
1. Select a server from the quick panel
2. Confirm installation (shows required env vars like `GITHUB_PAT`)
3. Automatically updates `.mcp.json` in your project (or `~/.claude.json` globally)
4. Uses `npx -y` — no manual `npm install` needed
5. Template variables auto-resolved: `${project_root}`, `${database_path}`

[↑ Back to Top](#table-of-contents)

---

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

[↑ Back to Top](#table-of-contents)

---

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

[↑ Back to Top](#table-of-contents)

---

## Tests

Run the test suite from the project root:

```bash
cd ~/PhpstormProjects/sublime-claude
python3 -m unittest discover tests/ -v
```

**284 tests** covering all core utilities:
- Context window gauge, session tags, drag-drop, usage graph
- Attach commands (image/file auto-detect, MIME mapping)
- Swarm monitor (status icons, session tracking)
- MCP marketplace (config loading, install logic, template variables)
- Smart context (scope, git, open files, symbol definitions)
- Diff preview and undo logic
- Persistent memory (relevance scoring, auto-extraction)
- Scroll behavior, incremental rendering
- Constants, error handling, logging, prompt building
- Command parsing, context parsing, session state machine
- JSON-RPC client, tool routing, settings merging
- BackendSpec registry, TOOL_FORMATTERS registry
- Terminal integration (PTY lifecycle, ANSI rendering, blocking capture, quiescence)
- Undo quick panel, session bookmarks, live output settings
- Sleep protection (background tool abort, orphan cleanup)

All tests run in ~0.03s without requiring Sublime Text to be open (uses mock API).

[↑ Back to Top](#table-of-contents)

---

## Architecture

```
┌─────────────────┐     JSON-RPC/stdio     ┌─────────────────┐
│  Sublime Text   │ ◄────────────────────► │  bridge/main.py │ (Kimi/Claude)
│  (Python 3.8)   │                        │  (CLI wrapper)  │
│                 │                        └────────┬────────┘
│                 │                                 │
│                 │        JSON-RPC/stdio           │  Persistent CLI
│                 │ ◄────────────────────► ┌────────┴────────┐
│                 │                        │  claude_agent_  │
│                 │                        │  sdk/__init__.py│
│                 │                        │  (persistent    │
│                 │                        │   subprocess)   │
│                 │                        └────────┬────────┘
│                 │                                 │ stdin/stdout
│                 │                        ┌────────┴────────┐
│                 │                        │   claude CLI    │
│                 │                        │  (one per       │
│                 │                        │   session)      │
│                 │                        └─────────────────┘
│                 │
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
        │
        │ PTY (embedded terminal)
        ▼
┌─────────────────────────────────────────┐
│  terminal/ package                      │
│  ├─ terminal.py   — PTY lifecycle,     │
│  │                  blocking capture    │
│  ├─ ptty.py       — pyte screen emu    │
│  ├─ render.py     — ANSI → Sublime     │
│  └─ commands.py   — open/key/paste     │
└─────────────────────────────────────────┘
```

The plugin runs in Sublime's Python 3.8 environment and spawns a separate bridge process using Python 3.10+. Each bridge translates between Sublime's JSON-RPC protocol and the backend CLI:

### Persistent CLI Architecture (Claude/Kimi)

Instead of spawning a new `claude` process for every query, the bridge maintains **one persistent subprocess per session**:

1. **Launch** — `claude -p --output-format=stream-json --input-format=stream-json` starts once per session
2. **Query** — Each prompt is sent as a JSON line on stdin: `{"type":"user","message":{...}}`
3. **Read** — A background task reads JSON lines from stdout into an `asyncio.Queue`
4. **Interrupt** — `SIGKILL` terminates the process; next query starts a fresh one
5. **Stderr** — Redirected to `/tmp/claude_cli_stderr_{session_id}.log` to prevent pipe deadlock

This eliminates the session lock deadlock that occurred when a new `claude --resume` process tried to acquire the lock while the old process still held it.

### Backends
- **Kimi/Claude**: `bridge/main.py` — Wraps `claude` CLI v2.1+ with persistent subprocess
- **Ollama/OpenAI**: `bridge/openai_main.py` — Native Ollama `/api/chat` + OpenAI-compatible
- **Codex**: `bridge/codex_main.py` — Codex app-server protocol
- **Copilot**: `bridge/copilot_main.py` — GitHub Copilot SDK
- **DeepSeek**: `bridge/main.py` — Same Claude bridge, Anthropic-compatible endpoint

```
sublime-claude/
├── Core:
│   ├── claude_code.py          # Plugin entry point
│   ├── core.py                 # Session lifecycle coordination
│   ├── session.py              # Re-export compatibility layer
│   ├── session_core.py         # Session facade (delegates to collaborators)
│   ├── session_bridge.py       # Bridge lifecycle (start/stop/sleep/wake)
│   ├── session_query.py        # Query handling, smart context, @-commands
│   ├── session_context.py      # Pending files/selections, prompt building
│   ├── session_permissions.py  # Permission/plan/question UI
│   ├── session_state.py        # sessions.json, retain files, rewind
│   ├── session_notifications.py # Bridge notification dispatcher
│   ├── session_status.py       # Status bar, spinner, context gauge
│   ├── session_ui.py           # Phantom overlays (connecting, sleeping)
│   ├── session_services.py     # Notification subscriptions
│   ├── session_heartbeat.py    # Stall detection, auto-restart
│   ├── session_terminal.py     # Terminal adapter integration
│   └── session_env.py          # Environment & persistence helpers
│
├── Output & Rendering:
│   ├── output.py               # Output view facade (mixins + incremental render)
│   ├── output_models.py        # Data classes (ToolCall, Conversation, Todo)
│   ├── output_format.py        # TOOL_FORMATTERS registry + result formatters
│   ├── output_plan.py          # Plan UI renderer mixin
│   ├── output_permissions.py   # Permission UI renderer mixin
│   ├── output_question.py      # Question UI renderer mixin
│   └── output_input.py         # Input mode controller mixin
│
├── Commands (split by domain):
│   ├── commands.py             # Main command definitions
│   ├── commands_core.py        # Core commands (query, interrupt, toggle)
│   ├── commands_session.py     # Session commands (new, resume, wake, fork)
│   ├── commands_context.py     # Context commands (add file, attach, drag-drop)
│   ├── commands_tools.py       # Tool commands (undo edit, MCP marketplace)
│   ├── commands_ui.py          # UI commands (usage graph, swarm monitor)
│   └── commands_voice.py       # Voice input commands (macOS only)
│
├── Context & Search:
│   ├── smart_context.py        # Auto context expansion (git, symbols, scope)
│   ├── codebase_search.py      # TF-IDF @codebase search (SQLite index)
│   ├── web_search.py           # DuckDuckGo @web search (no API key)
│   └── context_parser.py       # Context menus & @ picker
│
├── Backends & Config:
│   ├── backends.py             # BackendSpec registry (centralized config)
│   ├── settings.py             # Settings loading & merging
│   └── constants.py            # Config & magic strings
│
├── MCP & Extensions:
│   ├── mcp_server.py           # MCP socket server (Unix socket)
│   ├── tool_router.py          # MCP tool dispatch to Sublime
│   ├── persona_client.py       # Persona server client
│   └── skills_manager.py       # Skills marketplace (install/manage)
│
├── Terminal (embedded PTY):
│   └── terminal/
│       ├── terminal.py         # PTY lifecycle, blocking capture
│       ├── ptty.py             # pyte screen emulator
│       ├── render.py           # ANSI → Sublime view rendering
│       ├── commands.py         # Terminal commands (open/key/paste)
│       ├── event.py            # Terminal view lifecycle listener
│       └── key.py              # ANSI key-code generator
│
├── Infrastructure:
│   ├── rpc.py                  # JSON-RPC client (stdio)
│   ├── terminal_view.py        # Legacy terminal output panel
│   ├── listeners.py            # Event handlers (input, clicks, drag-drop)
│   ├── permissions.py          # Shared permission pattern matching
│   ├── error_handler.py        # Error handling decorators
│   ├── logger.py               # File-based logging
│   ├── prompt_builder.py       # Prompt construction
│   ├── command_parser.py       # Slash command parsing
│   ├── memory.py               # Persistent memory across sessions
│   └── notalone.py             # Notalone integration
│
├── Bridge (Python 3.10+ subprocesses):
│   └── bridge/
│       ├── base.py             # Base bridge class
│       ├── main.py             # Claude/Kimi bridge (CLI wrapper)
│       ├── terminal.py         # Legacy PTY terminal manager
│       ├── openai_main.py      # Ollama/OpenAI bridge
│       ├── codex_main.py       # Codex bridge (app-server)
│       ├── copilot_main.py     # Copilot bridge (Copilot SDK)
│       └── rpc_helpers.py      # Shared JSON-RPC helpers
│
└── MCP Protocol:
    └── mcp/
        └── server.py           # MCP protocol server implementation
```

All bridges emit identical JSON-RPC notifications to Sublime, so the output view, permissions, and MCP tools work the same regardless of backend.

[↑ Back to Top](#table-of-contents)

---

## Troubleshooting & FAQ

### "python3 not found" or bridge won't start

Sublime Text's `PATH` can differ from your terminal's. The plugin searches for Python in this order:
1. `python3.13`, `python3.12`, `python3.11`, `python3.10`
2. `python3`
3. `uv`
4. `pyenv`

**Fix:** Set the full path in settings:
```json
{ "python_path": "/usr/local/bin/python3.12" }
```

Find your Python path with: `which python3.12` (or `pyenv which python`)

### Session stuck / Enter doesn't work

Usually means the input mode state got corrupted. Try:
1. `Cmd+Shift+P` → "Claude: Reset Input Mode"
2. If that fails, `Claude: Restart Session` (keeps conversation history)
3. If Sublime froze entirely, check Console (`View > Show Console`) for `plugin_host` errors

### @codebase index is broken / outdated

Delete the index file to force a rebuild:
```bash
rm .claude_codebase.db
```

Next `@codebase` query will re-index automatically.

### "Broken pipe" or bridge crashes repeatedly

The plugin has auto-restart built-in. If it keeps failing:
1. Check Python version: `python3 --version` (must be 3.10+)
2. Check the claude CLI is authenticated: `claude --version`
3. Check `~/.claude/settings.json` for invalid config
4. Restart Sublime Text (some plugin state can only be cleared on restart)

### Voice Input not working (macOS)

1. Grant microphone permission to Sublime Text:
   **System Settings → Privacy & Security → Microphone → Sublime Text**
2. Ensure `afrecord` is available: `which afrecord`
3. Ensure OpenAI API key is set in plugin settings

### Diff colors not showing

Diff highlighting requires a color scheme that defines these scopes:
- `diff.inserted` (green)
- `diff.deleted` (red)
- `comment` (gray for unchanged lines)

Most popular schemes (Monokai, Mariana, One Dark) support these out of the box.

### How do I migrate from tommo/sublime-claude?

1. Backup your sessions: `cp .sessions.json .sessions.json.backup`
2. Remove the old plugin: `rm -rf "Packages/sublime-claude"`
3. Install this version: `git clone https://github.com/KalimeroMK/sublime-claude ClaudeCode`
4. Copy your API keys from old settings to new settings file

### Can I use this without Claude API?

Yes. Set up Ollama (free, local) or DeepSeek (cheaper than Claude):
```json
// Ollama
{ "openai_base_url": "http://localhost:11434", "openai_model": "qwen2.5:7b" }

// DeepSeek
{ "deepseek_api_key": "sk-..." }
```

### Terminal panel not showing

1. Ensure your shell is executable: `echo $SHELL` (defaults to `/bin/bash` if not set)
2. Check Console (`View > Show Console`) for `terminal_start` errors
3. Terminal uses `pty.openpty()` — requires macOS/Linux (Windows PTY support is limited)
4. If terminal output looks garbled, ANSI codes are stripped automatically; some complex TUI apps may not render well

### "Session lock" or queries stalling for 120s

This was fixed by the persistent CLI architecture. If you still see stalls:
1. Check stderr logs: `tail -f /tmp/claude_cli_stderr_*.log`
2. Check if the `claude` CLI process is alive: `ps aux | grep claude`
3. The bridge heartbeat (15s) will auto-restart after 120s of no activity
4. Manually restart: `Claude: Restart Session`

### Debug logs

- **Bridge debug log**: `~/.claude/bridge_debug.log` (auto-rotates at 2MB)
- **CLI stderr** (per-session): `/tmp/claude_cli_stderr_{session_id}.log`
- **MCP config** (per-session): `/tmp/claude_mcp_servers_{session_id}.json`

### How do I disable auto-context?

```json
{
    "smart_context_enabled": false,
    "auto_add_current_file": false
}
```

[↑ Back to Top](#table-of-contents)

---

## License

MIT License — see [LICENSE](LICENSE) for the full text.

[↑ Back to Top](#table-of-contents)
