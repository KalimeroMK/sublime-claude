"""Tests for the artisan bridge — parsing only, no process is ever spawned."""
import json
import os
import unittest

from tests.plugin_pkg import load

art = load("laravel_artisan")


def runner_for(code=0, out="", err=""):
    """A stand-in for subprocess that records what it was asked to run."""
    calls = []

    def run(root, argv, timeout):
        calls.append({"root": root, "argv": argv, "timeout": timeout})
        return code, out, err
    run.calls = calls
    return run


ROUTE_JSON = json.dumps([
    {"method": "GET|HEAD", "uri": "api/brands", "name": "brands.index",
     "action": "App\\Http\\Controllers\\BrandController@index",
     "middleware": ["api", "App\\Http\\Middleware\\TenantMiddleware"],
     "path": "app/Modules/Brand/Infrastructure/Routes/api.php:42"},
    {"method": "POST", "uri": "api/brands", "name": None,
     "action": "Closure", "middleware": "api"},
])

TABLE_JSON = json.dumps({
    "table": "brands",
    "columns": [
        {"name": "id", "type": "bigint unsigned", "nullable": False, "default": None},
        {"name": "name", "type": "varchar(100)", "nullable": False, "default": None},
        {"name": "note", "type": "text", "nullable": True, "default": "x"},
    ],
})


class AvailabilityTest(unittest.TestCase):
    def test_artisan_file_means_available(self):
        self.assertTrue(art.artisan_available("/p", exists=lambda p: p.endswith("artisan")))

    def test_missing_artisan(self):
        self.assertFalse(art.artisan_available("/p", exists=lambda _p: False))

    def test_no_root(self):
        self.assertFalse(art.artisan_available(None, exists=lambda _p: True))


class PathTest(unittest.TestCase):
    """Sublime launched from the Dock gets /usr/bin:/bin and nothing else, so a
    Homebrew php is invisible — the same command that works in a terminal fails
    with "not found"."""

    def test_homebrew_bin_is_added_when_present(self):
        env = art._env_with_path()
        if os.path.isdir("/opt/homebrew/bin"):
            self.assertIn("/opt/homebrew/bin", env["PATH"].split(os.pathsep))

    def test_existing_path_entries_are_kept(self):
        for part in os.environ.get("PATH", "").split(os.pathsep):
            if part:
                self.assertIn(part, art._env_with_path()["PATH"])

    def test_no_duplicate_entries(self):
        parts = [p for p in art._env_with_path()["PATH"].split(os.pathsep) if p]
        self.assertEqual(len(parts), len(set(parts)))


class RunTest(unittest.TestCase):
    def test_command_setting_is_split_into_argv(self):
        """A dockerised app sets the command to `docker compose exec -T app php
        artisan`; passing that as one string would never execute."""
        r = runner_for(out="ok")
        art.run("/p", ["about"], command="docker compose exec -T app php artisan",
                runner=r)
        self.assertEqual(r.calls[0]["argv"],
                         ["docker", "compose", "exec", "-T", "app", "php",
                          "artisan", "about"])

    def test_runs_in_the_project_root(self):
        r = runner_for()
        art.run("/p", ["about"], runner=r)
        self.assertEqual(r.calls[0]["root"], "/p")

    def test_non_zero_exit_is_not_ok(self):
        ok, _out, err = art.run("/p", ["about"], runner=runner_for(code=1, err="boom"))
        self.assertFalse(ok)
        self.assertEqual(err, "boom")


class JsonPayloadTest(unittest.TestCase):
    def test_ignores_a_banner_before_the_json(self):
        """Deprecation notices and Xdebug banners routinely precede the payload."""
        self.assertEqual(art._json_payload('PHP Warning: x\n[{"a": 1}]'), [{"a": 1}])

    def test_object_payload(self):
        self.assertEqual(art._json_payload('{"a": 1}'), {"a": 1})

    def test_object_wins_when_it_opens_first(self):
        """db:table returns an object whose "columns" value is an array — taking
        the first "[" would return that array and lose the wrapper."""
        got = art._json_payload('{"table": "b", "columns": [{"name": "id"}]}')
        self.assertIsInstance(got, dict)
        self.assertEqual(got["table"], "b")

    def test_garbage_yields_none(self):
        self.assertIsNone(art._json_payload("not json at all"))

    def test_empty_yields_none(self):
        self.assertIsNone(art._json_payload("   "))


