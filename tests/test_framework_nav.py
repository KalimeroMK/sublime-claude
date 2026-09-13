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
        """uri is the full path a request hits — group prefixes are already
        folded in, so a caller never has to re-join prefix and uri itself."""
        self.assertEqual(self._routes()[0]["uri"], "/v1/webhooks/elasticemail")

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


MIGRATION_SRC = """<?php
return new class extends Migration {
    public function up(): void
    {
        Schema::create('brands', function (Blueprint $table): void {
            $table->id();
            $table->string('name', 100);
            $table->string('slug', 255)->nullable()->unique();
            $table->text('description')->nullable();
            $table->foreignId('company_id')->nullable()->constrained();
            $table->decimal('score', 8, 2)->default(0);
            $table->enum('status', ['draft', 'live'])->default('draft');
            $table->boolean('is_active')->default(true)->index();
            $table->morphs('owner');
            $table->timestamps();
            $table->softDeletes();
        });
    }
};
"""

ALTER_SRC = """<?php
Schema::table('brands', function (Blueprint $table): void {
    $table->dropColumn('description');
    $table->renameColumn('slug', 'handle');
    $table->string('website', 500)->nullable();
});
"""


class SchemaBlockTest(unittest.TestCase):
    def test_finds_create_block(self):
        blocks = nav.schema_blocks(MIGRATION_SRC)
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0]["op"], blocks[0]["table"]), ("create", "brands"))

    def test_body_stops_at_matching_brace(self):
        body = nav.schema_blocks(MIGRATION_SRC)[0]["body"]
        self.assertIn("$table->id()", body)
        self.assertNotIn("return new class", body)

    def test_connection_prefix_is_tolerated(self):
        src = "Schema::connection('tenant')->create('x', function ($t) { $t->id(); });"
        self.assertEqual(nav.schema_blocks(src)[0]["table"], "x")

    def test_no_schema_call(self):
        self.assertEqual(nav.schema_blocks("<?php echo 1;"), [])


class ParseColumnsTest(unittest.TestCase):
    def _cols(self):
        body = nav.schema_blocks(MIGRATION_SRC)[0]["body"]
        return {c["name"]: c for c in nav.parse_columns(body) if c["op"] == "add"}

    def test_id_is_big_int_primary_key(self):
        col = self._cols()["id"]
        self.assertEqual(col["type"], "bigint unsigned")
        self.assertTrue(col["pk"])

    def test_string_carries_its_length(self):
        self.assertEqual(self._cols()["name"]["type"], "string(100)")

    def test_nullable_and_unique_flags(self):
        col = self._cols()["slug"]
        self.assertTrue(col["nullable"])
        self.assertTrue(col["unique"])

    def test_decimal_keeps_precision_and_scale(self):
        self.assertEqual(self._cols()["score"]["type"], "decimal(8,2)")

    def test_enum_lists_its_values(self):
        self.assertEqual(self._cols()["status"]["type"], "enum(draft,live)")

    def test_default_is_captured(self):
        self.assertEqual(self._cols()["is_active"]["default"], "true")

    def test_foreign_id_infers_its_table(self):
        col = self._cols()["company_id"]
        self.assertEqual(col["fk"], "companies")
        self.assertTrue(col["nullable"])

    def test_morphs_expands_to_two_columns(self):
        cols = self._cols()
        self.assertEqual(cols["owner_id"]["type"], "bigint unsigned")
        self.assertEqual(cols["owner_type"]["type"], "string")

    def test_timestamps_expand(self):
        cols = self._cols()
        self.assertTrue(cols["created_at"]["nullable"])
        self.assertIn("updated_at", cols)

    def test_soft_deletes_expands(self):
        self.assertEqual(self._cols()["deleted_at"]["type"], "timestamp")

    def test_drop_and_rename_are_reported(self):
        body = nav.schema_blocks(ALTER_SRC)[0]["body"]
        ops = nav.parse_columns(body)
        kinds = {(o["op"], o["name"]) for o in ops}
        self.assertIn(("drop", "description"), kinds)
        self.assertIn(("rename", "slug"), kinds)


