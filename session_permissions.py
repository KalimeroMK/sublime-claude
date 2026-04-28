"""Session permissions and plan mode mixin."""
import os
from typing import Optional

import sublime


class SessionPermissionsMixin:
    def _handle_permission_request(self, params: dict) -> None:
        """Handle permission request from bridge - show in output view."""
        from .output import PERM_ALLOW

        pid = params.get("id")
        tool = params.get("tool", "Unknown")
        tool_input = params.get("input", {})
        def on_response(response: str) -> None:
            if self.client:
                allow = (response == PERM_ALLOW)
                if not allow:
                    # Mark tool as error immediately - SDK won't send tool_result for denied
                    self.output.tool_error(tool)
                    self.current_tool = None
                self.client.send("permission_response", {
                    "id": pid,
                    "allow": allow,
                    "input": tool_input if allow else None,
                    "message": None if allow else "User denied permission",
                })

        # Show permission UI in output view
        self.output.permission_request(pid, tool, tool_input, on_response)

    def _handle_question_request(self, params: dict) -> None:
        """Handle AskUserQuestion from Claude - show inline question UI."""
        qid = params.get("id")
        questions = params.get("questions", [])
        if not questions:
            if self.client:
                self.client.send("question_response", {"id": qid, "answers": {}})
            return

        def on_done(answers):
            if self.client:
                self.client.send("question_response", {"id": qid, "answers": answers})

        self.output.question_request(qid, questions, on_done)

    # ─── Plan Mode ─────────────────────────────────────────────────────

    def _handle_plan_mode_enter(self, params: dict) -> None:
        """Handle entering plan mode."""
        self.plan_mode = True
        self._status("plan mode")

    def _handle_plan_mode_exit(self, params: dict) -> None:
        """Handle exiting plan mode - show inline approval UI."""
        from .output import PLAN_APPROVE
        plan_id = params.get("id")
        tool_input = params.get("tool_input", {})

        # Find the most recent plan file
        plan_file = self._find_plan_file()
        self.plan_file = plan_file
        allowed_prompts = tool_input.get("allowedPrompts", [])

        def on_response(response: str):
            approved = response == PLAN_APPROVE
            self.plan_mode = False

            if self.client:
                self.client.send("plan_response", {
                    "id": plan_id,
                    "approved": approved,
                })

            if approved:
                self._status("implementing...")
            else:
                self._status("ready")

        # Show inline approval block (like permission UI)
        self.output.plan_approval_request(
            plan_id=plan_id,
            plan_file=plan_file or "",
            allowed_prompts=allowed_prompts,
            callback=on_response,
        )

        # Open plan file if found
        if plan_file and os.path.exists(plan_file):
            view = self.window.open_file(plan_file)
            def enable_wrap(v=view):
                if v.is_loading():
                    sublime.set_timeout(lambda: enable_wrap(v), 100)
                    return
                v.settings().set("word_wrap", True)
            enable_wrap()

    def _find_plan_file(self) -> Optional[str]:
        """Find the most recent plan file in ~/.claude/plans/."""
        import glob
        plans_dir = os.path.expanduser("~/.claude/plans")
        if not os.path.exists(plans_dir):
            return None

        plan_files = glob.glob(os.path.join(plans_dir, "*.md"))
        if not plan_files:
            return None

        return max(plan_files, key=os.path.getmtime)

    # ─── Notification API (notalone2) ──────────────────────────────────

