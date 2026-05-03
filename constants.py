"""Constants and configuration values for Claude Code plugin."""
from pathlib import Path

# ─── Application ──────────────────────────────────────────────────────────────
APP_NAME = "Claude"
DEFAULT_SESSION_NAME = "Claude"
PLUGIN_NAME = "ClaudeCode"

# ─── User Directories ─────────────────────────────────────────────────────────
USER_SETTINGS_DIR = Path.home() / ".claude"
USER_SETTINGS_FILE = Path.home() / ".claude.json"  # User-level settings (MCP, etc.)
USER_PROFILES_DIR = Path.home() / ".claude-sublime"

# ─── Project Directories ──────────────────────────────────────────────────────
PROJECT_SETTINGS_DIR = ".claude"
PROJECT_SUBLIME_TOOLS_DIR = ".claude/sublime_tools"

# ─── File Names ───────────────────────────────────────────────────────────────
SETTINGS_FILE = "settings.json"
PROFILES_FILE = "profiles.json"
SESSIONS_FILE = ".sessions.json"
MCP_CONFIG_FILE = ".mcp.json"

# ─── Socket & IPC ─────────────────────────────────────────────────────────────
MCP_SOCKET_PATH = "/tmp/sublime_claude_mcp.sock"

# ─── Logging ──────────────────────────────────────────────────────────────────
BRIDGE_LOG_PATH = "/tmp/claude_bridge.log"
LOG_PREFIX_INFO = "  "
LOG_PREFIX_ERROR = "ERROR: "

# ─── View Settings ────────────────────────────────────────────────────────────
OUTPUT_VIEW_SETTING = "claude_output"
INPUT_MODE_SETTING = "claude_input_mode"
ACTIVE_VIEW_SETTING = "claude_active_view"
BACKEND_SETTING = "claude_backend"
CONVERSATION_REGION_KEY = "claude_conversation"
PERMISSION_REGION_KEY = "claude_permission_block"
PLAN_REGION_KEY = "claude_plan_block"
QUESTION_REGION_KEY = "claude_question_block"
UNDO_BUTTON_REGION_KEY = "claude_undo_buttons"
DIFF_HIGHLIGHT_REGION_KEY = "claude_diff_highlight"
PENDING_CONTEXT_SESSION_SETTING = "claude_pending_context_session"
PENDING_CONTEXT_TIME_SETTING = "claude_pending_context_time"
FONT_SIZE = 12

# ─── Status Indicators ────────────────────────────────────────────────────────
# Status prefixes for view titles
STATUS_ACTIVE_WORKING = "◉"    # Active session, working
STATUS_ACTIVE_IDLE = "◇"       # Active session, idle
STATUS_INACTIVE_WORKING = "•"  # Inactive session, working
STATUS_INACTIVE_IDLE = ""      # Inactive session, idle

# Spinner frames for loading
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# ─── Input Mode ───────────────────────────────────────────────────────────────
INPUT_MARKER = "◎ "

# ─── Tool Status ──────────────────────────────────────────────────────────────
TOOL_STATUS_PENDING = "pending"
TOOL_STATUS_DONE = "done"
TOOL_STATUS_ERROR = "error"
TOOL_STATUS_BACKGROUND = "background"

# ─── Limits & Thresholds ──────────────────────────────────────────────────────
MAX_SESSIONS = 200                      # Max sessions to keep in registry
MAX_RELATED_FILES = 5                   # Max related files to auto-add
MAX_FILE_SIZE_AUTO_ADD = 100000         # Skip files larger than this (bytes)
MAX_DIFF_LENGTH = 20000                 # Truncate diffs longer than this
MAX_SESSION_NAME_LENGTH = 23            # Truncate session names in UI
