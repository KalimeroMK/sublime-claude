# LSP tool surface + install check

## Problem

The plugin exposes 6 of the language server's capabilities to Claude — hover,
definition, references, documentSymbol, workspace/symbol, diagnostics. It has no
`completion`, so Claude cannot ask the server "what can I call here?" before
writing a call. That is the check that would stop invented method names.

Four more capabilities became available once the intelephense premium licence was
actually applied (`renameProvider`, `typeDefinitionProvider`,
`implementationProvider`, `foldingRangeProvider` all report `true`).

Nothing verifies that the `LSP` package is installed. Without it every lsp tool
returns "LSP package not installed", and `LSP` alone is not enough — it is a
framework with no server, so PHP also needs `LSP-intelephense`.

## Decisions

- All 14 subcommands, including the two that mutate (`rename`, `code_action`).
- Install check covers `LSP` **and** a language server matched to the project.
- Mutating subcommands preview by default; `--apply` routes through the existing
  permission prompt.
- macOS + Linux. Windows is out of scope (not supported, not broken).

## Modules

| file | ~lines | responsibility |
|---|---|---|
| `lsp_client.py` | 130 | the only importer of `LSP.plugin.*`: session lookup, sync request, capability check, package detection |
| `lsp_tools.py` | 470 | the 14 subcommands, each shallow over the client |
| `lsp_install.py` | 120 | first-run check, language detection, Package Control call |
| `mcp_server.py` | −371 | registration only; 2044 → ~1690 lines |

`lsp_client.py` is the test seam — replaced by a fake so all 14 subcommands are
testable without Sublime and without a server.

### Threading constraint

`request()` must not run on Sublime's async thread. LSP delivers responses on
that thread, so blocking it guarantees a timeout — observed as a reproducible
45s hang during design. `mcp_server` already satisfies this: its socket loop runs
on its own daemon thread (`mcp_server.py:98`). `request()` documents the rule and
raises if called from the async thread, once, instead of the rule being implicit
in 14 call sites.

## Subcommands

Existing: `hover`, `definition`, `references`, `symbols`, `workspace_symbols`,
`diagnostics`.

| subcommand | LSP method | capability |
|---|---|---|
| `completion` | `textDocument/completion` | `completionProvider` |
| `signature_help` | `textDocument/signatureHelp` | `signatureHelpProvider` |
| `type_definition` | `textDocument/typeDefinition` | `typeDefinitionProvider` |
| `implementation` | `textDocument/implementation` | `implementationProvider` |
| `call_hierarchy` | `prepareCallHierarchy` → `incomingCalls`/`outgoingCalls` | `callHierarchyProvider` |
| `inlay_hint` | `textDocument/inlayHint` | `inlayHintProvider` |
| `rename` | `prepareRename` → `rename` | `renameProvider` |
| `code_action` | `textDocument/codeAction` | `codeActionProvider` |

All eleven methods exist in the installed LSP package. Each subcommand checks its
capability first and returns "server has no <X> capability" rather than hanging —
four of these are premium and absent without a licence.

Stays a single `lsp` MCP tool with subcommands. `mcp/server.py` already declares
28 tools; 14 more would inflate the tool list sent on every request, and
subcommands are the established shape (`lsp hover <file> <line> <col>`).

## Permission

`can_use_tool` (`bridge/main.py:661`) already gates every MCP tool unless
`autoAllowedMcpTools` matches, so no new permission machinery is needed.

One gap: `match_permission_pattern` (`permissions.py:251`) inspects
`command`/`path`/`query`, but the `lsp` tool carries its subcommand in `cmd`, so
no pattern can ever match. Fix is to add `cmd` to the fields it inspects. Then:

```jsonc
"autoAllowedMcpTools": [
  "mcp__sublime__lsp(hover:*)",
  "mcp__sublime__lsp(completion:*)"
  // ... the 12 read-only subcommands; rename and code_action omitted
]
```

`rename` and `code_action` without `--apply` return a summary of the
WorkspaceEdit (files touched, edit count) and write nothing. With `--apply` they
are a distinct tool use, so they hit the existing Y/N/S/A/B prompt.

## Install check

Runs from `core.plugin_loaded` via `set_timeout` so it never blocks startup.

1. `LSP` present? Look for `Packages/LSP` or `Installed Packages/LSP.sublime-package`.
2. Server for the project's language, by marker file:
   `composer.json` → `LSP-intelephense`, `package.json`/`tsconfig.json` →
   `LSP-typescript`, `pyproject.toml`/`requirements.txt` → `LSP-pyright`,
   `go.mod` → `LSP-gopls`, `Cargo.toml` → `LSP-rust-analyzer`.

Missing either one shows a dialog with `[Install] [Not now] [Never]`. Install
calls `sublime.run_command("install_packages", {"packages": [...], "unattended": False})`
— the documented Package Control 4 API.

`ClaudeCode.sublime-settings` gains `lsp_install_prompt: "ask" | "never"`.
"Not now" writes nothing and asks again next start; "Never" writes `"never"`.

## Testing

`tests/test_lsp_tools.py` against a fake client:

- one per subcommand: correct method and params
- capability absent → clean error, no request issued
- `rename`/`code_action` without `--apply` must issue no applyEdit — this test is
  what holds the safety decision in place

`tests/test_lsp_install.py`: detection by marker file, "Never" is remembered, no
dialog when everything is present.

`tests/test_permissions.py` gains cases for the `cmd` field and for read-only vs
mutating separation.

## Build order

Value first, risk last. Each stage ends green.

1. Extract `lsp_client.py`, move the existing 6 across. No behaviour change.
2. Add `completion` and `signature_help` — the two that change how Claude writes code.
3. Add `type_definition`, `implementation`, `call_hierarchy`, `inlay_hint`.
4. `permissions.py` `cmd` field, then `rename` and `code_action` with preview/`--apply`.
5. `lsp_install.py` and the first-run check.

## Out of scope

`formatting` (PHP CS Fixer already covers it), `documentHighlight`,
`foldingRange`, `semanticTokens`, `selectionRange` — low value to an agent.
Windows support. Any change to how completions reach the user while typing: that
is LSP's job and the plugin is not a completion provider.
