"""Claude Code plugin for Sublime Text.

Session accessor facade. NOT a registration surface.

Sublime scans every top-level .py in the package (sublime_plugin.load_module)
and registers any command/listener class it finds in the module dict —
including *imported* ones. Every commands_*.py, output.py and listeners.py is
already top-level, so re-exporting their classes here registered each one a
2nd/3rd time: 186 registrations for 102 commands, and ClaudeCodeEventListener
twice, so every on_activated/on_close/on_post_save fired twice.

__all__ is honoured by load_module, so it pins this module to functions only.
Do not add classes here, and do not re-export plugin_loaded/plugin_unloaded —
plugin_loaded dispatch uses getattr(module, ...) and ignores __all__, so a
re-export makes core.py's lifecycle hooks run twice.
"""

from .core import (
    get_session_for_view,
    get_active_session,
    create_session,
)

__all__ = [
    "get_session_for_view",
    "get_active_session",
    "create_session",
]

# Removed — each caused duplicate registration (see module docstring):
#
# from .core import plugin_loaded, plugin_unloaded   # core.py is top-level
# from .commands import (ClaudeCodeStartCommand, ...) # commands_*.py are top-level
# from .output import ClaudeInsertCommand, ClaudeReplaceCommand
# from .listeners import ClaudeCodeEventListener, ClaudeOutputEventListener
