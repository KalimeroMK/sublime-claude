"""Question UI mixin for OutputView."""
import re

import sublime

from .constants import INPUT_MODE_SETTING, QUESTION_REGION_KEY
from .output_models import QuestionRequest


class QuestionUIRendererMixin:
    """Mixin for rendering question blocks and handling user input."""

    def question_request(self, qid: int, questions: list, callback) -> None:
        """Show an inline question block."""
        self.show(focus=False)

        if self.view:
            self.view.settings().set(INPUT_MODE_SETTING, False)

        self.pending_question = QuestionRequest(
            qid=qid,
            questions=questions,
            callback=callback,
        )
        self._render_question()
        self._scroll_to_end(force=True)

    def _render_question(self) -> None:
        """Render the current question inline."""
        if not self.pending_question or not self.view:
            return

        q_req = self.pending_question
        if q_req.current_idx >= len(q_req.questions):
            return

        q = q_req.questions[q_req.current_idx]
        question_text = q.get("question", "")
        options = q.get("options", [])
        multi = q.get("multiSelect", False)

        lines = ["\n"]
        if multi:
            lines.append(f"  ❓ {question_text} (Enter to confirm)\n")
        else:
            lines.append(f"  ❓ {question_text}\n")

        # Numbered options
        for i, opt in enumerate(options):
            label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
            desc = opt.get("description", "") if isinstance(opt, dict) else ""
            num = i + 1
            if multi:
                check = "✓" if i in q_req.selected else " "
                line = f"    [{num}] {check} {label}"
            else:
                line = f"    [{num}] {label}"
            if desc:
                line += f" — {desc}"
            lines.append(line + "\n")

        # Other + confirm buttons
        if multi:
            lines.append(f"    [O] Other...  [⏎] Confirm\n")
        else:
            lines.append(f"    [O] Other...\n")

        text = "".join(lines)

        # Write to view
        start = self.view.size()
        end = self._write(text)
        q_req.region = (start, end)

        # Track region
        self.view.add_regions(
            QUESTION_REGION_KEY,
            [sublime.Region(start, end)],
            "", "", sublime.HIDDEN,
        )

        # Highlight option keys [1], [2], ..., [O], [⏎]
        key_regions = []
        for m in re.finditer(r'\[\d+\]|\[O\]|\[⏎\]', text):
            key_regions.append(sublime.Region(start + m.start(), start + m.end()))
        if key_regions:
            self.view.add_regions(
                "claude_question_keys",
                key_regions,
                "claude.permission.button.allow",
                "", sublime.DRAW_NO_OUTLINE,
            )

    def _clear_question(self, summary: str = "") -> None:
        """Remove question block and optionally write compact summary."""
        if not self.pending_question or not self.view:
            return

        # Erase the block
        regions = self.view.get_regions(QUESTION_REGION_KEY)
        if regions and regions[0].size() > 0:
            region = regions[0]
            if summary:
                self._replace(region.begin(), region.end(), f"\n  ❓ {summary}\n")
            else:
                self._replace(region.begin(), region.end(), "")
        elif not summary and self.current:
            # Fallback: remove everything after conversation region
            conv_end = self.current.region[1]
            view_size = self.view.size()
            if view_size > conv_end:
                self._replace(conv_end, view_size, "")
        self.view.erase_regions(QUESTION_REGION_KEY)
        self.view.erase_regions("claude_question_keys")

    def _advance_question(self) -> None:
        """Advance to next question or fire callback."""
        q_req = self.pending_question
        if not q_req:
            return

        q_req.current_idx += 1
        q_req.selected = set()  # Reset for next question

        if q_req.current_idx >= len(q_req.questions):
            # All done
            callback = q_req.callback
            answers = q_req.answers
            self.pending_question = None
            self._move_cursor_to_end()
            if callback:
                callback(answers)
        else:
            # Render next question
            self._render_question()
            self._scroll_to_end()

    def handle_question_key(self, key: str) -> bool:
        """Handle key press for question UI. Returns True if consumed."""
        if not self.pending_question:
            return False
        if self.pending_question.callback is None:
            return False

        q_req = self.pending_question
        q = q_req.questions[q_req.current_idx]
        options = q.get("options", [])
        multi = q.get("multiSelect", False)
        header = q.get("header", f"Q{q_req.current_idx + 1}")
        key = key.lower()

        # Number keys 1-4
        if key in ("1", "2", "3", "4"):
            idx = int(key) - 1
            if idx >= len(options):
                return True  # Consumed but invalid

            opt = options[idx]
            label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)

            if multi:
                # Toggle selection
                if idx in q_req.selected:
                    q_req.selected.discard(idx)
                else:
                    q_req.selected.add(idx)
                # Re-render (erase + redraw)
                self._clear_question()
                self._render_question()
                self._scroll_to_end()
            else:
                # Single select - record and advance
                q_req.answers[str(q_req.current_idx)] = label
                self._clear_question(f"{header} → {label}")
                self._advance_question()
            return True

        # O key - other (custom input via inline input mode)
        if key == "o":
            self._question_enter_input_mode()
            return True

        # Enter - confirm multi-select
        if key == "enter":
            if multi:
                selected_labels = []
                for idx in sorted(q_req.selected):
                    opt = options[idx]
                    label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
                    selected_labels.append(label)
                answer = ", ".join(selected_labels) if selected_labels else "(none)"
                q_req.answers[str(q_req.current_idx)] = answer
                self._clear_question(f"{header} → {answer}")
                self._advance_question()
                return True
            return False

        # Escape handled by interrupt flow
        return False

    def _question_enter_input_mode(self) -> None:
        """Enter inline input mode for free-text question answer."""
        if not self.view or not self.pending_question:
            return

        # Append input prompt after question block
        self.view.set_read_only(False)
        marker = "    ▸ "
        self.view.run_command("append", {"characters": marker})
        self._question_input_start = self.view.size()
        self._question_input_mode = True

        # Set standard input mode so keyboard/selection handling works
        self._input_start = self._question_input_start
        self._input_mode = True
        self.view.settings().set(INPUT_MODE_SETTING, True)

        # Move cursor to input position
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(self._question_input_start, self._question_input_start))
        self.view.show(self._question_input_start)

    def submit_question_input(self) -> bool:
        """Submit free-text input for question. Returns True if handled."""
        if not getattr(self, '_question_input_mode', False):
            return False
        if not self.pending_question or not self.view:
            self._question_input_mode = False
            return False

        # Get typed text
        text = self.view.substr(sublime.Region(self._question_input_start, self.view.size())).strip()
        self._question_input_mode = False
        self._input_mode = False
        self.view.settings().set(INPUT_MODE_SETTING, False)
        self.view.set_read_only(True)

        # Remove the input line
        marker_start = self._question_input_start - len("    ▸ ")
        self.view.set_read_only(False)
        self.view.run_command("claude_replace", {
            "start": max(0, marker_start),
            "end": self.view.size(),
            "text": ""
        })
        self.view.set_read_only(True)

        if text:
            q_req = self.pending_question
            q = q_req.questions[q_req.current_idx]
            header = q.get("header", f"Q{q_req.current_idx + 1}")
            q_req.answers[str(q_req.current_idx)] = text
            self._clear_question(f"{header} → {text}")
            self._advance_question()

        return True