class RouteListTest(unittest.TestCase):
    def _routes(self):
        routes, _err = art.route_list("/p", runner=runner_for(out=ROUTE_JSON))
        return routes

    def test_parses_every_route(self):
        self.assertEqual(len(self._routes()), 2)

    def test_uri_gets_a_leading_slash(self):
        self.assertEqual(self._routes()[0]["uri"], "/api/brands")

    def test_action_is_shortened_to_class_and_method(self):
        self.assertEqual(self._routes()[0]["action"], "BrandController::index")

    def test_closure_action_is_blank_not_the_word_closure(self):
        self.assertEqual(self._routes()[1]["action"], "")

    def test_null_name_becomes_empty(self):
        self.assertEqual(self._routes()[1]["name"], "")

    def test_string_middleware_is_wrapped_in_a_list(self):
        self.assertEqual(self._routes()[1]["middleware"], ["api"])

    def test_declaration_path_gives_file_and_line(self):
        r = self._routes()[0]
        self.assertEqual((r["file"], r["line"]), ("api.php", "42"))

    def test_declaration_path_gives_the_module(self):
        self.assertEqual(self._routes()[0]["module"], "Brand")

    def test_missing_path_falls_back(self):
        r = self._routes()[1]
        self.assertEqual(r["file"], "artisan")
        self.assertEqual(r["module"], "")

    def test_middleware_class_is_shortened(self):
        """route:list prints fully-qualified middleware; the FQN is noise in a
        prompt and pushes the useful part off the line."""
        self.assertEqual(self._routes()[0]["middleware"], ["api", "TenantMiddleware"])

    def test_entries_are_marked_as_coming_from_artisan(self):
        self.assertEqual(self._routes()[0]["source"], "artisan")

    def test_failure_returns_the_error_not_an_exception(self):
        routes, err = art.route_list("/p", runner=runner_for(code=1, err="no app"))
        self.assertIsNone(routes)
        self.assertEqual(err, "no app")

    def test_non_json_output_is_reported(self):
        routes, err = art.route_list("/p", runner=runner_for(out="hello"))
        self.assertIsNone(routes)
        self.assertIn("no JSON", err)


class ModuleFromPathTest(unittest.TestCase):
    def test_segment_after_modules(self):
        self.assertEqual(
            art._module_from_path("app/Modules/Brand/Infrastructure/Routes/api.php"),
            "Brand")

    def test_windows_separators(self):
        self.assertEqual(
            art._module_from_path("app\\Modules\\Brand\\Routes\\api.php"), "Brand")

    def test_plain_layout(self):
        self.assertEqual(art._module_from_path("routes/web.php"), "")

    def test_empty(self):
        self.assertEqual(art._module_from_path(""), "")


class DbTableTest(unittest.TestCase):
    def _cols(self):
        cols, _err = art.db_table("/p", "brands", runner=runner_for(out=TABLE_JSON))
        return {c["name"]: c for c in cols}

    def test_reads_every_column(self):
        self.assertEqual(sorted(self._cols()), ["id", "name", "note"])

    def test_type_is_the_live_database_type(self):
        self.assertEqual(self._cols()["name"]["type"], "varchar(100)")

    def test_nullable_flag_only_when_true(self):
        self.assertTrue(self._cols()["note"]["nullable"])
        self.assertNotIn("nullable", self._cols()["id"])

    def test_null_default_is_not_recorded(self):
        self.assertNotIn("default", self._cols()["id"])
        self.assertEqual(self._cols()["note"]["default"], "x")

    def test_failure_is_reported(self):
        cols, err = art.db_table("/p", "x", runner=runner_for(code=1, err="no db"))
        self.assertIsNone(cols)
        self.assertEqual(err, "no db")


class ModelShowTest(unittest.TestCase):
    def test_payload_is_returned(self):
        payload, err = art.model_show("/p", "Brand",
                                      runner=runner_for(out='{"class": "App\\\\Models\\\\Brand"}'))
        self.assertEqual(payload["class"], "App\\Models\\Brand")
        self.assertEqual(err, "")

    def test_failure_is_reported(self):
        payload, err = art.model_show("/p", "Nope", runner=runner_for(code=1, err="not found"))
        self.assertIsNone(payload)
        self.assertEqual(err, "not found")


class AboutTest(unittest.TestCase):
    def test_payload_is_returned(self):
        payload, _err = art.about("/p", runner=runner_for(out='{"Environment": {}}'))
        self.assertIn("Environment", payload)

    def test_failure_is_reported(self):
        payload, err = art.about("/p", runner=runner_for(code=127, err="php: not found"))
        self.assertIsNone(payload)
        self.assertEqual(err, "php: not found")


if __name__ == "__main__":
    unittest.main()
