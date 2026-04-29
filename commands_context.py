"""Claude Code commands for Sublime Text."""
import json
import os
import sublime
import sublime_plugin
import platform

from .core import get_active_session, get_session_for_view, create_session
from .session import Session, load_saved_sessions
from .prompt_builder import PromptBuilder
from .command_parser import CommandParser

# Fallback model lists per backend (used when no cache/settings available)
DEFAULT_MODELS = {
    "claude": [
        ["opus", "Opus 4.7"],
        ["opus@400k", "Opus 4.7 (400K context)"],
        ["claude-opus-4-6[1m]", "Opus 4.6 (1M context)"],
        ["claude-opus-4-6[1m]@400k", "Opus 4.6 (400K context)"],
        ["claude-opus-4-6", "Opus 4.6"],
        ["sonnet", "Sonnet 4.6"],
        ["haiku", "Haiku 4.5"],
        ["claude-opus-4-5", "Opus 4.5"],
        ["claude-sonnet-4-5", "Sonnet 4.5"],
    ],
    "copilot": [
        ["claude-sonnet-4-6", "Sonnet 4.6"],
        ["claude-opus-4-6", "Opus 4.6"],
        ["gpt-5.3-codex", "GPT-5.3 Codex"],
        ["gpt-5-mini", "GPT-5 Mini (free)"],
    ],
    "codex": [
        ["gpt-5.5", "GPT-5.5"],
        ["gpt-5.4", "GPT-5.4"],
        ["gpt-5.4-mini", "GPT-5.4 Mini"],
        ["gpt-5.3-codex", "GPT-5.3 Codex"],
        ["o3", "O3"],
    ],
    "deepseek": [
        ["deepseek-v4-pro", "DeepSeek V4 Pro"],
        ["deepseek-v4-flash", "DeepSeek V4 Flash"],
    ],
    "openai": [
        ["gpt-4o", "GPT-4o"],
        ["gpt-4o-mini", "GPT-4o Mini"],
        ["gpt-4-turbo", "GPT-4 Turbo"],
        ["o3-mini", "O3 Mini"],
        ["llama3.1", "Ollama: Llama 3.1"],
        ["qwen2.5", "Ollama: Qwen 2.5"],
        ["mistral", "Ollama: Mistral"],
        ["phi4", "Ollama: Phi-4"],
    ],
}


class ClaudeCodeAddFileCommand(sublime_plugin.WindowCommand):
    """Add current file to context."""
    def run(self) -> None:
        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file to add")
            return
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return
        content = view.substr(sublime.Region(0, view.size()))
        s.add_context_file(view.file_name(), content)
        name = view.file_name().split("/")[-1]
        sublime.status_message(f"Added: {name}")



class ClaudeCodeAddSelectionCommand(sublime_plugin.WindowCommand):
    """Add selection to context."""
    def run(self) -> None:
        view = self.window.active_view()
        if not view:
            sublime.status_message("No active view")
            return
        sel = view.sel()
        if not sel or sel[0].empty():
            sublime.status_message("No selection")
            return
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return
        content = view.substr(sel[0])
        path = view.file_name() or "untitled"
        s.add_context_selection(path, content)
        name = path.split("/")[-1] if "/" in path else path
        sublime.status_message(f"Added selection from: {name}")



class ClaudeCodeAddOpenFilesCommand(sublime_plugin.WindowCommand):
    """Add all open files to context."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return
        count = 0
        for view in self.window.views():
            if view.file_name() and not view.settings().get("claude_output"):
                content = view.substr(sublime.Region(0, view.size()))
                s.add_context_file(view.file_name(), content)
                count += 1
        sublime.status_message(f"Added {count} files")



class ClaudeCodeAddFolderCommand(sublime_plugin.WindowCommand):
    """Add current file's folder path to context."""
    def run(self) -> None:
        import os

        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file open")
            return

        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session. Use 'Claude: New Session' first.")
            return

        folder = os.path.dirname(view.file_name())
        s.add_context_folder(folder)
        folder_name = folder.split("/")[-1]
        sublime.status_message(f"Added folder: {folder_name}/")



