"""Action verbs against the stub corgi: re-check, close (US2) and message (US3).

SC-007: the exact commands issued are recorded, and a re-check mismatch issues none.
"""
import json
import os
import unittest

from tests import helpers
from roundup import answers


def sid(n, provider="claude"):
    if provider == "codex":
        return "019a0000-0000-7000-8000-%012d" % n
    return "00000000-0000-4000-8000-%012d" % n


def key(n, provider="claude"):
    return "%s:%s" % (provider, sid(n, provider))


class ActionCase(unittest.TestCase):
    fixtures = "corgi"
    caller = 108

    def setUp(self):
        self.env = helpers.StubEnv(self.fixtures, caller_pane=self.caller).__enter__()
        out = self.env.run("gather")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.digest = self.env.path("digest.json")
        with open(self.digest, "w", encoding="utf-8") as fh:
            fh.write(out.stdout)
        self.env.clear_log()

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def act(self, verb, k, text=None):
        proc = self.env.run("act", verb, "--digest", self.digest, "--key", k, input=text)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        return json.loads(lines[0])

    def corgi_calls(self):
        return [c["argv"] for c in self.env.invocations("corgi")]

    def edit_list(self, fn):
        doc = self.env.load_fixture_json("list.json")
        fn(doc["result"])
        self.env.write_fixture("list.json", doc)

    @staticmethod
    def pane_of(result, pane_id):
        return next(p for p in result["panes"] if p["id"] == pane_id)


class CloseTest(ActionCase):
    def test_close_rechecks_then_closes(self):
        out = self.act("close", key(101))
        self.assertEqual(out, {"key": key(101), "verb": "close", "outcome": "done",
                               "reason": "pane 101 closed"})
        self.assertEqual(self.corgi_calls(), [["list", "--json"], ["pane", "close", "101"]])

    def test_headless_stops_headless_agent(self):
        out = self.act("close", key(201))
        self.assertEqual(out["outcome"], "done")
        self.assertEqual(self.corgi_calls(),
                         [["list", "--json"], ["headless", "stop", "claude", sid(201)]])

    def test_hibernated_pane_closes_with_pane_close(self):
        out = self.act("close", key(106))
        self.assertEqual(out["outcome"], "done")
        self.assertEqual(self.corgi_calls()[-1], ["pane", "close", "106"])

    def test_pane_gone_skipped(self):
        self.edit_list(lambda r: r.__setitem__("panes", [p for p in r["panes"] if p["id"] != 101]))
        out = self.act("close", key(101))
        self.assertEqual(out["outcome"], "skipped")
        self.assertIn("no longer", out["reason"])
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_state_changed_skipped(self):
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].__setitem__("state", "working"))
        out = self.act("close", key(101))
        self.assertEqual(out["outcome"], "skipped")
        self.assertIn("idle", out["reason"])
        self.assertIn("working", out["reason"])
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_changed_at_changed_skipped(self):
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].__setitem__(
            "changed_at", self.pane_of(r, 101)["agent"]["changed_at"] + 5_000_000))
        out = self.act("close", key(101))
        self.assertEqual(out["outcome"], "skipped")
        self.assertIn("last change time", out["reason"])
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_other_conversation_in_pane_skipped(self):
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].__setitem__("session", sid(999)))
        out = self.act("close", key(101))
        self.assertEqual(out["outcome"], "skipped")
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_headless_state_changed_skipped(self):
        def change(r):
            h = next(h for h in r["headless_sessions"] if h["id"] == 5)
            h["state"] = "working"

        self.edit_list(change)
        out = self.act("close", key(201))
        self.assertEqual(out["outcome"], "skipped")
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_headless_replaced_by_another_agent_skipped(self):
        def change(r):
            h = next(h for h in r["headless_sessions"] if h["id"] == 5)
            h["id"] = 6

        self.edit_list(change)
        out = self.act("close", key(201))
        self.assertEqual(out["outcome"], "skipped")
        self.assertIn("replaced", out["reason"])
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_corgi_error_fails_without_retry(self):
        self.env.write_fixture("close-reply.json.exit", "2")
        self.env.write_fixture("close-reply.json.stderr",
                               '{"ok":false,"err":"pane 101 refused to close"}\n')
        out = self.act("close", key(101))
        self.assertEqual(out["outcome"], "failed")
        self.assertEqual(out["reason"], "pane 101 refused to close")
        closes = [c for c in self.corgi_calls() if c[:2] == ["pane", "close"]]
        self.assertEqual(len(closes), 1)

    def test_unreachable_runtime_exits_3(self):
        proc = self.env.run("act", "close", "--digest", self.digest, "--key", key(101),
                            env={"ROUNDUP_STUB_CORGI_FAIL": "unreachable"})
        self.assertEqual(proc.returncode, 3)
        self.assertIn("connect ENOENT", proc.stderr)

    def test_unknown_key_exits_4(self):
        proc = self.env.run("act", "close", "--digest", self.digest, "--key", "claude:nope")
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(self.corgi_calls(), [])