class TableColumnsTest(unittest.TestCase):
    FILES = ["/p/database/migrations/2024_01_01_create_brands.php",
             "/p/database/migrations/2024_02_01_alter_brands.php"]

    def _cols(self):
        def read(p):
            return MIGRATION_SRC if "create" in p else ALTER_SRC
        return nav.table_columns("/p", "brands", read=read, files=self.FILES)

    def test_later_migration_drops_a_column(self):
        names = [c["name"] for c in self._cols()]
        self.assertNotIn("description", names)

    def test_later_migration_renames_a_column(self):
        names = [c["name"] for c in self._cols()]
        self.assertIn("handle", names)
        self.assertNotIn("slug", names)

    def test_later_migration_adds_a_column(self):
        cols = {c["name"]: c for c in self._cols()}
        self.assertEqual(cols["website"]["type"], "string(500)")

    def test_source_file_is_recorded(self):
        cols = {c["name"]: c for c in self._cols()}
        self.assertEqual(cols["website"]["source"], "2024_02_01_alter_brands.php")

    def test_other_table_is_ignored(self):
        def read(_p):
            return MIGRATION_SRC
        self.assertEqual(nav.table_columns("/p", "widgets", read=read, files=self.FILES), [])

    def test_unreadable_migration_is_skipped(self):
        def boom(_p):
            raise OSError("nope")
        self.assertEqual(nav.table_columns("/p", "brands", read=boom, files=self.FILES), [])


class FindMigrationsTest(unittest.TestCase):
    def _walk(self):
        return lambda _root: [
            ("/p/database/migrations", [], ["2024_02_01_b.php", "2024_01_01_a.php"]),
            ("/p/app/Modules/License/Database/Migrations/Tenant", [], ["2023_01_01_c.php"]),
            ("/p/vendor/x/database/migrations", [], ["2020_01_01_vendor.php"]),
            ("/p/app/Models", [], ["Brand.php"]),
        ]

    def test_orders_by_timestamp_across_modules(self):
        hits = nav.find_migrations("/p", walk=self._walk())
        self.assertEqual([os.path.basename(p) for p in hits],
                         ["2023_01_01_c.php", "2024_01_01_a.php", "2024_02_01_b.php"])

    def test_skips_vendor(self):
        hits = nav.find_migrations("/p", walk=self._walk())
        self.assertFalse(any("vendor" in p for p in hits))

    def test_finds_nested_tenant_directories(self):
        """A multi-tenant app splits migrations into Migrations/Tenant — a
        basename-only match would miss every one of them."""
        hits = nav.find_migrations("/p", walk=self._walk())
        self.assertTrue(any("Tenant" in p for p in hits))


class TableNameForTest(unittest.TestCase):
    def test_explicit_table_wins(self):
        self.assertEqual(nav.table_name_for({"table": "custom", "class": "Brand"}), "custom")

    def test_plural_of_class_name(self):
        self.assertEqual(nav.table_name_for({"class": "Brand"}), "brands")

    def test_studly_becomes_snake(self):
        self.assertEqual(nav.table_name_for({"class": "ApiKey"}), "api_keys")

    def test_consonant_y_pluralises_to_ies(self):
        self.assertEqual(nav.table_name_for({"class": "Company"}), "companies")

    def test_sibilant_takes_es(self):
        self.assertEqual(nav.table_name_for({"class": "Address"}), "addresses")

    def test_no_class_no_table(self):
        self.assertEqual(nav.table_name_for({}), "")


NESTED_SRC = """<?php

Route::prefix('api')->name('api.')->middleware('auth:sanctum')->group(function () {
    Route::prefix('v1')->name('v1.')->group(function () {
        Route::get('/brands', [BrandController::class, 'index'])->name('brands.index');
        Route::middleware('can:admin')->group(function () {
            Route::delete('/brands/{id}', [BrandController::class, 'destroy']);
        });
    });
    Route::get('/ping', [PingController::class, 'show']);
});

Route::get('/outside', [PublicController::class, 'home']);
"""

RESOURCE_SRC = """<?php
Route::prefix('admin')->group(function () {
    Route::resource('companies', CompanyController::class);
    Route::apiResource('brands', BrandController::class)->only(['index', 'show']);
});
"""

ARRAY_GROUP_SRC = """<?php
Route::group(['prefix' => 'v2', 'middleware' => ['auth', 'throttle:60,1']], function () {
    Route::get('/stats', 'StatsController@index')->name('stats');
});
"""


