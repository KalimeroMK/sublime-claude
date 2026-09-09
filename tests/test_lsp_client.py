"""Tests for lsp_client. The LSP package itself is faked — these tests assert the
contract lsp_tools depends on, including the async-thread guard."""
import os
import threading
import unittest

from tests.plugin_pkg import load, sublime

client = load("lsp_client")


class FakeSession:
    def __init__(self, name="fake-server", caps=None, reply=None, error=None):
        self.config = type("C", (), {"name": name})()
        self._caps = caps or {}
        self._reply = reply
        self._error = error
        self.sent = []

    def has_capability(self, cap):
        return bool(self._caps.get(cap))

    def send_request(self, request, on_result, on_error):
        self.sent.append(request)
        if self._error is not None:
            on_error(self._error)
        else:
            on_result(self._reply)


class FakeRequest:
    def __init__(self, method, params, view=None):
        self.method = method
        self.params = params
        self.view = view


class RequestTest(unittest.TestCase):
    def setUp(self):
        client._REQUEST_FACTORY = FakeRequest

    def tearDown(self):
        client._REQUEST_FACTORY = None

    def test_returns_result(self):
        s = FakeSession(reply={"ok": 1})
        result, err = client.request(s, "textDocument/hover", {"p": 1})
        self.assertEqual(result, {"ok": 1})
        self.assertIsNone(err)

    def test_sends_expected_method_and_params(self):
        s = FakeSession(reply={})
        client.request(s, "textDocument/completion", {"position": {"line": 3}})
        self.assertEqual(s.sent[0].method, "textDocument/completion")
        self.assertEqual(s.sent[0].params, {"position": {"line": 3}})

    def test_propagates_error(self):
        s = FakeSession(error="boom")
        result, err = client.request(s, "textDocument/hover", {})
        self.assertIsNone(result)
        self.assertEqual(err, "boom")

    def test_timeout_when_no_callback_fires(self):
        class Silent(FakeSession):
            def send_request(self, request, on_result, on_error):
                pass

        result, err = client.request(Silent(), "textDocument/hover", {}, timeout=0.05)
        self.assertIsNone(result)
        self.assertIn("timeout", err.lower())

    def test_refuses_to_run_on_the_async_thread(self):
        """Blocking Sublime's async worker is what makes every request time out."""
        client._async_thread_id = threading.get_ident()
        try:
            with self.assertRaises(RuntimeError) as cm:
                client.request(FakeSession(reply={}), "textDocument/hover", {})
            self.assertIn("async", str(cm.exception).lower())
        finally:
            client._async_thread_id = None


class CapabilityTest(unittest.TestCase):
    def test_reports_missing_capability(self):
        s = FakeSession(caps={"hoverProvider": True})
        self.assertTrue(client.has_capability(s, "hoverProvider"))
        self.assertFalse(client.has_capability(s, "renameProvider"))


class PackageDetectionTest(unittest.TestCase):
    """A package counts as installed either as a loose directory under
    Packages/ or as a .sublime-package archive under Installed Packages/."""

    def _probed(self, name="LSP"):
        seen = []
        client.is_package_installed(name, lambda p: seen.append(p) or False)
        return seen

    def test_checks_both_locations(self):
        seen = self._probed()
        self.assertEqual(len(seen), 2)
        self.assertTrue(any(p.endswith(os.path.join("sublime-packages", "LSP")) for p in seen),
                        "loose package dir not probed: %s" % seen)
        self.assertTrue(any(p.endswith("LSP.sublime-package") for p in seen),
                        "sublime-package archive not probed: %s" % seen)

    def test_true_when_loose_package_dir_exists(self):
        loose = os.path.join(sublime.packages_path(), "LSP")
        self.assertTrue(client.is_package_installed("LSP", lambda p: p == loose))

    def test_true_when_sublime_package_exists(self):
        archive = os.path.join(sublime.installed_packages_path(), "LSP.sublime-package")
        self.assertTrue(client.is_package_installed("LSP", lambda p: p == archive))

    def test_false_when_neither_exists(self):
        self.assertFalse(client.is_package_installed("LSP", lambda p: False))


class ApplyWorkspaceEditTest(unittest.TestCase):
    def test_schedules_apply_on_the_async_thread(self):
        """apply_workspace_edit_async must run on the async thread, which is the
        one request() refuses to block — so the apply is scheduled, not called."""
        scheduled = []

        class FakeSublime:
            @staticmethod
            def set_timeout_async(fn, delay=0):
                scheduled.append(fn)
                fn()  # run it as the async worker would

        applied = []

        class Session:
            def apply_workspace_edit_async(self, edit, label=None, is_refactoring=False):
                applied.append({"edit": edit, "label": label, "is_refactoring": is_refactoring})

        original = client.sublime
        client.sublime = FakeSublime
        try:
            ok, err = client.apply_workspace_edit(
                Session(), {"changes": {}}, label="rename x", timeout=1.0)
        finally:
            client.sublime = original

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(applied[0]["label"], "rename x")
        self.assertTrue(applied[0]["is_refactoring"])

    def test_reports_apply_failure(self):
        class FakeSublime:
            @staticmethod
            def set_timeout_async(fn, delay=0):
                fn()

        class Session:
            def apply_workspace_edit_async(self, edit, label=None, is_refactoring=False):
                raise RuntimeError("server refused")

        original = client.sublime
        client.sublime = FakeSublime
        try:
            ok, err = client.apply_workspace_edit(Session(), {"changes": {}}, timeout=1.0)
        finally:
            client.sublime = original

        self.assertFalse(ok)
        self.assertIn("server refused", err)


class ExecuteCommandTest(unittest.TestCase):
    """Intelephense's code actions carry a Command, not an edit — applying one
    means workspace/executeCommand, after which the server pushes
    workspace/applyEdit back and LSP applies it."""

    def setUp(self):
        client._REQUEST_FACTORY = FakeRequest

    def tearDown(self):
        client._REQUEST_FACTORY = None

    def test_sends_command_and_arguments(self):
        s = FakeSession(reply=None)
        ok, err = client.execute_command(
            s, "intelephense.import.symbol", ["file:///a.php", "X", 1])
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(s.sent[0].method, "workspace/executeCommand")
        self.assertEqual(s.sent[0].params, {
            "command": "intelephense.import.symbol",
            "arguments": ["file:///a.php", "X", 1]})

    def test_missing_arguments_sends_empty_list(self):
        s = FakeSession(reply=None)
        client.execute_command(s, "some.command", None)
        self.assertEqual(s.sent[0].params["arguments"], [])

    def test_propagates_error(self):
        s = FakeSession(error="Unhandled method")
        ok, err = client.execute_command(s, "nope", [])
        self.assertFalse(ok)
        self.assertEqual(err, "Unhandled method")


if __name__ == "__main__":
    unittest.main()