class EditedBatchTest(ActionCase):
    """US2 independent test: drop one done session, add one stale session, close the batch."""

    fixtures = "world"
    caller = 900

    def setUp(self):
        self.env = helpers.StubEnv(self.fixtures, caller_pane=self.caller).__enter__()
        self.env.build_world_repos()
        out = self.env.run("gather")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.digest = self.env.path("digest.json")
        with open(self.digest, "w", encoding="utf-8") as fh:
            fh.write(out.stdout)
        ov = self.env.run("overview", "--digest", self.digest, "--judgments",
                          os.path.join(self.env.fixtures, "judgments.json"), "--format", "json")
        self.entries = json.loads(ov.stdout)["entries"]
        self.env.clear_log()

    def test_edited_batch_closes_exactly_the_batch(self):
        done = [e["key"] for e in self.entries if e["action"]["verb"] == "close"
                and e["action"]["preselected"]]
        stale = [e["key"] for e in self.entries if e["category"] == "stale_decide"
                 and e["addable_to_close"]]
        self.assertGreaterEqual(len(done), 4)
        self.assertGreaterEqual(len(stale), 2)
        batch = done[1:4] + stale[:1]  # drop one done session, add one stale one
        outcomes = [self.act("close", k) for k in batch]
        self.assertTrue(all(o["outcome"] == "done" for o in outcomes), outcomes)
        closes = [c for c in self.corgi_calls() if c[:2] == ["pane", "close"]]
        by_key = {e["key"]: e for e in self.entries}
        self.assertEqual(closes, [["pane", "close", str(by_key[k]["pane"])] for k in batch])
        self.assertNotIn(["pane", "close", str(by_key[done[0]]["pane"])], closes)


NO_CHANNEL = "agent channel not available; not typing into the pane"


