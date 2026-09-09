"""Tests for lsp_install. No dialogs are shown — the prompt function is injected."""
import unittest

from tests.plugin_pkg import load

install = load("lsp_install")


class Recorder:
    """Captures prompts and installs instead of performing them."""

    def __init__(self, answer="install"):
        self.answer = answer
        self.prompts = []
        self.installed = []
        self.saved = []

    def prompt(self, packages, reason):
        self.prompts.append({"packages": list(packages), "reason": reason})
        return self.answer

    def install(self, packages):
        self.installed.append(list(packages))

    def save(self, value):
        self.saved.append(value)


def check(rec, present=(), folders=("/proj",), markers=(), setting="ask"):
    return install.check(
        installed=lambda name: name in present,
        marker_exists=lambda path: any(path.endswith(m) for m in markers),
        folders=list(folders),
        setting=setting,
        prompt=rec.prompt,
        install=rec.install,
        save_setting=rec.save,
    )


class LanguageServerForTest(unittest.TestCase):
    def test_composer_json_means_php(self):
        self.assertEqual(install.server_for_markers(["composer.json"]), "LSP-intelephense")

    def test_package_json_means_typescript(self):
        self.assertEqual(install.server_for_markers(["package.json"]), "LSP-typescript")

    def test_go_mod_means_gopls(self):
        self.assertEqual(install.server_for_markers(["go.mod"]), "LSP-gopls")

    def test_cargo_toml_means_rust_analyzer(self):
        self.assertEqual(install.server_for_markers(["Cargo.toml"]), "LSP-rust-analyzer")

    def test_pyproject_means_pyright(self):
        self.assertEqual(install.server_for_markers(["pyproject.toml"]), "LSP-pyright")

    def test_unknown_project_has_no_server(self):
        self.assertIsNone(install.server_for_markers(["Makefile"]))


class CheckTest(unittest.TestCase):
    def test_prompts_for_lsp_when_missing(self):
        rec = Recorder()
        check(rec, present=(), markers=("composer.json",))
        self.assertEqual(rec.prompts[0]["packages"], ["LSP", "LSP-intelephense"])
        self.assertEqual(rec.installed, [["LSP", "LSP-intelephense"]])

    def test_prompts_for_server_only_when_lsp_present(self):
        rec = Recorder()
        check(rec, present=("LSP",), markers=("composer.json",))
        self.assertEqual(rec.prompts[0]["packages"], ["LSP-intelephense"])

    def test_silent_when_everything_is_installed(self):
        rec = Recorder()
        check(rec, present=("LSP", "LSP-intelephense"), markers=("composer.json",))
        self.assertEqual(rec.prompts, [])
        self.assertEqual(rec.installed, [])

    def test_prompts_for_lsp_alone_when_language_is_unknown(self):
        rec = Recorder()
        check(rec, present=(), markers=("Makefile",))
        self.assertEqual(rec.prompts[0]["packages"], ["LSP"])

    def test_never_is_remembered(self):
        rec = Recorder(answer="never")
        check(rec, present=(), markers=("composer.json",))
        self.assertEqual(rec.installed, [])
        self.assertEqual(rec.saved, ["never"])

    def test_not_now_is_not_remembered(self):
        rec = Recorder(answer="later")
        check(rec, present=(), markers=("composer.json",))
        self.assertEqual(rec.installed, [])
        self.assertEqual(rec.saved, [])

    def test_setting_never_suppresses_the_prompt(self):
        rec = Recorder()
        check(rec, present=(), markers=("composer.json",), setting="never")
        self.assertEqual(rec.prompts, [])

    def test_no_folders_means_no_prompt(self):
        """Nothing to detect a language from, so stay quiet."""
        rec = Recorder()
        check(rec, present=(), folders=(), markers=())
        self.assertEqual(rec.prompts, [])


if __name__ == "__main__":
    unittest.main()
