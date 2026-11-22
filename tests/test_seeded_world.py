"""The seeded world end to end: gather, then overview with the recorded judgments.

SC-002 (every top-level session exactly once, no excluded ones), SC-003 (nothing
runs, every session has a category and a reason) and the mechanical part of
SC-004 (100% of labelled categories).
"""
import json
import os
import unittest

from tests import helpers

MUTATING = (["pane", "close"], ["message"], ["headless", "stop"], ["pane", "send"],
            ["pane", "keys"])


class SeededWorldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = helpers.StubEnv("world", caller_pane=900).__enter__()
        cls.env.build_world_repos()
        gathered = cls.env.run("gather")
        assert gathered.returncode == 0, gathered.stderr
        cls.digest_path = cls.env.path("digest.json")
        with open(cls.digest_path, "w", encoding="utf-8") as fh:
            fh.write(gathered.stdout)
        cls.digest = json.loads(gathered.stdout)
        cls.judgments_path = os.path.join(cls.env.fixtures, "judgments.json")
        out = cls.env.run("overview", "--digest", cls.digest_path, "--judgments",
                          cls.judgments_path, "--format", "json")
        assert out.returncode == 0, out.stderr
        cls.overview = json.loads(out.stdout)
        text = cls.env.run("overview", "--digest", cls.digest_path, "--judgments",
                           cls.judgments_path)
        assert text.returncode == 0, text.stderr
        cls.text = text.stdout
        cls.expected = cls.env.load_fixture_json("expected.json")["sessions"]
        cls.calls = cls.env.invocations()

    @classmethod
    def tearDownClass(cls):
        cls.env.__exit__(None, None, None)

    def test_every_top_level_session_exactly_once(self):
        keys = [s["key"] for s in self.digest["sessions"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(self.expected))
        entry_keys = [e["key"] for e in self.overview["entries"]]
        self.assertEqual(sorted(entry_keys), sorted(keys))

    def test_excluded_sessions_absent(self):
        keys = {s["key"] for s in self.digest["sessions"]}
        for excluded in ("claude:00000000-0000-4000-8000-000000000900",  # caller
                         "claude:00000000-0000-4000-8000-000000000990",  # Ask Corgi helper
                         "claude:00000000-0000-4000-8000-000000000950"):  # archived
            self.assertNotIn(excluded, keys)
        self.assertFalse(any(k.startswith("claude:a0000") for k in keys))  # subagents
        self.assertTrue(self.digest["caller"]["excluded"])

    def test_categories_match_labels(self):
        got = {e["key"]: e for e in self.overview["entries"]}
        wrong = {k: (got[k]["category"], v["category"]) for k, v in self.expected.items()
                 if got[k]["category"] != v["category"] or got[k]["rule"] != v["rule"]}
        self.assertEqual(wrong, {})
        mechanical = [k for k, v in self.expected.items() if v["decided_by"] == "mechanical"]
        judged = [k for k, v in self.expected.items() if v["decided_by"] == "judged"]
        self.assertGreaterEqual(len(self.expected), 12)
        self.assertGreaterEqual(len(judged), 10)
        self.assertTrue(mechanical)

    def test_proposed_actions_match_labels(self):
        got = {e["key"]: e for e in self.overview["entries"]}
        for k, v in self.expected.items():
            self.assertEqual(got[k]["action"]["verb"], v["action"], k)

    def test_every_session_has_reason(self):
        for e in self.overview["entries"]:
            self.assertTrue(e["reason"], e["key"])
            self.assertIn(e["category"], ("waiting_on_you", "stale_decide", "waiting_on_others",
                                          "done_close_it"))
        self.assertIn("approval pending", self.text)

    def test_nothing_mutating_ran(self):
        for call in self.calls:
            if call["tool"] in ("pbcopy", "slack-pbcopy"):
                self.fail("clipboard touched: %r" % call)
            if call["tool"] == "corgi":
                for prefix in MUTATING:
                    self.assertNotEqual(call["argv"][:len(prefix)], prefix, call)

    def test_shared_folder_marked(self):
        by_key = {s["key"]: s for s in self.digest["sessions"]}
        a = by_key["claude:00000000-0000-4000-8000-000000000020"]
        b = by_key["claude:00000000-0000-4000-8000-000000000021"]
        self.assertTrue(a["signals"]["shared_folder"]["shared"])
        self.assertEqual(a["folder"], b["folder"])
        got = {e["key"]: e for e in self.overview["entries"]}
        self.assertIn("shared folder", got[a["key"]]["reason"])


if __name__ == "__main__":
    unittest.main()
