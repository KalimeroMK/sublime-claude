"""Every bridge must import without executing its main loop.

bridge/openai_main.py shipped with `sys.path.insert(0, str(Path(...)))` at
module top but no `from pathlib import Path`, so the process died with
NameError the instant Sublime spawned it — the whole OpenAI/Ollama backend was
dead and nothing caught it, because a missing import is a runtime error that
py_compile does not see. Importing the module does.
"""
import glob
import importlib
import os
import sys
import unittest

BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge")


class BridgeImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # bridges resolve `from settings import ...` etc. against their own dir
        if BRIDGE_DIR not in sys.path:
            sys.path.insert(0, BRIDGE_DIR)

    def _import(self, name):
        # the __main__ guard keeps asyncio.run() from firing on import
        sys.modules.pop(name, None)
        importlib.import_module(name)

    def test_openai_main_imports(self):
        self._import("openai_main")

    def test_all_bridge_mains_import(self):
        for path in sorted(glob.glob(os.path.join(BRIDGE_DIR, "*_main.py"))):
            name = os.path.splitext(os.path.basename(path))[0]
            with self.subTest(bridge=name):
                self._import(name)

    def test_bridge_support_modules_import(self):
        for name in ("base", "rpc_helpers", "settings"):
            with self.subTest(module=name):
                self._import(name)


if __name__ == "__main__":
    unittest.main()
