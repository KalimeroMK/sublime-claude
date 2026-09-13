"""Tests for the panel-hosted PTY terminal.

The panel used to be a text appender: `create_output_panel` on every show
(which wipes the buffer), a single CSI regex that missed OSC and private-mode
sequences, and no handling of `\r` or `\x1b[2J` at all.
"""
import unittest

from tests.plugin_pkg import load

ct = load("commands_terminal")


class FakeSettings:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, default)

    def erase(self, key):
        self.values.pop(key, None)


class FakeView:
    _next_id = 1

    def __init__(self):
        FakeView._next_id += 1
        self._id = FakeView._next_id
        self._settings = FakeSettings()
        self.commands = []

    def id(self):
        return self._id

    def settings(self):
        return self._settings

    def run_command(self, name, args=None):
        self.commands.append((name, args))


class FakeWindow:
    def __init__(self, active_panel=None):
        self.panels = {}
        self.created = []
        self._active_panel = active_panel
        self.commands = []
        self.focused = None

    def find_output_panel(self, name):
        return self.panels.get(name)

    def create_output_panel(self, name):
        # the real API returns the same view but empties it
        self.created.append(name)
        view = FakeView()
        self.panels[name] = view
        return view

    def active_panel(self):
        return self._active_panel

    def run_command(self, name, args=None):
        self.commands.append((name, args))
        if name == "show_panel":
            self._active_panel = args["panel"]
        elif name == "hide_panel":
            self._active_panel = None

    def focus_view(self, view):
        self.focused = view

    def folders(self):
        return ["/proj"]


class FakeScreen:
    def __init__(self, display):
        self.display = display


class FakeTerminal:
    def __init__(self, alive=True, display=("",)):
        self.alive = alive
        self.screen = FakeScreen(list(display))
        self.sent = []

    def is_alive(self):
        return self.alive

    def send_string(self, text):
        self.sent.append(text)


class PanelViewTest(unittest.TestCase):
    def test_existing_panel_is_reused_not_recreated(self):
        """create_output_panel empties the panel it returns, so recreating on
        every show wiped the whole scrollback."""
        w = FakeWindow()
        first = ct.panel_view(w, create=True)
        again = ct.panel_view(w, create=True)
        self.assertIs(first, again)
        self.assertEqual(w.created, [ct.PANEL_NAME])

    def test_missing_panel_without_create_is_none(self):
        self.assertIsNone(ct.panel_view(FakeWindow(), create=False))

    def test_new_panel_is_marked_as_a_terminal(self):
        """The package's 273 terminal key bindings all match on this setting;
        without it every keystroke goes to the editor instead of the shell."""
        view = ct.panel_view(FakeWindow(), create=True)
        self.assertTrue(view.settings().get("claude_terminal"))

    def test_new_panel_disables_editor_chrome(self):
        settings = ct.panel_view(FakeWindow(), create=True).settings()
        self.assertFalse(settings.get("gutter"))
        self.assertFalse(settings.get("line_numbers"))
        self.assertFalse(settings.get("word_wrap"))


class PanelVisibilityTest(unittest.TestCase):
    def test_visible_when_it_is_the_active_panel(self):
        self.assertTrue(ct.panel_is_visible(FakeWindow(active_panel=ct.PANEL_ID)))

    def test_not_visible_when_another_panel_is_active(self):
        self.assertFalse(ct.panel_is_visible(FakeWindow(active_panel="output.find_results")))

    def test_not_visible_when_no_panel_is_open(self):
        self.assertFalse(ct.panel_is_visible(FakeWindow()))

    def test_panel_id_is_the_output_prefixed_name(self):
        self.assertEqual(ct.PANEL_ID, "output." + ct.PANEL_NAME)


class SendWhenReadyTest(unittest.TestCase):
    def setUp(self):
        self._real = ct._get_terminal

    def tearDown(self):
        ct._get_terminal = self._real

    def _install(self, terminal):
        ct._get_terminal = lambda _view: terminal
        return terminal

    def test_sends_at_once_when_the_prompt_is_up(self):
        term = self._install(FakeTerminal(display=["$ "]))
        ct.send_when_ready(FakeView(), "ls\n")
        self.assertEqual(term.sent, ["ls\n"])

    def test_waits_while_the_screen_is_still_blank(self):
        """A freshly spawned `zsh -i -l` sources its rc files before reading
        stdin; anything written in that window is swallowed silently."""
        term = self._install(FakeTerminal(display=["", "   "]))
        ct.send_when_ready(FakeView(), "ls\n", attempts=3)
        # mock set_timeout runs callbacks inline, so the retries are exhausted
        # and the text is sent once rather than dropped
        self.assertEqual(term.sent, ["ls\n"])

    def test_never_sends_to_a_dead_shell(self):
        term = self._install(FakeTerminal(alive=False, display=["$ "]))
        ct.send_when_ready(FakeView(), "ls\n")
        self.assertEqual(term.sent, [])

    def test_no_terminal_is_not_an_error(self):
        ct._get_terminal = lambda _view: None
        ct.send_when_ready(FakeView(), "ls\n")  # must not raise


if __name__ == "__main__":
    unittest.main()
