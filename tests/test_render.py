"""judge-view and overview output through the command line."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import helpers

CLIP = {"status": "found", "method": "pbcopy", "args": "", "text": "Draft for Anna\nmore",
        "truncated": False, "at": "2026-11-21T10:00:00Z", "first_line": "Draft for Anna"}
MERGED = {"status": "found", "current": {"url": "https://github.com/me/app/pull/9",
                                         "state": "merged"}, "others": []}


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def files(self, sessions, judgments=None):
        d = helpers.write_json(os.path.join(self.tmp, "digest.json"), helpers.make_digest(sessions))
        j = helpers.write_json(os.path.join(self.tmp, "judgments.json"), {
            "format": "roundup-judgments", "version": 1, "sessions": judgments or {}})
        return d, j

    def run_cli(self, *args):
        return subprocess.run([sys.executable, helpers.ROUNDUP_SCRIPT] + list(args),
                              capture_output=True, text=True, timeout=60)

    def test_judge_view_pages(self):
        sessions = [helpers.make_session(i) for i in range(1, 26)]
        d, _ = self.files(sessions)
        p1 = self.run_cli("judge-view", "--digest", d)
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertEqual(p1.stdout.strip().splitlines()[-1], "page 1 of 2")
        self.assertEqual(sum(s["key"] in p1.stdout for s in sessions), 20)
        p2 = self.run_cli("judge-view", "--digest", d, "--page", "2")
        self.assertEqual(p2.stdout.strip().splitlines()[-1], "page 2 of 2")
        self.assertEqual(sum(s["key"] in p2.stdout for s in sessions), 5)
        self.assertIn("please do it", p2.stdout)  # recent messages are shown
        p3 = self.run_cli("judge-view", "--digest", d, "--page", "3")
        self.assertEqual(p3.returncode, 2)

    def test_overview_text(self):
        sessions = [
            helpers.make_session(1, pr=MERGED, name="merged work"),
            helpers.make_session(2, clipboard=CLIP, hibernated=True, name="clip work"),
            helpers.make_session(3, name="quiet work", changed_at="2026-11-17T12:00:00Z"),
        ]
        d, j = self.files(sessions, {sessions[1]["key"]: {
            "unanswered_agent": False, "task_finished": False, "about": "Note for Anna",
            "stopped": "Copied the draft", "followup": None}})
        out = self.run_cli("overview", "--digest", d, "--judgments", j)
        self.assertEqual(out.returncode, 0, out.stderr)
        text = out.stdout
        order = [text.index(h) for h in ("Waiting on you", "Stale, decide", "Done, close it")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Waiting on others", text)  # empty categories are left out
        self.assertIn("clipboard copy never pasted", text)
        self.assertIn("Draft for Anna", text)
        self.assertIn("hibernated", text)
        self.assertIn("quiet 5d, stale", text)
        self.assertIn("PR merged: https://github.com/me/app/pull/9", text)
        self.assertIn("Note for Anna", text)

    def test_overview_json(self):
        sessions = [helpers.make_session(1, pr=MERGED)]
        d, j = self.files(sessions)
        out = self.run_cli("overview", "--digest", d, "--judgments", j, "--format", "json")
        self.assertEqual(out.returncode, 0, out.stderr)
        doc = json.loads(out.stdout)
        self.assertIn("copyback_available", doc)
        e = doc["entries"][0]
        for field in ("key", "category", "rule", "reason", "quiet_seconds", "recap", "action",
                      "addable_to_close", "notes"):
            self.assertIn(field, e)
        self.assertLessEqual(len(e["recap"]), 3)

    def test_overview_requires_judgments_file(self):
        d, _ = self.files([helpers.make_session(1)])
        out = self.run_cli("overview", "--digest", d)
        self.assertEqual(out.returncode, 2)

    def test_overview_key(self):
        sessions = [helpers.make_session(1, pr=MERGED), helpers.make_session(2)]
        d, j = self.files(sessions)
        out = self.run_cli("overview", "--digest", d, "--judgments", j, "--key", sessions[0]["key"])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(sessions[0]["key"], out.stdout)
        self.assertNotIn(sessions[1]["key"], out.stdout)
        self.assertIn("PR merged", out.stdout)
        bad = self.run_cli("overview", "--digest", d, "--judgments", j, "--key", "claude:nope")
        self.assertEqual(bad.returncode, 4)

    def test_compact_mode_at_100(self):
        sessions = [helpers.make_session(i, name="s%03d" % i) for i in range(1, 101)]
        d, j = self.files(sessions)
        out = self.run_cli("overview", "--digest", d, "--judgments", j)
        self.assertEqual(out.returncode, 0, out.stderr)
        session_lines = [l for l in out.stdout.splitlines() if l.startswith("  - ")]
        self.assertEqual(len(session_lines), 100)
        self.assertIn("[app]", session_lines[0])
        self.assertIn("quiet", session_lines[0])
        self.assertNotIn("Done.", out.stdout)  # no recap lines in compact mode
        self.assertIn("--key", out.stdout)  # tells how to get a full recap

    def test_empty_digest(self):
        d, j = self.files([])
        out = self.run_cli("overview", "--digest", d, "--judgments", j)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "No open sessions besides this one.")
        out = self.run_cli("overview", "--digest", d, "--judgments", j, "--format", "json")
        self.assertEqual(json.loads(out.stdout)["entries"], [])

    def test_invalid_stale(self):
        d, j = self.files([helpers.make_session(1)])
        out = self.run_cli("overview", "--digest", d, "--judgments", j, "--stale", "3w")
        self.assertEqual(out.returncode, 2)
        self.assertIn("invalid duration: 3w (use Nd, Nh or Nm)", out.stderr)

    def test_stale_option_changes_threshold(self):
        s = helpers.make_session(1, changed_at="2026-11-17T12:00:00Z")
        d, j = self.files([s])
        out = self.run_cli("overview", "--digest", d, "--judgments", j, "--stale", "7d")
        self.assertIn("quiet 5d", out.stdout)
        self.assertNotIn("stale", out.stdout.split("quiet 5d", 1)[1].splitlines()[0])


if __name__ == "__main__":
    unittest.main()
