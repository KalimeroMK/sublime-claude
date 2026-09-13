"""Recover tool calls a model emitted as text instead of the structured field.

An abliterated or loosely-templated Ollama model intermittently prints
<tool_call>{"name": ...}</tool_call> (or the bare JSON) into the content and
leaves message.tool_calls empty. The bridge used to forward that content
verbatim as the answer, so the JSON leaked to the screen and nothing ran.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge"))
import openai_main as om  # noqa: E402


class ExtractTextToolCallsTest(unittest.TestCase):
    def test_the_exact_leak_the_user_saw(self):
        """Bare JSON followed by an orphan </tool_call>, verbatim from the wild."""
        content = ('{"name": "Bash", "arguments": {"command": '
                   '"curl -s https://www.php.net/releases.json | jq .releases[0].version", '
                   '"description": "Fetching the latest PHP version number"}}\n</tool_call>')
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "Bash")
        self.assertIn("curl", calls[0]["function"]["arguments"]["command"])
        self.assertEqual(cleaned, "")

    def test_wrapped_in_tool_call_tags(self):
        content = '<tool_call>{"name": "Read", "arguments": {"file_path": "a.php"}}</tool_call>'
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(calls[0]["function"]["name"], "Read")
        self.assertEqual(calls[0]["function"]["arguments"], {"file_path": "a.php"})
        self.assertEqual(cleaned, "")

    def test_text_before_the_call_is_kept(self):
        content = 'Let me check that.\n<tool_call>{"name": "Bash", "arguments": {"command": "ls"}}</tool_call>'
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cleaned, "Let me check that.")

    def test_generates_an_id_and_function_shape(self):
        calls, _ = om.extract_text_tool_calls('<tool_call>{"name":"Glob","arguments":{"pattern":"*.php"}}</tool_call>')
        tc = calls[0]
        self.assertTrue(tc["id"].startswith("call_"))
        self.assertEqual(tc["type"], "function")
        self.assertIn("name", tc["function"])

    def test_plain_text_is_left_alone(self):
        content = "PHP 8.4 is the latest stable release."
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(calls, [])
        self.assertEqual(cleaned, content)

    def test_json_that_is_not_a_tool_call_is_ignored(self):
        content = 'Here is a config: {"name": "app", "version": "1.0"}'
        calls, _ = om.extract_text_tool_calls(content)
        self.assertEqual(calls, [])

    def test_malformed_json_does_not_raise(self):
        content = '<tool_call>{"name": "Bash", "arguments": {broken</tool_call>'
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(calls, [])

    def test_empty_content(self):
        self.assertEqual(om.extract_text_tool_calls(""), ([], ""))

    def test_none_content(self):
        self.assertEqual(om.extract_text_tool_calls(None), ([], None))

    def test_two_calls_in_one_message(self):
        content = ('<tool_call>{"name":"Read","arguments":{"file_path":"a"}}</tool_call>'
                   '<tool_call>{"name":"Read","arguments":{"file_path":"b"}}</tool_call>')
        calls, cleaned = om.extract_text_tool_calls(content)
        self.assertEqual(len(calls), 2)
        self.assertEqual(cleaned, "")


if __name__ == "__main__":
    unittest.main()
