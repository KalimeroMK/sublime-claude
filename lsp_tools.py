"""The lsp subcommands. Each is a shallow call into lsp_client.

`client` is injectable purely so tests can pass a fake; production callers
leave it at None and get the real module.
"""
from typing import Any, Dict, Optional

from . import lsp_format

_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def _client(client):
    if client is not None:
        return client
    from . import lsp_client
    return lsp_client


def _hover_text(contents):
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, list):
        return "\n\n".join(
            item.get("value", "") if isinstance(item, dict) else str(item)
            for item in contents
        )
    return str(contents or "")


def hover(window, file_path, line, col, client=None):
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/hover", "hoverProvider")
    if err:
        return {"error": err}
    if not result:
        return {"result": None, "message": "No hover info at this position"}
    return {"content": _hover_text(result.get("contents", ""))}


def definition(window, file_path, line, col, client=None):
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/definition", "definitionProvider")
    if err:
        return {"error": err}
    if not result:
        return {"locations": [], "message": "No definition found"}
    return {"locations": lsp_format.parse_locations(result)}


def references(window, file_path, line, col, client=None):
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/references", "referencesProvider",
        extra_params={"context": {"includeDeclaration": True}})
    if err:
        return {"error": err}
    if not result:
        return {"locations": [], "message": "No references found"}
    locations = lsp_format.parse_locations(result)
    return {"locations": locations, "count": len(locations)}


def symbols(window, file_path, client=None):
    c = _client(client)
    view, err = c.resolve_view(window, file_path)
    if err:
        return {"error": err}
    session, err = c.session_for_view(view, "documentSymbolProvider")
    if err:
        return {"error": err}
    result, err = c.request(session, "textDocument/documentSymbol",
                            c.document_params(view), view)
    if err:
        return {"error": err}
    flat = lsp_format.flatten_document_symbols(result)
    return {"symbols": flat, "count": len(flat)}


def workspace_symbols(window, query, client=None):
    c = _client(client)
    view = window.active_view() if window else None
    if not view:
        return {"error": "No active view"}
    session, err = c.session_for_view(view, "workspaceSymbolProvider")
    if err:
        return {"error": err}
    result, err = c.request(session, "workspace/symbol", {"query": query})
    if err:
        return {"error": err}
    out = []
    for sym in result or []:
        location = sym.get("location", {})
        pos = (location.get("range") or {}).get("start", {})
        out.append({
            "name": sym.get("name", ""),
            "kind": lsp_format.symbol_kind_name(sym.get("kind", 0)),
            "file": lsp_format.uri_to_path(location.get("uri", "")),
            "line": pos.get("line", 0),
            "col": pos.get("character", 0),
            "container": sym.get("containerName", ""),
        })
    return {"symbols": out, "count": len(out)}


def diagnostics(window, file_path=None, client=None):
    c = _client(client)
    if file_path:
        view, err = c.resolve_view(window, file_path)
        if err:
            return {"error": err}
    else:
        view = window.active_view() if window else None
        if not view:
            return {"error": "No active view"}
    # Read LSP's store rather than issuing textDocument/diagnostic: intelephense
    # pushes diagnostics, so a pull request would need a capability it lacks.
    items, err = c.diagnostics_for_view(view)
    if err:
        return {"error": err}
    out = [{
        "severity": _SEVERITY.get(d.get("severity", 4), "unknown"),
        "message": d.get("message", ""),
        "line": ((d.get("range") or {}).get("start") or {}).get("line", 0),
        "col": ((d.get("range") or {}).get("start") or {}).get("character", 0),
        "source": d.get("source", ""),
    } for d in items or []]
    return {"diagnostics": out, "count": len(out)}


_COMPLETION_LIMIT = 200

_COMPLETION_KINDS = {
    1: "Text", 2: "Method", 3: "Function", 4: "Constructor", 5: "Field",
    6: "Variable", 7: "Class", 8: "Interface", 9: "Module", 10: "Property",
    11: "Unit", 12: "Value", 13: "Enum", 14: "Keyword", 15: "Snippet",
    16: "Color", 17: "File", 18: "Reference", 19: "Folder", 20: "EnumMember",
    21: "Constant", 22: "Struct", 23: "Event", 24: "Operator", 25: "TypeParameter",
}


def completion(window, file_path, line, col, prefix="", detailed=False, client=None):
    """What the server says is callable at this position."""
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/completion", "completionProvider",
        extra_params={"context": {"triggerKind": 1}}, timeout=15.0)
    if err:
        return {"error": err}

    if isinstance(result, dict):
        raw = result.get("items", [])
    else:
        raw = result or []

    if prefix:
        raw = [i for i in raw if str(i.get("label", "")).startswith(prefix)]

    total = len(raw)
    shown = raw[:_COMPLETION_LIMIT]
    if detailed:
        items = [{
            "label": i.get("label", ""),
            "kind": _COMPLETION_KINDS.get(i.get("kind", 0), "Unknown"),
            "detail": i.get("detail", ""),
        } for i in shown]
    else:
        items = [i.get("label", "") for i in shown]

    out = {"items": items, "count": total}
    if total > len(shown):
        out["truncated"] = True
    return out
