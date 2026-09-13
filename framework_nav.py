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
    r"""@(?P<name>extends|includeIf|include|component|each|livewire)\s*\(\s*
        (?P<quote>['"])(?P<arg>[^'"]*)(?P=quote)""",
    re.X,
)
# <x-forms.input />, <x-slot:foo>, <livewire:brand.table /> — a component tag
# carries no quotes, so the generic helper regex never sees it.
_TAG_CALL = re.compile(
    r"""<(?P<name>x|livewire)(?P<sep>[-:])(?P<arg>[A-Za-z0-9_.\-]+)""")


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
    for m in _TAG_CALL.finditer(text):
        start, end = m.span("arg")
        if start <= point <= end:
            kind = "livewire" if m.group("name") == "livewire" else "component-tag"
            return kind, m.group("arg")
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


def _studly(word):
    """`forms-input` / `forms_input` → `FormsInput`, as Laravel resolves it."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[-_]", word) if p)


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

    if kind == "component-tag":
        # <x-forms.input> is resources/views/components/forms/input.blade.php,
        # and may also have a class at app/View/Components/Forms/Input.php
        rel = arg.replace(".", os.sep)
        out = []
        for candidate in (
            os.path.join(root, "resources", "views", "components", rel + ".blade.php"),
            os.path.join(root, "resources", "views", "components", rel,
                         "index.blade.php"),
        ):
            if exists(candidate):
                out.append({"path": candidate, "line": 0})
        studly = os.sep.join(_studly(p) for p in arg.split("."))
        for candidate in (
            os.path.join(root, "app", "View", "Components", studly + ".php"),
        ):
            if exists(candidate):
                out.append({"path": candidate, "line": 0})
        return out

    if kind == "livewire":
        rel = arg.replace(".", os.sep)
        studly = os.sep.join(_studly(p) for p in arg.split("."))
        out = []
        for candidate in (
            os.path.join(root, "app", "Livewire", studly + ".php"),
            os.path.join(root, "app", "Http", "Livewire", studly + ".php"),
        ):
            if exists(candidate):
                out.append({"path": candidate, "line": 0})
        for candidate in (
            os.path.join(root, "resources", "views", "livewire", rel + ".blade.php"),
        ):
            if exists(candidate):
                out.append({"path": candidate, "line": 0})
        if not out and glob_files:
            name = _studly(arg.split(".")[-1]) + ".php"
            out = [{"path": p, "line": 0}
                   for p in sorted(glob_files(os.path.join(root, "app"), name))]
        return out

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


_GROUP_OPEN = re.compile(r"->\s*group\s*\(|Route::group\s*\(")
_CH_PREFIX = re.compile(r"""(?:->|::)\s*prefix\s*\(\s*['"]([^'"]*)['"]""")
_AR_PREFIX = re.compile(r"""['"]prefix['"]\s*=>\s*['"]([^'"]*)['"]""")
_CH_NAME = re.compile(r"""(?:->|::)\s*name\s*\(\s*['"]([^'"]*)['"]""")
_AR_NAME = re.compile(r"""['"]as['"]\s*=>\s*['"]([^'"]*)['"]""")
_CH_MW = re.compile(r"""(?:->|::)\s*middleware\s*\(\s*(?P<body>\[[^\]]*\]|['"][^'"]*['"])""")
_AR_MW = re.compile(r"""['"]middleware['"]\s*=>\s*(?P<body>\[[^\]]*\]|['"][^'"]*['"])""")
_CH_CONTROLLER = re.compile(r"""(?:->|::)\s*controller\s*\(\s*([\w\\]+)::class""")
_AR_CONTROLLER = re.compile(r"""['"]controller['"]\s*=>\s*([\w\\]+)::class""")
_RESOURCE = re.compile(
    r"""Route::(?P<kind>apiResource|resource)\s*\(\s*['"](?P<name>[^'"]+)['"]\s*,\s*
        (?P<controller>[\w\\]+)::class""", re.X)
_ONLY = re.compile(r"->\s*only\s*\(\s*\[(?P<body>[^\]]*)\]")
_EXCEPT = re.compile(r"->\s*except\s*\(\s*\[(?P<body>[^\]]*)\]")
_STRING_ACTION = re.compile(r"""['"](?P<c>[\w\\]+)@(?P<m>\w+)['"]""")

# verb, uri suffix, name suffix — Laravel's own resource route table
_RESOURCE_ACTIONS = (
    ("index", "GET", "", "index"),
    ("create", "GET", "/create", "create"),
    ("store", "POST", "", "store"),
    ("show", "GET", "/{param}", "show"),
    ("edit", "GET", "/{param}/edit", "edit"),
    ("update", "PUT|PATCH", "/{param}", "update"),
    ("destroy", "DELETE", "/{param}", "destroy"),
)
_API_RESOURCE_SKIP = ("create", "edit")


def _singular(word):
    """Route-parameter name for a resource — `photos` → `photo`."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _join_uri(*parts):
    segments = []
    for p in parts:
        for seg in (p or "").strip("/").split("/"):
            if seg:
                segments.append(seg)
    return "/" + "/".join(segments)


def _group_attrs(line):
    """Prefix, name, middleware and controller a group line establishes."""
    attrs = {"prefix": "", "name": "", "middleware": [], "controller": ""}
    for pat in (_CH_PREFIX, _AR_PREFIX):
        m = pat.search(line)
        if m:
            attrs["prefix"] = m.group(1)
            break
    for pat in (_CH_NAME, _AR_NAME):
        m = pat.search(line)
        if m:
            attrs["name"] = m.group(1)
            break
    for pat in (_CH_MW, _AR_MW):
        m = pat.search(line)
        if m:
            attrs["middleware"] = _QUOTED.findall(m.group("body"))
            break
    for pat in (_CH_CONTROLLER, _AR_CONTROLLER):
        m = pat.search(line)
        if m:
            attrs["controller"] = m.group(1).split("\\")[-1]
            break
    return attrs


def _module_of(path):
    """Module a route file belongs to — the segment after `Modules`."""
    parts = path.split(os.sep)
    for i, p in enumerate(parts):
        if p.lower() in ("modules", "module") and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def find_route_files(root, walk=None, exists=os.path.exists):
    """Every file that can declare routes, not just the four Laravel ships.

    A modular app keeps its routes beside each module
    (app/Modules/Brand/Infrastructure/Routes/brand.php), so a hard-coded list
    of routes/*.php reports almost nothing on those projects.
    """
    if walk is None:
        walk = os.walk
    found = []
    for name in ("web.php", "api.php", "console.php", "channels.php"):
        path = os.path.join(root, "routes", name)
        if exists(path):
            found.append(path)
    seen = set(found)
    for dirpath, dirs, files in walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        parts = dirpath.split(os.sep)
        if _SKIP_DIRS.intersection(parts):
            continue
        if "routes" not in [p.lower() for p in parts]:
            continue
        for name in files:
            path = os.path.join(dirpath, name)
            if name.endswith(".php") and path not in seen:
                seen.add(path)
                found.append(path)
    return found


def _resource_routes(line, frame, fname, module, lineno):
    """Expand Route::resource / apiResource into the routes it registers."""
    m = _RESOURCE.search(line)
    if not m:
        return []
    name, kind = m.group("name"), m.group("kind")
    controller = m.group("controller").split("\\")[-1]
    wanted = [a[0] for a in _RESOURCE_ACTIONS]
    if kind == "apiResource":
        wanted = [a for a in wanted if a not in _API_RESOURCE_SKIP]
    only = _ONLY.search(line)
    if only:
        picked = _QUOTED.findall(only.group("body"))
        wanted = [a for a in wanted if a in picked]
    excl = _EXCEPT.search(line)
    if excl:
        dropped = _QUOTED.findall(excl.group("body"))
        wanted = [a for a in wanted if a not in dropped]

    param = _singular(name.split(".")[-1])
    out = []
    for action, verb, suffix, name_suffix in _RESOURCE_ACTIONS:
        if action not in wanted:
            continue
        uri = _join_uri(frame["prefix"], name) + suffix.replace("{param}", "{%s}" % param)
        entry = {"file": fname, "line": lineno, "verb": verb,
                 "uri": uri, "prefix": frame["prefix"],
                 "name": frame["name"] + name + "." + name_suffix,
                 "action": "{}::{}".format(controller, action),
                 "module": module}
        if frame["middleware"]:
            entry["middleware"] = list(frame["middleware"])
        out.append(entry)
    return out


def route_summary(root, read=None, exists=os.path.exists, walk=None, files=None):
    """Routes parsed out of the project source — no artisan, works on a broken app.

    Group prefixes, name prefixes and middleware nest properly: each `group()`
    closure pushes a frame that is popped when its brace closes, so a route
    three groups deep reports the full URI a request would actually hit.
    """
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    if files is None:
        files = find_route_files(root, walk, exists)

    out = []
    for path in files:
        fname = os.path.basename(path)
        module = _module_of(path)
        try:
            lines = read(path).splitlines()
        except OSError:
            continue

        depth = 0
        stack = []

        def frame():
            merged = {"prefix": "", "name": "", "middleware": [], "controller": ""}
            for f in stack:
                merged["prefix"] = _join_uri(merged["prefix"], f["prefix"]).strip("/")
                merged["name"] += f["name"]
                merged["middleware"] = merged["middleware"] + f["middleware"]
                merged["controller"] = f["controller"] or merged["controller"]
            return merged

        for i, line in enumerate(lines):
            here = frame()
            out.extend(_resource_routes(line, here, fname, module, i + 1))

            m = _ROUTE_CALL.search(line)
            if m:
                verbs = m.group("verbs")
                if verbs:
                    verb = "|".join(v.strip().strip("'\"").upper()
                                    for v in verbs.split(",") if v.strip())
                else:
                    verb = m.group("verb").upper()
                entry = {"file": fname, "line": i + 1, "verb": verb,
                         "uri": _join_uri(here["prefix"], m.group("uri")),
                         "prefix": here["prefix"], "module": module}
                if here["middleware"]:
                    entry["middleware"] = list(here["middleware"])
                window = "\n".join(lines[i:i + 4])
                n = _ROUTE_NAME.search(window)
                # a route with no ->name() is unnamed in Laravel; inheriting
                # the group prefix alone would invent a name like "dev."
                if n:
                    entry["name"] = here["name"] + n.group(1)
                a = _ROUTE_ACTION.search(window)
                if a:
                    entry["action"] = "{}::{}".format(
                        a.group(1).split("\\")[-1], a.group(2))
                else:
                    s = _STRING_ACTION.search(window)
                    if s:
                        entry["action"] = "{}::{}".format(
                            s.group("c").split("\\")[-1], s.group("m"))
                    elif here["controller"]:
                        u = re.search(r"""->\s*uses\s*\(\s*['"](\w+)['"]""", window)
                        if u:
                            entry["action"] = "{}::{}".format(here["controller"], u.group(1))
                        else:
                            entry["action"] = here["controller"] + "::?"
                out.append(entry)

            opened = _GROUP_OPEN.search(line)
            before = depth
            depth += line.count("{") - line.count("}")
            if opened and depth > before:
                attrs = _group_attrs(line)
                attrs["depth"] = depth
                stack.append(attrs)
            while stack and stack[-1]["depth"] > depth:
                stack.pop()
    return out


# ─── Migrations → real table columns ─────────────────────────────────────────
#
# A model's $fillable is what mass assignment allows, not what the table holds.
# Reading the migrations is the only way to know the real column set without
# booting the app or touching a database.

_SCHEMA_OPEN = re.compile(
    r"""Schema::(?:connection\s*\(\s*['"][^'"]*['"]\s*\)\s*->\s*)?
        (?P<op>create|table)\s*\(\s*['"](?P<table>[^'"]+)['"]""", re.X)

# Longest-first so `unsignedBigInteger` never matches as `unsigned` + junk and
# `dateTime` wins over `date`.
_COLUMN_TYPES = (
    "bigIncrements", "bigInteger", "binary", "boolean", "char", "dateTimeTz",
    "dateTime", "date", "decimal", "double", "enum", "float", "foreignId",
    "foreignUlid", "foreignUuid", "geometry", "increments", "integer",
    "ipAddress", "jsonb", "json", "longText", "macAddress", "mediumIncrements",
    "mediumInteger", "mediumText", "nullableUuidMorphs", "nullableMorphs",
    "set", "smallIncrements", "smallInteger", "string", "text", "timeTz",
    "time", "timestampTz", "timestamp", "tinyIncrements", "tinyInteger",
    "tinyText", "ulid", "unsignedBigInteger", "unsignedDecimal",
    "unsignedInteger", "unsignedMediumInteger", "unsignedSmallInteger",
    "unsignedTinyInteger", "uuidMorphs", "uuid", "year", "morphs",
)
_COLUMN = re.compile(
    r"""\$table\s*->\s*(?P<type>%s)\s*\(\s*
        (?P<q>['"])(?P<name>[^'"]+)(?P=q)
        (?P<rest>.*)""" % "|".join(_COLUMN_TYPES), re.X | re.S)

_NOARG = re.compile(r"\$table\s*->\s*(?P<type>id|uuid|ulid|timestamps|timestampsTz|"
                    r"softDeletes|softDeletesTz|rememberToken)\s*\(\s*\)")
_DROP = re.compile(r"""\$table\s*->\s*dropColumn\s*\(\s*(?P<body>.*)""", re.S)
_DROP_SOFT = re.compile(r"\$table\s*->\s*dropSoftDeletes\s*\(")
_DROP_TS = re.compile(r"\$table\s*->\s*dropTimestamps\s*\(")
_RENAME = re.compile(
    r"""\$table\s*->\s*renameColumn\s*\(\s*['"](?P<old>[^'"]+)['"]\s*,\s*['"](?P<new>[^'"]+)['"]""")
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")
_DEFAULT = re.compile(r"->\s*default\s*\(\s*(?P<val>[^)]*)\)")

# Column sets the no-argument helpers stand in for.
_NOARG_COLUMNS = {
    "id": [("id", "bigint unsigned", {"pk": True})],
    "uuid": [("uuid", "uuid", {})],
    "ulid": [("ulid", "ulid", {})],
    "timestamps": [("created_at", "timestamp", {"nullable": True}),
                   ("updated_at", "timestamp", {"nullable": True})],
    "timestampsTz": [("created_at", "timestamptz", {"nullable": True}),
                     ("updated_at", "timestamptz", {"nullable": True})],
    "softDeletes": [("deleted_at", "timestamp", {"nullable": True})],
    "softDeletesTz": [("deleted_at", "timestamptz", {"nullable": True})],
    "rememberToken": [("remember_token", "string(100)", {"nullable": True})],
}


def _block_body(src, at):
    """Text between the first `{` at or after `at` and its matching `}`."""
    start = src.find("{", at)
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(src)):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return src[start + 1:]


def schema_blocks(src):
    """Every Schema::create/table block in a migration, in source order.

    Yields dicts: {"op": "create"|"table", "table": str, "body": str}.
    """
    out = []
    for m in _SCHEMA_OPEN.finditer(src):
        out.append({"op": m.group("op"), "table": m.group("table"),
                    "body": _block_body(src, m.end())})
    return out


def _statements(body):
    """Split a closure body into `;`-terminated statements."""
    return [s.strip() for s in body.split(";") if s.strip()]


def _render_type(kind, head_args):
    """`string` + `, 255` → `string(255)`; decimal → decimal(8,2); enum → enum(a,b)."""
    base = {
        "bigIncrements": "bigint unsigned", "increments": "int unsigned",
        "mediumIncrements": "mediumint unsigned", "smallIncrements": "smallint unsigned",
        "tinyIncrements": "tinyint unsigned", "foreignId": "bigint unsigned",
        "foreignUuid": "uuid", "foreignUlid": "ulid",
        "unsignedBigInteger": "bigint unsigned", "unsignedInteger": "int unsigned",
        "unsignedMediumInteger": "mediumint unsigned",
        "unsignedSmallInteger": "smallint unsigned",
        "unsignedTinyInteger": "tinyint unsigned",
        "bigInteger": "bigint", "mediumInteger": "mediumint",
        "smallInteger": "smallint", "tinyInteger": "tinyint",
        "dateTime": "datetime", "dateTimeTz": "datetimetz",
        "timestampTz": "timestamptz", "timeTz": "timetz",
    }.get(kind, kind)
    if kind in ("enum", "set"):
        vals = _QUOTED.findall(head_args)
        return "{}({})".format(base, ",".join(vals)) if vals else base
    nums = re.findall(r"\b\d+\b", head_args)
    if nums:
        return "{}({})".format(base, ",".join(nums))
    return base


def _modifiers(rest):
    """Flags a chained column definition carries."""
    out = {}
    if re.search(r"->\s*nullable\s*\(", rest):
        out["nullable"] = True
    if re.search(r"->\s*unique\s*\(", rest):
        out["unique"] = True
    if re.search(r"->\s*(?:index|fulltext|spatialIndex)\s*\(", rest):
        out["index"] = True
    if re.search(r"->\s*primary\s*\(", rest):
        out["pk"] = True
    if re.search(r"->\s*autoIncrement\s*\(", rest):
        out["pk"] = True
    if re.search(r"->\s*useCurrent\s*\(", rest):
        out["default"] = "CURRENT_TIMESTAMP"
    d = _DEFAULT.search(rest)
    if d:
        out["default"] = d.group("val").strip().strip("'\"")
    c = re.search(r"""->\s*constrained\s*\(\s*(?:['"](?P<t>[^'"]+)['"])?""", rest)
    if c:
        out["fk"] = c.group("t") or ""
    if re.search(r"->\s*nullableConstrained\s*\(", rest):
        out["nullable"] = True
        if "fk" not in out:
            n = re.search(r"""->\s*nullableConstrained\s*\(\s*['"]([^'"]+)['"]""", rest)
            out["fk"] = n.group(1) if n else ""
    return out


def _split_head(rest):
    """Split a column tail into its own remaining args and the chained calls."""
    depth = 1
    for i, c in enumerate(rest):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return rest[:i], rest[i + 1:]
    return rest, ""


def _guess_fk(name):
    """`company_id` → companies — Laravel's own convention for ->constrained()."""
    if not name.endswith("_id"):
        return ""
    stem = name[:-3]
    if stem.endswith("y") and stem[-2:-1] not in "aeiou":
        return stem[:-1] + "ies"
    if stem.endswith(("s", "x", "z", "ch", "sh")):
        return stem + "es"
    return stem + "s"


def parse_columns(body):
    """Column operations in one Schema closure, in order.

    Each entry is {"op": "add"|"drop"|"rename", ...}; an add carries
    name, type and the modifier flags.
    """
    ops = []
    for stmt in _statements(body):
        if _DROP_SOFT.search(stmt):
            ops.append({"op": "drop", "name": "deleted_at"})
            continue
        if _DROP_TS.search(stmt):
            ops.append({"op": "drop", "name": "created_at"})
            ops.append({"op": "drop", "name": "updated_at"})
            continue
        d = _DROP.search(stmt)
        if d:
            for name in _QUOTED.findall(d.group("body")):
                ops.append({"op": "drop", "name": name})
            continue
        r = _RENAME.search(stmt)
        if r:
            ops.append({"op": "rename", "name": r.group("old"), "to": r.group("new")})
            continue
        n = _NOARG.search(stmt)
        if n:
            for name, kind, flags in _NOARG_COLUMNS[n.group("type")]:
                entry = {"op": "add", "name": name, "type": kind}
                entry.update(flags)
                entry.update(_modifiers(stmt))
                ops.append(entry)
            continue
        m = _COLUMN.search(stmt)
        if not m:
            continue
        kind, name = m.group("type"), m.group("name")
        head, chained = _split_head(m.group("rest"))
        if kind in ("morphs", "nullableMorphs", "uuidMorphs", "nullableUuidMorphs"):
            id_type = "uuid" if "uuid" in kind.lower() else "bigint unsigned"
            nullable = kind.startswith("nullable")
            for suffix, t in ((("_id"), id_type), (("_type"), "string")):
                entry = {"op": "add", "name": name + suffix, "type": t, "index": True}
                if nullable:
                    entry["nullable"] = True
                ops.append(entry)
            continue
        entry = {"op": "add", "name": name, "type": _render_type(kind, head)}
        entry.update(_modifiers(chained))
        if kind.startswith("foreign") and "fk" not in entry:
            entry["fk"] = ""
        if entry.get("fk") == "":
            guessed = _guess_fk(name)
            if guessed:
                entry["fk"] = guessed
        ops.append(entry)
    return ops


_SKIP_DIRS = {"vendor", "node_modules", ".git", "storage", "public", "bootstrap"}


def find_migrations(root, walk=None):
    """Migration files anywhere under the project, ordered by filename.

    Laravel ships them in database/migrations; modular apps keep a set per
    module. Sorting by basename puts them in the order Laravel would run them,
    since the timestamp prefix is the filename.
    """
    if walk is None:
        walk = os.walk
    hits = []
    for dirpath, dirs, files in walk(root):
        # prune in place so os.walk never descends into vendor at all
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        parts = dirpath.split(os.sep)
        if _SKIP_DIRS.intersection(parts):
            continue
        if "migrations" not in [p.lower() for p in parts]:
            continue
        for name in files:
            if name.endswith(".php"):
                hits.append(os.path.join(dirpath, name))
    hits.sort(key=lambda p: (os.path.basename(p), p))
    return hits


def table_columns(root, table, walk=None, read=None, files=None):
    """Replay every migration touching `table` and return its columns.

    Later migrations win: a create resets the set, a table() adds, drops or
    renames on top of it.
    """
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    if files is None:
        files = find_migrations(root, walk)

    columns = []

    def index_of(name):
        for i, c in enumerate(columns):
            if c["name"] == name:
                return i
        return -1

    for path in files:
        try:
            src = read(path)
        except OSError:
            continue
        if table not in src:
            continue
        for block in schema_blocks(src):
            if block["table"] != table:
                continue
            if block["op"] == "create":
                columns = []
            for op in parse_columns(block["body"]):
                if op["op"] == "drop":
                    i = index_of(op["name"])
                    if i >= 0:
                        columns.pop(i)
                elif op["op"] == "rename":
                    i = index_of(op["name"])
                    if i >= 0:
                        columns[i]["name"] = op["to"]
                else:
                    entry = {k: v for k, v in op.items() if k != "op"}
                    entry["source"] = os.path.basename(path)
                    i = index_of(entry["name"])
                    if i >= 0:
                        columns[i] = entry
                    else:
                        columns.append(entry)
    return columns


def table_name_for(info):
    """The table a model summary points at — explicit $table, else the plural."""
    if info.get("table"):
        return info["table"]
    cls = info.get("class")
    if not cls:
        return ""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cls).lower()
    if snake.endswith("y") and snake[-2:-1] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


# ─── Form request validation rules ───────────────────────────────────────────

_RULES_FN = re.compile(r"function\s+rules\s*\([^)]*\)")
_CLASS_NAME = re.compile(r"\b(?:final\s+|abstract\s+|readonly\s+)*(?:class|interface|trait|enum)\s+(\w+)")
_PUBLIC_FN = re.compile(r"public\s+(?:static\s+)?function\s+(\w+)\s*\(")


def _bracket_body(src, at, open_ch="[", close_ch="]"):
    """Text inside the first `open_ch` at or after `at`, to its match."""
    start = src.find(open_ch, at)
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(src)):
        c = src[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return src[start + 1:]


def _split_top(text, sep=","):
    """Split on `sep` at bracket depth 0 and outside quotes.

    A rule like 'exists:companies,id' carries a comma inside the string, so a
    plain split would tear it in half.
    """
    out, buf, depth, quote = [], [], 0, None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return [p for p in out if p]


def _array_pairs(body):
    """Top-level `'key' => value` pairs of a PHP array literal, in order."""
    pairs = []
    depth = 0
    key = None
    buf = []
    i = 0
    while i < len(body):
        c = body[i]
        if c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        if depth == 0 and c == "," :
            if key is not None:
                pairs.append((key, "".join(buf).strip()))
            key, buf = None, []
            i += 1
            continue
        if depth == 0 and c == "=" and body[i:i + 2] == "=>":
            k = _QUOTED.findall("".join(buf))
            key = k[-1] if k else None
            buf = []
            i += 2
            continue
        buf.append(c)
        i += 1
    if key is not None:
        pairs.append((key, "".join(buf).strip()))
    return pairs


def request_rules(path, read=None, src=None):
    """Validation rules a FormRequest declares, as {field: rule text}.

    The migrations say what the table holds; the rules say what a request is
    allowed to put there. Both are needed before changing a field.
    """
    if src is None:
        if read is None:
            def read(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    return f.read()
        try:
            src = read(path)
        except OSError:
            return {}
    m = _RULES_FN.search(src)
    if not m:
        return {}
    body = _block_body(src, m.end())
    at = body.find("return")
    if at < 0:
        return {}
    out = {}
    for key, value in _array_pairs(_bracket_body(body, at)):
        text = " ".join(value.split())
        if text.startswith("[") and text.endswith("]"):
            text = "|".join(p.strip("'\"") for p in _split_top(text[1:-1]))
        out[key] = text.strip("'\"")
    return out


# ─── Module summaries (the vertical slice, not the file) ─────────────────────
#
# A DDD/modular Laravel app is read feature-first: touching "Brand" means the
# model, its actions, its requests, its routes and its migrations together.

_LAYERS = (
    ("models", ("Models", "Model", "Entities")),
    ("controllers", ("Controllers", "Controller")),
    ("requests", ("Requests", "Request")),
    ("resources", ("Resources", "Resource", "Transformers")),
    ("actions", ("Actions", "Action", "UseCases")),
    ("dto", ("DTO", "DTOs", "Data", "ValueObjects")),
    ("services", ("Services", "Service")),
    ("repositories", ("Repositories", "Repository")),
    ("policies", ("Policies", "Policy")),
    ("observers", ("Observers", "Observer")),
    ("jobs", ("Jobs", "Job")),
    ("events", ("Events", "Event")),
    ("listeners", ("Listeners", "Listener")),
    ("commands", ("Commands", "Console")),
    ("enums", ("Enums", "Enum")),
    ("exceptions", ("Exceptions", "Exception")),
    ("providers", ("Providers", "Provider")),
    ("migrations", ("Migrations",)),
    ("factories", ("Factories",)),
    ("seeders", ("Seeders", "Seeds")),
    ("routes", ("Routes", "routes")),
    ("views", ("Views", "views", "resources")),
    ("tests", ("Tests", "tests")),
)


_MODULE_PARENTS = ("modules", "module", "domains")
# tests/Feature/Modules and database/factories/Modules mirror the module names
# but hold no source — a module lookup that lands there reports an empty slice.
_MODULE_DECOYS = ("tests", "test", "database", "docs", "factories", "stubs")


def _module_roots(root, walk):
    """Directories that hold modules, best source root first."""
    roots = []
    for dirpath, dirs, _files in walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        parts = dirpath.split(os.sep)
        if _SKIP_DIRS.intersection(parts):
            continue
        if parts and parts[-1].lower() in _MODULE_PARENTS:
            lowered = [p.lower() for p in parts]
            decoy = any(d in lowered for d in _MODULE_DECOYS)
            roots.append((decoy, len(parts), dirpath, sorted(dirs)))
    roots.sort()
    return roots


def find_module(root, name, walk=None):
    """Directory of a module by name, whatever layout the project uses."""
    if walk is None:
        walk = os.walk
    wanted = name.lower()
    for _decoy, _depth, dirpath, dirs in _module_roots(root, walk):
        for d in dirs:
            if d.lower() == wanted:
                return os.path.join(dirpath, d)
    return None


def list_modules(root, walk=None):
    """Every module name in the project, from the real source root only."""
    if walk is None:
        walk = os.walk
    roots = _module_roots(root, walk)
    if not roots:
        return []
    return list(roots[0][3])


def _layer_of(rel_path):
    """Which layer a file inside a module belongs to."""
    parts = [p for p in rel_path.split(os.sep)[:-1]]
    for layer, names in _LAYERS:
        for p in parts:
            if p in names:
                return layer
    return "other"


def module_summary(root, name, walk=None, read=None, path=None):
    """What a module contains, grouped by layer.

    Controllers list their public methods, requests their validation rules and
    models their table — enough for the model to place a change without
    reading twenty files first.
    """
    if read is None:
        def read(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
    if walk is None:
        walk = os.walk
    if path is None:
        path = find_module(root, name, walk)
    if not path:
        return {}

    out = {"name": name, "path": path, "layers": {}}
    for dirpath, dirs, files in walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in sorted(files):
            if not fname.endswith(".php"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, path)
            layer = _layer_of(rel)
            entry = {"file": rel}
            if layer in ("migrations", "routes", "views", "seeders", "factories"):
                out["layers"].setdefault(layer, []).append(entry)
                continue
            try:
                src = read(full)
            except OSError:
                out["layers"].setdefault(layer, []).append(entry)
                continue
            cls = _CLASS_NAME.search(src)
            if cls:
                entry["class"] = cls.group(1)
            if layer == "controllers":
                methods = [m for m in _PUBLIC_FN.findall(src)
                           if m not in ("__construct", "__invoke", "authorize", "rules")]
                if "__invoke" in _PUBLIC_FN.findall(src):
                    methods.insert(0, "__invoke")
                if methods:
                    entry["methods"] = methods
            elif layer == "requests":
                rules = request_rules(full, src=src)
                if rules:
                    entry["rules"] = rules
            elif layer == "models":
                info = model_summary(full, read=lambda _p, s=src: s)
                if info.get("table") or info.get("class"):
                    entry["table"] = table_name_for(info)
                if info.get("relations"):
                    entry["relations"] = info["relations"]
            out["layers"].setdefault(layer, []).append(entry)
    return out
