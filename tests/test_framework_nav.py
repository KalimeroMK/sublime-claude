"""Tests for framework_nav — pure resolvers, no Sublime, no subprocess."""
import os
import unittest

from tests.plugin_pkg import load

nav = load("framework_nav")


class DetectFrameworkTest(unittest.TestCase):
    def test_artisan_means_laravel(self):
        self.assertEqual(nav.detect_framework("/p", lambda p: p.endswith("artisan")), "laravel")

    def test_yii_console_means_yii2(self):
        self.assertEqual(nav.detect_framework("/p", lambda p: p.endswith("/yii")), "yii2")

    def test_nothing_means_none(self):
        self.assertIsNone(nav.detect_framework("/p", lambda p: False))


class CallAtTest(unittest.TestCase):
    def test_finds_view_call(self):
        src = "return view('emails.layout');"
        self.assertEqual(nav.call_at(src, src.index("emails") + 2), ("view", "emails.layout"))

    def test_finds_config_call(self):
        src = "$x = config('instacom.sends.read_rate_limit_per_minute');"
        self.assertEqual(
            nav.call_at(src, src.index("instacom") + 3),
            ("config", "instacom.sends.read_rate_limit_per_minute"))

    def test_finds_translation_call(self):
        src = "throw ValidationException::withMessages([__('auth.failed')]);"
        self.assertEqual(nav.call_at(src, src.index("auth.failed") + 2), ("__", "auth.failed"))

    def test_ignores_request_route_parameter(self):
        """$request->route('id') reads a route parameter, not a named route.
        Every route(...) in the instacom codebase is this form, so a resolver
        that matched it would navigate nowhere on every hit."""
        src = "$id = $request->route('importId');"
        self.assertIsNone(nav.call_at(src, src.index("importId") + 2))

    def test_ignores_static_call_with_same_name(self):
        src = "Foo::config('a.b');"
        self.assertIsNone(nav.call_at(src, src.index("a.b") + 1))

    def test_finds_bare_route_helper(self):
        src = "return redirect(route('api-keys.rotate'));"
        self.assertEqual(nav.call_at(src, src.index("api-keys") + 2),
                         ("route", "api-keys.rotate"))

    def test_finds_blade_extends(self):
        src = "@extends('emails.layout')"
        self.assertEqual(nav.call_at(src, src.index("emails") + 2), ("extends", "emails.layout"))

    def test_finds_blade_include(self):
        src = "    @include('emails.button', ['x' => 1])"
        self.assertEqual(nav.call_at(src, src.index("emails") + 2), ("include", "emails.button"))

    def test_point_outside_any_argument(self):
        src = "$x = config('a.b'); $y = 1;"
        self.assertIsNone(nav.call_at(src, len(src) - 2))

    def test_double_quoted_argument(self):
        src = 'return view("emails.layout");'
        self.assertEqual(nav.call_at(src, src.index("emails") + 2), ("view", "emails.layout"))


class FakeTree:
    """In-memory project so resolution is tested without touching disk."""

    def __init__(self, files):
        self.files = files            # path -> contents

    def exists(self, p):
        if p in self.files:
            return True
        pre = p.rstrip("/") + "/"
        return any(f.startswith(pre) for f in self.files)

    def read(self, p):
        return self.files[p]

    def list_dir(self, p):
        pre = p.rstrip("/") + "/"
        out = set()
        for f in self.files:
            if f.startswith(pre):
                out.add(f[len(pre):].split("/")[0])
        return sorted(out)


class ResolveViewTest(unittest.TestCase):
    def test_dots_become_directories(self):
        t = FakeTree({"/p/resources/views/emails/layout.blade.php": ""})
        self.assertEqual(
            nav.resolve("view", "emails.layout", "/p", exists=t.exists, read=t.read),
            [{"path": "/p/resources/views/emails/layout.blade.php", "line": 0}])

    def test_falls_back_to_plain_php_view(self):
        t = FakeTree({"/p/resources/views/legacy.php": ""})
        self.assertEqual(
            nav.resolve("view", "legacy", "/p", exists=t.exists, read=t.read)[0]["path"],
            "/p/resources/views/legacy.php")

    def test_blade_extends_resolves_like_view(self):
        t = FakeTree({"/p/resources/views/emails/layout.blade.php": ""})
        self.assertEqual(len(nav.resolve("extends", "emails.layout", "/p",
                                         exists=t.exists, read=t.read)), 1)

    def test_missing_view_yields_nothing(self):
        t = FakeTree({})
        self.assertEqual(nav.resolve("view", "nope", "/p", exists=t.exists, read=t.read), [])


