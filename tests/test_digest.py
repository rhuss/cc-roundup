import io
import json
import os
import tempfile
import unittest

from tests import helpers
from roundup import InputError, digest


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, doc):
        return helpers.write_json(os.path.join(self.tmp, "digest.json"), doc)

    def test_constants(self):
        self.assertEqual(digest.FORMAT, "roundup-digest")
        self.assertEqual(digest.VERSION, 1)

    def test_valid_digest_loads(self):
        doc = helpers.make_digest([helpers.make_session(1), helpers.make_session(2)])
        self.assertEqual(digest.validate(doc), [])
        loaded = digest.load(self._write(doc))
        self.assertEqual(len(loaded["sessions"]), 2)

    def test_unknown_version_rejected(self):
        doc = helpers.make_digest([])
        doc["version"] = 2
        with self.assertRaises(InputError) as ctx:
            digest.load(self._write(doc))
        self.assertIn("unsupported digest version 2", str(ctx.exception))

    def test_malformed_json_and_missing_file(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w") as fh:
            fh.write("{not json")
        with self.assertRaises(InputError):
            digest.load(p)
        with self.assertRaises(InputError):
            digest.load(os.path.join(self.tmp, "missing.json"))

    def test_missing_required_field(self):
        s = helpers.make_session(1)
        del s["agent_state"]
        errors = digest.validate(helpers.make_digest([s]))
        self.assertTrue(any("agent_state" in e for e in errors), errors)

    def test_signal_status_and_cause(self):
        s = helpers.make_session(1, clipboard={"status": "maybe"})
        self.assertTrue(digest.validate(helpers.make_digest([s])))
        s = helpers.make_session(1, pr={"status": "unknown", "current": None, "others": []})
        errors = digest.validate(helpers.make_digest([s]))
        self.assertTrue(any("without cause" in e for e in errors), errors)
        s = helpers.make_session(1, pr={"status": "unknown", "cause": "gh missing",
                                        "current": None, "others": []})
        self.assertEqual(digest.validate(helpers.make_digest([s])), [])

    def test_message_limits(self):
        msg = {"role": "user", "at": None, "text": "x", "cut": False}
        s = helpers.make_session(1, messages=[msg] * 7)
        self.assertTrue(any("more than 6" in e for e in digest.validate(helpers.make_digest([s]))))
        s = helpers.make_session(1, messages=[dict(msg, text="y" * 601)])
        self.assertTrue(any("600" in e for e in digest.validate(helpers.make_digest([s]))))

    def test_unfinished_items_validated(self):
        s = helpers.make_session(1, unfinished={"status": "found", "items": [
            {"kind": "bogus", "status": "found", "detail": "x", "shared": False}]})
        self.assertTrue(digest.validate(helpers.make_digest([s])))

    def test_malformed_entries_raise_input_error(self):
        for mutate in (
            lambda s: s.__setitem__("messages", ["just a string"]),
            lambda s: s.__setitem__("messages", {"role": "user"}),
            lambda s: s["signals"]["unfinished"].__setitem__("items", ["x"]),
            lambda s: s.__setitem__("signals", "nope"),
            lambda s: s.__setitem__("key", []),
            lambda s: s.__setitem__("key", "claude:someone-else"),
            lambda s: s["signals"]["unfinished"].__setitem__(
                "items", [{"kind": "uncommitted", "status": "found", "detail": 42}]),
            lambda s: s.__setitem__("folder", []),
            lambda s: s.__setitem__("workspace", []),
            lambda s: s.__setitem__("kind", "tmux"),
            lambda s: s.__setitem__("changed_at", "yesterday"),
            lambda s: s["signals"].__setitem__(
                "pr", {"status": "found", "current": {"state": "merged"}, "others": []}),
            lambda s: s["signals"].__setitem__(
                "clipboard", {"status": "found", "method": "pbcopy", "text": 42}),
            lambda s: s["signals"].__setitem__(
                "clipboard", {"status": "found", "method": "/bin/sh", "text": "x"}),
        ):
            s = helpers.make_session(1)
            mutate(s)
            with self.assertRaises(InputError):
                digest.load(self._write(helpers.make_digest([s])))
        for version in (True, 1.0, "1"):
            doc = helpers.make_digest([])
            doc["version"] = version
            with self.assertRaises(InputError):
                digest.load(self._write(doc))

    def test_build_isolates_a_failing_session(self):
        from unittest import mock
        from roundup.signals import conversation as convsig

        real = convsig.read_conversation

        def flaky(path):
            if path == "/bad.jsonl":
                raise RuntimeError("boom")
            return real(path)

        snap = {"backend": "corgi", "generated_at": helpers.TEST_NOW, "archived": False,
                "caller": {"pane": None, "excluded": False, "cause": "test"},
                "sessions": []}
        for n, path in ((1, "/bad.jsonl"), (2, None)):
            s = helpers.make_session(n)
            snap["sessions"].append({
                "key": s["key"], "provider": s["provider"], "session_id": s["session_id"],
                "name": s["name"], "kind": "pane", "pane": 100 + n, "headless_id": None,
                "hibernated": False, "workspace": s["workspace"], "folder": None,
                "agent_state": "idle", "backend_state": {}, "changed_at": None,
                "also_open_in": [], "copy": {"path": path, "tools_path": None, "cause": None},
                "interrupted": {"status": "not_found"}})
        with mock.patch.object(convsig, "read_conversation", flaky):
            doc = digest.build(snap, lookup=lambda url: "open")
        bad = doc["sessions"][0]
        self.assertEqual(bad["conversation"]["status"], "unknown")
        self.assertIn("boom", bad["conversation"]["cause"])
        self.assertEqual(len(doc["sessions"]), 2)

    def test_duplicate_keys(self):
        doc = helpers.make_digest([helpers.make_session(1), helpers.make_session(1)])
        self.assertTrue(any("duplicate" in e for e in digest.validate(doc)))

    def test_dump_roundtrip(self):
        doc = helpers.make_digest([helpers.make_session(1)])
        buf = io.StringIO()
        digest.dump(doc, buf)
        self.assertEqual(json.loads(buf.getvalue()), doc)

    def test_cut(self):
        self.assertEqual(digest.cut("abc", 5), "abc")
        out = digest.cut("x" * 700, 600)
        self.assertEqual(len(out), 600)
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
