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


class ClaudeCodeTogglePermissionModeCommand(sublime_plugin.WindowCommand):
    """Toggle between permission modes."""

    MODES = ["default", "acceptEdits", "bypassPermissions"]
    MODE_LABELS = {
        "default": "Default (prompt for all)",
        "acceptEdits": "Accept Edits (auto-approve file ops)",
        "bypassPermissions": "Bypass (allow all - use with caution)",
    }

    def run(self):
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        current = settings.get("permission_mode", "default")

        items = []
        current_idx = 0
        for i, mode in enumerate(self.MODES):
            label = self.MODE_LABELS[mode]
            if mode == current:
                label = f"● {label}"
                current_idx = i
            else:
                label = f"  {label}"
            items.append(label)

        def on_select(idx):
            if idx >= 0:
                new_mode = self.MODES[idx]
                settings.set("permission_mode", new_mode)
                sublime.save_settings("ClaudeCode.sublime-settings")
                sublime.status_message(f"Claude: permission mode = {new_mode}")

                s = get_active_session(self.window)
                if s and s.client:
                    s.client.send("set_permission_mode", {"mode": new_mode})

        self.window.show_quick_panel(items, on_select, selected_index=current_idx)


# --- Input Mode Commands ---


class ClaudeSubmitInputCommand(sublime_plugin.TextCommand):
    """Handle Enter key in input mode - submit the prompt."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if not s:
            return

        # Wake sleeping session on Enter
        if s.is_sleeping:
            s.wake()
            return

        # Check for question free-text input first
        if s.output.submit_question_input():
            return

        if not s.output.is_input_mode():
            return

        text = s.output.get_input_text().strip()

        # Ignore empty input
        if not text:
            return

        # Check for slash commands
        cmd = CommandParser.parse(text)
        if cmd:
            s.output.exit_input_mode(keep_text=False)
            s.draft_prompt = ""
            self._handle_command(s, cmd)
            return

        s.output.exit_input_mode(keep_text=False)
        s.draft_prompt = ""

        # If session is working, queue the prompt instead
        if s.working:
            s.queue_prompt(text)
        else:
            s.query(text)

    def _handle_command(self, session, cmd):
        """Handle a slash command."""
        if cmd.name == "clear":
            self._cmd_clear(session)
        elif cmd.name == "compact":
            self._cmd_compact(session)
        elif cmd.name == "context":
            self._cmd_context(session)
        else:
            # Unknown command - send as regular prompt to Claude
            session.query(cmd.raw)

    def _cmd_clear(self, session):
        """Clear conversation history."""
        session.output.clear()
        sublime.status_message("Claude: conversation cleared")

    def _cmd_compact(self, session):
        """Send /compact to Claude for context summarization."""
        session.query("/compact", display_prompt="/compact")

    def _cmd_context(self, session):
        """Show pending context items."""
        if not session.pending_context:
            session.output.text("\n*No pending context.*\n")
        else:
            lines = ["\n*Pending context:*"]
            for item in session.pending_context:
                lines.append(f"  📎 {item.name}")
            lines.append("")
            session.output.text("\n".join(lines))
        session.output.enter_input_mode()



class ClaudeReplaceContentCommand(sublime_plugin.TextCommand):
    """Replace entire view content."""
    def run(self, edit, content):
        self.view.replace(edit, sublime.Region(0, self.view.size()), content)



class ClaudeInsertNewlineCommand(sublime_plugin.TextCommand):
    """Insert newline in input mode (Shift+Enter)."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s and s.output.is_input_mode():
            for region in self.view.sel():
                if s.output.is_in_input_region(region.begin()):
                    self.view.insert(edit, region.begin(), "\n")


# --- Permission Commands ---


class ClaudePermissionAllowCommand(sublime_plugin.TextCommand):
    """Handle Y key - allow permission or approve plan."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            if not s.output.handle_plan_key("y"):
                s.output.handle_permission_key("y")



class ClaudePermissionDenyCommand(sublime_plugin.TextCommand):
    """Handle N key - deny permission or reject plan."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            if not s.output.handle_plan_key("n"):
                s.output.handle_permission_key("n")



