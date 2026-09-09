"""Tests for lsp_format — pure result formatters, no Sublime, no LSP."""
import unittest

from tests.plugin_pkg import load

fmt = load("lsp_format")


class UriToPathTest(unittest.TestCase):
    def test_strips_file_scheme(self):
        self.assertEqual(fmt.uri_to_path("file:///src/a.php"), "/src/a.php")

    def test_decodes_percent_escapes(self):
        self.assertEqual(fmt.uri_to_path("file:///src/my%20file.php"), "/src/my file.php")

    def test_passes_through_non_uri(self):
        self.assertEqual(fmt.uri_to_path("/src/a.php"), "/src/a.php")


class SymbolKindNameTest(unittest.TestCase):
    def test_known_kinds(self):
        self.assertEqual(fmt.symbol_kind_name(5), "Class")
        self.assertEqual(fmt.symbol_kind_name(6), "Method")
        self.assertEqual(fmt.symbol_kind_name(12), "Function")

    def test_unknown_kind_falls_back(self):
        self.assertEqual(fmt.symbol_kind_name(0), "Unknown")
        self.assertEqual(fmt.symbol_kind_name(999), "Unknown")


class ParseLocationsTest(unittest.TestCase):
    def test_single_location_dict(self):
        loc = {"uri": "file:///src/a.php", "range": {"start": {"line": 4, "character": 8}}}
        self.assertEqual(
            fmt.parse_locations(loc),
            [{"file": "/src/a.php", "line": 4, "col": 8}],
        )

    def test_location_list(self):
        locs = [
            {"uri": "file:///src/a.php", "range": {"start": {"line": 1, "character": 2}}},
            {"uri": "file:///src/b.php", "range": {"start": {"line": 3, "character": 4}}},
        ]
        self.assertEqual(len(fmt.parse_locations(locs)), 2)

    def test_location_link_uses_target_uri(self):
        link = {"targetUri": "file:///src/c.php",
                "targetSelectionRange": {"start": {"line": 7, "character": 1}}}
        self.assertEqual(
            fmt.parse_locations(link),
            [{"file": "/src/c.php", "line": 7, "col": 1}],
        )

    def test_empty_input(self):
        self.assertEqual(fmt.parse_locations(None), [])
        self.assertEqual(fmt.parse_locations([]), [])


class FlattenDocumentSymbolsTest(unittest.TestCase):
    def test_nested_symbols_are_flattened_with_container(self):
        tree = [{
            "name": "ApiKey", "kind": 5,
            "selectionRange": {"start": {"line": 10, "character": 6}},
            "children": [{
                "name": "rotate", "kind": 6,
                "selectionRange": {"start": {"line": 20, "character": 4}},
            }],
        }]
        out = fmt.flatten_document_symbols(tree)
        self.assertEqual(
            out,
            [
                {"name": "ApiKey", "kind": "Class", "line": 10, "col": 6, "container": ""},
                {"name": "rotate", "kind": "Method", "line": 20, "col": 4, "container": "ApiKey"},
            ],
        )

    def test_symbol_information_shape(self):
        flat = [{"name": "helper", "kind": 12,
                 "location": {"range": {"start": {"line": 3, "character": 0}}}}]
        out = fmt.flatten_document_symbols(flat)
        self.assertEqual(out[0]["name"], "helper")
        self.assertEqual(out[0]["line"], 3)


class SummarizeWorkspaceEditTest(unittest.TestCase):
    def test_counts_edits_per_file(self):
        edit = {"changes": {
            "file:///src/a.php": [{"range": {}}, {"range": {}}],
            "file:///src/b.php": [{"range": {}}],
        }}
        s = fmt.summarize_workspace_edit(edit)
        self.assertEqual(s["file_count"], 2)
        self.assertEqual(s["edit_count"], 3)
        self.assertEqual(
            sorted(s["files"], key=lambda f: f["file"]),
            [{"file": "/src/a.php", "edits": 2}, {"file": "/src/b.php", "edits": 1}],
        )

    def test_document_changes_form(self):
        edit = {"documentChanges": [
            {"textDocument": {"uri": "file:///src/a.php"}, "edits": [{"range": {}}]},
        ]}
        s = fmt.summarize_workspace_edit(edit)
        self.assertEqual((s["file_count"], s["edit_count"]), (1, 1))

    def test_empty_edit(self):
        s = fmt.summarize_workspace_edit({})
        self.assertEqual((s["file_count"], s["edit_count"], s["files"]), (0, 0, []))


if __name__ == "__main__":
    unittest.main()