class NestedGroupTest(unittest.TestCase):
    def _routes(self):
        return nav.route_summary("/p", read=lambda _p: NESTED_SRC,
                                 files=["/p/routes/api.php"])

    def _by_action(self, name):
        for r in self._routes():
            if r.get("action") == name:
                return r
        raise AssertionError("no route for " + name)

    def test_two_levels_of_prefix_are_joined(self):
        self.assertEqual(self._by_action("BrandController::index")["uri"], "/api/v1/brands")

    def test_three_levels_deep_still_joins(self):
        self.assertEqual(self._by_action("BrandController::destroy")["uri"],
                         "/api/v1/brands/{id}")

    def test_name_prefixes_stack(self):
        self.assertEqual(self._by_action("BrandController::index")["name"],
                         "api.v1.brands.index")

    def test_middleware_accumulates_down_the_stack(self):
        mw = self._by_action("BrandController::destroy")["middleware"]
        self.assertEqual(mw, ["auth:sanctum", "can:admin"])

    def test_frame_pops_when_its_brace_closes(self):
        """/ping sits in the outer group only — if the inner v1 frame leaked it
        would come out as /api/v1/ping."""
        self.assertEqual(self._by_action("PingController::show")["uri"], "/api/ping")

    def test_unnamed_route_in_a_named_group_stays_unnamed(self):
        """Laravel only names a route that calls ->name(); inheriting the group
        prefix alone would invent a dangling name like "api.v1."."""
        self.assertNotIn("name", self._by_action("BrandController::destroy"))

    def test_route_outside_every_group_keeps_a_bare_uri(self):
        self.assertEqual(self._by_action("PublicController::home")["uri"], "/outside")


class ResourceRouteTest(unittest.TestCase):
    def _routes(self):
        return nav.route_summary("/p", read=lambda _p: RESOURCE_SRC,
                                 files=["/p/routes/web.php"])

    def test_resource_expands_to_seven_routes(self):
        names = [r["name"] for r in self._routes() if r["name"].startswith("companies.")]
        self.assertEqual(len(names), 7)

    def test_resource_show_uses_singular_parameter(self):
        show = [r for r in self._routes() if r["name"] == "companies.show"][0]
        self.assertEqual(show["uri"], "/admin/companies/{company}")

    def test_resource_update_takes_both_write_verbs(self):
        upd = [r for r in self._routes() if r["name"] == "companies.update"][0]
        self.assertEqual(upd["verb"], "PUT|PATCH")

    def test_resource_action_names_the_controller_method(self):
        idx = [r for r in self._routes() if r["name"] == "companies.index"][0]
        self.assertEqual(idx["action"], "CompanyController::index")

    def test_api_resource_only_keeps_what_only_lists(self):
        names = sorted(r["name"] for r in self._routes() if r["name"].startswith("brands."))
        self.assertEqual(names, ["brands.index", "brands.show"])

    def test_resource_inherits_the_group_prefix(self):
        idx = [r for r in self._routes() if r["name"] == "companies.index"][0]
        self.assertEqual(idx["uri"], "/admin/companies")


class ArrayGroupTest(unittest.TestCase):
    def _route(self):
        return nav.route_summary("/p", read=lambda _p: ARRAY_GROUP_SRC,
                                 files=["/p/routes/api.php"])[0]

    def test_array_prefix_is_read(self):
        self.assertEqual(self._route()["uri"], "/v2/stats")

    def test_array_middleware_is_read(self):
        self.assertEqual(self._route()["middleware"], ["auth", "throttle:60,1"])

    def test_string_action_syntax_resolves(self):
        self.assertEqual(self._route()["action"], "StatsController::index")


class FindRouteFilesTest(unittest.TestCase):
    def _walk(self):
        return lambda _root: [
            ("/p/routes", [], ["api.php", "web.php"]),
            ("/p/app/Modules/Brand/Infrastructure/Routes", [], ["brand.php", "web.php"]),
            ("/p/vendor/pkg/routes", [], ["vendor.php"]),
            ("/p/app/Models", [], ["Brand.php"]),
        ]

    def _files(self):
        return nav.find_route_files("/p", walk=self._walk(),
                                    exists=lambda p: p.endswith(("api.php", "web.php")))

    def test_finds_module_route_files(self):
        """The whole point: a modular app keeps routes beside each module, and
        a hard-coded routes/*.php list reports nothing for them."""
        self.assertIn("/p/app/Modules/Brand/Infrastructure/Routes/brand.php", self._files())

    def test_keeps_the_canonical_four(self):
        self.assertIn(os.path.join("/p", "routes", "api.php"), self._files())

    def test_does_not_list_a_file_twice(self):
        self.assertEqual(len(self._files()), len(set(self._files())))

    def test_skips_vendor(self):
        self.assertFalse(any("vendor" in p for p in self._files()))


