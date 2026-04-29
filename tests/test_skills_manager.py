"""Tests for skills_manager.py."""
import json
import os
import tempfile
import shutil
import unittest

# Ensure project root is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills_manager import (
    load_marketplace,
    get_active_skills,
    is_skill_active,
    toggle_skill,
    set_skill_state,
    _build_skills_content,
    _inject_into_claude_md,
    rebuild_global_claude_md,
    rebuild_project_claude_md,
    rebuild_all,
    get_skill_status,
    list_installed_skills,
    SKILLS_START_MARKER,
    SKILLS_END_MARKER,
)


class TestSkillsManager(unittest.TestCase):
    """Test skills manager functionality."""

    def setUp(self):
        """Set up temporary directories for each test."""
        self.temp_dir = tempfile.mkdtemp(prefix="skills_test_")
        self.project_dir = os.path.join(self.temp_dir, "project")
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, ".claude"), exist_ok=True)

        # Patch base dir
        import skills_manager
        self._orig_base_dir = skills_manager._SKILLES_BASE_DIR
        self._orig_global_manifest = skills_manager._GLOBAL_MANIFEST_PATH
        skills_manager._SKILLES_BASE_DIR = os.path.join(self.temp_dir, "skills")
        skills_manager._GLOBAL_MANIFEST_PATH = os.path.join(self.temp_dir, "skills", "global_manifest.json")
        os.makedirs(skills_manager._SKILLES_BASE_DIR, exist_ok=True)

        self.marketplace = {
            "php-strict": {
                "name": "PHP Strict",
                "description": "Strict PHP",
                "category": "backend",
                "content": "# PHP Strict\n- Use strict_types=1."
            },
            "react-modern": {
                "name": "React Modern",
                "description": "React 19",
                "category": "frontend",
                "content": "# React Modern\n- Use hooks."
            },
            "security-owasp": {
                "name": "Security OWASP",
                "description": "OWASP",
                "category": "security",
                "content": "# Security\n- Never trust input."
            },
        }

    def tearDown(self):
        """Clean up temporary directories."""
        import skills_manager
        skills_manager._SKILLES_BASE_DIR = self._orig_base_dir
        skills_manager._GLOBAL_MANIFEST_PATH = self._orig_global_manifest
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_marketplace_from_file(self):
        """Test loading marketplace from JSON file."""
        marketplace_path = os.path.join(self.temp_dir, "marketplace.json")
        with open(marketplace_path, "w") as f:
            json.dump({
                "version": "1.0",
                "skills": self.marketplace
            }, f)

        result = load_marketplace(marketplace_path)
        self.assertEqual(len(result), 3)
        self.assertIn("php-strict", result)
        self.assertEqual(result["php-strict"]["name"], "PHP Strict")

    def test_load_marketplace_missing_file(self):
        """Test loading marketplace with missing file returns empty."""
        result = load_marketplace(os.path.join(self.temp_dir, "nonexistent.json"))
        self.assertEqual(result, {})

    def test_get_active_skills_empty(self):
        """Test getting active skills when none are set."""
        result = get_active_skills("global")
        self.assertEqual(result, [])

    def test_set_skill_state_global(self):
        """Test enabling a skill globally."""
        result = set_skill_state("php-strict", "global", True)
        self.assertTrue(result)
        self.assertTrue(is_skill_active("php-strict", "global"))
        self.assertEqual(get_active_skills("global"), ["php-strict"])

    def test_set_skill_state_project(self):
        """Test enabling a skill per-project."""
        result = set_skill_state("react-modern", "project", True, self.project_dir)
        self.assertTrue(result)
        self.assertTrue(is_skill_active("react-modern", "project", self.project_dir))
        self.assertEqual(get_active_skills("project", self.project_dir), ["react-modern"])

    def test_toggle_skill(self):
        """Test toggling a skill on and off."""
        # Toggle on
        state = toggle_skill("php-strict", "global")
        self.assertTrue(state)
        self.assertTrue(is_skill_active("php-strict", "global"))

        # Toggle off
        state = toggle_skill("php-strict", "global")
        self.assertFalse(state)
        self.assertFalse(is_skill_active("php-strict", "global"))

    def test_multiple_skills(self):
        """Test managing multiple skills."""
        set_skill_state("php-strict", "global", True)
        set_skill_state("react-modern", "global", True)
        set_skill_state("security-owasp", "global", True)

        active = get_active_skills("global")
        self.assertEqual(len(active), 3)
        self.assertIn("php-strict", active)
        self.assertIn("react-modern", active)
        self.assertIn("security-owasp", active)

    def test_disable_skill(self):
        """Test disabling a specific skill."""
        set_skill_state("php-strict", "global", True)
        set_skill_state("react-modern", "global", True)

        set_skill_state("php-strict", "global", False)
        active = get_active_skills("global")
        self.assertEqual(active, ["react-modern"])

    def test_build_skills_content(self):
        """Test building markdown content from active skills."""
        content = _build_skills_content(["php-strict", "react-modern"], self.marketplace)
        self.assertIn(SKILLS_START_MARKER, content)
        self.assertIn(SKILLS_END_MARKER, content)
        self.assertIn("# PHP Strict", content)
        self.assertIn("# React Modern", content)
        self.assertNotIn("# Security", content)

    def test_build_skills_content_empty(self):
        """Test building content with no active skills."""
        content = _build_skills_content([], self.marketplace)
        self.assertIn(SKILLS_START_MARKER, content)
        self.assertIn(SKILLS_END_MARKER, content)

    def test_build_skills_content_unknown_skill(self):
        """Test building content with unknown skill ID."""
        content = _build_skills_content(["unknown-skill"], self.marketplace)
        self.assertIn(SKILLS_START_MARKER, content)
        # Should not crash, just skip unknown skill
        self.assertIn(SKILLS_END_MARKER, content)

    def test_inject_into_claude_md_new_file(self):
        """Test injecting skills into a new CLAUDE.md file."""
        claude_md = os.path.join(self.temp_dir, "CLAUDE.md")
        result = _inject_into_claude_md(claude_md, ["php-strict"], self.marketplace)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(claude_md))

        with open(claude_md, "r") as f:
            content = f.read()
        self.assertIn("# PHP Strict", content)
        self.assertIn(SKILLS_START_MARKER, content)
        self.assertIn(SKILLS_END_MARKER, content)

    def test_inject_into_claude_md_preserves_user_content(self):
        """Test that user content is preserved when injecting skills."""
        claude_md = os.path.join(self.temp_dir, "CLAUDE.md")
        user_content = "# My Project\n\nThis is my custom CLAUDE.md content.\n"
        with open(claude_md, "w") as f:
            f.write(user_content)

        result = _inject_into_claude_md(claude_md, ["php-strict"], self.marketplace)
        self.assertTrue(result)

        with open(claude_md, "r") as f:
            content = f.read()

        self.assertIn("# My Project", content)
        self.assertIn("# PHP Strict", content)
        self.assertIn(SKILLS_START_MARKER, content)

    def test_inject_removes_old_section(self):
        """Test that old skills section is replaced, not duplicated."""
        claude_md = os.path.join(self.temp_dir, "CLAUDE.md")
        # First inject
        _inject_into_claude_md(claude_md, ["php-strict"], self.marketplace)
        # Second inject with different skill
        _inject_into_claude_md(claude_md, ["react-modern"], self.marketplace)

        with open(claude_md, "r") as f:
            content = f.read()

        # Should only have one skills section
        self.assertEqual(content.count(SKILLS_START_MARKER), 1)
        self.assertIn("# React Modern", content)
        self.assertNotIn("# PHP Strict", content)

    def test_inject_empty_skills_removes_section(self):
        """Test that empty skills list removes the managed section."""
        claude_md = os.path.join(self.temp_dir, "CLAUDE.md")
        user_content = "# My Project\n\nKeep this.\n"
        with open(claude_md, "w") as f:
            f.write(user_content)

        # Add skills
        _inject_into_claude_md(claude_md, ["php-strict"], self.marketplace)
        # Remove all skills
        result = _inject_into_claude_md(claude_md, [], self.marketplace)
        self.assertTrue(result)

        with open(claude_md, "r") as f:
            content = f.read()

        self.assertNotIn(SKILLS_START_MARKER, content)
        self.assertIn("# My Project", content)

    def test_rebuild_global_claude_md(self):
        """Test rebuilding global CLAUDE.md."""
        import skills_manager
        original_path = os.path.expanduser("~/.claude/CLAUDE.md")
        # We'll test with a temp file by using inject directly
        set_skill_state("php-strict", "global", True)
        result = rebuild_global_claude_md(self.marketplace)
        self.assertTrue(result)

        # Verify file was created
        self.assertTrue(os.path.exists(skills_manager._GLOBAL_MANIFEST_PATH))

    def test_rebuild_project_claude_md(self):
        """Test rebuilding project CLAUDE.md."""
        set_skill_state("react-modern", "project", True, self.project_dir)
        result = rebuild_project_claude_md(self.project_dir, self.marketplace)
        self.assertTrue(result)

        claude_md = os.path.join(self.project_dir, "CLAUDE.md")
        self.assertTrue(os.path.exists(claude_md))

        with open(claude_md, "r") as f:
            content = f.read()
        self.assertIn("# React Modern", content)

    def test_rebuild_all(self):
        """Test rebuilding both global and project files."""
        set_skill_state("php-strict", "global", True)
        set_skill_state("react-modern", "project", True, self.project_dir)

        g_ok, p_ok = rebuild_all(self.project_dir, self.marketplace)
        self.assertTrue(g_ok)
        self.assertTrue(p_ok)

    def test_get_skill_status(self):
        """Test getting skill status in both scopes."""
        set_skill_state("php-strict", "global", True)
        set_skill_state("react-modern", "project", True, self.project_dir)

        status = get_skill_status("php-strict", self.project_dir)
        self.assertTrue(status["global"])
        self.assertFalse(status["project"])

        status = get_skill_status("react-modern", self.project_dir)
        self.assertFalse(status["global"])
        self.assertTrue(status["project"])

    def test_list_installed_skills(self):
        """Test listing skills with their status."""
        set_skill_state("php-strict", "global", True)
        set_skill_state("react-modern", "project", True, self.project_dir)

        skills = list_installed_skills(self.project_dir)
        # Sorting should put active skills first
        self.assertTrue(skills[0]["global_active"] or skills[0]["project_active"])

        php = next(s for s in skills if s["id"] == "php-strict")
        self.assertTrue(php["global_active"])
        self.assertFalse(php["project_active"])

        react = next(s for s in skills if s["id"] == "react-modern")
        self.assertFalse(react["global_active"])
        self.assertTrue(react["project_active"])

    def test_list_without_project(self):
        """Test listing skills without a project root."""
        set_skill_state("php-strict", "global", True)
        skills = list_installed_skills(None)

        php = next(s for s in skills if s["id"] == "php-strict")
        self.assertTrue(php["global_active"])
        self.assertFalse(php["project_active"])

    def test_unknown_skill_not_in_marketplace(self):
        """Test handling skills not in marketplace gracefully."""
        set_skill_state("nonexistent", "global", True)
        active = get_active_skills("global")
        self.assertIn("nonexistent", active)

        # Building content should skip it
        content = _build_skills_content(["nonexistent"], self.marketplace)
        self.assertNotIn("nonexistent", content)
        self.assertIn(SKILLS_START_MARKER, content)


if __name__ == "__main__":
    unittest.main()
