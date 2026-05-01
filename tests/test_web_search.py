"""Tests for DuckDuckGo web search module."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_search import _parse_lite_results, _parse_html_results


class WebSearchTest(unittest.TestCase):
    """Test DuckDuckGo result parsing."""

    def test_parse_lite_results_basic(self):
        """Parse basic DuckDuckGo Lite HTML."""
        html = '''
        <table>
        <tr><td><a class="result-link" href="https://example.com">Example Site</a></td></tr>
        <tr><td class="result-snippet">This is a description of the example.</td></tr>
        </table>
        <table>
        <tr><td><a class="result-link" href="https://test.org">Test Org</a></td></tr>
        <tr><td class="result-snippet">Another description here.</td></tr>
        </table>
        '''
        results = _parse_lite_results(html)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Example Site")
        self.assertEqual(results[0]["url"], "https://example.com")
        self.assertEqual(results[0]["snippet"], "This is a description of the example.")
        self.assertEqual(results[1]["title"], "Test Org")
        self.assertEqual(results[1]["url"], "https://test.org")

    def test_parse_lite_results_skips_internal_links(self):
        """Skip DuckDuckGo internal redirect links."""
        html = '''
        <a class="result-link" href="/l/?kh=-1">Internal Link</a>
        <td class="result-snippet">Should be skipped.</td>
        <a class="result-link" href="https://real.com">Real Site</a>
        <td class="result-snippet">Should be included.</td>
        '''
        results = _parse_lite_results(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Real Site")
        self.assertEqual(results[0]["url"], "https://real.com")

    def test_parse_lite_results_limits_to_five(self):
        """Parser limits results to 5."""
        html = ""
        for i in range(10):
            html += f'<a class="result-link" href="https://site{i}.com">Site {i}</a>'
            html += f'<td class="result-snippet">Desc {i}</td>'
        results = _parse_lite_results(html)
        self.assertEqual(len(results), 5)

    def test_parse_lite_results_strips_tags(self):
        """HTML tags are stripped from title and snippet."""
        html = '''
        <a class="result-link" href="https://example.com"><b>Bold</b> Title</a>
        <td class="result-snippet">Some <em>emphasis</em> here.</td>
        '''
        results = _parse_lite_results(html)
        self.assertEqual(results[0]["title"], "Bold Title")
        self.assertEqual(results[0]["snippet"], "Some emphasis here.")

    def test_parse_lite_results_empty_html(self):
        """Empty HTML returns empty list."""
        results = _parse_lite_results("")
        self.assertEqual(results, [])

    def test_parse_html_results_basic(self):
        """Parse basic DuckDuckGo HTML results."""
        html = '''
        <div class="result results_links_deep">
            <a class="result__a" href="https://example.com">Example Site</a>
            <a class="result__snippet">Description of the site.</a>
        </div>
        <div class="result">
            <a class="result__a" href="https://test.org">Test Org</a>
            <a class="result__snippet">Another description.</a>
        </div>
        '''
        results = _parse_html_results(html)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Example Site")
        self.assertEqual(results[0]["url"], "https://example.com")
        self.assertEqual(results[0]["snippet"], "Description of the site.")

    def test_parse_html_results_skips_duckduckgo_links(self):
        """Skip DuckDuckGo internal links."""
        html = '''
        <div class="result">
            <a class="result__a" href="https://duckduckgo.com/y.js">Ad</a>
            <a class="result__snippet">Ad description.</a>
        </div>
        <div class="result">
            <a class="result__a" href="https://real.com">Real Site</a>
            <a class="result__snippet">Real description.</a>
        </div>
        '''
        results = _parse_html_results(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://real.com")

    def test_parse_html_results_empty(self):
        """Empty HTML returns empty list."""
        results = _parse_html_results("")
        self.assertEqual(results, [])

    def test_parse_html_results_limits_to_five(self):
        """Parser limits results to 5."""
        html = ""
        for i in range(10):
            html += f'<div class="result">'
            html += f'<a class="result__a" href="https://site{i}.com">Site {i}</a>'
            html += f'<a class="result__snippet">Desc {i}</a>'
            html += '</div>'
        results = _parse_html_results(html)
        self.assertEqual(len(results), 5)


if __name__ == "__main__":
    unittest.main()
