"""Bridge lifecycle management — start, stop, interrupt, sleep, wake, restart."""
import sublime


class BridgeManager:
    """Manages the bridge process lifecycle for a Session."""

    def __init__(self, session):
        self._s = session

    def interrupt(self, break_channel: bool = True) -> None:
        """Interrupt current query."""
        if self._s.client:
            sent = self._s.client.send("interrupt", {})
            self._s._status_mgr.status("interrupting...")
            self._s._queued_prompts.clear()
            if not sent:
                self._s.working = False
                self._s._status_mgr.status("error: bridge died")
                self._s.output.text("\n\n*Bridge process died. Please restart the session.*\n")
                self._s._enter_input_with_draft()

        if break_channel and self._s.output.view:
            from . import notalone
            notalone.interrupt_channel(self._s.output.view.id())

    def stop(self) -> None:
        """Stop session and clean up."""
        self._s._persist_state("closed")
        self._s._stop_heartbeat()
        if self._s.persona_session_id and self._s.persona_url:
            self._s._release_persona()

        if self._s.client:
            client = self._s.client
            client.send("shutdown", {}, lambda _: client.stop())
        self._s._status_mgr.clear()

        if self._s.output:
            self._s.output.conversations.clear()
        self._s.pending_context.clear()
        self._s._queued_prompts.clear()

    def sleep(self) -> None:
        """Put session to sleep — kill bridge, keep view."""
        if not self._s.session_id:
            return
        if self._s.working:
            self.interrupt()
            sublime.set_timeout(self.sleep, 500)
            return
        self._s._stop_heartbeat()
        if self._s.client:
            client = self._s.client
            self._s.client = None
            client.send("shutdown", {}, lambda _: client.stop())
        self._s.initialized = False
        self._s._persist_state("sleeping")
        self._s._apply_sleep_ui()

    def wake(self) -> None:
        """Wake a sleeping session — re-spawn bridge with resume."""
        if self._s.client or self._s.initialized:
            return
        if not self._s.session_id:
            return
        self._s._ui.clear_overlay()
        if self._s.output and self._s.output.view:
            view = self._s.output.view
            view.settings().erase("claude_sleeping")
            end = view.size()
            view.sel().clear()
            view.sel().add(end)
            view.show(end)
        self._s.resume_id = self._s.session_id
        self._s.fork = False
        resume_at = self._s._pending_resume_at
        self._s.current_tool = "waking..."
        self._s.start(resume_session_at=resume_at)
        self._s._persist_state("open")
        if self._s.output and self._s.output.view:
            self._s.output.set_name(self._s.display_name)

    def restart(self) -> None:
        """Restart session — sleep then immediately wake."""
        def do_wake():
            if self._s.output and self._s.output.view and self._s.output.view.settings().get("claude_sleeping"):
                self.wake()
        self.sleep()
        sublime.set_timeout(do_wake, 600)

    def ensure_alive(self, silent: bool = False) -> bool:
        """Check bridge health; auto-restart if dead."""
        if self._s.client and self._s.client.is_alive() and self._s.initialized:
            return True
        if not silent:
            self._s.output.text("\n*Bridge process died. Auto-restarting...*\n")
        return self.auto_restart()

    def auto_restart(self) -> bool:
        """Kill dead bridge and restart with resume."""
        if self._s.client:
            try:
                self._s.client.stop()
            except Exception:
                pass
            self._s.client = None
        self._s.initialized = False
        self._s.working = False
        self._s._clear_deferred_state()

        if not self._s.session_id:
            return False

        self._s.resume_id = self._s.session_id
        self._s.fork = False
        resume_at = self._s._pending_resume_at
        self._s.current_tool = "reconnecting..."
        self._s._status_mgr.status("reconnecting...")
        try:
            self._s.start(resume_session_at=resume_at)
            self._s._persist_state("open")
            return True
        except Exception as e:
            print(f"[Claude] Auto-restart failed: {e}")
            self._s._status_mgr.status("error: restart failed")
            return False

    def release_persona(self) -> None:
        """Release acquired persona."""
        import threading
        from . import persona_client

        session_id = self._s.persona_session_id
        persona_url = self._s.persona_url

        def release():
            result = persona_client.release_persona(session_id, base_url=persona_url)
            if "error" not in result:
                print(f"[Claude] Released persona for session {session_id}")

        threading.Thread(target=release, daemon=True).start()