class ClaudeUndoMessageCommand(sublime_plugin.TextCommand):
    """Undo last conversation turn."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            s.undo_message()



class ClaudeClearNotificationsCommand(sublime_plugin.WindowCommand):
    """List and clear active notifications."""
    def run(self) -> None:
        import threading

        def fetch():
            import json, socket
            sock_path = os.path.expanduser("~/.notalone/notalone.sock")
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(sock_path)
                sock.sendall((json.dumps({"method": "list"}) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                sock.close()
                result = json.loads(data.decode().strip())
                notifications = result.get("notifications", [])
            except Exception as e:
                sublime.set_timeout(lambda: sublime.status_message(f"notalone not available: {e}"), 0)
                return

            if not notifications:
                sublime.set_timeout(lambda: sublime.status_message("No active notifications"), 0)
                return

            items = []
            for n in notifications:
                ntype = n.get("type", "?")
                nid = n.get("id", "?")
                params = n.get("params", {})
                desc = params.get("display_message") or params.get("wake_prompt", "")[:50] or str(params)[:50]
                items.append([f"{ntype}: {desc}", f"id: {nid}"])

            def show():
                def on_select(idx):
                    if idx < 0:
                        return
                    # Clear selected notification
                    nid = notifications[idx].get("id")
                    if nid:
                        threading.Thread(target=lambda: _unregister(nid, sock_path), daemon=True).start()

                self.window.show_quick_panel(items, on_select)

            sublime.set_timeout(show, 0)

        def _unregister(nid, sock_path):
            import json, socket
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(sock_path)
                sock.sendall((json.dumps({"method": "unregister", "notification_id": nid}) + "\n").encode())
                data = sock.recv(4096)
                sock.close()
                sublime.set_timeout(lambda: sublime.status_message(f"Cleared notification {nid}"), 0)
            except Exception as e:
                sublime.set_timeout(lambda: sublime.status_message(f"Failed to clear: {e}"), 0)

        threading.Thread(target=fetch, daemon=True).start()



class ClaudePermissionAllowSessionCommand(sublime_plugin.TextCommand):
    """Handle S key - allow for 30s."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            s.output.handle_permission_key("s")



class ClaudePermissionAllowAllCommand(sublime_plugin.TextCommand):
    """Handle A key - allow all for this tool."""
    def run(self, edit):
        s = get_session_for_view(self.view)
        if s:
            s.output.handle_permission_key("a")



class ClaudeQuestionKeyCommand(sublime_plugin.TextCommand):
    """Handle number/o/enter keys for inline question UI."""
    def run(self, edit, key=""):
        s = get_session_for_view(self.view)
        if s:
            s.output.handle_question_key(key)


# --- Quick Prompts ---

QUICK_PROMPTS = {
    "refresh": "Re-read docs/agent/knowledge_index.md and the relevant guide for the current task. Then continue.",
    "retry": "That didn't work. Read the error carefully and try again with a different approach.",
    "continue": "Continue.",
}



class ClaudeQuickPromptCommand(sublime_plugin.TextCommand):
    """Send a quick prompt by key."""
    def run(self, edit, key: str):
        s = get_session_for_view(self.view)
        if not s:
            return
        prompt = QUICK_PROMPTS.get(key)
        if prompt and s.initialized and not s.working:
            s.query(prompt)


