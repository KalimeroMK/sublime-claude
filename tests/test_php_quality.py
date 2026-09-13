"""Tests for the PHP quality bridge — parsing only, no process is spawned."""
import json
import os
import unittest

from tests.plugin_pkg import load

q = load("php_quality")


def runner_for(code=0, out="", err=""):
    calls = []

    def run(root, argv, timeout):
        calls.append({"root": root, "argv": argv, "timeout": timeout})
        return code, out, err
    run.calls = calls
    return run


# shape captured from a real `pint --test --format=json` run
PINT_JSON = json.dumps({
    "tool": "pint",
    "result": "fail",
    "files": [
        {"path": "app/Models/Brand.php", "fixers": ["no_unused_imports"]},
        {"path": "app/Actions/Create.php", "fixers": []},
    ],
})

PINT_JSON_LEGACY = json.dumps({
    "files": [{"name": "app/Models/Brand.php", "appliedFixers": ["braces_position"]}],
})

PHPSTAN_JSON = json.dumps({
    "totals": {"errors": 0, "file_errors": 2},
    "files": {
        "/p/app/Models/Brand.php": {"errors": 2, "messages": [
            {"message": "Access to an undefined property Brand::$slug.",
             "line": 22, "identifier": "property.notFound"},
            {"message": "Method returns int but should return string.",
             "line": 30, "identifier": "return.type"},
        ]},
    },
    "errors": ["Config file not found"],
})


class ToolPathTest(unittest.TestCase):
    def test_prefers_the_projects_own_binary(self):
        self.assertEqual(q.tool_path("/p", "pint", exists=lambda p: "vendor" in p),
                         os.path.join("/p", "vendor", "bin", "pint"))

    def test_falls_back_to_path(self):
        self.assertEqual(q.tool_path("/p", "pint", exists=lambda _p: False), "pint")


class ParsePintTest(unittest.TestCase):
    def test_lists_every_file(self):
        self.assertEqual(len(q.parse_pint(PINT_JSON)), 2)

    def test_keeps_the_applied_fixers(self):
        self.assertEqual(q.parse_pint(PINT_JSON)[0]["fixers"], ["no_unused_imports"])

    def test_legacy_key_names_still_parse(self):
        got = q.parse_pint(PINT_JSON_LEGACY)
        self.assertEqual(got[0]["file"], "app/Models/Brand.php")
        self.assertEqual(got[0]["fixers"], ["braces_position"])

    def test_non_json_is_not_an_exception(self):
        self.assertEqual(q.parse_pint("Laravel Pint\n  ......"), [])

    def test_empty(self):
        self.assertEqual(q.parse_pint(""), [])


class PintTest(unittest.TestCase):
    def test_test_mode_does_not_rewrite(self):
        """Default must never modify the user's files — only report."""
        r = runner_for(out=PINT_JSON)
        q.pint("/p", ["app/X.php"], runner=r, exists=lambda _p: False)
        self.assertIn("--test", r.calls[0]["argv"])

    def test_fix_mode_drops_test(self):
        r = runner_for(out=PINT_JSON)
        q.pint("/p", None, runner=r, exists=lambda _p: False, fix=True)
        self.assertNotIn("--test", r.calls[0]["argv"])

    def test_paths_are_relative_to_the_root(self):
        r = runner_for(out=PINT_JSON)
        q.pint("/p", ["/p/app/X.php"], runner=r, exists=lambda _p: False)
        self.assertIn(os.path.join("app", "X.php"), r.calls[0]["argv"])

    def test_relative_paths_are_passed_through_unchanged(self):
        """relpath() on an already-relative path resolves it against the CWD and
        produces a ../../.. chain that Pint cannot open."""
        r = runner_for(out=PINT_JSON)
        q.pint("/p", ["app/X.php"], runner=r, exists=lambda _p: False)
        self.assertIn("app/X.php", r.calls[0]["argv"])

    def test_a_crashed_run_is_an_error_not_a_clean_result(self):
        found, err = q.pint("/p", runner=runner_for(code=2, out="Path not found"),
                            exists=lambda _p: False)
        self.assertIsNone(found)
        self.assertIn("Path not found", err)

    def test_missing_binary_is_reported_not_raised(self):
        found, err = q.pint("/p", runner=runner_for(code=127, err="no pint"),
                            exists=lambda _p: False)
        self.assertIsNone(found)
        self.assertEqual(err, "no pint")


class ParsePhpstanTest(unittest.TestCase):
    def test_flattens_messages_across_files(self):
        self.assertEqual(len([e for e in q.parse_phpstan(PHPSTAN_JSON) if e["line"]]), 2)

    def test_keeps_line_and_identifier(self):
        first = q.parse_phpstan(PHPSTAN_JSON)[0]
        self.assertEqual(first["line"], 22)
        self.assertEqual(first["identifier"], "property.notFound")

    def test_top_level_errors_are_included(self):
        msgs = [e["message"] for e in q.parse_phpstan(PHPSTAN_JSON)]
        self.assertIn("Config file not found", msgs)

    def test_non_json_is_not_an_exception(self):
        self.assertEqual(q.parse_phpstan("Note: Using configuration file"), [])


