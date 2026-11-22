"""`roundup collect`: reads RUN/sent.jsonl and the transcripts, never runs Corgi."""
import json
import os
import unittest

from tests import helpers
from roundup import answers


class CollectCliTest(unittest.TestCase):
    def setUp(self):
        self.env = helpers.StubEnv().__enter__()
        self.digest = self.env.path("digest.json")
        helpers.write_json(self.digest, helpers.make_digest([helpers.make_session(1)]))

    def tearDown(self):
        self.assertEqual(self.env.invocations("corgi"), [])
        self.env.__exit__(None, None, None)

    def collect(self, *extra):
        return self.env.run("collect", "--digest", self.digest, *extra)

    def test_collect_without_sent_file_prints_empty(self):
        proc = self.collect("--wait", "0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"sessions": []})

    def test_collect_wait_zero_reports_answer(self):
        transcript = self.env.path("t.jsonl")
        records = [
            {"type": "user", "isMeta": True, "origin": {"kind": "peer", "from": "unknown"},
             "message": {"role": "user", "content": "Another Claude session sent a message:\n"
                         + answers.relay_text("Please push.")}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": [{"type": "text", "text": "Pushed."}]}},
            {"type": "system", "subtype": "turn_duration", "timestamp": "2026-11-22T12:01:00Z"},
        ]
        with open(transcript, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        session = helpers.make_session(1)
        answers.record_sent(self.env.tmp, session, "Please push.\n", transcript, 0,
                            "2026-11-22T12:00:00Z")
        proc = self.collect("--wait", "0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = json.loads(proc.stdout)["sessions"][0]
        self.assertEqual(entry["key"], session["key"])
        self.assertEqual(entry["status"], "answered")
        self.assertEqual(entry["answer"], "Pushed.")

    def test_collect_rejects_bad_wait(self):
        for wait in ("-1", "541"):
            proc = self.collect("--wait", wait)
            self.assertEqual(proc.returncode, 2, wait)

    def test_collect_malformed_sent_exits_4(self):
        with open(os.path.join(self.env.tmp, answers.SENT_FILE), "w", encoding="utf-8") as fh:
            fh.write("not json\n")
        proc = self.collect("--wait", "0")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("malformed sent.jsonl line 1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
