"""Plan approval UI mixin for OutputView."""
import sublime

from .constants import INPUT_MODE_SETTING, PLAN_REGION_KEY
from .output_models import PLAN_APPROVE, PLAN_REJECT, PLAN_VIEW, PlanApproval


class PlanUIRendererMixin:
    """Mixin for rendering plan approval blocks and handling user input."""

    def plan_approval_request(self, plan_id: int, plan_file: str,
                               allowed_prompts: list, callback) -> None:
        """Show an inline plan approval block."""
        self.show(focus=False)

        if self.view:
            self.view.settings().set(INPUT_MODE_SETTING, False)

        self.pending_plan = PlanApproval(
            id=plan_id,
            plan_file=plan_file,
            allowed_prompts=allowed_prompts,
            callback=callback,
        )
        self._render_plan_approval()
        self._scroll_to_end()

    def _render_plan_approval(self) -> None:
        """Render the plan approval block in the view."""
        if not self.pending_plan or not self.view:
            return

        plan = self.pending_plan
        lines = ["\n"]

        # Header
        lines.append("  ⚙ Plan complete — approve to start implementation\n")

        # Plan file
        if plan.plan_file:
            import os
            basename = os.path.basename(plan.plan_file)
            lines.append(f"    plan: {basename}\n")

        # Allowed prompts summary
        if plan.allowed_prompts:
            lines.append(f"    permissions: {len(plan.allowed_prompts)}\n")
            for p in plan.allowed_prompts[:3]:
                tool = p.get("tool", "?")
                prompt = p.get("prompt", "")
                lines.append(f"      • {tool}: {prompt}\n")
            if len(plan.allowed_prompts) > 3:
                lines.append(f"      ... and {len(plan.allowed_prompts) - 3} more\n")

        # Buttons
        lines.append("    ")
        text_before_buttons = "".join(lines)

        btn_y = "[Y] Approve"
        btn_n = "[N] Reject"
        btn_v = "[V] View Plan"

        lines.append(btn_y)
        lines.append("  ")
        lines.append(btn_n)
        lines.append("  ")
        lines.append(btn_v)
        lines.append("\n")

        text = "".join(lines)

        # Write to view
        start = self.view.size()
        end = self._write(text)
        plan.region = (start, end)

        # Track region
        self.view.add_regions(
            PLAN_REGION_KEY,
            [sublime.Region(start, end)],
            "", "", sublime.HIDDEN,
        )

        # Button regions
        btn_start = start + len(text_before_buttons)
        plan.button_regions[PLAN_APPROVE] = (btn_start, btn_start + len(btn_y))
        btn_start += len(btn_y) + 2
        plan.button_regions[PLAN_REJECT] = (btn_start, btn_start + len(btn_n))
        btn_start += len(btn_n) + 2
        plan.button_regions[PLAN_VIEW] = (btn_start, btn_start + len(btn_v))

        # Highlight buttons
        scope_map = {
            PLAN_APPROVE: "claude.permission.button.allow",
            PLAN_REJECT: "claude.permission.button.deny",
            PLAN_VIEW: "claude.permission.button.allow_session",
        }
        for btn_type, (bs, be) in plan.button_regions.items():
            self.view.add_regions(
                f"claude_plan_btn_{btn_type}",
                [sublime.Region(bs, be)],
                scope_map.get(btn_type, ""),
                "", sublime.DRAW_NO_OUTLINE,
            )

    def _clear_plan_approval(self) -> None:
        """Remove plan approval block from view."""
        if not self.pending_plan or not self.view:
            return

        for btn_type in self.pending_plan.button_regions:
            self.view.erase_regions(f"claude_plan_btn_{btn_type}")

        regions = self.view.get_regions(PLAN_REGION_KEY)
        if regions and regions[0].size() > 0:
            self._replace(regions[0].begin(), regions[0].end(), "")
        elif self.current:
            conv_end = self.current.region[1]
            view_size = self.view.size()
            if view_size > conv_end:
                self._replace(conv_end, view_size, "")
        self.view.erase_regions(PLAN_REGION_KEY)

    def handle_plan_key(self, key: str) -> bool:
        """Handle Y/N key for plan approval. Returns True if handled."""
        if not self.pending_plan:
            return False
        if self.pending_plan.callback is None:
            return False

        plan = self.pending_plan
        key = key.lower()

        if key == "v":
            if plan.plan_file:
                view = sublime.active_window().open_file(plan.plan_file)
                def enable_wrap(v=view):
                    if v.is_loading():
                        sublime.set_timeout(lambda: enable_wrap(v), 100)
                        return
                    v.settings().set("word_wrap", True)
                enable_wrap()
            return True

        if key == "y":
            response = PLAN_APPROVE
        elif key == "n":
            response = PLAN_REJECT
        else:
            return False

        callback = plan.callback
        plan.callback = None
        self._clear_plan_approval()
        self.pending_plan = None
        self._move_cursor_to_end()
        callback(response)
        return True
