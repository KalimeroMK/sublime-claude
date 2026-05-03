"""Status bar and spinner animation for Session."""
from typing import Optional

import sublime

from .session_env import _CONTEXT_LIMITS, _MODEL_CONTEXT_LIMITS


class StatusManager:
    """Manages status bar text, context gauge, and spinner animation."""

    def __init__(self, session):
        self._s = session

    def status(self, text: str) -> None:
        """Update status on output view only."""
        output = self._s.output
        if not output.view or not output.view.is_valid():
            return
        label = self._s.backend.title() if self._s.backend != "claude" else "Claude"
        prefix = "[PLAN] " if self._s.plan_mode else ""
        parts = [f"{prefix}{text}"]
        if self._s.backend == "claude":
            settings = sublime.load_settings("ClaudeCode.sublime-settings")
            effort = settings.get("effort", "high")
            parts.append(f"effort:{effort}")
        # Show model (short form) and profile
        model_info = []
        if self._s.sdk_model:
            # Shorten model name: claude-opus-4-5-20251101 -> opus.4.5
            short = self._s.sdk_model.replace("claude-", "").split("-202")[0].replace("-", ".")
            model_info.append(short)
        if self._s.profile_name:
            model_info.append(f"@{self._s.profile_name}")
        if model_info:
            parts.append("".join(model_info))
        if self._s.tags:
            parts.append("[" + ",".join(self._s.tags) + "]")
        if self._s.total_cost > 0:
            parts.append(f"${self._s.total_cost:.4f}")
        if self._s.query_count > 0:
            parts.append(f"{self._s.query_count}q")
        if self._s.context_usage:
            ctx_k = self.context_tokens_k()
            if ctx_k is not None:
                parts.append(f"ctx:{ctx_k}k")
            gauge = self.context_window_gauge()
            if gauge:
                parts.append(gauge)
        output.view.set_status("claude", f"{label}: {', '.join(parts)}")

    def update_status_bar(self) -> None:
        """Update status bar with session info."""
        if self._s.is_sleeping:
            self.status("sleeping")
        elif self._s.working:
            self.status("working")
        else:
            self.status("ready")

    def context_tokens_k(self) -> Optional[int]:
        """Get context token count in thousands from latest usage data."""
        if not self._s.context_usage:
            return None
        u = self._s.context_usage
        input_t = (u.get("input_tokens", 0)
                 + u.get("cache_read_input_tokens", 0)
                 + u.get("cache_creation_input_tokens", 0))
        if not input_t:
            return None
        return max(1, input_t // 1000)

    def context_window_gauge(self) -> Optional[str]:
        """Return a visual gauge showing context window utilization.

        Format: ▓▓▓▓░░░░░ 45% (colored by severity)
        """
        if not self._s.context_usage:
            return None
        u = self._s.context_usage
        used = (u.get("input_tokens", 0)
                + u.get("cache_read_input_tokens", 0)
                + u.get("cache_creation_input_tokens", 0))
        if not used:
            return None

        # Determine max context for this model
        max_ctx = None
        model_id = self._s.sdk_model or ""
        if model_id:
            # Check suffix overrides first
            for suffix, tokens in _CONTEXT_LIMITS.items():
                if model_id.endswith(suffix):
                    max_ctx = tokens
                    break
            # Fall back to model family lookup
            if max_ctx is None:
                for family, tokens in _MODEL_CONTEXT_LIMITS.items():
                    if family in model_id.lower():
                        max_ctx = tokens
                        break
        # Ultimate fallback: 200k for Claude, 128k for others
        if max_ctx is None:
            max_ctx = 200000 if self._s.backend in ("claude", "kimi", "default", "") else 128000

        pct = min(100, int(used / max_ctx * 100))
        # Build bar: 10 segments
        filled = min(10, round(pct / 10))
        bar = "█" * filled + "░" * (10 - filled)
        # Color thresholds
        if pct >= 90:
            color = "🔴"
        elif pct >= 70:
            color = "🟡"
        else:
            color = "🟢"
        return f"{color} {bar} {pct}%"

    def clear(self) -> None:
        """Clear the status bar."""
        if self._s.output.view and self._s.output.view.is_valid():
            self._s.output.view.erase_status("claude")

    def animate(self) -> None:
        """Animate spinner in status bar and output view."""
        if not self._s.working:
            # Restore normal title when done
            self._s.output.set_name(self._s.name or "Claude")
            return
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        s = chars[self._s.spinner_frame % len(chars)]
        self._s.spinner_frame += 1
        # Show spinner in status bar only (not title - causes cursor flicker)
        status = self._s.current_tool or "thinking..."
        self.status(f"{s} {status}")
        # Animate spinner in output view
        self._s.output.advance_spinner()
        sublime.set_timeout(self.animate, 200)
