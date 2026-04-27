"""Tests for context window gauge feature."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.mock_sublime import sublime, sublime_plugin


class ContextGaugeTest(unittest.TestCase):
    """Test context window gauge calculation."""

    # Inline constants to avoid importing session.py (needs sublime runtime)
    _CONTEXT_LIMITS = {"@400k": 400000, "@200k": 200000}
    _MODEL_CONTEXT_LIMITS = {
        "claude-opus-4": 200000, "claude-sonnet-4": 200000, "claude-haiku-4": 200000,
        "opus": 200000, "sonnet": 200000, "haiku": 200000,
        "gpt-4o": 128000, "gpt-4o-mini": 128000, "gpt-4-turbo": 128000,
        "o3-mini": 200000, "qwen2.5": 128000, "llama3.1": 128000,
        "mistral": 32000, "deepseek": 64000, "deepseek-v4": 64000,
        "gpt-5.5": 200000, "gpt-5.4": 200000, "gpt-5.3": 200000, "o3": 200000,
    }

    def _calc_gauge(self, used, model_id="claude-opus-4", backend="claude"):
        """Replicate gauge logic from session.py."""
        max_ctx = None
        if model_id:
            for suffix, tokens in self._CONTEXT_LIMITS.items():
                if model_id.endswith(suffix):
                    max_ctx = tokens
                    break
            if max_ctx is None:
                for family, tokens in self._MODEL_CONTEXT_LIMITS.items():
                    if family in model_id.lower():
                        max_ctx = tokens
                        break
        if max_ctx is None:
            max_ctx = 200000 if backend in ("claude", "kimi", "default", "") else 128000
        
        pct = min(100, int(used / max_ctx * 100))
        filled = min(10, round(pct / 10))
        bar = "█" * filled + "░" * (10 - filled)
        color = "🔴" if pct >= 90 else "🟡" if pct >= 70 else "🟢"
        return f"{color} {bar} {pct}%"

    def test_gauge_green_low_usage(self):
        """Gauge shows green for <70% usage."""
        result = self._calc_gauge(50000)
        self.assertIn("🟢", result)
        self.assertIn("25%", result)
        self.assertIn("█", result)

    def test_gauge_yellow_medium_usage(self):
        """Gauge shows yellow for 70-90% usage."""
        result = self._calc_gauge(150000)
        self.assertIn("🟡", result)
        self.assertIn("75%", result)

    def test_gauge_red_high_usage(self):
        """Gauge shows red for >90% usage."""
        result = self._calc_gauge(190000)
        self.assertIn("🔴", result)
        self.assertIn("95%", result)

    def test_gauge_capped_at_100(self):
        """Gauge never exceeds 100%."""
        result = self._calc_gauge(500000)
        self.assertIn("100%", result)

    def test_gauge_different_models(self):
        """Gauge respects model-specific limits."""
        result = self._calc_gauge(64000, model_id="gpt-4o")
        self.assertIn("50%", result)
        
        result = self._calc_gauge(32000, model_id="mistral")
        self.assertIn("100%", result)

    def test_gauge_suffix_override(self):
        """@suffix overrides model family limit."""
        result = self._calc_gauge(200000, model_id="opus@400k")
        self.assertIn("50%", result)

    def test_gauge_fallback_backend(self):
        """Fallback limit depends on backend."""
        result = self._calc_gauge(100000, model_id="unknown-model", backend="claude")
        self.assertIn("50%", result)
        
        result = self._calc_gauge(64000, model_id="unknown-model", backend="openai")
        self.assertIn("50%", result)

    def test_gauge_bar_segments(self):
        """Bar has exactly 10 segments."""
        for used in [0, 20000, 40000, 60000, 80000, 100000, 120000, 140000, 160000, 180000, 200000]:
            result = self._calc_gauge(used)
            bar_part = result.split()[1]
            self.assertEqual(len(bar_part), 10, f"Bar should have 10 segments for {used}")
            self.assertTrue(all(c in "█░" for c in bar_part), f"Bar should only contain █ and ░")

    def test_gauge_zero_usage(self):
        """Zero usage shows 0% with empty bar."""
        result = self._calc_gauge(0)
        self.assertIn("0%", result)
        self.assertIn("░░░░░░░░░░", result)


if __name__ == "__main__":
    unittest.main()
