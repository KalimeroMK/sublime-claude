"""Import the real plugin modules so tests exercise them, not a copy.

Plugin modules use relative imports (`from .session import ...`), so they are
only importable as part of a package. This aliases the repo root as package
"CC" and imports through it — that is what lets a test call the real
core._check_auto_sleep instead of reimplementing its logic.
"""
import importlib
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_sublime import sublime, sublime_plugin  # noqa: E402  installs mocks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "CC"

if PKG not in sys.modules:
    _pkg = types.ModuleType(PKG)
    _pkg.__path__ = [ROOT]
    sys.modules[PKG] = _pkg


def load(name):
    """Import a real plugin module by its bare name (e.g. "core")."""
    return importlib.import_module("{}.{}".format(PKG, name))


def reset_sessions():
    """Replace the global session registry with a fresh dict."""
    sublime._claude_sessions = {}
    return sublime._claude_sessions


class FakeSettings:
    """Settings double with a real .get — MagicMock.get returns a MagicMock,
    which blows up on the `timeout_min <= 0` comparison in _check_auto_sleep."""

    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        self._values[key] = value

    def clear_on_change(self, key):
        pass

    def add_on_change(self, key, cb):
        pass


class RecordingTimeout:
    """Captures set_timeout callbacks instead of running them.

    mock_sublime runs set_timeout callbacks synchronously; _check_auto_sleep
    re-arms itself through set_timeout, so the mock default would recurse
    forever. Install this, then call run_pending() explicitly.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, fn, ms=0):
        self.calls.append((fn, ms))
        return len(self.calls)

    def run_pending(self):
        pending, self.calls = self.calls, []
        for fn, _ms in pending:
            fn()
