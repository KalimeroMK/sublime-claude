"""Tests for JSON-RPC client."""
import unittest
import sys
import os
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpc import JsonRpcClient


class RpcClientTest(unittest.TestCase):
    """Test JSON-RPC client logic."""

    def setUp(self):
        self.notifications = []
        def on_notify(method, params):
            self.notifications.append((method, params))
        self.client = JsonRpcClient(on_notify)

    def test_initial_state(self):
        """Client starts in correct state."""
        self.assertIsNone(self.client.proc)
        self.assertEqual(self.client.request_id, 0)
        self.assertEqual(len(self.client.pending), 0)
        self.assertFalse(self.client.running)

    def test_send_without_proc_returns_false(self):
        """Send without process returns False."""
        result = self.client.send("test", {})
        self.assertFalse(result)

    def test_send_format(self):
        """Send produces correct JSON-RPC format."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        
        self.client.proc = mock_proc
        self.client.running = True
        
        result = self.client.send("initialize", {"key": "value"})
        self.assertTrue(result)
        
        # Check what was written
        written = mock_proc.stdin.write.call_args[0][0]
        msg = json.loads(written.decode().strip())
        
        self.assertEqual(msg["jsonrpc"], "2.0")
        self.assertEqual(msg["method"], "initialize")
        self.assertEqual(msg["params"], {"key": "value"})
        self.assertEqual(msg["id"], 1)

    def test_send_increments_request_id(self):
        """Each send increments request ID."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        
        self.client.proc = mock_proc
        self.client.running = True
        
        self.client.send("a", {})
        self.client.send("b", {})
        self.client.send("c", {})
        
        self.assertEqual(self.client.request_id, 3)

    def test_send_with_callback_stores_pending(self):
        """Callback is stored in pending."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        
        self.client.proc = mock_proc
        self.client.running = True
        
        cb = MagicMock()
        self.client.send("test", {}, callback=cb)
        
        self.assertIn(1, self.client.pending)
        self.assertEqual(self.client.pending[1], cb)

    def test_handle_response_with_result(self):
        """Response with result calls callback."""
        cb = MagicMock()
        self.client.pending[5] = cb
        
        self.client._handle({"id": 5, "result": {"data": "ok"}})
        
        cb.assert_called_once_with({"data": "ok"})
        self.assertNotIn(5, self.client.pending)

    def test_handle_response_with_error(self):
        """Response with error calls callback with error."""
        cb = MagicMock()
        self.client.pending[3] = cb
        
        self.client._handle({"id": 3, "error": {"message": "failed"}})
        
        cb.assert_called_once_with({"error": {"message": "failed"}})

    def test_handle_notification(self):
        """Notification calls on_notification."""
        self.client._handle({"method": "system.message", "params": {"text": "hello"}})
        
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(self.notifications[0], ("system.message", {"text": "hello"}))

    def test_handle_unknown_id_ignored(self):
        """Response with unknown ID is ignored."""
        cb = MagicMock()
        self.client.pending[1] = cb
        
        self.client._handle({"id": 99, "result": {}})
        
        cb.assert_not_called()
        self.assertIn(1, self.client.pending)

    def test_is_alive_with_running_proc(self):
        """is_alive returns True when process is running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.client.proc = mock_proc
        
        self.assertTrue(self.client.is_alive())

    def test_is_alive_with_dead_proc(self):
        """is_alive returns False when process has exited."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        self.client.proc = mock_proc
        
        self.assertFalse(self.client.is_alive())

    def test_is_alive_without_proc(self):
        """is_alive returns False without process."""
        self.assertFalse(self.client.is_alive())

    def test_stop_clears_state(self):
        """Stop clears running flag and pending."""
        self.client.running = True
        self.client.pending[1] = MagicMock()
        mock_proc = MagicMock()
        self.client.proc = mock_proc
        
        self.client.stop()
        
        self.assertFalse(self.client.running)
        self.assertEqual(len(self.client.pending), 0)
        mock_proc.terminate.assert_called_once()

    def test_send_wait_timeout(self):
        """send_wait returns error on timeout."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        
        self.client.proc = mock_proc
        self.client.running = True
        
        result = self.client.send_wait("test", {}, timeout=0.01)
        
        self.assertIn("error", result)
        self.assertIn("timed out", result["error"]["message"])

    def test_send_wait_dead_bridge(self):
        """send_wait returns error when bridge is dead."""
        result = self.client.send_wait("test", {})

        self.assertIn("error", result)
        self.assertIn("dead", result["error"]["message"])

    def test_fail_pending_invokes_callbacks_with_error(self):
        """_fail_pending fires every pending callback with an error and clears the map."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        self.client.pending[1] = cb1
        self.client.pending[2] = cb2

        self.client._fail_pending()

        self.assertEqual(len(self.client.pending), 0)
        cb1.assert_called_once()
        cb2.assert_called_once()
        for call in (cb1.call_args, cb2.call_args):
            payload = call[0][0]
            self.assertIn("error", payload)
            self.assertIn("died", payload["error"]["message"])

    def test_fail_pending_no_pending_is_noop(self):
        """_fail_pending with no pending callbacks does nothing."""
        # Should not raise
        self.client._fail_pending()
        self.assertEqual(len(self.client.pending), 0)

    def test_fail_pending_swallows_callback_exception(self):
        """A throwing callback should not stop other callbacks from firing."""
        bad = MagicMock(side_effect=RuntimeError("boom"))
        good = MagicMock()
        self.client.pending[1] = bad
        self.client.pending[2] = good

        self.client._fail_pending()

        bad.assert_called_once()
        good.assert_called_once()
        self.assertEqual(len(self.client.pending), 0)


if __name__ == "__main__":
    unittest.main()
