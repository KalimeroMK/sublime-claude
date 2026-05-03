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
