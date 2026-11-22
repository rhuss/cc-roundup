"""Conversation copy reading: recent messages, first activity, PR links, checklist."""
import json
import os
import shutil
import tempfile
import unittest

from tests import helpers  # noqa: F401
from roundup.signals import conversation


def row(role, text, ts=1795340000000, ref="1"):
    return {"role": role, "timestamp": ts, "ref": ref, "text": text}


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rows, trailer=""):
        p = os.path.join(self.tmp, "conv.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
            fh.write(trailer)
        return p

    def test_last_six_messages_oldest_first_and_cut(self):
        rows = [row("user" if i % 2 == 0 else "assistant", "m%d" % i, ts=1795340000000 + i * 1000,
                    ref=str(i + 1)) for i in range(9)]
        rows[-1]["text"] = "z" * 800
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.status, "found")
        self.assertEqual(len(c.messages), 6)
        self.assertEqual([m["text"] for m in c.messages[:5]], ["m3", "m4", "m5", "m6", "m7"])
        last = c.messages[-1]
        self.assertTrue(last["cut"])
        self.assertLessEqual(len(last["text"]), 600)
        self.assertFalse(c.messages[0]["cut"])
        self.assertEqual(c.messages[0]["role"], "assistant")
        self.assertTrue(c.messages[0]["at"].endswith("Z"))

    def test_first_and_last_activity(self):
        rows = [row("user", "a", ts=1795320000000), row("assistant", "b", ts=1795323600000)]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.first_activity_at, "2026-11-22T04:00:00Z")
        self.assertEqual(c.last_message_at, "2026-11-22T05:00:00Z")

    def test_mixed_host_links_ordered_by_text_position(self):
        rows = [row("assistant", "Old MR https://gitlab.com/me/app/-/merge_requests/5 superseded by "
                                 "https://github.com/me/app/pull/7")]
        c = conversation.read_conversation(self.write(rows))
        self.assertTrue(c.newest_pr_is_github)
        self.assertEqual(c.pr_links, ["https://github.com/me/app/pull/7"])

    def test_api_github_links_are_not_other_hosts(self):
        rows = [row("assistant", "See https://github.com/me/app/pull/7 and "
                                 "https://api.github.com/repos/me/app/pulls/7")]
        c = conversation.read_conversation(self.write(rows))
        self.assertTrue(c.newest_pr_is_github)
        self.assertEqual(c.non_github_pr_links, [])

    def test_missing_endpoint_timestamp_stays_unknown(self):
        rows = [row("user", "a", ts=1795320000000), row("assistant", "b", ts=None)]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.first_activity_at, "2026-11-22T04:00:00Z")
        self.assertIsNone(c.last_message_at)

    def test_malformed_timestamps_do_not_raise(self):
        rows = [row("user", "a", ts="2026-11-21T10:00:00Z"), row("assistant", "b", ts=[1])]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.status, "found")
        self.assertIsNone(c.first_activity_at)
        self.assertEqual(c.user_message_refs[0][0], None)

    def test_pr_links_whole_copy_most_recent_first(self):
        rows = [row("assistant", "See https://github.com/me/app/pull/1 and http://github.com/me/app/pull/2/files")]
        rows += [row("user", "filler %d" % i) for i in range(10)]
        rows += [row("assistant", "Back to https://github.com/me/app/pull/1#issuecomment-5 again")]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.pr_links, ["https://github.com/me/app/pull/1",
                                      "https://github.com/me/app/pull/2"])

    def test_non_github_pr_links(self):
        rows = [row("assistant", "MR at https://gitlab.com/me/app/-/merge_requests/4 and "
                                 "https://git.example.com/me/app/pulls/9")]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.pr_links, [])
        self.assertEqual(len(c.non_github_pr_links), 2)

    def test_newest_pr_host(self):
        rows = [row("assistant", "https://github.com/me/app/pull/1"),
                row("assistant", "now at https://gitlab.com/me/app/-/merge_requests/4")]
        self.assertFalse(conversation.read_conversation(self.write(rows)).newest_pr_is_github)
        rows.reverse()
        self.assertTrue(conversation.read_conversation(self.write(rows)).newest_pr_is_github)

    def test_checklist_only_in_last_assistant_message(self):
        rows = [
            row("assistant", "- [ ] old item\n- [ ] another"),
            row("user", "go on"),
            row("assistant", "Status:\n- [x] done item\n  - [ ] nested open\n* [ ] star open\n- [] not a box"),
            row("user", "thanks"),
        ]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.checklist_items, ["nested open", "star open"])

    def test_unreadable_copy_is_unknown(self):
        c = conversation.read_conversation(os.path.join(self.tmp, "missing.jsonl"))
        self.assertEqual(c.status, "unknown")
        self.assertTrue(c.cause)
        c = conversation.read_conversation(None)
        self.assertEqual(c.status, "unknown")
        self.assertTrue(c.cause)

    def test_partial_trailing_line_skipped(self):
        rows = [row("user", "hello"), "{not json", row("assistant", "hi")]
        p = self.write(rows, trailer='{"role":"user","timest')
        c = conversation.read_conversation(p)
        self.assertEqual(c.status, "found")
        self.assertEqual([m["text"] for m in c.messages], ["hello", "hi"])

    def test_user_message_refs(self):
        rows = [row("user", "a", ts=None, ref="11"), row("assistant", "b", ref="12"),
                row("user", "c", ts=1795340000000, ref="20")]
        c = conversation.read_conversation(self.write(rows))
        self.assertEqual(c.user_message_refs, [(None, "11"), (1795340000000, "20")])


if __name__ == "__main__":
    unittest.main()