class ClaudeCodeClearContextCommand(sublime_plugin.WindowCommand):
    """Clear pending context."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if s:
            s.clear_context()
            sublime.status_message("Context cleared")



class ClaudeCodeQueuePromptCommand(sublime_plugin.WindowCommand):
    """Queue a prompt to be sent when current query finishes."""
    def run(self) -> None:
        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session")
            return
        s.show_queue_input()



class ClaudeAttachFileCommand(sublime_plugin.WindowCommand):
    """Attach a file or image to the current session."""
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}

    def run(self):
        session = get_active_session(self.window)
        if not session:
            sublime.status_message("Нема активна сесија")
            return
        # Use native file picker on macOS, input panel otherwise
        if platform.system() == "Darwin":
            import subprocess
            try:
                result = subprocess.run([
                    "osascript", "-e",
                    'POSIX path of (choose file with prompt "Избери фајл")'
                ], capture_output=True, text=True, timeout=30)
                path = result.stdout.strip()
                if path and os.path.isfile(path):
                    self._add(session, path)
                    return
            except Exception as e:
                print(f"[Claude] macOS picker error: {e}")
        # Fallback to input panel
        self.window.show_input_panel("Патека до фајл:", "", lambda p: self._add(session, p), None, None)

    def _add(self, session, path):
        if not path or not os.path.isfile(path):
            sublime.status_message("Невалидна патека")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in self._IMAGE_EXTS:
            # Image — send as binary with mime type
            try:
                with open(path, "rb") as f:
                    data = f.read()
                mime = "image/png"
                if ext in (".jpg", ".jpeg"): mime = "image/jpeg"
                elif ext == ".gif": mime = "image/gif"
                elif ext == ".webp": mime = "image/webp"
                elif ext == ".svg": mime = "image/svg+xml"
                session.add_context_image(data, mime)
                sublime.status_message(f"Додадена слика: {os.path.basename(path)}")
            except Exception as e:
                sublime.status_message(f"Грешка: {e}")
        else:
            # Regular file — send as text
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                session.add_context_file(path, content)
                sublime.status_message(f"Додаден фајл: {os.path.basename(path)}")
            except Exception as e:
                sublime.status_message(f"Грешка: {e}")

    def is_enabled(self):
        session = get_active_session(self.window)
        return session is not None


class ClaudeCodeGitCommitMessageCommand(sublime_plugin.WindowCommand):
    """Generate commit message from git diff."""
    def run(self) -> None:
        import subprocess

        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session")
            return

        project_root = self.window.folders()[0] if self.window.folders() else None
        if not project_root:
            sublime.status_message("No project folder")
            return

        # Get staged diff
        result = subprocess.run(
            ["git", "-C", project_root, "diff", "--staged"],
            capture_output=True, text=True, timeout=10
        )
        diff = result.stdout.strip() if result.returncode == 0 else ""

        # Fallback to unstaged
        if not diff:
            result = subprocess.run(
                ["git", "-C", project_root, "diff"],
                capture_output=True, text=True, timeout=10
            )
            diff = result.stdout.strip() if result.returncode == 0 else ""

        if not diff:
            sublime.status_message("No changes to commit")
            return

        # Truncate if too large
        if len(diff) > 20000:
            diff = diff[:20000] + "\n\n... [truncated]\n"

        prompt = (
            "Write a concise, conventional commit message for the following changes.\n"
            "Format: <type>(<scope>): <description>\n\n"
            "```diff\n" + diff + "\n```"
        )

        def on_done(response: str) -> None:
            if response and not response.startswith("Error"):
                # Show result in output view
                s.output.text("\n\n**Generated commit message:**\n```\n" + response.strip() + "\n```\n")
                s.output.show()
                sublime.status_message("Commit message generated")
            else:
                sublime.status_message("Failed to generate commit message")

        s.send_message_with_callback(prompt, on_done, display_prompt="[git commit message]")
        sublime.status_message("Generating commit message...")


class ClaudeCodeGitStatusCommand(sublime_plugin.WindowCommand):
    """Show git status in the Claude output view."""
    def run(self) -> None:
        import subprocess

        s = get_active_session(self.window)
        if not s:
            sublime.status_message("No active session")
            return

        project_root = self.window.folders()[0] if self.window.folders() else None
        if not project_root:
            sublime.status_message("No project folder")
            return

        result = subprocess.run(
            ["git", "-C", project_root, "status", "--short"],
            capture_output=True, text=True, timeout=10
        )
        status = result.stdout.strip() if result.returncode == 0 else ""

        if not status:
            s.output.text("\n\n*Working tree clean*\n")
        else:
            s.output.text("\n\n**Git status:**\n```\n" + status + "\n```\n")

        s.output.show()
        sublime.status_message("Git status shown")


