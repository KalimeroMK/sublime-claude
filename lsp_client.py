"""The only module that talks to the LSP package.

Threading rule: LSP delivers responses on Sublime's async worker thread, so
`request()` must never be called from it — blocking there means the response can
never arrive and every call times out. mcp_server is safe: its socket loop runs
on its own daemon thread (mcp_server.py:98). The guard below turns a silent
45s hang into an immediate, named error.

`apply_workspace_edit` is the exception: it must run *on* the async thread, so
it schedules itself there and waits from the caller's thread.
"""
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import sublime

# Test seams. Left None in production; tests substitute them.
_REQUEST_FACTORY = None
_async_thread_id = None


def _mark_async_thread():
    """Record Sublime's async worker so request() can refuse to block it."""
    global _async_thread_id
    _async_thread_id = threading.get_ident()


def _request_factory():
    if _REQUEST_FACTORY is not None:
        return _REQUEST_FACTORY
    from LSP.plugin.core.protocol import Request
    return Request


def request(session, method, params, view=None, timeout=5.0):
    """Issue a blocking LSP request. Returns (result, error)."""
    if _async_thread_id is not None and threading.get_ident() == _async_thread_id:
        raise RuntimeError(
            "lsp_client.request called on Sublime's async thread; LSP delivers "
            "responses there, so this would block until timeout. Call it from a "
            "worker thread instead."
        )

    Request = _request_factory()
    done = threading.Event()
    result = [None]
    error = [None]

    def on_result(r):
        result[0] = r
        done.set()

    def on_error(e):
        error[0] = str(e) if e else "Unknown error"
        done.set()

    session.send_request(Request(method, params, view=view), on_result, on_error)
    if not done.wait(timeout):
        return None, "LSP request timeout after {}s: {}".format(timeout, method)
    if error[0]:
        return None, error[0]
    return result[0], None


def has_capability(session, capability):
    return bool(session.has_capability(capability))


def is_package_installed(name, exists=os.path.exists):
    """True if `name` is present as a loose package or a .sublime-package."""
    candidates = (
        os.path.join(sublime.packages_path(), name),
        os.path.join(sublime.installed_packages_path(), name + ".sublime-package"),
    )
    return any(exists(p) for p in candidates)


def is_lsp_installed():
    return is_package_installed("LSP")


def resolve_view(window, file_path):
    """Find or transiently open the view for file_path. Returns (view, error)."""
    if not window:
        return None, "No window"

    if not os.path.isabs(file_path):
        for folder in window.folders():
            full = os.path.join(folder, file_path)
            if os.path.exists(full):
                file_path = full
                break
    file_path = os.path.normpath(file_path)

    for v in window.views():
        if v.file_name() and os.path.normpath(v.file_name()) == file_path:
            return v, None

    if os.path.exists(file_path):
        view = window.open_file(file_path, sublime.TRANSIENT)
        deadline = time.time() + 2.0
        while view.is_loading() and time.time() < deadline:
            time.sleep(0.05)
        return view, None

    return None, "File not found: {}".format(file_path)


def session_for_view(view, capability=None):
    """Best LSP session for a view, optionally requiring a capability."""
    try:
        from LSP.plugin.core.registry import windows as lsp_windows
    except ImportError:
        return None, "LSP package not installed"

    listener = lsp_windows.listener_for_view(view)
    if not listener:
        return None, "No LSP listener for this view"

    if capability:
        session = listener.session_async(capability)
        if not session:
            return None, "No LSP server with {} capability".format(capability)
        return session, None

    sessions = listener.sessions_async()
    if sessions:
        return sessions[0], None
    return None, "No LSP server for this view"


def diagnostics_for_view(view):
    """Diagnostics LSP already holds for this view. Returns (items, error).

    These arrive by push (textDocument/publishDiagnostics) and are cached by
    LSP, so this reads the cache instead of issuing textDocument/diagnostic —
    which intelephense does not serve.
    """
    try:
        from LSP.plugin.core.registry import windows as lsp_windows
        from LSP.plugin.core.views import uri_from_view
    except ImportError:
        return None, "LSP package not installed"

    listener = lsp_windows.listener_for_view(view)
    if not listener:
        return None, "No LSP listener for this view"
    sessions = listener.sessions_async()
    if not sessions:
        return None, "No LSP server for this view"

    uri = uri_from_view(view)
    items = []
    for session in sessions:
        try:
            items.extend(session.diagnostics.get_diagnostics_for_uri(uri))
        except Exception as e:
            return None, "Failed to read diagnostics from {}: {}".format(
                session.config.name, e)
    return items, None


def position_params(view, line, col):
    from LSP.plugin.core.views import text_document_position_params
    return text_document_position_params(view, view.text_point(line, col))


def document_params(view):
    from LSP.plugin.core.views import text_document_identifier
    return {"textDocument": text_document_identifier(view)}


def position_request(window, file_path, line, col, method, capability,
                     extra_params=None, timeout=5.0):
    """resolve view -> require capability -> position params -> request.

    This is the shape eight of the subcommands need; it exists so they do not
    each repeat the seven steps the old mcp_server code repeated per tool.
    Returns (result, error, view, session).
    """
    view, err = resolve_view(window, file_path)
    if err:
        return None, err, None, None
    session, err = session_for_view(view, capability)
    if err:
        return None, err, view, None
    params = position_params(view, line, col)
    if extra_params:
        params.update(extra_params)
    result, err = request(session, method, params, view, timeout)
    return result, err, view, session