class ModuleOfTest(unittest.TestCase):
    def test_segment_after_modules_is_the_module(self):
        self.assertEqual(
            nav._module_of("/p/app/Modules/Brand/Infrastructure/Routes/web.php"), "Brand")

    def test_plain_layout_has_no_module(self):
        self.assertEqual(nav._module_of("/p/routes/web.php"), "")


class SingularTest(unittest.TestCase):
    def test_plain_plural(self):
        self.assertEqual(nav._singular("photos"), "photo")

    def test_ies_becomes_y(self):
        self.assertEqual(nav._singular("companies"), "company")

    def test_sibilant_plural(self):
        self.assertEqual(nav._singular("addresses"), "address")

    def test_double_s_is_left_alone(self):
        self.assertEqual(nav._singular("address"), "address")


REQUEST_SRC = """<?php
class CreateBrandRequest extends FormRequest
{
    public function authorize(): bool { return true; }

    public function rules(): array
    {
        return [
            'name' => 'required|string|max:100',
            'company_id' => ['nullable', 'integer', 'exists:companies,id'],
            'is_active' => 'boolean',
        ];
    }
}
"""

CONTROLLER_SRC = """<?php
class BrandController extends Controller
{
    public function __construct(private BrandRepository $repo) {}
    public function index(Request $r) {}
    public function store(CreateBrandRequest $r) {}
    private function helper() {}
}
"""

MODULE_MODEL_SRC = """<?php
class Brand extends Model
{
    protected $table = 'brands';
    public function company() { return $this->belongsTo(Company::class); }
}
"""


class RequestRulesTest(unittest.TestCase):
    def _rules(self):
        return nav.request_rules("/p/CreateBrandRequest.php", src=REQUEST_SRC)

    def test_string_rule_is_read_verbatim(self):
        self.assertEqual(self._rules()["name"], "required|string|max:100")

    def test_array_rule_is_joined_with_pipes(self):
        self.assertEqual(self._rules()["company_id"],
                         "nullable|integer|exists:companies,id")

    def test_every_field_is_listed(self):
        self.assertEqual(sorted(self._rules()), ["company_id", "is_active", "name"])

    def test_class_without_rules_yields_nothing(self):
        self.assertEqual(nav.request_rules("/p/X.php", src="<?php class X {}"), {})

    def test_unreadable_file_yields_nothing(self):
        def boom(_p):
            raise OSError("nope")
        self.assertEqual(nav.request_rules("/p/X.php", read=boom), {})


class ArrayPairsTest(unittest.TestCase):
    def test_nested_array_stays_with_its_key(self):
        pairs = dict(nav._array_pairs("'a' => ['x', 'y'], 'b' => 'z'"))
        self.assertEqual(pairs["a"], "['x', 'y']")
        self.assertEqual(pairs["b"], "'z'")

    def test_comma_inside_a_call_does_not_split(self):
        pairs = dict(nav._array_pairs("'a' => Rule::in(['x', 'y']), 'b' => 1"))
        self.assertEqual(pairs["b"], "1")


class FindModuleTest(unittest.TestCase):
    def _walk(self):
        return lambda _root: [
            ("/p/app/Modules", ["Brand", "License"], []),
            ("/p/app/Modules/Brand", [], ["x.php"]),
            ("/p/tests/Feature/Modules", ["Brand"], []),
            ("/p/database/factories/Modules", ["Brand"], []),
        ]

    def test_source_module_wins_over_the_test_mirror(self):
        """tests/Feature/Modules/Brand has the same name and no source; picking
        it would report an empty module."""
        self.assertEqual(nav.find_module("/p", "Brand", walk=self._walk()),
                         os.path.join("/p/app/Modules", "Brand"))

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(nav.find_module("/p", "brand", walk=self._walk()),
                         os.path.join("/p/app/Modules", "Brand"))

    def test_unknown_module(self):
        self.assertIsNone(nav.find_module("/p", "Nope", walk=self._walk()))

    def test_list_modules_uses_the_source_root_only(self):
        self.assertEqual(nav.list_modules("/p", walk=self._walk()), ["Brand", "License"])