class ClaudePasteImageCommand(sublime_plugin.TextCommand):
    """Paste image from clipboard into context."""

    def run(self, edit):
        import os
        from .core import get_session_for_view

        session = get_session_for_view(self.view)
        if not session:
            sublime.status_message("No active Claude session")
            return

        image_data, mime_type, file_paths_from_clip = self._get_clipboard_image()

        # File/dir paths from Finder copy — use full paths from pasteboard
        if file_paths_from_clip:
            valid_paths = [p for p in file_paths_from_clip if os.path.exists(p)]
            if valid_paths:
                # Paste paths as text into the input
                path_text = "\n".join(valid_paths)
                self.view.run_command("insert", {"characters": path_text})
                sublime.status_message(f"Pasted {len(valid_paths)} path(s)")
                return

        if image_data:
            session.add_context_image(image_data, mime_type)
            sublime.status_message(f"Image added to context ({len(image_data)} bytes)")
            return

        # No image or file paths from pasteboard, check text clipboard
        text = sublime.get_clipboard()
        if text:
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            file_paths = [line for line in lines if os.path.isfile(line)]
            if file_paths:
                for path in file_paths:
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        session.add_context_file(path, content)
                    except Exception as e:
                        print(f"[Claude] Failed to add file {path}: {e}")
                sublime.status_message(f"Added {len(file_paths)} file(s) to context")
                return

            print(f"[Claude] paste: trying context paste...")
            if self._try_paste_as_context(session, text):
                print(f"[Claude] paste: added as context")
                return
            print(f"[Claude] paste: plain text insert")
            self.view.run_command("insert", {"characters": text})

    def _try_paste_as_context(self, session, text):
        import os
        from .listeners import _last_copy_meta
        if not _last_copy_meta:
            return False
        if _last_copy_meta["text"] != text:
            return False
        path = _last_copy_meta["file"]
        regions = _last_copy_meta["regions"]
        region_parts = []
        for start, end in regions:
            if start == end:
                region_parts.append(f"L{start}")
            else:
                region_parts.append(f"L{start}-L{end}")
        region_str = ",".join(region_parts)
        label = f"{path}:{region_str}"
        session.add_context_selection(label, text)
        sublime.status_message(f"Pasted as context: {os.path.basename(path)}:{region_str}")
        return True

    def _get_clipboard_image(self):
        """Check if clipboard contains image data using platform-specific helper."""
        import os
        import platform
        import subprocess
        import base64

        try:
            helpers_dir = os.path.join(os.path.dirname(__file__), "helpers")
            system = platform.system()

            if system == "Darwin":
                cmd = ["osascript", "-l", "JavaScript", os.path.join(helpers_dir, "clipboard_image.js")]
            elif system == "Linux":
                cmd = ["bash", os.path.join(helpers_dir, "clipboard_image_linux.sh")]
            elif system == "Windows":
                cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(helpers_dir, "clipboard_image_windows.ps1")]
            else:
                return None, None

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            output = result.stdout.strip()

            if output.startswith("file_paths"):
                paths = output.split("\n")[1:]
                paths = [p.strip() for p in paths if p.strip()]
                return None, None, paths

            if output.startswith("image/"):
                lines = output.split("\n")
                mime_type = lines[0]
                b64_data = lines[1] if len(lines) > 1 else ""
                if b64_data:
                    return base64.b64decode(b64_data), mime_type, None

            return None, None, None
        except Exception as e:
            print(f"[Claude] Clipboard error: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None



class ClaudeOpenLinkCommand(sublime_plugin.TextCommand):
    """Open file path or URL under cursor with Cmd+click."""

    def run(self, edit, event=None):
        import os
        import re
        import webbrowser

        # Get click position from event or use cursor
        if event:
            pt = self.view.window_to_text((event["x"], event["y"]))
        else:
            sel = self.view.sel()
            if not sel:
                return
            pt = sel[0].begin()

        # Get the line at cursor
        line_region = self.view.line(pt)
        line = self.view.substr(line_region)
        col = pt - line_region.begin()

        # Try to find URL at position
        url_pattern = r'https?://[^\s\]\)>\'"]+|file://[^\s\]\)>\'"]+'
        for match in re.finditer(url_pattern, line):
            if match.start() <= col <= match.end():
                url = match.group()
                webbrowser.open(url)
                return

        # Try to find file path at position (absolute or relative with common extensions)
        # Match paths like /foo/bar.py, ./foo/bar.nim, src/file.ts:123
        path_pattern = r'(?:[/.]|[a-zA-Z]:)[^\s:,\]\)\}>\'\"]+(?::\d+)?'
        for match in re.finditer(path_pattern, line):
            if match.start() <= col <= match.end():
                path_with_line = match.group()
                # Extract line number if present (path:123)
                line_num = None
                if ':' in path_with_line:
                    parts = path_with_line.rsplit(':', 1)
                    if parts[1].isdigit():
                        path_with_line = parts[0]
                        line_num = int(parts[1])

                # Check if file exists
                if os.path.isfile(path_with_line):
                    window = self.view.window()
                    if window:
                        if line_num:
                            window.open_file(f"{path_with_line}:{line_num}", sublime.ENCODED_POSITION)
                        else:
                            window.open_file(path_with_line)
                    return

        sublime.status_message("No link or file path found at cursor")

    def want_event(self):
        return True



