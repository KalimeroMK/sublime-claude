"""Commands compatibility facade.

All command classes live in commands_*.py, each of which Sublime already loads
as a top-level plugin module. This module's star-imports therefore add nothing
to registration — they only made load_module register every class a second
time. __all__ is empty so load_module finds nothing to register here.

Kept as an import path for external/legacy callers; add nothing to __all__.
"""

from .commands_core import *      # noqa: F401,F403
from .commands_context import *   # noqa: F401,F403
from .commands_session import *   # noqa: F401,F403
from .commands_tools import *     # noqa: F401,F403
from .commands_ui import *        # noqa: F401,F403
from .commands_voice import *     # noqa: F401,F403

__all__ = []