class ResolveConfigTest(unittest.TestCase):
    CONF = "\n".join([
        "<?php",
        "return [",
        "    'single_database_testing' => false,",
        "    'sends' => [",
        "        'read_rate_limit_per_minute' => 120,",
        "    ],",
        "];",
    ])

    def _tree(self):
        return FakeTree({"/p/config/instacom.php": self.CONF})

    def test_top_level_key_line(self):
        t = self._tree()
        out = nav.resolve("config", "instacom.single_database_testing", "/p",
                          exists=t.exists, read=t.read)
        self.assertEqual(out, [{"path": "/p/config/instacom.php", "line": 3}])

    def test_nested_key_line(self):
        t = self._tree()
        out = nav.resolve("config", "instacom.sends.read_rate_limit_per_minute", "/p",
                          exists=t.exists, read=t.read)
        self.assertEqual(out[0]["line"], 5)

    def test_file_only_when_key_is_absent(self):
        t = self._tree()
        out = nav.resolve("config", "instacom.nope", "/p", exists=t.exists, read=t.read)
        self.assertEqual(out, [{"path": "/p/config/instacom.php", "line": 0}])

    def test_unknown_config_file(self):
        t = self._tree()
        self.assertEqual(nav.resolve("config", "nothing.here", "/p",
                                     exists=t.exists, read=t.read), [])


class ResolveLangTest(unittest.TestCase):
    def _tree(self):
        return FakeTree({
            "/p/lang/en/auth.php": "<?php\nreturn [\n    'failed' => 'nope',\n];",
            "/p/lang/mk/auth.php": "<?php\nreturn [\n    'failed' => 'ne',\n];",
        })

    def test_finds_key_in_each_locale(self):
        t = self._tree()
        out = nav.resolve("__", "auth.failed", "/p", exists=t.exists, read=t.read,
                          list_dir=t.list_dir)
        self.assertEqual([o["path"] for o in out],
                         ["/p/lang/en/auth.php", "/p/lang/mk/auth.php"])
        self.assertEqual([o["line"] for o in out], [3, 3])

    def test_missing_key_still_points_at_the_file(self):
        """instacom calls __('auth.user_not_found') but never defines it."""
        t = self._tree()
        out = nav.resolve("__", "auth.user_not_found", "/p", exists=t.exists,
                          read=t.read, list_dir=t.list_dir)
        self.assertEqual(out[0]["line"], 0)

    def test_trans_behaves_like_underscore(self):
        t = self._tree()
        self.assertEqual(nav.resolve("trans", "auth.failed", "/p", exists=t.exists,
                                     read=t.read, list_dir=t.list_dir)[0]["line"], 3)

    def test_resources_lang_layout_is_supported(self):
        t = FakeTree({"/p/resources/lang/en/auth.php": "<?php\n    'failed' => 'x',"})
        out = nav.resolve("__", "auth.failed", "/p", exists=t.exists, read=t.read,
                          list_dir=t.list_dir)
        self.assertEqual(out[0]["path"], "/p/resources/lang/en/auth.php")


class ResolveRouteTest(unittest.TestCase):
    def test_finds_named_route_line(self):
        t = FakeTree({"/p/routes/api.php": "\n".join([
            "<?php",
            "Route::get('/a', [A::class, 'x'])->name('api-keys.rotate');",
        ])})
        out = nav.resolve("route", "api-keys.rotate", "/p", exists=t.exists, read=t.read)
        self.assertEqual(out, [{"path": "/p/routes/api.php", "line": 2}])

    def test_unnamed_route_yields_nothing(self):
        t = FakeTree({"/p/routes/api.php": "<?php\nRoute::get('/a', $h);"})
        self.assertEqual(nav.resolve("route", "nope", "/p", exists=t.exists, read=t.read), [])


