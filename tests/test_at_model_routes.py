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

    def test_columns_are_aligned(self):
        body = sq._format_routes(self.ROUTES).splitlines()[1:]
        starts = [line.index("/") for line in body]
        self.assertEqual(len(set(starts)), 1, "uri column not aligned: %s" % body)

    def test_empty(self):
        self.assertEqual(sq._format_routes([]), "[routes] none found")


if __name__ == "__main__":
    unittest.main()
