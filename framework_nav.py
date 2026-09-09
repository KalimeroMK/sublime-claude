"""Resolve Laravel/Yii helper strings to the file they name.

A PHP language server sees `view('emails.layout')` as a string, so Cmd+Click
lands nowhere. These are the mappings PhpStorm needs the Laravel Idea plugin
for. Pure functions, stdlib only — no Sublime, no subprocess, so the whole
resolver is testable and works even when the app cannot boot.
"""
import os
import re

# Helpers whose first string argument names a file or key.
# `route` is deliberately absent from the bare-name set: `$request->route('id')`
# reads a route *parameter* and must not be mistaken for the route() helper.
_LARAVEL = {
    "view": "view", "render": None,
    "config": "config",
    "__": "lang", "trans": "lang", "trans_choice": "lang",
    "route": "route",
}
_BLADE_DIRECTIVES = ("extends", "include", "includeIf", "component", "each")

_CALL = re.compile(
    r"""(?P<prefix>->\s*|::\s*|\$)?          # what precedes the name, if anything
        \b(?P<name>__|trans_choice|trans|view|config|route|render|renderPartial|renderAjax)\s*\(\s*
        (?P<quote>['"])(?P<arg>[^'"]*)(?P=quote)""",
    re.X,
)
_BLADE_CALL = re.compile(
    r"""@(?P<name>extends|includeIf|include|component|each)\s*\(\s*
        (?P<quote>['"])(?P<arg>[^'"]*)(?P=quote)""",
    re.X,
)


def detect_framework(root, exists=os.path.exists):
    """laravel | yii2 | None, from marker files in the project root."""
    if exists(os.path.join(root, "artisan")):
        return "laravel"
    if exists(os.path.join(root, "yii")) or exists(os.path.join(root, "yii.bat")):
        return "yii2"
    composer = os.path.join(root, "composer.json")
    if exists(composer):
        try:
            with open(composer, encoding="utf-8") as f:
                body = f.read()
        except OSError:
            return None
        if "yiisoft/yii2" in body:
            return "yii2"
        if "laravel/framework" in body:
            return "laravel"
    return None


def call_at(text, point):
    """The helper call whose string argument contains `point`.

    Returns (kind, argument) or None. `kind` is the helper name; a Blade
    directive comes back as its bare name (`extends`, `include`, ...).
    """
    for pattern, blade in ((_BLADE_CALL, True), (_CALL, False)):
        for m in pattern.finditer(text):
            start, end = m.span("arg")
            if not (start <= point <= end):
                continue
            name = m.group("name")
            if blade:
                return name, m.group("arg")
            # `$request->route('id')` and `Foo::route('x')` are not the helper
            if m.group("prefix") and name in ("route", "config", "view", "__",
                                              "trans", "trans_choice"):
                continue
            return name, m.group("arg")
    return None


def _first_existing(paths, exists):
    for p in paths:
        if exists(p):
            return p
    return None


def _key_line(path, keys, read):
    """Line of the last key in `keys`, searched nested-in-order. 0 if not found."""
    try:
        lines = read(path).splitlines()
    except OSError:
        return 0
    at = 0
    line = 0
    for key in keys:
        pat = re.compile(r"""['"]%s['"]\s*=>""" % re.escape(key))
        for i in range(at, len(lines)):
            if pat.search(lines[i]):
                line = i + 1
                at = i + 1
                break
        else:
            return 0
    return line


def resolve(kind, arg, root, framework="laravel", exists=os.path.exists,
            read=None, glob_files=None, list_dir=None):
    """Candidate targets for a helper string.

    Returns a list of {"path": ..., "line": int}; line 0 means "top of file".
    """
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    if list_dir is None:
        list_dir = os.listdir
    if glob_files is None:
        def glob_files(pattern_root, name):
            hits = []
            for dirpath, _dirs, files in os.walk(pattern_root):
                if name in files:
                    hits.append(os.path.join(dirpath, name))
            return hits

    if kind in ("view",) or kind in _BLADE_DIRECTIVES:
        rel = arg.replace(".", os.sep)
        found = _first_existing([
            os.path.join(root, "resources", "views", rel + ".blade.php"),
            os.path.join(root, "resources", "views", rel + ".php"),
        ], exists)
        return [{"path": found, "line": 0}] if found else []

    if kind == "config":
        parts = arg.split(".")
        path = os.path.join(root, "config", parts[0] + ".php")
        if not exists(path):
            return []
        return [{"path": path, "line": _key_line(path, parts[1:], read)}]

    if kind in ("__", "trans", "trans_choice"):
        parts = arg.split(".")
        lang_root = _first_existing([os.path.join(root, "lang"),
                                     os.path.join(root, "resources", "lang")], exists)
        if not lang_root:
            return []
        out = []
        for locale in sorted(_locales(lang_root, list_dir)):
            php = os.path.join(lang_root, locale, parts[0] + ".php")
            if exists(php):
                out.append({"path": php, "line": _key_line(php, parts[1:], read)})
            js = os.path.join(lang_root, locale + ".json")
            if exists(js):
                out.append({"path": js, "line": 0})
        return out

    if kind == "route":
        routes = os.path.join(root, "routes")
        if not exists(routes):
            return []
        pat = re.compile(r"""->\s*name\(\s*['"]%s['"]""" % re.escape(arg))
        out = []
        for name in ("web.php", "api.php", "console.php", "channels.php"):
            path = os.path.join(routes, name)
            if not exists(path):
                continue
            try:
                lines = read(path).splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if pat.search(line):
                    out.append({"path": path, "line": i + 1})
        return out

    if kind in ("render", "renderPartial", "renderAjax") and framework == "yii2":
        views = os.path.join(root, "views")
        if not exists(views):
            return []
        name = arg.split("/")[-1] + ".php"
        return [{"path": p, "line": 0} for p in sorted(glob_files(views, name))]

    return []


def _locales(lang_root, list_dir):
    """Locale directory names under lang/ — entries without a dot."""
    try:
        return [n for n in list_dir(lang_root) if "." not in n]
    except OSError:
        return []


def find_root(file_path, folders=(), exists=os.path.exists):
    """Nearest framework root at or above file_path, else the first matching folder.

    Walks up so a modular app (app/Modules/... in instacom) resolves against the
    real project root rather than the module directory.
    """
    seen = set()
    d = os.path.dirname(file_path or "") or None
    while d and d not in seen and d != os.path.dirname(d):
        seen.add(d)
        if detect_framework(d, exists):
            return d
        d = os.path.dirname(d)
    for folder in folders:
        if detect_framework(folder, exists):
            return folder
    return None
