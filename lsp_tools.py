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


def _doc_text(doc):
    if isinstance(doc, dict):
        return doc.get("value", "")
    return str(doc or "")


def signature_help(window, file_path, line, col, client=None):
    """Parameter info for the call being typed at this position."""
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/signatureHelp", "signatureHelpProvider")
    if err:
        return {"error": err}
    if not result:
        return {"signatures": []}

    signatures = []
    for sig in result.get("signatures", []) or []:
        entry = {"label": sig.get("label", "")}
        params = sig.get("parameters")
        if params:
            entry["parameters"] = [p.get("label", "") if isinstance(p, dict) else str(p)
                                   for p in params]
        doc = _doc_text(sig.get("documentation"))
        if doc:
            entry["documentation"] = doc
        signatures.append(entry)

    return {
        "signatures": signatures,
        "active_signature": result.get("activeSignature", 0),
        "active_parameter": result.get("activeParameter", 0),
    }


def type_definition(window, file_path, line, col, client=None):
    """Where the *type* of the symbol is declared. Premium in intelephense."""
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/typeDefinition", "typeDefinitionProvider")
    if err:
        return {"error": err}
    locations = lsp_format.parse_locations(result)
    if not locations:
        return {"locations": [], "message": "No type definition found"}
    return {"locations": locations, "count": len(locations)}


def implementation(window, file_path, line, col, client=None):
    """Concrete implementations of an interface or abstract member. Premium."""
    c = _client(client)
    result, err, _view, _s = c.position_request(
        window, file_path, line, col, "textDocument/implementation", "implementationProvider")
    if err:
        return {"error": err}
    locations = lsp_format.parse_locations(result)
    if not locations:
        return {"locations": [], "message": "No implementation found"}
    return {"locations": locations, "count": len(locations)}


def call_hierarchy(window, file_path, line, col, direction="incoming", client=None):
    """Who calls this (incoming) or what this calls (outgoing)."""
    if direction not in ("incoming", "outgoing"):
        return {"error": "direction must be 'incoming' or 'outgoing', got {!r}".format(direction)}

    c = _client(client)
    items, err, view, session = c.position_request(
        window, file_path, line, col,
        "textDocument/prepareCallHierarchy", "callHierarchyProvider")
    if err:
        return {"error": err}
    if not items:
        return {"calls": [], "message": "No call hierarchy item at this position"}

    method = "callHierarchy/{}Calls".format(direction)
    result, err = c.request(session, method, {"item": items[0]}, view, 15.0)
    if err:
        return {"error": err}

    key = "from" if direction == "incoming" else "to"
    calls = []
    for entry in result or []:
        node = entry.get(key) or {}
        rng = node.get("selectionRange") or node.get("range") or {}
        start = rng.get("start", {})
        calls.append({
            "name": node.get("name", ""),
            "kind": lsp_format.symbol_kind_name(node.get("kind", 0)),
            "file": lsp_format.uri_to_path(node.get("uri", "")),
            "line": start.get("line", 0),
            "col": start.get("character", 0),
        })

    return {"direction": direction, "calls": calls, "count": len(calls)}


def _hint_label(label):
    if isinstance(label, list):
        return "".join(p.get("value", "") if isinstance(p, dict) else str(p) for p in label)
    return str(label or "")


def inlay_hint(window, file_path, start_line, end_line, client=None):
    """Inferred types and parameter names the server would render inline."""
    if end_line < start_line:
        return {"error": "end_line ({}) is before start_line ({})".format(end_line, start_line)}

    c = _client(client)
    view, err = c.resolve_view(window, file_path)
    if err:
        return {"error": err}
    session, err = c.session_for_view(view, "inlayHintProvider")
    if err:
        return {"error": err}

    params = c.document_params(view)
    params["range"] = {
        "start": {"line": start_line, "character": 0},
        "end": {"line": end_line + 1, "character": 0},
    }
    result, err = c.request(session, "textDocument/inlayHint", params, view)
    if err:
        return {"error": err}

    hints = []
    for h in result or []:
        pos = h.get("position") or {}
        hints.append({
            "label": _hint_label(h.get("label")),
            "line": pos.get("line", 0),
            "col": pos.get("character", 0),
        })
    return {"hints": hints, "count": len(hints)}


def rename(window, file_path, line, col, new_name, apply=False, client=None):
    """Rename a symbol project-wide.

    Without apply=True this only describes the edit. That split is deliberate:
    the apply is a separate tool use, so it is not covered by the read-only
    auto-allow patterns and reaches the permission prompt.
    """
    if not new_name:
        return {"error": "new_name is required"}

    c = _client(client)
    result, err, _view, session = c.position_request(
        window, file_path, line, col, "textDocument/rename", "renameProvider",
        extra_params={"newName": new_name}, timeout=30.0)
    if err:
        return {"error": err}

    summary = lsp_format.summarize_workspace_edit(result)
    if not summary["file_count"]:
        return dict(summary, applied=False,
                    message="The symbol at this position cannot be renamed")

    if not apply:
        return dict(summary, applied=False,
                    message="Preview only — nothing written. Re-run with --apply to write it.")

    ok, err = c.apply_workspace_edit(session, result, label="rename to {}".format(new_name))
    if not ok:
        return dict(summary, applied=False, error=err)
    return dict(summary, applied=True)


def code_action(window, file_path, line, col, apply_index=None, client=None):
    """List the fixes and refactors the server offers at a position.

    Listing never writes. Pass apply_index to apply one — that is a separate
    tool use, so it reaches the permission prompt.
    """
    c = _client(client)
    view, err = c.resolve_view(window, file_path)
    if err:
        return {"error": err}
    session, err = c.session_for_view(view, "codeActionProvider")
    if err:
        return {"error": err}

    params = c.document_params(view)
    params["range"] = {"start": {"line": line, "character": col},
                       "end": {"line": line, "character": col}}
    params["context"] = {"diagnostics": []}
    result, err = c.request(session, "textDocument/codeAction", params, view, 15.0)
    if err:
        return {"error": err}

    actions = result or []
    listed = [{
        "index": i,
        "title": a.get("title", ""),
        "kind": a.get("kind", ""),
        "has_edit": bool(a.get("edit")),
    } for i, a in enumerate(actions)]

    if apply_index is None:
        if not listed:
            return {"actions": [], "message": "No code actions at this position"}
        return {"actions": listed,
                "message": "Listed only — nothing written. Re-run with --apply <index> to apply one."}

    if not 0 <= apply_index < len(actions):
        return {"actions": listed,
                "error": "apply index {} is out of range (0-{})".format(
                    apply_index, len(actions) - 1 if actions else 0)}

    chosen = actions[apply_index]
    edit = chosen.get("edit")
    if not edit:
        return {"actions": listed,
                "error": "Action {!r} carries no edit; it needs a server command, "
                         "which is not supported".format(chosen.get("title", ""))}

    ok, err = c.apply_workspace_edit(session, edit, label=chosen.get("title", ""))
    if not ok:
        return {"actions": listed, "applied": False, "error": err}
    summary = lsp_format.summarize_workspace_edit(edit)
    return dict(summary, actions=listed, applied=True, title=chosen.get("title", ""))
