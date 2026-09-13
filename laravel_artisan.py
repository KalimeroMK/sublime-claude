"""Ask artisan when the app can boot; fall back to the source parser when not.

framework_nav reads the project source and works on an app that cannot boot.
That is the right default, but it cannot resolve what only the framework knows:
route model binding, middleware groups, macros, package routes, the real
database schema. When `php artisan` runs, its answer is authoritative.

Everything takes an injectable `run` so the parsing is testable without
spawning a process.
"""
import json
import os
import re
import shlex
import subprocess

DEFAULT_TIMEOUT = 20


def artisan_available(root, exists=os.path.exists):
    return bool(root) and exists(os.path.join(root, "artisan"))


# A GUI app launched from the Dock inherits a minimal PATH (/usr/bin:/bin:...),
# so `php` installed by Homebrew or asdf is simply not found. Same binary, same
# machine, works from a terminal — a confusing failure worth pre-empting.
_EXTRA_PATH = (
    "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
    "/usr/local/sbin", os.path.expanduser("~/.composer/vendor/bin"),
    os.path.expanduser("~/.config/composer/vendor/bin"),
)


def _env_with_path():
    env = dict(os.environ)
    parts = env.get("PATH", "").split(os.pathsep)
    for extra in _EXTRA_PATH:
        if extra and extra not in parts and os.path.isdir(extra):
            parts.append(extra)
    env["PATH"] = os.pathsep.join(p for p in parts if p)
    return env


def _default_run(root, argv, timeout):
    try:
        p = subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True,
                             env=_env_with_path())
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        p.kill()
        return 124, "", "artisan timed out after {}s".format(timeout)
    except OSError as e:
        return 127, "", str(e)


def run(root, args, command="php artisan", timeout=DEFAULT_TIMEOUT, runner=None):
    """Run an artisan subcommand. Returns (ok, stdout, stderr).

    `command` is a setting so a dockerised app can use
    "docker compose exec -T app php artisan".
    """
    runner = runner or _default_run
    argv = shlex.split(command) + list(args)
    code, out, err = runner(root, argv, timeout)
    return code == 0, out, err


def _json_payload(text):
    """The JSON body of an artisan response, ignoring any banner around it."""
    text = (text or "").strip()
    if not text:
        return None
    # whichever bracket opens first wins: picking "[" unconditionally would
    # grab an inner array (db:table's "columns") out of an object payload
    candidates = [(text.find(o), o, c) for o, c in (("[", "]"), ("{", "}"))
                  if text.find(o) >= 0]
    for _pos, opener, closer in sorted(candidates):
        start = text.find(opener)
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


def _clean_action(action):
    """`App\\Http\\Controllers\\BrandController@index` → `BrandController::index`."""
    if not action or action == "Closure":
        return ""
    if "@" in action:
        cls, method = action.rsplit("@", 1)
        return "{}::{}".format(cls.split("\\")[-1], method)
    return action.split("\\")[-1]


def _module_from_path(path):
    """Module a declaration path sits in — the segment after `Modules`."""
    parts = (path or "").replace("\\", "/").split("/")
    for i, p in enumerate(parts):
        if p.lower() in ("modules", "module") and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _short_middleware(name):
    """`App\\Http\\Middleware\\TenantMiddleware` → `TenantMiddleware`."""
    return (name or "").split("\\")[-1]


def route_list(root, command="php artisan", timeout=DEFAULT_TIMEOUT, runner=None):
    """Routes as the framework itself resolves them.

    Shaped like framework_nav.route_summary output so either source can feed
    the same formatter.
    """
    ok, out, err = run(root, ["route:list", "--json"], command, timeout, runner)
    if not ok:
        return None, (err or out or "artisan route:list failed").strip()
    payload = _json_payload(out)
    if not isinstance(payload, list):
        return None, "artisan route:list returned no JSON"
    routes = []
    for r in payload:
        uri = r.get("uri") or ""
        if not uri.startswith("/"):
            uri = "/" + uri
        middleware = r.get("middleware") or []
        if isinstance(middleware, str):
            middleware = [middleware]
        # route:list reports where the route was declared, e.g.
        # "app/Modules/Brand/Infrastructure/Routes/web.php:85"
        where = r.get("path") or ""
        fname, line = "artisan", ""
        if ":" in where:
            head, _sep, tail = where.rpartition(":")
            if tail.isdigit():
                fname, line = os.path.basename(head), tail
            else:
                fname = os.path.basename(where)
        elif where:
            fname = os.path.basename(where)
        entry = {"verb": r.get("method", ""), "uri": uri,
                 "name": r.get("name") or "",
                 "action": _clean_action(r.get("action", "")),
                 "file": fname, "line": line, "prefix": "",
                 "module": _module_from_path(where),
                 "middleware": [_short_middleware(m) for m in middleware],
                 "source": "artisan"}
        routes.append(entry)
    return routes, ""


_COLUMN_ROW = re.compile(r"^\s*(?P<name>\w+)\s+(?P<type>[\w()\s,]+?)\s{2,}", re.M)


def db_table(root, table, command="php artisan", timeout=DEFAULT_TIMEOUT, runner=None):
    """Live column list for a table, straight from the connected database."""
    ok, out, err = run(root, ["db:table", table, "--json"], command, timeout, runner)
    if not ok:
        return None, (err or out or "artisan db:table failed").strip()
    payload = _json_payload(out)
    if not isinstance(payload, dict):
        return None, "artisan db:table returned no JSON"
    cols = []
    for c in payload.get("columns", []):
        entry = {"name": c.get("name", ""), "type": c.get("type", "")}
        if c.get("nullable"):
            entry["nullable"] = True
        if c.get("default") is not None:
            entry["default"] = c["default"]
        cols.append(entry)
    return cols, ""


def model_show(root, model, command="php artisan", timeout=DEFAULT_TIMEOUT, runner=None):
    """Attributes and relations as Eloquent reports them (Laravel 10+)."""
    ok, out, err = run(root, ["model:show", model, "--json"], command, timeout, runner)
    if not ok:
        return None, (err or out or "artisan model:show failed").strip()
    payload = _json_payload(out)
    if not isinstance(payload, dict):
        return None, "artisan model:show returned no JSON"
    return payload, ""


def about(root, command="php artisan", timeout=DEFAULT_TIMEOUT, runner=None):
    """Environment summary — versions, drivers, cache state."""
    ok, out, err = run(root, ["about", "--json"], command, timeout, runner)
    if not ok:
        return None, (err or out or "artisan about failed").strip()
    payload = _json_payload(out)
    if payload is None:
        return None, "artisan about returned no JSON"
    return payload, ""
