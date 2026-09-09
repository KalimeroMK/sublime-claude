"""Tests for the real ClaudeCodeEventListener in listeners.py.

This listener was registered twice (once from listeners.py, once via the
re-export in claude_code.py), so every on_close/on_activated/on_post_save ran
twice. The re-export is gone; these tests cover what the handlers actually do,
so a second regression in session teardown or settings reload is caught here.
"""
import unittest

from tests.plugin_pkg import FakeSettings, load, reset_sessions, sublime

listeners = load("listeners")
OUTPUT_VIEW_SETTING = load("constants").OUTPUT_VIEW_SETTING


class FakeView:
    def __init__(self, vid=1, is_output=False, file_name=None, window=None):
        self._id = vid
        self._settings = FakeSettings({OUTPUT_VIEW_SETTING: is_output} if is_output else {})
        self._file_name = file_name
        self._window = window
        self.closed = 0

    def id(self):
        return self._id

    def settings(self):
        return self._settings

    def file_name(self):
        return self._file_name

    def window(self):
        return self._window

    def close(self):
        self.closed += 1

    def is_scratch(self):
        return False


class FakeWindow:
    def __init__(self, groups=1, active_view=None, wid=1):
        self._groups = groups
        self._active_view = active_view
        self._id = wid
        self._index = {}
        self._group_views = {0: [], 1: []}
        self.moved = []

    def num_groups(self):
        return self._groups

    def active_view(self):
        return self._active_view

    def get_view_index(self, view):
        return self._index.get(view.id(), (0, 0))

    def set_view_index(self, view, group, index):
        self.moved.append((view.id(), group, index))
        self._index[view.id()] = (group, index)

    def views_in_group(self, group):
        return self._group_views.get(group, [])


class FakeSession:
    def __init__(self, window=None, initialized=True, is_sleeping=False):
        self.window = window
        self.initialized = initialized
        self.is_sleeping = is_sleeping
        self.stopped = 0
        self.output = None

    def stop(self):
        self.stopped += 1


class ListenerTestBase(unittest.TestCase):
    def setUp(self):
        self.listener = listeners.ClaudeCodeEventListener()
        self.sessions = reset_sessions()
        self.settings = FakeSettings()
        self._orig_load = sublime.load_settings
        sublime.load_settings = lambda name: self.settings

    def tearDown(self):
        sublime.load_settings = self._orig_load


class OnCloseTest(ListenerTestBase):
    def test_closing_output_view_stops_and_deregisters_session(self):
        view = FakeView(vid=7, is_output=True)
        session = FakeSession()
        self.sessions[7] = session

        self.listener.on_close(view)

        self.assertEqual(session.stopped, 1)
        self.assertNotIn(7, self.sessions)

    def test_closing_untracked_view_is_a_noop(self):
        self.sessions[7] = FakeSession()
        self.listener.on_close(FakeView(vid=99))
        self.assertIn(7, self.sessions)

    def test_close_is_idempotent(self):
        """Guards the duplicate-listener failure mode: a second delivery of the
        same on_close must not raise on the already-removed session."""
        view = FakeView(vid=7, is_output=True)
        session = FakeSession()
        self.sessions[7] = session

        self.listener.on_close(view)
        self.listener.on_close(view)  # would KeyError if unguarded

        self.assertEqual(session.stopped, 1)


class OnPostSaveTest(ListenerTestBase):
    def _session_with_output(self):
        session = FakeSession()

        class Output:
            def __init__(self):
                self.applied = 0

            def _apply_output_settings(self):
                self.applied += 1

        session.output = Output()
        return session

    def test_saving_output_settings_reapplies_them(self):
        session = self._session_with_output()
        self.sessions[1] = session

        self.listener.on_post_save(FakeView(file_name="/x/ClaudeOutput.sublime-settings"))

        self.assertEqual(session.output.applied, 1)

    def test_saving_unrelated_file_does_nothing(self):
        session = self._session_with_output()
        self.sessions[1] = session

        self.listener.on_post_save(FakeView(file_name="/x/main.py"))

        self.assertEqual(session.output.applied, 0)

    def test_session_without_output_is_skipped(self):
        self.sessions[1] = FakeSession()
        self.listener.on_post_save(FakeView(file_name="/x/ClaudeOutput.sublime-settings"))

    def test_unsaved_view_without_filename_is_skipped(self):
        session = self._session_with_output()
        self.sessions[1] = session
        self.listener.on_post_save(FakeView(file_name=None))
        self.assertEqual(session.output.applied, 0)


class CloseWindowTest(ListenerTestBase):
    def test_close_window_stops_only_that_windows_sessions(self):
        win_a, win_b = FakeWindow(wid=1), FakeWindow(wid=2)
        a = FakeSession(window=win_a)
        b = FakeSession(window=win_b)
        self.sessions[1] = a
        self.sessions[2] = b

        self.listener.on_window_command(win_a, "close_window", {})

        self.assertEqual((a.stopped, b.stopped), (1, 0))
        self.assertNotIn(1, self.sessions)
        self.assertIn(2, self.sessions)

    def test_close_window_with_no_sessions_is_a_noop(self):
        self.listener.on_window_command(FakeWindow(), "close_window", {})
        self.assertEqual(self.sessions, {})


class EnsureLeftGroupTest(ListenerTestBase):
    def test_non_output_view_is_moved_out_of_right_group(self):
        window = FakeWindow(groups=2)
        view = FakeView(vid=5, window=window)
        window._index[5] = (1, 0)

        self.listener.on_load(view)

        self.assertEqual(window.moved, [(5, 0, 0)])

    def test_output_view_is_left_in_place(self):
        window = FakeWindow(groups=2)
        view = FakeView(vid=5, is_output=True, window=window)
        window._index[5] = (1, 0)

        self.listener.on_load(view)

        self.assertEqual(window.moved, [])

    def test_single_group_layout_is_untouched(self):
        window = FakeWindow(groups=1)
        view = FakeView(vid=5, window=window)
        window._index[5] = (0, 0)

        self.listener.on_load(view)

        self.assertEqual(window.moved, [])

    def test_view_already_in_left_group_is_untouched(self):
        window = FakeWindow(groups=2)
        view = FakeView(vid=5, window=window)
        window._index[5] = (0, 0)

        self.listener.on_load(view)

        self.assertEqual(window.moved, [])

    def test_view_without_window_is_a_noop(self):
        self.listener.on_load(FakeView(vid=5, window=None))


if __name__ == "__main__":
    unittest.main()