class BannerTest(unittest.TestCase):
    """Real tools wrap their JSON in notes and warnings; json.loads on the whole
    stream fails and every finding is silently lost."""

    BANNERED = ('Note: Using configuration file /p/phpstan.neon.\n'
                + PHPSTAN_JSON
                + '\n  Result is incomplete because of severe errors.')

    def test_phpstan_json_is_found_between_banners(self):
        self.assertEqual(len(q.parse_phpstan(self.BANNERED)), 3)

    def test_pint_json_is_found_after_a_banner(self):
        out = 'Laravel Pint\n' + PINT_JSON
        self.assertEqual(len(q.parse_pint(out)), 2)

    def test_object_payload_is_not_mistaken_for_its_inner_array(self):
        payload = q._json_payload('{"files": [1, 2]}')
        self.assertIsInstance(payload, dict)


class PhpstanTest(unittest.TestCase):
    def test_exit_one_still_yields_findings(self):
        """PHPStan exits 1 when it finds errors — that is a result, not a
        failure, and treating it as one would silently drop every finding."""
        found, err = q.phpstan("/p", runner=runner_for(code=1, out=PHPSTAN_JSON),
                               exists=lambda _p: False)
        self.assertEqual(err, "")
        self.assertEqual(len(found), 3)

    def test_level_is_passed_through(self):
        r = runner_for(out=PHPSTAN_JSON)
        q.phpstan("/p", None, runner=r, exists=lambda _p: False, level=8)
        self.assertIn("--level", r.calls[0]["argv"])
        self.assertIn("8", r.calls[0]["argv"])

    def test_memory_limit_is_passed_by_default(self):
        """128M is the stock PHP limit and PHPStan crashes on a real project
        with it, reporting zero errors while actually having analysed nothing."""
        r = runner_for(out=PHPSTAN_JSON)
        q.phpstan("/p", None, runner=r, exists=lambda _p: False)
        self.assertIn("--memory-limit", r.calls[0]["argv"])
        self.assertIn("512M", r.calls[0]["argv"])

    def test_memory_limit_can_be_turned_off(self):
        r = runner_for(out=PHPSTAN_JSON)
        q.phpstan("/p", None, runner=r, exists=lambda _p: False, memory_limit=None)
        self.assertNotIn("--memory-limit", r.calls[0]["argv"])

    def test_crash_reported_in_the_errors_array_is_surfaced(self):
        crash = json.dumps({"totals": {"errors": 1}, "files": {},
                            "errors": ["PHPStan process crashed: memory limit"]})
        found, _err = q.phpstan("/p", runner=runner_for(code=1, out=crash),
                                exists=lambda _p: False)
        self.assertIn("memory limit", found[0]["message"])

    def test_missing_binary_is_reported(self):
        found, err = q.phpstan("/p", runner=runner_for(code=127, err="no phpstan"),
                               exists=lambda _p: False)
        self.assertIsNone(found)
        self.assertEqual(err, "no phpstan")


class CheckTest(unittest.TestCase):
    def _exists(self, *names):
        return lambda p: any(p.endswith(n) for n in names)

    def test_skips_tools_the_project_does_not_configure(self):
        result = q.check("/p", runner=runner_for(), exists=lambda _p: False)
        self.assertEqual(len(result["skipped"]), 2)

    def test_runs_pint_when_pint_json_exists(self):
        result = q.check("/p", runner=runner_for(out=PINT_JSON),
                         exists=self._exists("pint.json"))
        self.assertEqual(len(result["pint"]), 2)

    def test_runs_phpstan_when_neon_exists(self):
        result = q.check("/p", runner=runner_for(out=PHPSTAN_JSON),
                         exists=self._exists("phpstan.neon"))
        self.assertEqual(len(result["phpstan"]), 3)

    def test_a_tool_can_be_turned_off(self):
        result = q.check("/p", settings={"php_phpstan": False},
                         runner=runner_for(out=PINT_JSON),
                         exists=self._exists("pint.json", "phpstan.neon"))
        self.assertEqual(result["phpstan"], [])
        self.assertEqual(len(result["pint"]), 2)


class FormatReportTest(unittest.TestCase):
    def test_clean_run(self):
        self.assertIn("clean", q.format_report({"pint": [], "phpstan": []}))

    def test_skipped_tools_are_named(self):
        out = q.format_report({"skipped": ["pint (no pint.json)"]})
        self.assertIn("pint (no pint.json)", out)

    def test_pint_files_are_listed(self):
        out = q.format_report({"pint": q.parse_pint(PINT_JSON)})
        self.assertIn("app/Models/Brand.php", out)
        self.assertIn("no_unused_imports", out)

    def test_phpstan_errors_carry_file_and_line(self):
        out = q.format_report({"phpstan": q.parse_phpstan(PHPSTAN_JSON)}, root="/p")
        self.assertIn(os.path.join("app", "Models", "Brand.php") + ":22", out)
        self.assertIn("undefined property", out)

    def test_long_lists_are_truncated(self):
        many = [{"file": "a.php", "line": i, "message": "x", "identifier": ""}
                for i in range(60)]
        out = q.format_report({"phpstan": many}, limit=10)
        self.assertIn("and 50 more", out)


if __name__ == "__main__":
    unittest.main()
