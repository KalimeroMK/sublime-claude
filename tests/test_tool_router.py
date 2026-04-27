"""Tests for MCP tool routing."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin

from tool_router import ToolRouter


class ToolRouterTest(unittest.TestCase):
    """Test tool routing registry."""

    def test_register_and_lookup(self):
        """Tools can be registered and looked up."""
        router = ToolRouter()
        router.register("test_tool", lambda args: "test_result")
        
        self.assertTrue(router.has_tool("test_tool"))
        result = router.route("test_tool", {})
        self.assertEqual(result, "test_result")

    def test_missing_tool(self):
        """Missing tool raises ValueError."""
        router = ToolRouter()
        with self.assertRaises(ValueError) as ctx:
            router.route("nonexistent", {})
        self.assertIn("Unknown tool", str(ctx.exception))

    def test_multiple_tools(self):
        """Multiple tools can be registered."""
        router = ToolRouter()
        router.register("tool_a", lambda args: "a")
        router.register("tool_b", lambda args: "b")
        
        self.assertEqual(router.route("tool_a", {}), "a")
        self.assertEqual(router.route("tool_b", {}), "b")

    def test_tool_args_passed(self):
        """Arguments are passed to tool handler."""
        router = ToolRouter()
        router.register("echo", lambda args: args.get("msg", ""))
        
        result = router.route("echo", {"msg": "hello"})
        self.assertEqual(result, "hello")

    def test_has_tool_false(self):
        """has_tool returns False for unregistered tools."""
        router = ToolRouter()
        self.assertFalse(router.has_tool("unknown"))


if __name__ == "__main__":
    unittest.main()
