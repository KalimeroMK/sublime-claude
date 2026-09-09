"""Tests for lsp_tools. lsp_client is faked, so no Sublime and no server needed."""
import unittest

from tests.plugin_pkg import load

tools = load("lsp_tools")


class FakeClient:
    """Stands in for lsp_client. Records calls, returns canned replies."""

    def __init__(self, reply=None, error=None, capability_error=None):
        self.reply = reply
        self.error = error
        self.capability_error = capability_error
        self.calls = []

    def position_request(self, window, file_path, line, col, method, capability,
                         extra_params=None, timeout=5.0):
        self.calls.append({"method": method, "capability": capability,
                           "file": file_path, "line": line, "col": col,
                           "extra": extra_params})
        if self.capability_error:
            return None, self.capability_error, None, None
        return self.reply, self.error, object(), object()

    def resolve_view(self, window, file_path):
        self.calls.append({"resolve": file_path})
        return object(), None

    def session_for_view(self, view, capability=None):
        self.calls.append({"session_capability": capability})
        if self.capability_error:
            return None, self.capability_error
        return object(), None

    def document_params(self, view):
        return {"textDocument": {"uri": "file:///x.php"}}

    def request(self, session, method, params, view=None, timeout=5.0):
        self.calls.append({"method": method, "params": params})
        return self.reply, self.error

    def diagnostics_for_view(self, view):
        self.calls.append({"diagnostics_for_view": True})
        if self.capability_error:
            return None, self.capability_error
        return self.reply or [], None


def run(subcommand, client, **kwargs):
    return getattr(tools, subcommand)(object(), client=client, **kwargs)


class HoverTest(unittest.TestCase):
    def test_requests_hover_with_capability(self):
        c = FakeClient(reply={"contents": {"kind": "markdown", "value": "int"}})
        out = run("hover", c, file_path="/x.php", line=1, col=2)
        self.assertEqual(c.calls[0]["method"], "textDocument/hover")
        self.assertEqual(c.calls[0]["capability"], "hoverProvider")
        self.assertEqual(out["content"], "int")

    def test_marked_string_list_is_joined(self):
        c = FakeClient(reply={"contents": [{"value": "a"}, {"value": "b"}]})
        self.assertEqual(run("hover", c, file_path="/x.php", line=0, col=0)["content"], "a\n\nb")

    def test_missing_capability_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP server with hoverProvider capability")
        out = run("hover", c, file_path="/x.php", line=0, col=0)
        self.assertIn("hoverProvider", out["error"])

    def test_empty_result_is_not_an_error(self):
        c = FakeClient(reply=None)
        out = run("hover", c, file_path="/x.php", line=0, col=0)
        self.assertIsNone(out["result"])
        self.assertIn("No hover", out["message"])