class ModuleSummaryTest(unittest.TestCase):
    FILES = {
        "Infrastructure/Models/Brand.php": MODULE_MODEL_SRC,
        "Infrastructure/Http/Controllers/BrandController.php": CONTROLLER_SRC,
        "Infrastructure/Http/Requests/CreateBrandRequest.php": REQUEST_SRC,
        "Database/Migrations/2024_01_01_create_brands.php": MIGRATION_SRC,
        "Infrastructure/Routes/brand.php": "<?php Route::get('/x', 'C@i');",
        "Application/Actions/CreateBrand.php": "<?php class CreateBrand {}",
    }

    def _walk(self):
        def walk(start):
            seen = {}
            for rel in self.FILES:
                d = os.path.join(start, os.path.dirname(rel))
                seen.setdefault(d, []).append(os.path.basename(rel))
            return [(d, [], files) for d, files in seen.items()]
        return walk

    def _summary(self):
        def read(p):
            for rel, body in self.FILES.items():
                if p.endswith(rel.replace("/", os.sep)):
                    return body
            raise OSError("missing")
        return nav.module_summary("/p", "Brand", walk=self._walk(),
                                  read=read, path="/p/app/Modules/Brand")

    def test_layers_are_grouped(self):
        layers = self._summary()["layers"]
        for expected in ("models", "controllers", "requests", "actions",
                         "migrations", "routes"):
            self.assertIn(expected, layers, expected + " missing")

    def test_controller_lists_its_public_methods(self):
        ctrl = self._summary()["layers"]["controllers"][0]
        self.assertEqual(ctrl["methods"], ["index", "store"])

    def test_constructor_and_privates_are_not_actions(self):
        ctrl = self._summary()["layers"]["controllers"][0]
        self.assertNotIn("__construct", ctrl["methods"])
        self.assertNotIn("helper", ctrl["methods"])

    def test_request_carries_its_rules(self):
        req = self._summary()["layers"]["requests"][0]
        self.assertEqual(req["rules"]["name"], "required|string|max:100")

    def test_model_reports_its_table_and_relations(self):
        model = self._summary()["layers"]["models"][0]
        self.assertEqual(model["table"], "brands")
        self.assertEqual(model["relations"][0]["name"], "company")

    def test_interfaces_and_enums_name_themselves_too(self):
        """An interface or enum is not `class X`, and falling back to the raw
        filename makes the outline read inconsistently."""
        cases = [("interface BrandRepositoryInterface", "BrandRepositoryInterface"),
                 ("enum BrandStatus: string", "BrandStatus"),
                 ("trait HasBrand", "HasBrand"),
                 ("final readonly class BrandData", "BrandData")]
        for decl, expected in cases:
            got = nav._CLASS_NAME.search("<?php " + decl + " {}")
            self.assertIsNotNone(got, decl)
            self.assertEqual(got.group(1), expected)

    def test_class_names_are_captured(self):
        self.assertEqual(self._summary()["layers"]["actions"][0]["class"], "CreateBrand")

    def test_migrations_are_listed_without_reading_them(self):
        migs = self._summary()["layers"]["migrations"]
        self.assertEqual(len(migs), 1)
        self.assertNotIn("class", migs[0])

    def test_unknown_module_is_empty(self):
        self.assertEqual(nav.module_summary("/p", "Nope", walk=lambda _r: []), {})


class LayerOfTest(unittest.TestCase):
    def test_ddd_controller_path(self):
        self.assertEqual(
            nav._layer_of(os.path.join("Infrastructure", "Http", "Controllers", "X.php")),
            "controllers")

    def test_flat_models_path(self):
        self.assertEqual(nav._layer_of(os.path.join("Models", "X.php")), "models")

    def test_unrecognised_path(self):
        self.assertEqual(nav._layer_of(os.path.join("Weird", "X.php")), "other")


