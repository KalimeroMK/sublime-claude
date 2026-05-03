"""Heartbeat monitor for detecting dead or stalled bridge processes."""
import time

import sublime


class HeartbeatMonitor:
    """Periodic heartbeat to detect dead bridges and stalls early.

    Delegates bridge actions back to the Session instance.
    """

    HEARTBEAT_INTERVAL_MS = 15000  # 15 seconds
    STALL_WARNING_THRESHOLD_S = 60
    STALL_RESTART_THRESHOLD_S = 120

    def __init__(self, session):
        self._s = session
        self._timer = None
        self._stall_warning_shown = False

    # ─── Public API ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start periodic heartbeat."""
        self.stop()
        self._timer = sublime.set_timeout(self._beat, self.HEARTBEAT_INTERVAL_MS)

    def stop(self) -> None:
        """Stop the heartbeat timer."""
        if self._timer:
            sublime.cancel_timeout(self._timer)
            self._timer = None

    def reset_stall_warning(self) -> None:
        """Reset stall warning flag (call at start of new query)."""
        self._stall_warning_shown = False

    # ─── Internal ─────────────────────────────────────────────────────────

    def _beat(self) -> None:
        """Periodic check: if bridge died silently, show warning."""
        self._timer = None
        s = self._s
        if not s.client or not s.initialized:
            return

        if not s.client.is_alive():
            # Bridge died silently — auto-restart.
            if s.working:
                print("[Claude] Heartbeat: bridge died mid-query, auto-restarting (in-flight query lost)...")
                try:
                    s.output.text("\n\n*Bridge process died mid-query. Auto-restarting — please resubmit your last prompt.*\n")
                except Exception:
                    pass
            else:
                print("[Claude] Heartbeat: bridge died silently, auto-restarting...")
            s._auto_restart_bridge()
        elif self._is_stalled():
            stalled_for = time.time() - s.last_activity
            print(f"[Claude] Heartbeat: bridge stalled ({stalled_for:.0f}s no events), auto-restarting...")
            try:
                s.output.text("\n\n*No response for ~2 min — likely stalled. Auto-restarting; please resubmit your last prompt.*\n")
            except Exception:
                pass
            s._auto_restart_bridge()
        else:
            if s.working and not self._stall_warning_shown:
                silent_for = time.time() - s.last_activity
                if silent_for > self.STALL_WARNING_THRESHOLD_S and not (
                    s.output.pending_permission
                    or s.output.pending_plan
                    or s.output.pending_question
                ):
                    self._stall_warning_shown = True
                    s._status("waiting for response...")
                    print(f"[Claude] Heartbeat: {silent_for:.0f}s of silence — will auto-restart at {self.STALL_RESTART_THRESHOLD_S}s if no events arrive")
            # Schedule next beat
            self.start()

    def _is_stalled(self) -> bool:
        """Bridge is alive but produced no events for too long while working."""
        s = self._s
        if not s.working:
            return False
        if (time.time() - s.last_activity) <= self.STALL_RESTART_THRESHOLD_S:
            return False
        # User is reviewing a permission/plan/question — not a stall.
        if s.output.pending_permission or s.output.pending_plan or s.output.pending_question:
            return False
        return True
