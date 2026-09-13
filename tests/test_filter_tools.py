"""_filter_tools must be able to send NO tools.

Empty allowed_tools used to return ALL tools, so there was no way to run a
chat-only session. Some local models (abliterated qwen) garble a plain
generation request when tools are present, so disabling them is how you get
clean code out of them.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge"))
import openai_main as om  # noqa: E402


class _Stub(om.Bridge):
    def __init__(self, allowed=None, enabled=True):
        self._allowed_tools = allowed or []
        self._tools_enabled = enabled


TOOLS = [{"function": {"name": n}} for n in ("Read", "Write", "Bash", "Glob")]


class FilterToolsTest(unittest.TestCase):
    def test_disabled_sends_nothing(self):
        self.assertEqual(_Stub(enabled=False)._filter_tools(TOOLS), [])

    def test_disabled_overrides_an_allow_list(self):
        self.assertEqual(_Stub(allowed=["Bash"], enabled=False)._filter_tools(TOOLS), [])

    def test_enabled_empty_allow_means_all(self):
        self.assertEqual(len(_Stub(enabled=True)._filter_tools(TOOLS)), 4)

    def test_enabled_allow_list_filters(self):
        got = _Stub(allowed=["Bash", "Read"], enabled=True)._filter_tools(TOOLS)
        self.assertEqual({t["function"]["name"] for t in got}, {"Bash", "Read"})


if __name__ == "__main__":
    unittest.main()
