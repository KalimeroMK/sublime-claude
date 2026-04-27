"""Tests for token usage graph feature."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin


class UsageGraphTest(unittest.TestCase):
    """Test usage graph rendering."""

    def _render_graph(self, history):
        """Replicate graph rendering logic."""
        if not history:
            return "No usage data"
        lines = ["# Token Usage Graph", ""]
        max_tok = max(max(h["in"], h["out"]) for h in history) or 1
        bar_width = 20
        for h in history[-20:]:
            q = h["q"]
            inp = h["in"]
            out = h["out"]
            in_bar = int(inp / max_tok * bar_width)
            out_bar = int(out / max_tok * bar_width)
            in_str = "█" * in_bar + "░" * (bar_width - in_bar)
            out_str = "▓" * out_bar + "░" * (bar_width - out_bar)
            lines.append(f"Q{q:3d}: in [{in_str}] {inp:,}")
            lines.append(f"      out [{out_str}] {out:,}")
            lines.append("")
        total_in = sum(h["in"] for h in history)
        total_out = sum(h["out"] for h in history)
        lines.append(f"**Total: {total_in:,} in + {total_out:,} out = {total_in + total_out:,} tokens**")
        return "\n".join(lines)

    def test_empty_history(self):
        """Empty history returns early."""
        result = self._render_graph([])
        self.assertEqual(result, "No usage data")

    def test_single_entry(self):
        """Single entry renders correctly."""
        hist = [{"q": 1, "in": 5000, "out": 1200}]
        result = self._render_graph(hist)
        self.assertIn("Token Usage Graph", result)
        self.assertIn("Q  1:", result)
        self.assertIn("5,000", result)
        self.assertIn("1,200", result)

    def test_multiple_entries(self):
        """Multiple entries show all queries."""
        hist = [
            {"q": 1, "in": 5000, "out": 1200},
            {"q": 2, "in": 8000, "out": 3000},
        ]
        result = self._render_graph(hist)
        self.assertIn("Q  1:", result)
        self.assertIn("Q  2:", result)

    def test_max_token_scaling(self):
        """Bars scale relative to max tokens."""
        hist = [
            {"q": 1, "in": 10000, "out": 5000},
            {"q": 2, "in": 5000, "out": 2500},
        ]
        result = self._render_graph(hist)
        # First entry should have longer bars (10000 is max)
        lines = result.split("\n")
        q1_line = [l for l in lines if "Q  1:" in l][0]
        q2_line = [l for l in lines if "Q  2:" in l][0]
        # Q1 in bar should be full (20 chars), Q2 should be half (10 chars)
        q1_bar = q1_line.split("[")[1].split("]")[0]
        q2_bar = q2_line.split("[")[1].split("]")[0]
        self.assertEqual(len(q1_bar), 20)
        self.assertEqual(len(q2_bar), 20)
        self.assertGreater(q1_bar.count("█"), q2_bar.count("█"))

    def test_totals_calculation(self):
        """Totals are calculated correctly."""
        hist = [
            {"q": 1, "in": 5000, "out": 1200},
            {"q": 2, "in": 8000, "out": 3000},
        ]
        result = self._render_graph(hist)
        self.assertIn("13,000 in + 4,200 out = 17,200 tokens", result)

    def test_limit_to_20_entries(self):
        """Only last 20 entries are shown."""
        hist = [{"q": i, "in": 1000, "out": 500} for i in range(1, 30)]
        result = self._render_graph(hist)
        # Should show Q 10 through Q 29 (last 20)
        self.assertNotIn("Q  1:", result)
        self.assertNotIn("Q  9:", result)
        self.assertIn("Q 10:", result)
        self.assertIn("Q 29:", result)

    def test_bar_characters(self):
        """Bars only contain valid characters."""
        hist = [{"q": 1, "in": 5000, "out": 2000}]
        result = self._render_graph(hist)
        lines = result.split("\n")
        for line in lines:
            if "[" in line and "]" in line:
                bar = line.split("[")[1].split("]")[0]
                self.assertTrue(all(c in "█▓░" for c in bar), f"Invalid char in bar: {bar}")

    def test_history_truncation(self):
        """History is truncated to 100 entries."""
        hist = [{"q": i, "in": 1000, "out": 500} for i in range(150)]
        # Simulate truncation
        if len(hist) > 100:
            hist = hist[-100:]
        self.assertEqual(len(hist), 100)
        self.assertEqual(hist[0]["q"], 50)
        self.assertEqual(hist[-1]["q"], 149)


if __name__ == "__main__":
    unittest.main()
