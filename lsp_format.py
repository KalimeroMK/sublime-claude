"""Pure formatters for LSP results. No Sublime, no LSP imports — keep it that way."""
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

_SYMBOL_KINDS = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
    6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
    11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
    15: "String", 16: "Number", 17: "Boolean", 18: "Array", 19: "Object",
    20: "Key", 21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}


def uri_to_path(uri: str) -> str:
    """file:///a/b%20c.php -> /a/b c.php. Non-URIs pass through."""
    if not uri:
        return ""
    if not uri.startswith("file:"):
        return uri
    return unquote(urlparse(uri).path)


def symbol_kind_name(kind: int) -> str:
    return _SYMBOL_KINDS.get(kind, "Unknown")


def _start(range_like: Dict[str, Any]) -> Dict[str, int]:
    start = (range_like or {}).get("start", {})
    return {"line": start.get("line", 0), "col": start.get("character", 0)}


def parse_locations(result: Any) -> List[Dict[str, Any]]:
    """Normalise Location | Location[] | LocationLink[] to {file, line, col}."""
    if not result:
        return []
    items = result if isinstance(result, list) else [result]
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "targetUri" in item:
            uri = item["targetUri"]
            rng = item.get("targetSelectionRange") or item.get("targetRange") or {}
        else:
            uri = item.get("uri", "")
            rng = item.get("range") or {}
        pos = _start(rng)
        out.append({"file": uri_to_path(uri), "line": pos["line"], "col": pos["col"]})
    return out


def flatten_document_symbols(result: Any, container: str = "") -> List[Dict[str, Any]]:
    """Flatten DocumentSymbol[] (nested) or SymbolInformation[] (flat)."""
    out = []
    for sym in result or []:
        if not isinstance(sym, dict):
            continue
        rng = sym.get("selectionRange") or sym.get("range")
        if rng is None:
            rng = (sym.get("location") or {}).get("range") or {}
        pos = _start(rng)
        out.append({
            "name": sym.get("name", ""),
            "kind": symbol_kind_name(sym.get("kind", 0)),
            "line": pos["line"],
            "col": pos["col"],
            "container": container or sym.get("containerName", "") or "",
        })
        children = sym.get("children")
        if children:
            out.extend(flatten_document_symbols(children, sym.get("name", "")))
    return out


def summarize_workspace_edit(edit: Any) -> Dict[str, Any]:
    """Describe a WorkspaceEdit without applying it: which files, how many edits."""
    files = []
    edit = edit or {}
    changes = edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            files.append({"file": uri_to_path(uri), "edits": len(edits or [])})
    for doc in edit.get("documentChanges") or []:
        if not isinstance(doc, dict) or "textDocument" not in doc:
            continue  # create/rename/delete ops carry no edit list
        uri = (doc.get("textDocument") or {}).get("uri", "")
        files.append({"file": uri_to_path(uri), "edits": len(doc.get("edits") or [])})
    return {
        "file_count": len(files),
        "edit_count": sum(f["edits"] for f in files),
        "files": files,
    }
