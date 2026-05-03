"""Session UI overlay helpers — phantom overlays and status indicators."""
import sublime


class SessionUIHelper:
    """Helper for managing session UI overlays (phantoms, status)."""

    def __init__(self, session):
        self._s = session
        self._overlay_phantom_set = None

    def _get_overlay_phantom_set(self):
        if self._overlay_phantom_set is None:
            output = self._s.output
            if output and output.view:
                self._overlay_phantom_set = sublime.PhantomSet(output.view, "claude_overlay")
        return self._overlay_phantom_set

    def show_overlay(self, html_body: str, color: str = "color(var(--foreground) alpha(0.5))") -> None:
        """Show an overlay phantom at the end of the output view."""
        ps = self._get_overlay_phantom_set()
        output = self._s.output
        if not ps or not output or not output.view:
            return
        view = output.view
        content = view.substr(sublime.Region(0, view.size()))
        last_nl = content.rfind("\n")
        pt = last_nl if last_nl >= 0 else 0
        html = f'<body style="margin: 8px 0; color: {color};">{html_body}</body>'
        ps.update([sublime.Phantom(sublime.Region(pt, pt), html, sublime.LAYOUT_BLOCK)])
        view.sel().clear()
        view.sel().add(sublime.Region(view.size(), view.size()))
        view.show(view.size())

    def clear_overlay(self) -> None:
        """Clear any overlay phantom."""
        ps = self._get_overlay_phantom_set()
        if ps:
            ps.update([])

    def show_connecting(self) -> None:
        """Show the 'Connecting...' overlay."""
        self.show_overlay("◎ Connecting...")

    def apply_sleep(self) -> None:
        """Apply sleeping state to view UI."""
        s = self._s
        if not s.output or not s.output.view:
            return
        if not s.session_id:
            return
        view = s.output.view
        view.settings().set("claude_sleeping", True)
        s.output.set_name(s.display_name)
        s._status_mgr.status("sleeping")
        if s.output.is_input_mode():
            s.draft_prompt = s.output.get_input_text().strip()
            s.output.exit_input_mode(keep_text=False)
            s._input_mode_entered = False
        else:
            # Clean stale input marker from view content
            content = view.substr(sublime.Region(0, view.size()))
            lines = content.rstrip("\n").split("\n")
            if lines and lines[-1].strip() == "\u25ce":
                erase_from = content.rstrip("\n").rfind("\n" + lines[-1])
                if erase_from >= 0:
                    view.set_read_only(False)
                    view.run_command("claude_replace", {"start": erase_from, "end": view.size(), "text": ""})
                    view.set_read_only(True)
        self.show_overlay("\u23f8 Session paused \u2014 press Enter to wake", color="var(--yellowish)")
