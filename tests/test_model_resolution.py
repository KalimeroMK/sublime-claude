"""Tests for which model a new session asks for.

The built-in fallback used to be checked before the user's own setting. It is
always set ("opus" for the claude backend), so `default_model` could never take
effect: you could write a model into the settings file, see it there, and still
have every session request opus.
"""
import unittest

from tests.plugin_pkg import load

env = load("session_env")
resolve = env.resolve_default_model


def getter(values):
    return lambda key, default=None: values.get(key, default)


class ResolveDefaultModelTest(unittest.TestCase):
    def test_per_backend_setting_wins(self):
        got = resolve(getter({"default_models": {"claude": "sonnet"},
                              "default_model": "opus"}), "claude", "haiku")
        self.assertEqual(got, "sonnet")

    def test_global_setting_beats_the_builtin_fallback(self):
        got = resolve(getter({"default_model": "kimi-for-coding"}), "claude", "opus")
        self.assertEqual(got, "kimi-for-coding")

    def test_legacy_anthropic_model_still_honoured(self):
        """Settings files in the wild already carry this key."""
        got = resolve(getter({"anthropic_model": "kimi-for-coding"}), "claude", "opus")
        self.assertEqual(got, "kimi-for-coding")

    def test_default_model_beats_the_legacy_alias(self):
        got = resolve(getter({"default_model": "sonnet",
                              "anthropic_model": "kimi-for-coding"}), "claude", "opus")
        self.assertEqual(got, "sonnet")

    def test_legacy_alias_is_claude_only(self):
        """anthropic_model must not leak into the openai or codex backends."""
        got = resolve(getter({"anthropic_model": "kimi-for-coding"}), "openai", "gpt-4o")
        self.assertEqual(got, "gpt-4o")

    def test_fallback_when_nothing_is_set(self):
        self.assertEqual(resolve(getter({}), "claude", "opus"), "opus")

    def test_other_backend_entry_is_not_used(self):
        got = resolve(getter({"default_models": {"openai": "qwen2.5"}}), "claude", "opus")
        self.assertEqual(got, "opus")

    def test_empty_per_backend_value_falls_through(self):
        got = resolve(getter({"default_models": {"claude": ""},
                              "default_model": "sonnet"}), "claude", "opus")
        self.assertEqual(got, "sonnet")

    def test_missing_default_models_key(self):
        self.assertEqual(resolve(getter({"default_models": None}), "claude", "opus"), "opus")

    def test_kimi_backend_name_counts_as_claude_family(self):
        got = resolve(getter({"anthropic_model": "kimi-for-coding"}), "kimi", "opus")
        self.assertEqual(got, "kimi-for-coding")


class ResolveModelIdTest(unittest.TestCase):
    def test_unknown_model_name_passes_through(self):
        """A provider-specific name must reach the CLI unchanged."""
        self.assertEqual(env._resolve_model_id("kimi-for-coding"), ("kimi-for-coding", None))

    def test_context_suffix_is_split_off(self):
        model, ctx = env._resolve_model_id("opus@400k")
        self.assertEqual(model, "opus")
        self.assertTrue(ctx)

    def test_empty(self):
        self.assertEqual(env._resolve_model_id(""), ("", None))


if __name__ == "__main__":
    unittest.main()
