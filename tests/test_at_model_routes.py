"""Tests for the @model / @routes formatters in session_query."""
import unittest

from tests.plugin_pkg import load

sq = load("session_query")


class FormatModelTest(unittest.TestCase):
    INFO = {
        "path": "/p/app/Modules/ApiKey/Infrastructure/Models/ApiKey.php",
        "class": "ApiKey", "extends": "Model", "table": "api_keys",
        "fillable": ["brand_id", "label"],
        "hidden": ["key_hash"],
        "casts": ["scopes", "array", "revoked_at", "datetime"],
        "properties": [{"name": "id", "type": "string"},
                       {"name": "revoked_at", "type": "Carbon|null"}],
        "relations": [{"name": "brand", "kind": "belongsTo", "target": "Brand"},
                      {"name": "sends", "kind": "hasMany", "target": "Send"}],
    }

    def test_header_and_relative_path(self):
        out = sq._format_model(self.INFO, "/p")
        self.assertIn("[model] ApiKey", out)
        self.assertIn("path: app/Modules/ApiKey/Infrastructure/Models/ApiKey.php", out)

    def test_table_and_parent(self):
        out = sq._format_model(self.INFO, "/p")
        self.assertIn("extends: Model", out)
        self.assertIn("table: api_keys", out)

    def test_casts_render_as_pairs(self):
        self.assertIn("casts: scopes => array, revoked_at => datetime",
                      sq._format_model(self.INFO, "/p"))

    def test_fillable_and_hidden(self):
        out = sq._format_model(self.INFO, "/p")
        self.assertIn("fillable: brand_id, label", out)
        self.assertIn("hidden: key_hash", out)

    def test_properties_and_relations(self):
        out = sq._format_model(self.INFO, "/p")
        self.assertIn("$id : string", out)
        self.assertIn("brand() belongsTo Brand", out)
        self.assertIn("sends() hasMany Send", out)

    def test_odd_length_casts_does_not_crash(self):
        info = dict(self.INFO, casts=["scopes"])
        self.assertNotIn("casts:", sq._format_model(info, "/p"))

    def test_empty_info(self):
        self.assertEqual(sq._format_model({}, "/p"), "[model] (unreadable)")

    def test_minimal_info_omits_absent_sections(self):
        out = sq._format_model({"path": "/p/X.php", "class": "X"}, "/p")
        self.assertIn("[model] X", out)
        for absent in ("table:", "fillable:", "casts:", "relations:", "properties:"):
            self.assertNotIn(absent, out)


class FormatRoutesTest(unittest.TestCase):
    ROUTES = [
        {"verb": "GET", "uri": "/healthz", "action": "HealthController::liveness",
         "file": "api.php", "line": 3, "prefix": ""},
        {"verb": "POST", "uri": "/events", "name": "events.ingest",
         "action": "EventController::ingest", "file": "api.php", "line": 6, "prefix": "v1"},
    ]

    def test_counts_in_the_header(self):
        self.assertIn("[routes] 2 found", sq._format_routes(self.ROUTES))

    def test_prefix_is_prepended_to_the_uri(self):
        self.assertIn("/v1/events", sq._format_routes(self.ROUTES))

    def test_unprefixed_uri_is_left_alone(self):
        out = sq._format_routes(self.ROUTES)
        self.assertIn("/healthz", out)
        self.assertNotIn("/v1/healthz", out)

    def test_name_and_location_present(self):
        out = sq._format_routes(self.ROUTES)
        self.assertIn("events.ingest", out)
        self.assertIn("api.php:6", out)

    def test_header_names_the_columns(self):
        head = sq._format_routes(self.ROUTES).splitlines()[1]
        self.assertTrue(head.startswith("VERB"))
        self.assertIn("URI", head)

    def test_header_is_aligned_with_the_rows(self):
        """Widths taken from the data alone leave the header out of step when a
        heading is longer than every value under it (VERB vs GET)."""
        lines = sq._format_routes(self.ROUTES).splitlines()[1:]
        starts = [line.index("URI" if i == 0 else "/") for i, line in enumerate(lines)]
        self.assertEqual(len(set(starts)), 1, "header not aligned: %s" % lines)

    def test_columns_are_aligned(self):
        body = sq._format_routes(self.ROUTES).splitlines()[2:]
        starts = [line.index("/") for line in body]
        self.assertEqual(len(set(starts)), 1, "uri column not aligned: %s" % body)

    def test_empty(self):
        self.assertEqual(sq._format_routes([]), "[routes] none found")


class FilterRoutesTest(unittest.TestCase):
    """A modular project reports hundreds of routes; injecting all of them
    costs more context than the question being asked."""

    ROUTES = [
        {"module": "Brand", "verb": "GET", "uri": "/api/brands",
         "name": "brands.index", "action": "BrandController::index", "file": "api.php"},
        {"module": "License", "verb": "POST", "uri": "/api/licenses",
         "name": "licenses.store", "action": "LicenseController::store", "file": "api.php"},
        {"module": "", "verb": "GET", "uri": "/health",
         "name": "", "action": "", "file": "web.php"},
    ]

    def test_filters_by_module(self):
        got = sq._filter_routes(self.ROUTES, "brand")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["module"], "Brand")

    def test_filters_by_uri(self):
        self.assertEqual(len(sq._filter_routes(self.ROUTES, "/api/")), 2)

    def test_filters_by_name(self):
        self.assertEqual(len(sq._filter_routes(self.ROUTES, "licenses.store")), 1)

    def test_filters_by_action(self):
        self.assertEqual(len(sq._filter_routes(self.ROUTES, "licensecontroller")), 1)

    def test_filters_by_verb(self):
        self.assertEqual(len(sq._filter_routes(self.ROUTES, "post")), 1)

    def test_no_match_is_empty(self):
        self.assertEqual(sq._filter_routes(self.ROUTES, "zzz"), [])


class ArgumentHeuristicTest(unittest.TestCase):
    """`@quality fix this` and `@routes please review` must not swallow the
    next word of the sentence as an argument."""

    def test_prose_is_not_a_route_filter(self):
        for word in ("please", "review", "this", "and"):
            self.assertFalse(sq._looks_like_route_filter(word), word)

    def test_module_name_is_a_route_filter(self):
        self.assertTrue(sq._looks_like_route_filter("Brand"))

    def test_uri_is_a_route_filter(self):
        self.assertTrue(sq._looks_like_route_filter("/api/v1"))

    def test_verb_is_a_route_filter(self):
        self.assertTrue(sq._looks_like_route_filter("POST"))

    def test_dotted_name_is_a_route_filter(self):
        self.assertTrue(sq._looks_like_route_filter("brands.index"))

    def test_empty_is_not_a_filter(self):
        self.assertFalse(sq._looks_like_route_filter(""))

    def test_php_file_is_a_path(self):
        self.assertTrue(sq._looks_like_path("app/Models/Brand.php"))
        self.assertTrue(sq._looks_like_path("Brand.php"))

    def test_directory_is_a_path(self):
        self.assertTrue(sq._looks_like_path("app/Modules/Brand"))

    def test_prose_is_not_a_path(self):
        for word in ("fix", "this", "Brand"):
            self.assertFalse(sq._looks_like_path(word), word)


if __name__ == "__main__":
    unittest.main()
