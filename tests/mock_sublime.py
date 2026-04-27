"""Mock Sublime Text API for testing outside Sublime."""
import sys
from unittest.mock import MagicMock

# Create mock sublime module
sublime = MagicMock()
sublime.__version__ = "4200"
sublime.packages_path = MagicMock(return_value="/tmp/sublime-packages")
sublime.installed_packages_path = MagicMock(return_value="/tmp/sublime-installed-packages")
sublime.cache_path = MagicMock(return_value="/tmp/sublime-cache")
sublime.load_settings = MagicMock(return_value=MagicMock())
sublime.save_settings = MagicMock()
sublime.status_message = MagicMock()
sublime.message_dialog = MagicMock()
sublime.error_message = MagicMock()
sublime.ok_cancel_dialog = MagicMock(return_value=True)
sublime.yes_no_cancel_dialog = MagicMock(return_value=sublime.DIALOG_YES)
sublime.get_clipboard = MagicMock(return_value="")
sublime.set_clipboard = MagicMock()
sublime.get_macro = MagicMock(return_value=[])
sublime.log_commands = MagicMock()
sublime.log_input = MagicMock()
sublime.log_result_regex = MagicMock()
sublime.log_indexing = MagicMock()
sublime.log_build_systems = MagicMock()
sublime.log_control_tree = MagicMock()
sublime.command_url = MagicMock(return_value="")
sublime.rich_text = MagicMock(return_value="")
sublime.html = MagicMock(return_value="")
sublime.windows = MagicMock(return_value=[])
sublime.active_window = MagicMock(return_value=MagicMock())
sublime.set_timeout = lambda fn, ms=0: fn()
sublime.set_async_timeout = lambda fn, ms=0: fn()
sublime.cancel_timeout = MagicMock()
sublime.get_asset = MagicMock(return_value=b"")
sublime.arch = MagicMock(return_value="arm64")
sublime.platform = MagicMock(return_value="osx")
sublime.channel = MagicMock(return_value="stable")
sublime.version = MagicMock(return_value="4200")

# Mock Region class
class Region:
    def __init__(self, a, b=None):
        self.a = a
        self.b = b if b is not None else a
    
    def begin(self):
        return min(self.a, self.b)
    
    def end(self):
        return max(self.a, self.b)
    
    def size(self):
        return abs(self.b - self.a)
    
    def empty(self):
        return self.a == self.b
    
    def cover(self, other):
        return Region(min(self.begin(), other.begin()), max(self.end(), other.end()))
    
    def intersects(self, other):
        return not (self.end() <= other.begin() or self.begin() >= other.end())
    
    def contains(self, other):
        if isinstance(other, Region):
            return self.begin() <= other.begin() and self.end() >= other.end()
        return self.begin() <= other <= self.end()
    
    def __repr__(self):
        return f"Region({self.a}, {self.b})"
    
    def __eq__(self, other):
        if isinstance(other, Region):
            return self.a == other.a and self.b == other.b
        return False
    
    def __hash__(self):
        return hash((self.a, self.b))

sublime.Region = Region

# Constants
sublime.DIALOG_YES = 0
sublime.DIALOG_NO = 1
sublime.DIALOG_CANCEL = 2
sublime.KIND_KEYWORD = (1, "", "")
sublime.KIND_TYPE = (2, "", "")
sublime.KIND_FUNCTION = (3, "", "")
sublime.KIND_NAMESPACE = (4, "", "")
sublime.KIND_NAVIGATION = (5, "", "")
sublime.KIND_MARKUP = (6, "", "")
sublime.KIND_VARIABLE = (7, "", "")
sublime.KIND_SNIPPET = (8, "", "")

# Mock sublime_plugin module
sublime_plugin = MagicMock()
sublime_plugin.EventListener = object
sublime_plugin.ViewEventListener = object
sublime_plugin.ApplicationCommand = object
sublime_plugin.WindowCommand = object
sublime_plugin.TextCommand = object

# Install mocks
sys.modules['sublime'] = sublime
sys.modules['sublime_plugin'] = sublime_plugin

# Global session registry (used by core.py and listeners.py)
sublime._claude_sessions = {}
