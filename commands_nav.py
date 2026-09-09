"""Cmd+Click / goto that understands Laravel and Yii helper strings.

A PHP language server sees view('emails.layout') as a string. This command tries
the framework resolvers first and hands off to LSP when the cursor is on a real
symbol, so one binding covers both.
"""
import os

import sublime
import sublime_plugin

from . import framework_nav
from .constants import OUTPUT_VIEW_SETTING


def _cursor_point(view, event=None):
    """Where the user actually pointed: the click position, else the caret."""
    if event and "x" in event and "y" in event:
        return view.window_to_text((event["x"], event["y"]))
    sel = view.sel()
    return sel[0].b if sel else 0


class ClaudeGotoDefinitionCommand(sublime_plugin.TextCommand):
    """Resolve a Laravel/Yii helper string, or fall through to LSP."""

    def want_event(self):
        return True

    def is_enabled(self, event=None):
        return not self.view.settings().get(OUTPUT_VIEW_SETTING)

    def run(self, edit, event=None):
        point = _cursor_point(self.view, event)
        targets = self._resolve(point)

        if not targets:
            # Not a framework string — let the language server answer.
            self.view.run_command("lsp_symbol_definition")
            return

        if len(targets) == 1:
            self._open(targets[0])
            return

        window = self.view.window()
        root = self._root() or ""
        labels = [[os.path.relpath(t["path"], root) if root else t["path"],
                   "line {}".format(t["line"]) if t["line"] else ""] for t in targets]

        def on_done(i):
            if i >= 0:
                self._open(targets[i])

        window.show_quick_panel(labels, on_done, placeholder="Go to…")

    def _root(self):
        window = self.view.window()
        folders = window.folders() if window else []
        return framework_nav.find_root(self.view.file_name(), folders)

    def _resolve(self, point):
        root = self._root()
        if not root:
            return []
        call = framework_nav.call_at(self.view.substr(sublime.Region(0, self.view.size())), point)
        if not call:
            return []
        kind, arg = call
        framework = framework_nav.detect_framework(root) or "laravel"
        try:
            return framework_nav.resolve(kind, arg, root, framework)
        except Exception as e:
            print("[Claude] framework goto failed for {}({!r}): {}".format(kind, arg, e))
            return []

    def _open(self, target):
        window = self.view.window()
        if not window:
            return
        spec = target["path"]
        if target["line"]:
            spec += ":{}".format(target["line"])
        window.open_file(spec, sublime.ENCODED_POSITION)