class MessageTest(ActionCase):
    """Follow-ups go only through the agent's own channel (FR-026, research R9)."""

    def setUp(self):
        # Point the panes at writable account directories before gathering.
        self.env = helpers.StubEnv(self.fixtures, caller_pane=self.caller).__enter__()
        self.claude_acct = self.env.path("acct-claude")
        self.codex_acct = self.env.path("acct-codex")
        os.makedirs(os.path.join(self.claude_acct, "sessions"))
        os.makedirs(self.codex_acct)

        def setup(r):
            self.pane_of(r, 101)["account"] = self.claude_acct
            codex = self.pane_of(r, 103)
            codex["account"] = self.codex_acct
            codex["agent"]["state"] = "idle"

        self.edit_list(setup)
        out = self.env.run("gather")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.digest = self.env.path("digest.json")
        with open(self.digest, "w", encoding="utf-8") as fh:
            fh.write(out.stdout)
        self.env.clear_log()

    def peer_file(self, session_id=None, protocol=1, pid=None):
        path = os.path.join(self.claude_acct, "sessions", "peer-1.json")
        helpers.write_json(path, {"sessionId": session_id or sid(101), "peerProtocol": protocol,
                                  "pid": os.getpid() if pid is None else pid})

    def codex_socket(self):
        d = os.path.join(self.codex_acct, "app-server-control")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "app-server-control.sock"), "w").close()

    def test_claude_channel_sends_exact_text(self):
        self.peer_file()
        text = "Please push the branch\nand open a PR."
        out = self.act("message", key(101), text=text)
        self.assertEqual(out["outcome"], "done")
        self.assertEqual(out["delivery"], "message")
        calls = self.env.invocations("corgi")
        self.assertEqual([c["argv"] for c in calls],
                         [["list", "--json"], ["message", "pane:101", "--stdin", "--json"]])
        self.assertEqual(calls[-1]["stdin"], answers.RELAY_HEADER + "\n\n" + text)

    def test_claude_without_channel_is_skipped_without_corgi(self):
        for setup in (lambda: None,
                      lambda: self.peer_file(protocol=2),
                      lambda: self.peer_file(session_id=sid(999)),
                      lambda: self.peer_file(pid=self.dead_pid())):
            for name in os.listdir(os.path.join(self.claude_acct, "sessions")):
                os.remove(os.path.join(self.claude_acct, "sessions", name))
            setup()
            self.env.clear_log()
            out = self.act("message", key(101), text="go on")
            self.assertEqual(out["outcome"], "skipped")
            self.assertEqual(out["reason"], NO_CHANNEL)
            self.assertEqual(self.corgi_calls(), [])

    def sent_records(self):
        path = self.env.path(answers.SENT_FILE)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_done_message_writes_sent_record(self):
        self.peer_file()
        transcript = self.env.path("transcript-101.jsonl")
        with open(transcript, "wb") as fh:
            fh.write(b"x" * 119 + b"\n")
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].__setitem__("transcript",
                                                                           transcript))
        text = "Please push the branch.\n"
        out = self.act("message", key(101), text=text)
        self.assertEqual(out["outcome"], "done")
        self.assertNotIn("transcript", out)
        self.assertNotIn("transcript_offset", out)
        records = self.sent_records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["key"], key(101))
        self.assertEqual(rec["provider"], "claude")
        self.assertEqual(rec["pane"], 101)
        self.assertEqual(rec["text"], text)
        self.assertEqual(rec["transcript"], transcript)
        self.assertEqual(rec["offset"], 120)
        self.assertEqual(rec["sent_at"], helpers.TEST_NOW)

    def test_missing_transcript_still_recorded(self):
        self.peer_file()
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].pop("transcript", None))
        out = self.act("message", key(101), text="go on")
        self.assertEqual(out["outcome"], "done")
        rec = self.sent_records()[0]
        self.assertIsNone(rec["transcript"])
        self.assertEqual(rec["offset"], 0)

    def test_skipped_message_writes_no_record(self):
        out = self.act("message", key(101), text="go on")  # no peer file: no channel
        self.assertEqual(out["outcome"], "skipped")
        self.assertIsNone(self.sent_records())

    @staticmethod
    def dead_pid():
        import subprocess
        import sys

        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_codex_protocol_channel_sends(self):
        self.codex_socket()
        out = self.act("message", key(103, "codex"), text="update the README")
        self.assertEqual(out["outcome"], "done")
        self.assertEqual(self.corgi_calls()[-1], ["message", "pane:103", "--stdin", "--json"])

    def test_codex_without_socket_or_protocol_is_skipped(self):
        out = self.act("message", key(103, "codex"), text="x")  # no socket
        self.assertEqual((out["outcome"], out["reason"]), ("skipped", NO_CHANNEL))
        self.assertEqual(self.corgi_calls(), [])
        self.codex_socket()
        with open(self.digest, encoding="utf-8") as fh:
            digest = json.load(fh)
        for s in digest["sessions"]:
            if s["key"] == key(103, "codex"):
                s["backend_state"]["observation_source"] = "hook"
        helpers.write_json(self.digest, digest)
        out = self.act("message", key(103, "codex"), text="x")
        self.assertEqual((out["outcome"], out["reason"]), ("skipped", NO_CHANNEL))
        self.assertEqual(self.corgi_calls(), [])

    def test_typed_delivery_is_failed(self):
        self.peer_file()
        self.env.write_fixture("message-reply.json",
                               {"ok": True, "result": {"delivery": "typed", "queued": False}})
        out = self.act("message", key(101), text="go on")
        self.assertEqual(out["outcome"], "failed")
        self.assertEqual(out["reason"],
                         "Corgi typed the message into the pane (agent channel unavailable)")
        self.assertEqual(out["delivery"], "typed")
        sends = [c for c in self.corgi_calls() if c[0] == "message"]
        self.assertEqual(len(sends), 1)

    def test_corgi_error_is_failed(self):
        self.peer_file()
        self.env.write_fixture("message-reply.json.exit", "1")
        self.env.write_fixture("message-reply.json.stderr", '{"ok":false,"err":"AgentBusy"}\n')
        out = self.act("message", key(101), text="go on")
        self.assertEqual((out["outcome"], out["reason"]), ("failed", "AgentBusy"))

    def test_headless_message(self):
        out = self.act("message", key(201), text="post it")
        self.assertEqual(out["outcome"], "done")
        self.assertEqual(self.corgi_calls()[-1], ["message", "headless:5", "--stdin", "--json"])

    def test_recheck_mismatch_skips_send(self):
        self.peer_file()
        self.edit_list(lambda r: self.pane_of(r, 101)["agent"].__setitem__("state", "working"))
        out = self.act("message", key(101), text="go on")
        self.assertEqual(out["outcome"], "skipped")
        self.assertEqual(self.corgi_calls(), [["list", "--json"]])

    def test_hibernated_exited_and_blocked_refused(self):
        for k in (key(106), key(105), key(104)):
            out = self.act("message", k, text="go on")
            self.assertEqual(out["outcome"], "skipped", k)
        self.assertEqual(self.corgi_calls(), [])

    def test_empty_text_is_usage_error(self):
        proc = self.env.run("act", "message", "--digest", self.digest, "--key", key(101),
                            input="  \n")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.corgi_calls(), [])


if __name__ == "__main__":
    unittest.main()
