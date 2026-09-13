"""Run the project's own PHP quality tools and report what they say.

The model writes PHP and never learns that Pint would reformat it or that
PHPStan rejects it at the configured level. LSP diagnostics come from
intelephense and do not know about Larastan rules, so this is a separate
signal. Parsing is split from execution so it is testable without a process.
"""
import json
import os
import shlex
import subprocess

DEFAULT_TIMEOUT = 120


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
        return 124, "", "timed out after {}s".format(timeout)
    except OSError as e:
        return 127, "", str(e)


def tool_path(root, name, exists=os.path.exists):
    """The project's own binary, else the bare name to try on PATH."""
    local = os.path.join(root, "vendor", "bin", name)
    return local if exists(local) else name


def has_config(root, names, exists=os.path.exists):
    for n in names:
        if exists(os.path.join(root, n)):
            return os.path.join(root, n)
    return None


def _rel(root, path):
    """Path as the tool should see it — relative paths are already correct.

    os.path.relpath resolves a relative input against the *current* directory,
    which turns "app/X.php" into a ../../.. chain the tool cannot open.
    """
    if not os.path.isabs(path):
        return path
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _json_payload(text):
    """The JSON body of a tool's output, ignoring banners around it.

    PHPStan prints "Note: Using configuration file ..." before the JSON and a
    warning block after it, so json.loads on the whole stream always fails.
    (laravel_artisan has the same helper; these two modules stay independent so
    either can be missing without breaking the other.)
    """
    text = (text or "").strip()
    if not text:
        return None
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


def parse_pint(out):
    """Files Pint would change, from its JSON report."""
    payload = _json_payload(out)
    if not isinstance(payload, dict):
        return []
    files = []
    for f in payload.get("files", []):
        if not isinstance(f, dict):
            if f:
                files.append({"file": f, "fixers": []})
            continue
        # real Pint emits {"path": ..., "fixers": [...]}; older/other builds
        # have been seen with name/appliedFixers, so accept both
        name = f.get("path") or f.get("name")
        if name:
            files.append({"file": name,
                          "fixers": f.get("fixers") or f.get("appliedFixers") or []})
    return files


def pint(root, paths=None, command=None, timeout=DEFAULT_TIMEOUT, runner=None,
         exists=os.path.exists, fix=False):
    """What Pint would reformat. `fix=True` actually rewrites the files."""
    runner = runner or _default_run
    argv = shlex.split(command) if command else [tool_path(root, "pint", exists)]
    if not fix:
        argv.append("--test")
    argv += ["--format=json"]
    argv += [_rel(root, p) for p in (paths or [])]
    code, out, err = runner(root, argv, timeout)
    if code == 127:
        return None, (err or "pint not found").strip()
    found = parse_pint(out)
    # a failed run that printed no JSON must not read as "nothing to fix"
    if not found and code not in (0, 1):
        return None, (err or out or "pint failed").strip()
    return found, ""


def parse_phpstan(out):
    """Errors from PHPStan's JSON output, flattened to one list."""
    payload = _json_payload(out)
    if not isinstance(payload, dict):
        return []
    errors = []
    files = payload.get("files") or {}
    for path, body in files.items():
        for m in body.get("messages", []):
            errors.append({"file": path, "line": m.get("line"),
                           "message": m.get("message", ""),
                           "identifier": m.get("identifier", "")})
    for m in payload.get("errors", []) or []:
        if isinstance(m, str):
            errors.append({"file": "", "line": None, "message": m, "identifier": ""})
    return errors


def phpstan(root, paths=None, command=None, timeout=DEFAULT_TIMEOUT, runner=None,
            exists=os.path.exists, level=None, memory_limit="512M"):
    """PHPStan/Larastan findings for the given paths."""
    runner = runner or _default_run
    argv = shlex.split(command) if command else [tool_path(root, "phpstan", exists)]
    argv += ["analyse", "--error-format=json", "--no-progress"]
    if memory_limit:
        argv += ["--memory-limit", str(memory_limit)]
    if level is not None:
        argv += ["--level", str(level)]
    argv += [_rel(root, p) for p in (paths or [])]
    code, out, err = runner(root, argv, timeout)
    if code == 127:
        return None, (err or "phpstan not found").strip()
    parsed = parse_phpstan(out)
    if not parsed and code not in (0, 1):
        return None, (err or out or "phpstan failed").strip()
    return parsed, ""


def check(root, paths=None, settings=None, runner=None, exists=os.path.exists):
    """Run whichever tools the project actually configures.

    Returns {"pint": [...], "phpstan": [...], "skipped": [...], "errors": [...]}.
    """
    settings = settings or {}
    result = {"pint": [], "phpstan": [], "skipped": [], "errors": []}

    if settings.get("php_pint", True):
        if has_config(root, ("pint.json", "pint.json.dist"), exists) or \
                exists(os.path.join(root, "vendor", "bin", "pint")):
            found, err = pint(root, paths, settings.get("php_pint_command"),
                              settings.get("php_timeout", DEFAULT_TIMEOUT),
                              runner, exists)
            if found is None:
                result["errors"].append("pint: " + err)
            else:
                result["pint"] = found
        else:
            result["skipped"].append("pint (no pint.json)")

    if settings.get("php_phpstan", True):
        if has_config(root, ("phpstan.neon", "phpstan.neon.dist", "phpstan.dist.neon"), exists):
            found, err = phpstan(root, paths, settings.get("php_phpstan_command"),
                                 settings.get("php_timeout", DEFAULT_TIMEOUT),
                                 runner, exists, settings.get("php_phpstan_level"),
                                 settings.get("php_phpstan_memory_limit", "512M"))
            if found is None:
                result["errors"].append("phpstan: " + err)
            else:
                result["phpstan"] = found
        else:
            result["skipped"].append("phpstan (no phpstan.neon)")

    return result


def format_report(result, root="", limit=40):
    """Render a check() result for the prompt."""
    lines = []
    pint_files = result.get("pint") or []
    if pint_files:
        lines.append("[pint] {} file(s) need formatting:".format(len(pint_files)))
        for f in pint_files[:limit]:
            fixers = ", ".join(f.get("fixers") or [])
            lines.append("  {}{}".format(_rel(root, f["file"]) if root else f["file"],
                                         " — " + fixers if fixers else ""))
    errors = result.get("phpstan") or []
    if errors:
        lines.append("[phpstan] {} error(s):".format(len(errors)))
        for e in errors[:limit]:
            where = _rel(root, e["file"]) if root and e.get("file") else e.get("file", "")
            loc = "{}:{}".format(where, e["line"]) if e.get("line") else where
            ident = " [{}]".format(e["identifier"]) if e.get("identifier") else ""
            lines.append("  {} {}{}".format(loc, e["message"], ident))
        if len(errors) > limit:
            lines.append("  ... and {} more".format(len(errors) - limit))
    for note in result.get("errors") or []:
        lines.append("[tool error] " + note)
    if not lines:
        skipped = result.get("skipped") or []
        return "[php quality] clean" + (" (skipped: {})".format(", ".join(skipped))
                                        if skipped else "")
    return "\n".join(lines)