class DefinitionTest(unittest.TestCase):
    def test_requests_definition(self):
        c = FakeClient(reply={"uri": "file:///a.php", "range": {"start": {"line": 3, "character": 1}}})
        out = run("definition", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(c.calls[0]["method"], "textDocument/definition")
        self.assertEqual(c.calls[0]["capability"], "definitionProvider")
        self.assertEqual(out["locations"], [{"file": "/a.php", "line": 3, "col": 1}])


class ReferencesTest(unittest.TestCase):
    def test_includes_declaration_in_context(self):
        c = FakeClient(reply=[])
        run("references", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(c.calls[0]["extra"], {"context": {"includeDeclaration": True}})
        self.assertEqual(c.calls[0]["capability"], "referencesProvider")

    def test_counts_locations(self):
        c = FakeClient(reply=[
            {"uri": "file:///a.php", "range": {"start": {"line": 1, "character": 0}}},
            {"uri": "file:///b.php", "range": {"start": {"line": 2, "character": 0}}},
        ])
        out = run("references", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["count"], 2)


class SymbolsTest(unittest.TestCase):
    def test_requests_document_symbols(self):
        c = FakeClient(reply=[{"name": "A", "kind": 5,
                               "selectionRange": {"start": {"line": 0, "character": 0}}}])
        out = run("symbols", c, file_path="/x.php")
        self.assertEqual(c.calls[-1]["method"], "textDocument/documentSymbol")
        self.assertEqual(out["symbols"][0]["name"], "A")
        self.assertEqual(out["count"], 1)


class WorkspaceSymbolsTest(unittest.TestCase):
    def test_requests_workspace_symbol(self):
        c = FakeClient(reply=[{"name": "ApiKey", "kind": 5, "containerName": "App",
                               "location": {"uri": "file:///A.php",
                                            "range": {"start": {"line": 9, "character": 6}}}}])

        class Win:
            def active_view(self):
                return object()

        out = tools.workspace_symbols(Win(), "ApiKey", client=c)
        self.assertEqual(c.calls[-1]["method"], "workspace/symbol")
        self.assertEqual(c.calls[-1]["params"], {"query": "ApiKey"})
        self.assertEqual(out["symbols"], [{"name": "ApiKey", "kind": "Class",
                                           "file": "/A.php", "line": 9, "col": 6,
                                           "container": "App"}])


class DiagnosticsTest(unittest.TestCase):
    """Diagnostics come from LSP's local store, not a request. intelephense
    pushes diagnostics, so there is no textDocument/diagnostic to call."""

    def test_reads_diagnostics_from_the_store(self):
        c = FakeClient(reply=[
            {"severity": 1, "message": "Undefined method", "source": "intelephense",
             "range": {"start": {"line": 12, "character": 8}}}])
        out = run("diagnostics", c, file_path="/x.php")
        self.assertTrue(any("diagnostics_for_view" in call for call in c.calls))
        self.assertEqual(out["diagnostics"], [{
            "severity": "error", "message": "Undefined method",
            "line": 12, "col": 8, "source": "intelephense"}])
        self.assertEqual(out["count"], 1)

    def test_issues_no_lsp_request(self):
        """Guards against regressing to a pull request the server may not support."""
        c = FakeClient(reply=[])
        run("diagnostics", c, file_path="/x.php")
        self.assertEqual([call for call in c.calls if "method" in call], [])

    def test_maps_all_severities(self):
        c = FakeClient(reply=[
            {"severity": 1, "message": "e", "range": {"start": {}}},
            {"severity": 2, "message": "w", "range": {"start": {}}},
            {"severity": 3, "message": "i", "range": {"start": {}}},
            {"severity": 4, "message": "h", "range": {"start": {}}},
        ])
        out = run("diagnostics", c, file_path="/x.php")
        self.assertEqual([d["severity"] for d in out["diagnostics"]],
                         ["error", "warning", "info", "hint"])

    def test_no_lsp_listener_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP listener for this view")
        out = run("symbols", c, file_path="/x.php")
        self.assertIn("No LSP listener", out["error"])


class CompletionTest(unittest.TestCase):
    def test_requests_completion_with_capability(self):
        c = FakeClient(reply={"items": [{"label": "where"}, {"label": "whereHas"}]})
        out = run("completion", c, file_path="/x.php", line=8, col=13)
        self.assertEqual(c.calls[0]["method"], "textDocument/completion")
        self.assertEqual(c.calls[0]["capability"], "completionProvider")
        self.assertEqual(out["items"], ["where", "whereHas"])
        self.assertEqual(out["count"], 2)

    def test_accepts_bare_list_response(self):
        c = FakeClient(reply=[{"label": "get"}])
        self.assertEqual(run("completion", c, file_path="/x.php", line=1, col=1)["items"], ["get"])

    def test_includes_detail_and_kind_when_present(self):
        c = FakeClient(reply={"items": [
            {"label": "where", "kind": 2, "detail": "Builder where(...)"}]})
        out = run("completion", c, file_path="/x.php", line=1, col=1, detailed=True)
        self.assertEqual(
            out["items"],
            [{"label": "where", "kind": "Method", "detail": "Builder where(...)"}],
        )

    def test_truncates_to_limit_and_says_so(self):
        c = FakeClient(reply={"items": [{"label": "m%d" % i} for i in range(300)]})
        out = run("completion", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(len(out["items"]), 200)
        self.assertEqual(out["count"], 300)
        self.assertTrue(out["truncated"])

    def test_prefix_filter(self):
        c = FakeClient(reply={"items": [{"label": "where"}, {"label": "get"}]})
        out = run("completion", c, file_path="/x.php", line=1, col=1, prefix="wh")
        self.assertEqual(out["items"], ["where"])

    def test_missing_capability_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP server with completionProvider capability")
        self.assertIn("completionProvider",
                      run("completion", c, file_path="/x.php", line=1, col=1)["error"])

    def test_empty_result(self):
        c = FakeClient(reply=None)
        out = run("completion", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["items"], [])
        self.assertEqual(out["count"], 0)


if __name__ == "__main__":
    unittest.main()
