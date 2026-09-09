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


class SignatureHelpTest(unittest.TestCase):
    def test_requests_signature_help(self):
        c = FakeClient(reply={"signatures": [
            {"label": "where(string $column, mixed $value)"}], "activeSignature": 0})
        out = run("signature_help", c, file_path="/x.php", line=8, col=20)
        self.assertEqual(c.calls[0]["method"], "textDocument/signatureHelp")
        self.assertEqual(c.calls[0]["capability"], "signatureHelpProvider")
        self.assertEqual(out["signatures"][0]["label"], "where(string $column, mixed $value)")

    def test_reports_active_signature_and_parameter(self):
        c = FakeClient(reply={
            "signatures": [{"label": "f(a, b)", "parameters": [{"label": "a"}, {"label": "b"}]}],
            "activeSignature": 0, "activeParameter": 1})
        out = run("signature_help", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["active_signature"], 0)
        self.assertEqual(out["active_parameter"], 1)
        self.assertEqual(out["signatures"][0]["parameters"], ["a", "b"])

    def test_includes_documentation_when_present(self):
        c = FakeClient(reply={"signatures": [
            {"label": "f()", "documentation": {"kind": "markdown", "value": "does f"}}]})
        out = run("signature_help", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["signatures"][0]["documentation"], "does f")

    def test_missing_capability_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP server with signatureHelpProvider capability")
        self.assertIn("signatureHelpProvider",
                      run("signature_help", c, file_path="/x.php", line=1, col=1)["error"])

    def test_empty_result(self):
        c = FakeClient(reply=None)
        out = run("signature_help", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["signatures"], [])