class ResolveYiiTest(unittest.TestCase):
    def test_render_searches_the_views_tree(self):
        t = FakeTree({"/p/views/site/index.php": ""})
        out = nav.resolve("render", "index", "/p", framework="yii2",
                          exists=t.exists, read=t.read,
                          glob_files=lambda r, n: ["/p/views/site/index.php"])
        self.assertEqual(out, [{"path": "/p/views/site/index.php", "line": 0}])

    def test_render_is_ignored_for_laravel(self):
        t = FakeTree({"/p/views/site/index.php": ""})
        self.assertEqual(nav.resolve("render", "index", "/p", framework="laravel",
                                     exists=t.exists, read=t.read), [])


class FindRootTest(unittest.TestCase):
    def test_walks_up_to_the_project_root(self):
        """instacom keeps code in app/Modules/<M>/..., so the root is several
        levels above the file being clicked."""
        root = "/p/api-laravel"
        deep = root + "/app/Modules/ApiKey/Infrastructure/Models/ApiKey.php"
        self.assertEqual(
            nav.find_root(deep, exists=lambda x: x == root + "/artisan"), root)

    def test_prefers_the_nearest_root(self):
        def exists(x):
            return x in ("/p/outer/artisan", "/p/outer/inner/artisan")
        self.assertEqual(nav.find_root("/p/outer/inner/app/X.php", exists=exists),
                         "/p/outer/inner")

    def test_falls_back_to_a_window_folder(self):
        self.assertEqual(
            nav.find_root("/somewhere/else/X.php", folders=["/p/api"],
                          exists=lambda x: x == "/p/api/artisan"),
            "/p/api")

    def test_no_framework_anywhere(self):
        self.assertIsNone(nav.find_root("/p/X.php", folders=["/q"], exists=lambda x: False))

    def test_unsaved_view_has_no_path(self):
        self.assertIsNone(nav.find_root(None, folders=[], exists=lambda x: False))


MODEL_SRC = """<?php

namespace App\\Modules\\ApiKey\\Infrastructure\\Models;

use Illuminate\\Database\\Eloquent\\Model;

/**
 * @property string $id
 * @property string $brand_id
 * @property \\Illuminate\\Support\\Carbon|null $revoked_at
 */
class ApiKey extends Model
{
    protected $table = 'api_keys';

    protected $fillable = [
        'brand_id',
        'label',
    ];

    protected $casts = [
        'scopes' => 'array',
        'revoked_at' => 'datetime',
    ];

    protected $hidden = ['key_hash'];

    public function brand()
    {
        return $this->belongsTo(Brand::class, 'brand_id');
    }

    public function sends()
    {
        return $this->hasMany(Send::class);
    }
}
"""


class ModelSummaryTest(unittest.TestCase):
    def _s(self):
        return nav.model_summary("/p/ApiKey.php", read=lambda _p: MODEL_SRC)

    def test_class_and_parent(self):
        s = self._s()
        self.assertEqual(s["class"], "ApiKey")
        self.assertEqual(s["extends"], "Model")

    def test_table(self):
        self.assertEqual(self._s()["table"], "api_keys")

    def test_fillable(self):
        self.assertEqual(self._s()["fillable"], ["brand_id", "label"])

    def test_casts_keys_and_values(self):
        self.assertEqual(self._s()["casts"],
                         ["scopes", "array", "revoked_at", "datetime"])

    def test_hidden(self):
        self.assertEqual(self._s()["hidden"], ["key_hash"])

    def test_docblock_properties(self):
        props = {p["name"]: p["type"] for p in self._s()["properties"]}
        self.assertEqual(props["id"], "string")
        self.assertEqual(props["revoked_at"], "\\Illuminate\\Support\\Carbon|null")

    def test_relations(self):
        rels = {r["name"]: (r["kind"], r["target"]) for r in self._s()["relations"]}
        self.assertEqual(rels["brand"], ("belongsTo", "Brand"))
        self.assertEqual(rels["sends"], ("hasMany", "Send"))

    def test_unreadable_file_yields_empty(self):
        def boom(_p):
            raise OSError("nope")
        self.assertEqual(nav.model_summary("/p/X.php", read=boom), {})


