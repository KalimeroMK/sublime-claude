"""First-run check for the LSP package and a language server for the project.

The lsp tools need both: LSP is a framework with no server of its own, so having
only LSP still leaves every subcommand returning "No LSP server for this view".
Every side effect is injectable so the tests never open a dialog.
"""
import os

import sublime

SETTINGS_FILE = "ClaudeCode.sublime-settings"
SETTING_KEY = "lsp_install_prompt"

# marker file -> the LSP-* package that serves that language
_MARKERS = (
    ("composer.json", "LSP-intelephense"),
    ("tsconfig.json", "LSP-typescript"),
    ("package.json", "LSP-typescript"),
    ("pyproject.toml", "LSP-pyright"),
    ("requirements.txt", "LSP-pyright"),
    ("go.mod", "LSP-gopls"),
    ("Cargo.toml", "LSP-rust-analyzer"),
)


def server_for_markers(names):
    """First matching server for the marker files present, in _MARKERS order."""
    present = set(names)
    for marker, package in _MARKERS:
        if marker in present:
            return package
    return None


def _detect_server(folders, marker_exists):
    for marker, package in _MARKERS:
        for folder in folders:
            if marker_exists(os.path.join(folder, marker)):
                return package
    return None


def _default_prompt(packages, reason):
    message = (
        "Claude Code: {}\n\n"
        "Install {} with Package Control?".format(reason, ", ".join(packages))
    )
    answer = sublime.yes_no_cancel_dialog(message, "Install", "Not now")
    if answer == sublime.DIALOG_YES:
        return "install"
    if answer == sublime.DIALOG_NO:
        return "later"
    return "never"


def _default_install(packages):
    sublime.run_command("install_packages",
                        {"packages": list(packages), "unattended": False})


def _default_save(value):
    settings = sublime.load_settings(SETTINGS_FILE)
    settings.set(SETTING_KEY, value)
    sublime.save_settings(SETTINGS_FILE)


def check(installed=None, marker_exists=os.path.exists, folders=None, setting=None,
          prompt=None, install=None, save_setting=None):
    """Prompt once for whatever the lsp tools are missing."""
    if installed is None:
        from . import lsp_client
        installed = lsp_client.is_package_installed
    if prompt is None:
        prompt = _default_prompt
    if install is None:
        install = _default_install
    if save_setting is None:
        save_setting = _default_save
    if setting is None:
        setting = sublime.load_settings(SETTINGS_FILE).get(SETTING_KEY, "ask")
    if folders is None:
        window = sublime.active_window()
        folders = window.folders() if window else []

    if setting == "never" or not folders:
        return

    missing = []
    if not installed("LSP"):
        missing.append("LSP")

    server = _detect_server(folders, marker_exists)
    if server and not installed(server):
        missing.append(server)

    if not missing:
        return

    if "LSP" in missing:
        reason = "the lsp tools need the LSP package to talk to a language server."
    else:
        reason = "LSP is installed but has no server for this project."

    answer = prompt(missing, reason)
    if answer == "install":
        install(missing)
    elif answer == "never":
        save_setting("never")
