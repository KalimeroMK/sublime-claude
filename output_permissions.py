"""Permission UI mixin for OutputView."""
import time

import sublime

from .constants import INPUT_MODE_SETTING, PERMISSION_REGION_KEY
from .output_models import (
    PERM_ALLOW,
    PERM_ALLOW_ALL,
    PERM_ALLOW_SESSION,
    PERM_BATCH,
    PERM_DENY,
    PermissionRequest,
)
from .permissions import make_auto_allow_pattern, match_permission_pattern


class PermissionUIRendererMixin:
    """Mixin for rendering permission requests and handling user responses."""

    def _remove_permission_block(self) -> None:
        """Remove permission block from view without callback."""
        if not self.pending_permission or not self.view:
            return
        perm = self.pending_permission
        # Remove button regions
        for btn_type in perm.button_regions:
            self.view.erase_regions(f"claude_btn_{btn_type}")
        # Get current region from tracked region (auto-adjusted for text shifts)
        regions = self.view.get_regions(PERMISSION_REGION_KEY)
        if regions and regions[0].size() > 0:
            region = regions[0]
            self._replace(region.begin(), region.end(), "")
        else:
            # Tracked region lost (zero-width or missing) — fallback:
            # permission block is everything after conversation region
            if self.current:
                conv_end = self.current.region[1]
                view_size = self.view.size()
                if view_size > conv_end:
                    self._replace(conv_end, view_size, "")
        self.view.erase_regions(PERMISSION_REGION_KEY)

    def clear_all_permissions(self) -> None:
        """Clear all pending permissions (called when query finishes)."""
        if self.pending_permission:
            self._clear_permission()
            self.pending_permission = None
        self._permission_queue.clear()
        self._batch_allow_active = False

    def permission_request(self, pid: int, tool: str, tool_input: dict, callback) -> None:
        """Show a permission request in the view."""
        self.show(focus=False)  # Don't steal focus from other views

        # IMPORTANT: Ensure input mode is OFF so permission keys (Y/N/S/A) work
        # Permission keys require claude_input_mode=false in Default.sublime-keymap
        if self.view:
            self.view.settings().set(INPUT_MODE_SETTING, False)

        # NOTE: Don't call clear_stale_permission here - concurrent permissions are valid
        # Stale permission cleanup is handled by clear_all_permissions() on query completion

        # Check if tool is auto-allowed for session (match against saved patterns)
        for pattern in self.auto_allow_tools:
            if match_permission_pattern(tool, tool_input, pattern):
                callback(PERM_ALLOW)
                return

        # Check if user chose "allow for 30s" recently
        now = time.time()
        if self._last_allowed_tool == tool and (now - self._last_allowed_time) < 30:
            callback(PERM_ALLOW)
            return

        # Check if batch allow is active for Write/Edit
        if self._batch_allow_active:
            if not self._batch_allow_edits_only or tool in ("Write", "Edit"):
                callback(PERM_ALLOW)
                return

        # Create the request
        perm = PermissionRequest(
            id=pid,
            tool=tool,
            tool_input=tool_input,
            callback=callback,
        )

        # If there's already a pending permission, queue this one
        if self.pending_permission and self.pending_permission.callback:
            self._permission_queue.append(perm)
            return

        # Show this one
        self.pending_permission = perm
        self._render_permission()
        self._scroll_to_end()

    def _render_permission(self) -> None:
        """Render the permission request block."""
        if not self.pending_permission or not self.view:
            return

        perm = self.pending_permission
        tool = perm.tool
        tool_input = perm.tool_input

        # Format tool details and display name
        detail = ""
        display_tool = tool
        if tool == "Bash" and "command" in tool_input:
            cmd = tool_input["command"]
            if len(cmd) > 80:
                cmd = cmd[:80] + "..."
            detail = cmd
        elif tool in ("Read", "Edit", "Write"):
            detail = tool_input.get("file_path") or tool_input.get("description") or ""
        elif tool == "Glob" and "pattern" in tool_input:
            detail = tool_input["pattern"]
        elif tool == "Grep" and "pattern" in tool_input:
            detail = tool_input["pattern"]
        elif tool == "Skill" and "skill" in tool_input:
            # Show skill name as the tool name for better clarity
            skill_name = tool_input["skill"]
            display_tool = f"Skill: {skill_name}"
            # Show args if present
            if "args" in tool_input and tool_input["args"]:
                detail = tool_input["args"]
        else:
            # Generic: show first param
            for k, v in list(tool_input.items())[:1]:
                detail = f"{k}: {str(v)[:60]}"

        # Build permission block
        lines = [
            "\n",
            f"  ⚠ Allow {display_tool}",
        ]
        if detail:
            lines.append(f": {detail}")
        lines.append("?\n")

        # Show diff preview for Edit/Write tools
        if tool == "Edit" and "file_path" in tool_input:
            from .output_format import format_edit_diff, format_unified_diff
            old = tool_input.get("old_string", "")
            new = tool_input.get("new_string", "")
            unified = tool_input.get("unified_diff", "")
            if unified:
                diff_preview = format_unified_diff(unified)
            else:
                diff_preview = format_edit_diff(old, new)
            if diff_preview:
                # Indent each line of the diff preview
                diff_lines = diff_preview.strip().split("\n")
                for dl in diff_lines:
                    lines.append(f"    {dl}\n")
        elif tool == "Write" and "file_path" in tool_input:
            content = tool_input.get("content", "")
            file_path = tool_input["file_path"]
            if content:
                content_lines = content.splitlines()
                preview_lines = content_lines[:15]
                if len(content_lines) > 15:
                    preview_lines.append(f"... ({len(content_lines) - 15} more lines)")
                lines.append(f"    → Will write {len(content_lines)} lines to {file_path}\n")
                for pl in preview_lines:
                    pl_truncated = pl[:76] + "…" if len(pl) > 76 else pl
                    lines.append(f"    │ {pl_truncated}\n")

        lines.append("    ")

        # Track button positions relative to block start
        text_before_buttons = "".join(lines)

        # Check if this is a dangerous command that shouldn't have "Always allow"
        hide_always = False
        if tool == "Bash" and "command" in tool_input:
            cmd = tool_input["command"]
            # Hide "Always" for dangerous commands: rm, git checkout, git reset
            dangerous_patterns = [
                'rm ', 'rm\t',
                'git checkout', 'git reset',
                'git clean', 'git stash drop'
            ]
            if any(pattern in cmd for pattern in dangerous_patterns):
                hide_always = True

        # Buttons
        btn_y = "[Y] Allow"
        btn_n = "[N] Deny"
        btn_s = "[S] Allow 30s"
        # Batch Allow: auto-approves all Write/Edit for current query
        show_batch = tool in ("Write", "Edit")
        btn_b = "[B] Batch Allow" if show_batch else None

        # Create descriptive "Always" button based on what pattern will be saved
        always_hint = ""
        if tool == "Bash" and "command" in tool_input:
            # Preview the pattern that make_auto_allow_pattern would create
            pattern = make_auto_allow_pattern(tool, tool_input)
            if pattern != tool and "(" in pattern:
                # Extract the specifier part: "Bash(git:*)" → "git:*"
                always_hint = f" `{pattern[pattern.index('(')+1:-1]}`"
        elif tool in ("Read", "Write", "Edit") and "file_path" in tool_input:
            import os
            dir_path = os.path.dirname(tool_input["file_path"])
            if dir_path:
                # Shorten long paths
                if len(dir_path) > 25:
                    dir_path = "..." + dir_path[-22:]
                always_hint = f" in `{dir_path}/`"
        btn_a = f"[A] Always{always_hint}"

        lines.append(btn_y)
        lines.append("  ")
        lines.append(btn_n)
        lines.append("  ")
        lines.append(btn_s)
        if show_batch and btn_b:
            lines.append("  ")
            lines.append(btn_b)
        if not hide_always:
            lines.append("  ")
            lines.append(btn_a)
        else:
            lines.append("  (Always disabled for safety)")
        lines.append("\n")

        text = "".join(lines)

        # Write to view
        start = self.view.size()
        end = self._write(text)
        perm.region = (start, end)

        # Add tracked region for the whole permission block (auto-adjusts when text shifts)
        self.view.add_regions(
            PERMISSION_REGION_KEY,
            [sublime.Region(start, end)],
            "",
            "",
            sublime.HIDDEN,
        )

        # Calculate button regions (absolute positions)
        btn_start = start + len(text_before_buttons)
        perm.button_regions[PERM_ALLOW] = (btn_start, btn_start + len(btn_y))
        btn_start += len(btn_y) + 2  # +2 for "  "
        perm.button_regions[PERM_DENY] = (btn_start, btn_start + len(btn_n))
        btn_start += len(btn_n) + 2
        perm.button_regions[PERM_ALLOW_SESSION] = (btn_start, btn_start + len(btn_s))
        btn_start += len(btn_s) + 2
        if show_batch and btn_b:
            perm.button_regions[PERM_BATCH] = (btn_start, btn_start + len(btn_b))
            btn_start += len(btn_b) + 2
        if not hide_always:
            perm.button_regions[PERM_ALLOW_ALL] = (btn_start, btn_start + len(btn_a))

        # Add regions for highlighting
        self._add_button_regions()

    def _add_button_regions(self) -> None:
        """Add sublime regions for button highlighting."""
        if not self.pending_permission or not self.view:
            return

        perm = self.pending_permission
        for btn_type, (start, end) in perm.button_regions.items():
            region_key = f"claude_btn_{btn_type}"
            self.view.add_regions(
                region_key,
                [sublime.Region(start, end)],
                f"claude.permission.button.{btn_type}",
                "",
                sublime.DRAW_NO_OUTLINE,
            )

    def _clear_permission(self) -> None:
        """Remove permission block from view (but keep pending_permission for same-tool detection)."""
        if not self.pending_permission or not self.view:
            return

        perm = self.pending_permission

        # Remove button regions
        for btn_type in perm.button_regions:
            self.view.erase_regions(f"claude_btn_{btn_type}")

        # Get current region from tracked region (auto-adjusted for text shifts)
        regions = self.view.get_regions(PERMISSION_REGION_KEY)
        if regions and regions[0].size() > 0:
            region = regions[0]
            self._replace(region.begin(), region.end(), "")
        elif self.current:
            # Fallback: remove everything after conversation region
            conv_end = self.current.region[1]
            view_size = self.view.size()
            if view_size > conv_end:
                self._replace(conv_end, view_size, "")

        # Update conversation region end to account for removed permission block
        if self.current:
            self.current.region = (self.current.region[0], self.view.size())

        self.view.erase_regions(PERMISSION_REGION_KEY)
        # Don't clear pending_permission - keep it to detect rapid same-tool requests
        # It will be overwritten when a different tool request comes in

    def _respond_permission_with_callback(self, response: str, callback, tool: str, tool_input: dict = None) -> None:
        """Respond to a permission request with given callback."""

        # Handle "allow all" - save to project settings and remember for this session
        if response == PERM_ALLOW_ALL:
            pattern = make_auto_allow_pattern(tool, tool_input)
            self.auto_allow_tools.add(pattern)
            self._save_auto_allowed_tool(pattern)
            response = PERM_ALLOW

        # Handle "allow 30s" - set timed auto-allow
        if response == PERM_ALLOW_SESSION:
            self._last_allowed_tool = tool
            self._last_allowed_time = time.time()
            response = PERM_ALLOW

        # Handle "batch allow" - auto-approve all Write/Edit for current query
        if response == PERM_BATCH:
            self._batch_allow_active = True
            self._batch_allow_edits_only = True
            response = PERM_ALLOW

        # Clear the UI
        self._clear_permission()
        self.pending_permission = None

        # Move cursor to end so auto-scroll resumes
        self._move_cursor_to_end()

        # Call the callback
        callback(response)

        # Process next queued permission if any
        self._process_permission_queue()

    def _load_persisted_auto_allow(self) -> set:
        """Load autoAllowedMcpTools from project settings at session start."""
        try:
            from .settings import load_project_settings
            folders = self.window.folders()
            project_dir = folders[0] if folders else None
            settings = load_project_settings(project_dir)
            return set(settings.get("autoAllowedMcpTools", []))
        except Exception:
            return set()

    def _save_auto_allowed_tool(self, tool: str) -> None:
        """Save a tool to the auto-allowed list in project settings."""
        import os
        import json

        # Get project directory
        folders = self.window.folders()
        if not folders:
            print(f"[Claude] Cannot save auto-allowed tool: no project folder")
            return

        project_dir = folders[0]
        settings_dir = os.path.join(project_dir, ".claude")
        settings_path = os.path.join(settings_dir, "settings.json")

        # Load current settings
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            except Exception as e:
                print(f"[Claude] Error loading settings: {e}")
                return

        # Add tool to auto-allowed list
        auto_allowed = settings.get("autoAllowedMcpTools", [])
        if tool not in auto_allowed:
            auto_allowed.append(tool)
            settings["autoAllowedMcpTools"] = auto_allowed

            # Save settings
            os.makedirs(settings_dir, exist_ok=True)
            try:
                with open(settings_path, "w") as f:
                    json.dump(settings, f, indent=2)
                print(f"[Claude] Saved auto-allowed tool: {tool}")
                sublime.status_message(f"Auto-allowed: {tool}")
            except Exception as e:
                print(f"[Claude] Failed to save settings: {e}")

    def _process_permission_queue(self) -> None:
        """Process the next permission request in queue."""

        while self._permission_queue:
            perm = self._permission_queue.pop(0)

            # Check if auto-allowed now (user may have clicked "Always" or "30s")
            auto_allowed = False
            for pattern in self.auto_allow_tools:
                if match_permission_pattern(perm.tool, perm.tool_input, pattern):
                    perm.callback(PERM_ALLOW)
                    auto_allowed = True
                    break
            if auto_allowed:
                continue

            now = time.time()
            if self._last_allowed_tool == perm.tool and (now - self._last_allowed_time) < 30:
                perm.callback(PERM_ALLOW)
                continue

            # Show this one
            self.pending_permission = perm
            self._render_permission()
            self._scroll_to_end()
            break

    def handle_permission_key(self, key: str) -> bool:
        """Handle Y/N/A key press. Returns True if handled."""
        if not self.pending_permission:
            return False

        # Check if already responded
        if self.pending_permission.callback is None:
            return False

        perm = self.pending_permission
        key = key.lower()
        response = None
        if key == "y":
            response = PERM_ALLOW
        elif key == "n":
            response = PERM_DENY
        elif key == "s":
            response = PERM_ALLOW_SESSION
        elif key == "a":
            response = PERM_ALLOW_ALL
        elif key == "b":
            response = PERM_BATCH

        if response:
            # Mark as handled immediately
            callback = perm.callback
            perm.callback = None
            self._respond_permission_with_callback(response, callback, perm.tool, perm.tool_input)
            return True
        return False