class FindModelTest(unittest.TestCase):
    def test_prefers_a_models_directory(self):
        def walk(start):
            if start.endswith("app"):
                return [("/p/app/Modules/ApiKey/Infrastructure/Models", [], ["ApiKey.php"]),
                        ("/p/app/Support", [], ["ApiKey.php"])]
            return []
        self.assertEqual(nav.find_model("/p", "ApiKey", walk=walk),
                         "/p/app/Modules/ApiKey/Infrastructure/Models/ApiKey.php")

    def test_accepts_a_filename(self):
        def walk(start):
            return [("/p/app/Models", [], ["User.php"])] if start.endswith("app") else []
        self.assertEqual(nav.find_model("/p", "User.php", walk=walk), "/p/app/Models/User.php")

    def test_missing_model(self):
        self.assertIsNone(nav.find_model("/p", "Nope", walk=lambda s: []))


MATCH_SRC = """<?php

Route::prefix('v1/webhooks')->group(function () {
    Route::match(['get', 'post'], '/elasticemail', [WebhookController::class, 'elasticemail']);
    Route::match(['get', 'post'], '/okroute', [WebhookController::class, 'okroute'])
        ->middleware('throttle:120,1');
});
"""


class RouteMatchTest(unittest.TestCase):
    """Route::match takes the verb array first, so the URI is not the first
    argument. The real project has three of these and an earlier regex that
    expected a quote right after "(" silently dropped all of them."""

    def _routes(self):
        return nav.route_summary("/p", read=lambda _p: MATCH_SRC,
                                 exists=lambda x: x.endswith(("routes", "api.php")))

    def test_match_routes_are_found(self):
        self.assertEqual(len(self._routes()), 2)

    def test_verbs_come_from_the_array(self):
        self.assertEqual(self._routes()[0]["verb"], "GET|POST")

    def test_uri_is_the_second_argument(self):
        self.assertEqual(self._routes()[0]["uri"], "/elasticemail")

    def test_prefix_still_applies(self):
        self.assertEqual(self._routes()[0]["prefix"], "v1/webhooks")

    def test_action_still_resolves(self):
        self.assertEqual(self._routes()[1]["action"], "WebhookController::okroute")


ROUTES_SRC = """<?php

Route::get('/healthz', [HealthController::class, 'liveness']);

Route::prefix('v1')->middleware('auth:api_key')->group(function () {
    Route::post('/events', [EventController::class, 'ingest'])
        ->name('events.ingest');
    Route::delete('/keys/{id}', [ApiKeyController::class, 'revoke']);
});
"""


class RouteSummaryTest(unittest.TestCase):
    def _routes(self):
        return nav.route_summary("/p", read=lambda _p: ROUTES_SRC,
                                 exists=lambda p: p.endswith(("routes", "api.php")))

    def test_finds_every_route(self):
        self.assertEqual(len(self._routes()), 3)

    def test_verb_uri_and_line(self):
        r = self._routes()[0]
        self.assertEqual((r["verb"], r["uri"], r["line"]), ("GET", "/healthz", 3))

    def test_action_from_array_callable(self):
        self.assertEqual(self._routes()[0]["action"], "HealthController::liveness")

    def test_name_found_on_a_following_line(self):
        self.assertEqual(self._routes()[1]["name"], "events.ingest")

    def test_prefix_is_carried(self):
        self.assertEqual(self._routes()[1]["prefix"], "v1")

    def test_unnamed_route_has_no_name_key(self):
        self.assertNotIn("name", self._routes()[2])

    def test_no_routes_dir(self):
        self.assertEqual(nav.route_summary("/p", read=lambda p: "",
                                           exists=lambda p: False), [])


if __name__ == "__main__":
    unittest.main()
