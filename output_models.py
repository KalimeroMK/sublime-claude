"""Data models for Claude Code output view."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Callable, Any

from .constants import (
    TOOL_STATUS_PENDING as PENDING,
    TOOL_STATUS_DONE as DONE,
    TOOL_STATUS_ERROR as ERROR,
    TOOL_STATUS_BACKGROUND as BACKGROUND,
)


# Permission button constants
PERM_ALLOW = "allow"
PERM_DENY = "deny"
PERM_ALLOW_ALL = "allow_all"
PERM_ALLOW_SESSION = "allow_session"  # Allow same tool for 30s
PERM_BATCH = "batch_allow"  # Allow all Write/Edit for current query

PLAN_APPROVE = "approve"
PLAN_REJECT = "reject"
PLAN_VIEW = "view"


@dataclass
class PlanApproval:
    """A pending plan approval request."""
    id: int
    plan_file: str
    allowed_prompts: List[dict]
    callback: Callable[[str], None]  # Called with PLAN_APPROVE or PLAN_REJECT
    region: tuple = (0, 0)
    button_regions: Dict[str, tuple] = field(default_factory=dict)


@dataclass
class PermissionRequest:
    """A pending permission request."""
    id: int
    tool: str
    tool_input: dict
    callback: Callable[[str], None]  # Called with PERM_ALLOW, PERM_DENY, or PERM_ALLOW_ALL
    region: tuple = (0, 0)  # Region in view
    button_regions: Dict[str, tuple] = field(default_factory=dict)  # button_type -> (start, end)


@dataclass
class PermissionBatch:
    """A batch of permission requests shown as a single approval block."""
    requests: List[PermissionRequest] = field(default_factory=list)
    callback: Callable[[str], None] = None  # Called with PERM_ALLOW or PERM_DENY
    region: tuple = (0, 0)
    button_regions: Dict[str, tuple] = field(default_factory=dict)


@dataclass
class QuestionRequest:
    """A pending inline question request."""
    qid: int
    questions: List[dict]     # [{question, options, header, multiSelect}]
    current_idx: int = 0
    answers: Dict[str, str] = field(default_factory=dict)
    callback: Callable = None  # Called with answers dict or None (cancelled)
    region: tuple = (0, 0)
    button_regions: Dict[str, tuple] = field(default_factory=dict)
    selected: set = field(default_factory=set)  # multi-select toggles


@dataclass
class ToolCall:
    """A single tool call."""
    name: str
    tool_input: dict
    status: str = PENDING  # pending, done, error, background
    result: Optional[str] = None  # tool result content
    id: Optional[str] = None  # tool_use_id, for precise matching
    snapshot: Optional[str] = None  # Original file content before Write/Edit (for undo)
    diff: Optional[str] = None  # Computed unified diff (for display)


@dataclass
class TodoItem:
    """A todo item from TodoWrite."""
    content: str
    status: str  # pending, in_progress, completed


@dataclass
class Conversation:
    """A single prompt + tools + response + meta."""
    prompt: str = ""
    # Events in time order - either ToolCall or str (text chunk)
    events: List = field(default_factory=list)
    todos: List[TodoItem] = field(default_factory=list)  # current todo state
    todos_all_done: bool = False  # True when all todos completed (don't carry to next)
    working: bool = True  # True while processing, False when done
    duration: float = 0.0
    usage: dict = None
    region: tuple = (0, 0)
    context_names: List[str] = field(default_factory=list)  # Context files used

    @property
    def tools(self) -> List[ToolCall]:
        """Get all tool calls (for compatibility)."""
        return [e for e in self.events if isinstance(e, ToolCall)]

    @property
    def text_chunks(self) -> List[str]:
        """Get all text chunks (for compatibility)."""
        return [e for e in self.events if isinstance(e, str)]
