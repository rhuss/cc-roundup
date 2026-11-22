"""Plugin packaging: entry point from anywhere, skill frontmatter, manifests, versions."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import helpers

ROOT = helpers.REPO_ROOT
PLUGIN = helpers.PLUGIN_ROOT


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_help(self, script):
        return subprocess.run([sys.executable, script, "--help"], cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def test_entry_point_from_any_directory(self):
        proc = self.run_help(helpers.ROUNDUP_SCRIPT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gather", proc.stdout)

    def test_entry_point_via_symlink(self):
        link = os.path.join(self.tmp, "roundup-link")
        os.symlink(helpers.ROUNDUP_SCRIPT, link)
        proc = self.run_help(link)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_entry_point_is_executable(self):
        self.assertTrue(os.access(helpers.ROUNDUP_SCRIPT, os.X_OK))
        with open(helpers.ROUNDUP_SCRIPT, encoding="utf-8") as fh:
            self.assertEqual(fh.readline().strip(), "#!/usr/bin/env python3")

    def test_skill_frontmatter(self):
        text = read(PLUGIN, "skills", "roundup", "SKILL.md")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m)
        front = m.group(1)
        self.assertRegex(front, r"(?m)^name: roundup$")
        self.assertRegex(front, r"(?m)^description: \S.+$")
        self.assertTrue(os.path.exists(os.path.join(PLUGIN, "skills", "roundup", "rules.md")))

    def test_skill_uses_plugin_root_only(self):
        text = read(PLUGIN, "skills", "roundup", "SKILL.md")
        self.assertIn("<skill dir>/../..", text)
        self.assertIn("scripts/roundup", text)
        self.assertNotRegex(text, r"(?<![\w/])\./scripts/roundup")
        self.assertNotRegex(text, r"(?<![\w/\"])roundup/scripts/roundup")

    def test_codex_manifest_points_at_skills(self):
        manifest = json.loads(read(PLUGIN, ".codex-plugin", "plugin.json"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["name"], "roundup")

    def test_plugin_names(self):
        claude = json.loads(read(PLUGIN, ".claude-plugin", "plugin.json"))
        market = json.loads(read(ROOT, ".claude-plugin", "marketplace.json"))
        self.assertEqual(claude["name"], "roundup")
        self.assertEqual(market["name"], "corgi-roundup-plugin-development")
        self.assertEqual(market["plugins"][0]["name"], "roundup")
        self.assertEqual(claude["repository"], "https://github.com/rhuss/corgi-roundup")

    def test_versions_in_sync(self):
        versions = {
            "VERSION": read(ROOT, "VERSION").strip(),
            "roundup/VERSION": read(PLUGIN, "VERSION").strip(),
            "marketplace": json.loads(read(ROOT, ".claude-plugin", "marketplace.json"))
            ["plugins"][0]["version"],
            "claude manifest": json.loads(read(PLUGIN, ".claude-plugin", "plugin.json"))["version"],
            "codex manifest": json.loads(read(PLUGIN, ".codex-plugin", "plugin.json"))["version"],
        }
        self.assertEqual(len(set(versions.values())), 1, versions)


if __name__ == "__main__":
    unittest.main()
