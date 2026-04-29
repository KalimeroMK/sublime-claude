"""Voice input commands using macOS afrecord + Whisper API."""
import os
import subprocess
import tempfile
import sublime
import sublime_plugin

from .core import get_active_session


class ClaudeVoiceInputCommand(sublime_plugin.WindowCommand):
    """Record audio and transcribe via Whisper API."""

    _recording = False
    _audio_path = None

    def run(self) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Start audio recording."""
        platform = sublime.platform()

        if platform == "osx":
            # macOS: use afrecord
            self._audio_path = os.path.join(tempfile.gettempdir(), "claude_voice_input.wav")
            # Remove old file
            if os.path.exists(self._audio_path):
                os.remove(self._audio_path)
            # Start recording in background (30s max)
            self._proc = subprocess.Popen(
                ["afrecord", "-d", "30", self._audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            sublime.status_message("Voice input: only macOS is supported")
            return

        self._recording = True
        sublime.status_message("Recording... press Cmd+Shift+V to stop")

    def _stop_recording(self) -> None:
        """Stop recording and transcribe."""
        if not self._recording or not self._audio_path:
            return

        # Stop the recording process
        if hasattr(self, "_proc") and self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

        self._recording = False
        sublime.status_message("Transcribing...")

        # Check if file exists and has content
        if not os.path.exists(self._audio_path) or os.path.getsize(self._audio_path) < 1024:
            sublime.status_message("No audio recorded")
            return

        # Transcribe via Whisper API
        self._transcribe()

    def _transcribe(self) -> None:
        """Send audio to Whisper API and insert text."""
        # Get API key from settings
        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        api_key = settings.get("openai_api_key", "")

        if not api_key:
            sublime.status_message("No OpenAI API key. Set openai_api_key in settings.")
            return

        try:
            import urllib.request
            import urllib.parse

            # Build multipart request
            boundary = "----VoiceFormBoundary"
            data = []
            data.append(f"--{boundary}\r\n".encode())
            data.append(b'Content-Disposition: form-data; name="model"\r\n\r\n')
            data.append(b"whisper-1\r\n")
            data.append(f"--{boundary}\r\n".encode())
            data.append(b'Content-Disposition: form-data; name="file"; filename="voice.wav"\r\n')
            data.append(b"Content-Type: audio/wav\r\n\r\n")
            with open(self._audio_path, "rb") as f:
                data.append(f.read())
            data.append(b"\r\n")
            data.append(f"--{boundary}--\r\n".encode())

            body = b"".join(data)

            req = urllib.request.Request(
                "https://api.openai.com/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                import json
                result = json.loads(resp.read().decode())
                text = result.get("text", "").strip()

            if text:
                # Insert text into active view (Claude output view if in input mode)
                session = get_active_session(self.window)
                if session and session.output.view and session.output.is_input_mode():
                    session.output.view.run_command("insert", {"characters": text})
                    sublime.status_message(f"Voice: {text[:40]}...")
                else:
                    # Fallback: insert into active view
                    view = self.window.active_view()
                    if view:
                        view.run_command("insert", {"characters": text})
                        sublime.status_message(f"Voice: {text[:40]}...")
            else:
                sublime.status_message("No speech detected")

        except Exception as e:
            sublime.status_message(f"Transcription error: {e}")
            print(f"[Claude] Voice input error: {e}")

        # Cleanup
        try:
            if os.path.exists(self._audio_path):
                os.remove(self._audio_path)
        except Exception:
            pass
        self._audio_path = None

    def is_enabled(self) -> bool:
        return sublime.platform() == "osx"
