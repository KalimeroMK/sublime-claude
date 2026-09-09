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


# ─── Static project summaries (no artisan, no booting the app) ───────────────

_MODEL_PATTERNS = {
    "table":    re.compile(r"""protected\s+\$table\s*=\s*['"]([^'"]+)['"]"""),
    "connection": re.compile(r"""protected\s+\$connection\s*=\s*['"]([^'"]+)['"]"""),
}
_PROPERTY = re.compile(r"@property(?:-read)?\s+(?P<type>\S+)\s+\$(?P<name>\w+)")
_ARRAY_PROP = re.compile(
    r"protected\s+\$(?P<name>fillable|casts|hidden|guarded|appends|dates)\s*=\s*\[(?P<body>.*?)\]",
    re.S)
_RELATION = re.compile(
    r"public\s+function\s+(?P<name>\w+)\s*\([^)]*\)[^{]*\{[^}]*?"
    r"\$this->(?P<kind>belongsToMany|belongsTo|hasManyThrough|hasOneThrough|hasMany|hasOne|morphMany|morphOne|morphTo)"
    r"\s*\(\s*(?P<target>[^,)\s]+)?",
    re.S)


def find_model(root, name, walk=None):
    """Model file for a bare class name. Modular layouts are searched too."""
    if walk is None:
        walk = os.walk
    wanted = name if name.endswith(".php") else name + ".php"
    hits = []
    for base in ("app", "src", "models"):
        start = os.path.join(root, base)
        for dirpath, _dirs, files in walk(start):
            if wanted in files:
                hits.append(os.path.join(dirpath, wanted))
    # prefer paths that look like model directories
    hits.sort(key=lambda p: (0 if os.sep + "Models" + os.sep in p else 1, len(p)))
    return hits[0] if hits else None


def model_summary(path, read=None):
    """What a model declares, read straight from the source."""
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    try:
        src = read(path)
    except OSError:
        return {}

    out = {"path": path, "properties": [], "relations": []}
    m = re.search(r"class\s+(\w+)\s+extends\s+(\S+)", src)
    if m:
        out["class"], out["extends"] = m.group(1), m.group(2)
    for key, pat in _MODEL_PATTERNS.items():
        hit = pat.search(src)
        if hit:
            out[key] = hit.group(1)
    for m in _ARRAY_PROP.finditer(src):
        items = re.findall(r"""['"]([^'"]+)['"]""", m.group("body"))
        if items:
            out[m.group("name")] = items
    for m in _PROPERTY.finditer(src):
        out["properties"].append({"name": m.group("name"), "type": m.group("type")})
    for m in _RELATION.finditer(src):
        out["relations"].append({
            "name": m.group("name"),
            "kind": m.group("kind"),
            "target": (m.group("target") or "").replace("::class", "").lstrip("\\"),
        })
    return out


_ROUTE_CALL = re.compile(
    r"""Route::(?P<verb>get|post|put|patch|delete|options|any|match)\s*\(\s*
        (?:\[(?P<verbs>[^\]]*)\]\s*,\s*)?   # Route::match takes the verb array first
        (?P<q>['"])(?P<uri>[^'"]*)(?P=q)""", re.X)
_ROUTE_NAME = re.compile(r"""->\s*name\(\s*['"]([^'"]+)['"]""")
_ROUTE_ACTION = re.compile(r"\[\s*([\w\\]+)::class\s*,\s*['\"](\w+)['\"]\s*\]")
_PREFIX = re.compile(r"""Route::prefix\(\s*['"]([^'"]*)['"]""")


def route_summary(root, read=None, exists=os.path.exists):
    """Routes parsed out of routes/*.php — no artisan, works on a broken app."""
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    out = []
    routes_dir = os.path.join(root, "routes")
    if not exists(routes_dir):
        return out
    for fname in ("api.php", "web.php", "console.php", "channels.php"):
        path = os.path.join(routes_dir, fname)
        if not exists(path):
            continue
        try:
            lines = read(path).splitlines()
        except OSError:
            continue
        prefix = ""
        for i, line in enumerate(lines):
            p = _PREFIX.search(line)
            if p:
                prefix = p.group(1)
            m = _ROUTE_CALL.search(line)
            if not m:
                continue
            verbs = m.group("verbs")
            if verbs:
                verb = "|".join(v.strip().strip("'\"").upper()
                                for v in verbs.split(",") if v.strip())
            else:
                verb = m.group("verb").upper()
            entry = {"file": fname, "line": i + 1, "verb": verb,
                     "uri": m.group("uri"), "prefix": prefix}
            # name and action may sit on the same line or the next few
            window = "\n".join(lines[i:i + 4])
            n = _ROUTE_NAME.search(window)
            if n:
                entry["name"] = n.group(1)
            a = _ROUTE_ACTION.search(window)
            if a:
                entry["action"] = "{}::{}".format(a.group(1).split("\\")[-1], a.group(2))
            out.append(entry)
    return out