class TypeDefinitionTest(unittest.TestCase):
    def test_requests_type_definition(self):
        c = FakeClient(reply={"uri": "file:///T.php", "range": {"start": {"line": 2, "character": 6}}})
        out = run("type_definition", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(c.calls[0]["method"], "textDocument/typeDefinition")
        self.assertEqual(c.calls[0]["capability"], "typeDefinitionProvider")
        self.assertEqual(out["locations"], [{"file": "/T.php", "line": 2, "col": 6}])

    def test_premium_capability_absent_reports_cleanly(self):
        """typeDefinition is an intelephense premium feature — without a licence
        the server does not advertise it, and that must read as a clear message."""
        c = FakeClient(capability_error="No LSP server with typeDefinitionProvider capability")
        out = run("type_definition", c, file_path="/x.php", line=1, col=1)
        self.assertIn("typeDefinitionProvider", out["error"])

    def test_empty_result(self):
        c = FakeClient(reply=None)
        out = run("type_definition", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["locations"], [])
        self.assertIn("No type definition", out["message"])


class ImplementationTest(unittest.TestCase):
    def test_requests_implementation(self):
        c = FakeClient(reply=[
            {"uri": "file:///A.php", "range": {"start": {"line": 1, "character": 0}}},
            {"uri": "file:///B.php", "range": {"start": {"line": 2, "character": 0}}},
        ])
        out = run("implementation", c, file_path="/I.php", line=5, col=10)
        self.assertEqual(c.calls[0]["method"], "textDocument/implementation")
        self.assertEqual(c.calls[0]["capability"], "implementationProvider")
        self.assertEqual(out["count"], 2)

    def test_premium_capability_absent_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP server with implementationProvider capability")
        self.assertIn("implementationProvider",
                      run("implementation", c, file_path="/x.php", line=1, col=1)["error"])

    def test_empty_result(self):
        c = FakeClient(reply=[])
        out = run("implementation", c, file_path="/x.php", line=1, col=1)
        self.assertEqual(out["locations"], [])
        self.assertIn("No implementation", out["message"])


class CallHierarchyTest(unittest.TestCase):
    def _client_with(self, prepare, calls):
        """prepare -> prepareCallHierarchy reply; calls -> incoming/outgoing reply."""
        class C(FakeClient):
            def __init__(self):
                super().__init__()
                self.methods = []

            def position_request(self, window, file_path, line, col, method, capability,
                                 extra_params=None, timeout=5.0):
                self.methods.append(method)
                self.calls.append({"method": method, "capability": capability})
                return prepare, None, object(), self

            def request(self, session, method, params, view=None, timeout=5.0):
                self.methods.append(method)
                self.calls.append({"method": method, "params": params})
                return calls, None

        return C()

    def test_incoming_calls(self):
        prepare = [{"name": "rotate", "kind": 6, "uri": "file:///A.php",
                    "selectionRange": {"start": {"line": 10, "character": 4}}}]
        calls = [{"from": {"name": "controller", "kind": 6, "uri": "file:///C.php",
                           "selectionRange": {"start": {"line": 3, "character": 2}}}}]
        c = self._client_with(prepare, calls)
        out = run("call_hierarchy", c, file_path="/A.php", line=10, col=4)
        self.assertEqual(c.methods[0], "textDocument/prepareCallHierarchy")
        self.assertEqual(c.methods[1], "callHierarchy/incomingCalls")
        self.assertEqual(out["direction"], "incoming")
        self.assertEqual(out["calls"], [{"name": "controller", "kind": "Method",
                                         "file": "/C.php", "line": 3, "col": 2}])

    def test_outgoing_calls(self):
        prepare = [{"name": "rotate", "kind": 6, "uri": "file:///A.php",
                    "selectionRange": {"start": {"line": 10, "character": 4}}}]
        calls = [{"to": {"name": "save", "kind": 6, "uri": "file:///R.php",
                         "selectionRange": {"start": {"line": 8, "character": 4}}}}]
        c = self._client_with(prepare, calls)
        out = run("call_hierarchy", c, file_path="/A.php", line=10, col=4,
                  direction="outgoing")
        self.assertEqual(c.methods[1], "callHierarchy/outgoingCalls")
        self.assertEqual(out["calls"][0]["name"], "save")

    def test_uses_call_hierarchy_capability(self):
        c = self._client_with([], [])
        run("call_hierarchy", c, file_path="/A.php", line=1, col=1)
        self.assertEqual(c.calls[0]["capability"], "callHierarchyProvider")

    def test_no_item_at_position_short_circuits(self):
        """prepare returned nothing, so no second request must be issued."""
        c = self._client_with([], [])
        out = run("call_hierarchy", c, file_path="/A.php", line=1, col=1)
        self.assertEqual(out["calls"], [])
        self.assertIn("No call hierarchy", out["message"])
        self.assertEqual(len(c.methods), 1)

    def test_rejects_unknown_direction(self):
        c = self._client_with([], [])
        out = run("call_hierarchy", c, file_path="/A.php", line=1, col=1, direction="sideways")
        self.assertIn("direction", out["error"])
        self.assertEqual(c.methods, [])


class InlayHintTest(unittest.TestCase):
    def test_requests_inlay_hints_for_a_line_range(self):
        c = FakeClient(reply=[
            {"label": ": string", "position": {"line": 5, "character": 12}},
            {"label": "$column:", "position": {"line": 6, "character": 20}},
        ])
        out = run("inlay_hint", c, file_path="/x.php", start_line=5, end_line=6)
        self.assertEqual(c.calls[-1]["method"], "textDocument/inlayHint")
        self.assertEqual(
            c.calls[-1]["params"]["range"],
            {"start": {"line": 5, "character": 0}, "end": {"line": 7, "character": 0}},
        )
        self.assertEqual(out["hints"][0], {"label": ": string", "line": 5, "col": 12})
        self.assertEqual(out["count"], 2)

    def test_uses_inlay_hint_capability(self):
        c = FakeClient(reply=[])
        run("inlay_hint", c, file_path="/x.php", start_line=0, end_line=0)
        # calls[0] is resolve_view; the capability check is the second call
        self.assertEqual(c.calls[1]["session_capability"], "inlayHintProvider")

    def test_label_parts_are_joined(self):
        c = FakeClient(reply=[
            {"label": [{"value": "$a"}, {"value": ": int"}], "position": {"line": 1, "character": 2}}])
        out = run("inlay_hint", c, file_path="/x.php", start_line=1, end_line=1)
        self.assertEqual(out["hints"][0]["label"], "$a: int")

    def test_missing_capability_reports_cleanly(self):
        c = FakeClient(capability_error="No LSP server with inlayHintProvider capability")
        self.assertIn("inlayHintProvider",
                      run("inlay_hint", c, file_path="/x.php", start_line=0, end_line=0)["error"])

    def test_rejects_inverted_range(self):
        c = FakeClient(reply=[])
        out = run("inlay_hint", c, file_path="/x.php", start_line=9, end_line=2)
        self.assertIn("end_line", out["error"])
        self.assertEqual(c.calls, [])

    def test_empty_result(self):
        c = FakeClient(reply=None)
        out = run("inlay_hint", c, file_path="/x.php", start_line=0, end_line=1)
        self.assertEqual(out["hints"], [])


class RenameTest(unittest.TestCase):
    EDIT = {"changes": {
        "file:///src/ApiKey.php": [{"range": {}}, {"range": {}}],
        "file:///src/ApiKeyRepo.php": [{"range": {}}],
    }}

    def _client(self, reply=None, error=None, capability_error=None):
        class C(FakeClient):
            def __init__(self):
                super().__init__(reply=reply, error=error,
                                 capability_error=capability_error)
                self.applied = []

            def apply_workspace_edit(self, session, edit, label=None, timeout=15.0):
                self.applied.append({"edit": edit, "label": label})
                return True, None

        return C()

    def test_preview_reports_files_and_edit_counts(self):
        c = self._client(reply=self.EDIT)
        out = run("rename", c, file_path="/src/ApiKey.php", line=10, col=4, new_name="ApiToken")
        self.assertEqual(c.calls[0]["method"], "textDocument/rename")
        self.assertEqual(c.calls[0]["capability"], "renameProvider")
        self.assertEqual(out["file_count"], 2)
        self.assertEqual(out["edit_count"], 3)
        self.assertFalse(out["applied"])

    def test_preview_writes_nothing(self):
        """This assertion is the safety decision — preview must never apply."""
        c = self._client(reply=self.EDIT)
        run("rename", c, file_path="/src/ApiKey.php", line=10, col=4, new_name="ApiToken")
        self.assertEqual(c.applied, [])

    def test_preview_says_how_to_apply(self):
        c = self._client(reply=self.EDIT)
        out = run("rename", c, file_path="/src/ApiKey.php", line=10, col=4, new_name="ApiToken")
        self.assertIn("--apply", out["message"])

    def test_apply_sends_new_name_and_applies(self):
        c = self._client(reply=self.EDIT)
        out = run("rename", c, file_path="/src/ApiKey.php", line=10, col=4,
                  new_name="ApiToken", apply=True)
        self.assertEqual(c.calls[0]["extra"], {"newName": "ApiToken"})
        self.assertEqual(len(c.applied), 1)
        self.assertEqual(c.applied[0]["label"], "rename to ApiToken")
        self.assertTrue(out["applied"])

    def test_rejects_empty_new_name(self):
        c = self._client(reply=self.EDIT)
        out = run("rename", c, file_path="/src/ApiKey.php", line=10, col=4, new_name="")
        self.assertIn("new_name", out["error"])
        self.assertEqual(c.calls, [])

    def test_missing_capability_reports_cleanly(self):
        c = self._client(capability_error="No LSP server with renameProvider capability")
        out = run("rename", c, file_path="/x.php", line=1, col=1, new_name="N")
        self.assertIn("renameProvider", out["error"])

    def test_server_returns_no_edit(self):
        c = self._client(reply=None)
        out = run("rename", c, file_path="/x.php", line=1, col=1, new_name="N")
        self.assertEqual(out["file_count"], 0)
        self.assertIn("cannot be renamed", out["message"])
        self.assertEqual(c.applied, [])


class CodeActionTest(unittest.TestCase):
    ACTIONS = [
        {"title": "Import 'App\\Models\\User'",
         "kind": "quickfix",
         "edit": {"changes": {"file:///src/a.php": [{"range": {}}]}}},
        {"title": "Add missing method", "kind": "quickfix"},
    ]

    def _client(self, reply=None, capability_error=None):
        class C(FakeClient):
            def __init__(self):
                super().__init__(reply=reply, capability_error=capability_error)
                self.applied = []

            def apply_workspace_edit(self, session, edit, label=None, timeout=15.0):
                self.applied.append({"edit": edit, "label": label})
                return True, None

        return C()

    def test_lists_available_actions(self):
        c = self._client(reply=self.ACTIONS)
        out = run("code_action", c, file_path="/src/a.php", line=5, col=0)
        self.assertEqual(c.calls[-1]["method"], "textDocument/codeAction")
        self.assertEqual(
            out["actions"],
            [{"index": 0, "title": "Import 'App\\Models\\User'", "kind": "quickfix",
              "has_edit": True},
             {"index": 1, "title": "Add missing method", "kind": "quickfix",
              "has_edit": False}],
        )

    def test_uses_code_action_capability(self):
        c = self._client(reply=[])
        run("code_action", c, file_path="/src/a.php", line=1, col=0)
        # calls[0] is resolve_view; the capability check is the second call
        self.assertEqual(c.calls[1]["session_capability"], "codeActionProvider")

    def test_sends_range_and_empty_diagnostic_context(self):
        c = self._client(reply=[])
        run("code_action", c, file_path="/src/a.php", line=5, col=0)
        params = c.calls[-1]["params"]
        self.assertEqual(params["range"], {"start": {"line": 5, "character": 0},
                                           "end": {"line": 5, "character": 0}})
        self.assertEqual(params["context"], {"diagnostics": []})

    def test_listing_writes_nothing(self):
        """The safety decision: listing actions must never apply one."""
        c = self._client(reply=self.ACTIONS)
        run("code_action", c, file_path="/src/a.php", line=5, col=0)
        self.assertEqual(c.applied, [])

    def test_apply_by_index(self):
        c = self._client(reply=self.ACTIONS)
        out = run("code_action", c, file_path="/src/a.php", line=5, col=0, apply_index=0)
        self.assertEqual(len(c.applied), 1)
        self.assertEqual(c.applied[0]["label"], "Import 'App\\Models\\User'")
        self.assertTrue(out["applied"])

    def test_apply_index_out_of_range(self):
        c = self._client(reply=self.ACTIONS)
        out = run("code_action", c, file_path="/src/a.php", line=5, col=0, apply_index=9)
        self.assertIn("out of range", out["error"])
        self.assertEqual(c.applied, [])

    def test_apply_action_without_an_edit(self):
        c = self._client(reply=self.ACTIONS)
        out = run("code_action", c, file_path="/src/a.php", line=5, col=0, apply_index=1)
        self.assertIn("no edit", out["error"])
        self.assertEqual(c.applied, [])

    def test_no_actions_available(self):
        c = self._client(reply=[])
        out = run("code_action", c, file_path="/src/a.php", line=5, col=0)
        self.assertEqual(out["actions"], [])
        self.assertIn("No code actions", out["message"])


if __name__ == "__main__":
    unittest.main()