class ComponentTagTest(unittest.TestCase):
    """A Blade component tag carries no quotes, so the helper-call regex that
    every other resolver relies on never matches it."""

    def test_finds_a_component_tag(self):
        src = '<x-forms.input name="a" />'
        self.assertEqual(nav.call_at(src, src.index("forms") + 2),
                         ("component-tag", "forms.input"))

    def test_finds_a_livewire_tag(self):
        src = '<livewire:brand.table />'
        self.assertEqual(nav.call_at(src, src.index("brand") + 2),
                         ("livewire", "brand.table"))

    def test_finds_the_livewire_directive(self):
        src = "@livewire('brand.table')"
        self.assertEqual(nav.call_at(src, src.index("brand") + 2),
                         ("livewire", "brand.table"))

    def test_point_outside_the_tag_name(self):
        src = '<x-forms.input name="a" />'
        self.assertIsNone(nav.call_at(src, src.index('name="a"') + 2))

    def test_plain_html_tag_is_not_a_component(self):
        src = "<div class='x'>"
        self.assertIsNone(nav.call_at(src, 2))


class ResolveComponentTest(unittest.TestCase):
    def test_blade_file_under_components(self):
        hits = nav.resolve("component-tag", "forms.input", "/p",
                           exists=lambda p: p.endswith(os.path.join(
                               "resources", "views", "components", "forms", "input.blade.php")))
        self.assertEqual(len(hits), 1)

    def test_index_blade_inside_a_component_directory(self):
        want = os.path.join("components", "forms", "input", "index.blade.php")
        hits = nav.resolve("component-tag", "forms.input", "/p",
                           exists=lambda p: p.endswith(want))
        self.assertEqual(len(hits), 1)

    def test_component_class_is_offered_too(self):
        want = os.path.join("app", "View", "Components", "Forms", "Input.php")
        hits = nav.resolve("component-tag", "forms.input", "/p",
                           exists=lambda p: p.endswith(want))
        self.assertEqual(len(hits), 1)

    def test_dashed_name_becomes_studly_for_the_class(self):
        want = os.path.join("app", "View", "Components", "FormInput.php")
        hits = nav.resolve("component-tag", "form-input", "/p",
                           exists=lambda p: p.endswith(want))
        self.assertEqual(len(hits), 1)

    def test_nothing_found(self):
        self.assertEqual(nav.resolve("component-tag", "x.y", "/p",
                                     exists=lambda _p: False), [])


class ResolveLivewireTest(unittest.TestCase):
    def test_modern_livewire_namespace(self):
        want = os.path.join("app", "Livewire", "Brand", "Table.php")
        hits = nav.resolve("livewire", "brand.table", "/p",
                           exists=lambda p: p.endswith(want))
        self.assertEqual(len(hits), 1)

    def test_legacy_http_livewire_namespace(self):
        want = os.path.join("app", "Http", "Livewire", "Brand", "Table.php")
        hits = nav.resolve("livewire", "brand.table", "/p",
                           exists=lambda p: p.endswith(want))
        self.assertEqual(len(hits), 1)

    def test_view_is_offered_alongside_the_class(self):
        def exists(p):
            return p.endswith(os.path.join("app", "Livewire", "Brand", "Table.php")) or \
                p.endswith(os.path.join("views", "livewire", "brand", "table.blade.php"))
        hits = nav.resolve("livewire", "brand.table", "/p", exists=exists)
        self.assertEqual(len(hits), 2)

    def test_falls_back_to_a_project_wide_search(self):
        """A modular app puts Livewire classes inside the module, not app/Livewire."""
        found = os.path.join("/p", "app", "Modules", "Brand", "Livewire", "Table.php")
        hits = nav.resolve("livewire", "brand.table", "/p",
                           exists=lambda _p: False,
                           glob_files=lambda _root, name: [found] if name == "Table.php" else [])
        self.assertEqual(hits, [{"path": found, "line": 0}])


class StudlyTest(unittest.TestCase):
    def test_dashes(self):
        self.assertEqual(nav._studly("form-input"), "FormInput")

    def test_underscores(self):
        self.assertEqual(nav._studly("form_input"), "FormInput")

    def test_already_studly_is_untouched(self):
        self.assertEqual(nav._studly("FormInput"), "FormInput")


if __name__ == "__main__":
    unittest.main()
