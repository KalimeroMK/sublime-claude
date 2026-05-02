"""Tests for smart_context noise filtering."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime
sys.modules["sublime"] = sublime

from smart_context import _is_noise


class IsNoiseTest(unittest.TestCase):
    def test_noise_basenames(self):
        for path in (
            "/p/.env.example",
            "/p/.env.testing",
            "/p/.env.staging",
            "/p/.phpunit.result.cache",
            "/p/phpunit.xml.dist",
            "/p/package-lock.json",
            "/p/yarn.lock",
            "/p/composer.lock",
            "/p/uv.lock",
            "/p/Cargo.lock",
        ):
            self.assertTrue(_is_noise(path), f"expected noise: {path}")

    def test_noise_suffixes(self):
        for path in (
            "/p/some.cache",
            "/p/foo.example",
            "/p/x.lock",
            "/p/server.log",
            "/p/bundle.min.js",
            "/p/style.min.css",
            "/p/app.map",
            "/p/swap.tmp",
            "/p/save.bak",
            "/p/file.orig",
            "/p/.session.swp",
        ):
            self.assertTrue(_is_noise(path), f"expected noise: {path}")

    def test_real_code_files_are_not_noise(self):
        for path in (
            "/p/main.py",
            "/p/app.js",
            "/p/index.ts",
            "/p/User.php",
            "/p/README.md",
            "/p/.env",
            "/p/composer.json",
            "/p/package.json",
        ):
            self.assertFalse(_is_noise(path), f"expected not noise: {path}")

    def test_case_insensitive(self):
        self.assertTrue(_is_noise("/p/Composer.LOCK"))
        self.assertTrue(_is_noise("/p/.ENV.example"))


if __name__ == "__main__":
    unittest.main()
