"""Follow-up answers: relay header, answer detection in transcripts, sent records, collect."""
import json
import os
import shutil
import tempfile
import unittest

from tests import helpers  # noqa: F401  (puts roundup/lib on sys.path)
from roundup import answers


PEER_PREFIX = "Another Claude session sent a message:\n"
PEER_SUFFIX = "\n\n\nThis came from another Claude session, not typed by your user."


def claude_user(text, meta=False):
    rec = {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}}
    if meta:
        rec["isMeta"] = True
        rec["origin"] = {"kind": "peer", "from": "unknown"}
    return rec


def claude_peer(text):
    return claude_user(PEER_PREFIX + answers.relay_text(text) + PEER_SUFFIX, meta=True)


def claude_assistant(*texts, tools=0):
    content = [{"type": "thinking", "thinking": "", "signature": "x"}]
    content += [{"type": "text", "text": t} for t in texts]
    content += [{"type": "tool_use", "id": "t%d" % i, "name": "Bash", "input": {}}
                for i in range(tools)]
    return {"type": "assistant", "isSidechain": False,
            "message": {"role": "assistant", "content": content}}


def claude_turn_end(ts="2026-11-22T11:20:00Z"):
    return {"type": "system", "subtype": "turn_duration", "timestamp": ts}


def claude_enqueue(text):
    return {"type": "queue-operation", "operation": "enqueue", "content": text}


def codex_event(kind, ts="2026-11-22T11:20:00Z", **fields):
    payload = {"type": kind}
    payload.update(fields)
    return {"timestamp": ts, "type": "event_msg", "payload": payload}


class RelayTextTest(unittest.TestCase):
    def test_relay_text_prefixes_header(self):
        self.assertEqual(answers.relay_text("Go on."), answers.RELAY_HEADER + "\n\n" + "Go on.")
        self.assertEqual(
            answers.RELAY_HEADER,
            "(Relayed from your user by their roundup session. Please answer here in this "
            "conversation; there is nothing to send back.)")


class FindAnswerClaudeTest(unittest.TestCase):
    def test_claude_peer_message_answered(self):
        text = "What is uncommitted?"
        records = [claude_peer(text), claude_assistant("Nothing tracked.", tools=1),
                   claude_turn_end("2026-11-22T11:20:00Z")]
        got = answers.find_answer("claude", records, text)
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["answer"], "Nothing tracked.")
        self.assertEqual(got["tool_calls"], 1)
        self.assertEqual(got["answered_at"], "2026-11-22T11:20:00Z")
        self.assertFalse(got["truncated"])

    def test_previous_turn_text_is_not_the_answer(self):
        text = "Push it."
        records = [claude_assistant("old work done"), claude_turn_end("2026-11-22T11:00:00Z"),
                   claude_peer(text), claude_assistant("new answer"), claude_turn_end()]
        got = answers.find_answer("claude", records, text)
        self.assertEqual(got["answer"], "new answer")

    def test_assistant_quoting_text_does_not_match(self):
        text = "Push it."
        records = [claude_assistant("You said: Push it."), claude_turn_end()]
        self.assertEqual(answers.find_answer("claude", records, text)["status"], "pending")

    def test_match_ignores_trailing_newline(self):
        records = [claude_user("Push it."), claude_assistant("Pushed."), claude_turn_end()]
        got = answers.find_answer("claude", records, "Push it.\n")
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["answer"], "Pushed.")

    def test_message_without_turn_end_is_working(self):
        records = [claude_peer("Go."), claude_assistant("Working on it")]
        self.assertEqual(answers.find_answer("claude", records, "Go.")["status"], "working")

    def test_turn_end_without_text_is_no_reply(self):
        records = [claude_peer("Go."), claude_assistant(tools=2), claude_turn_end()]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(got["status"], "no_reply")
        self.assertEqual(got["tool_calls"], 2)

    def test_queued_message_is_working(self):
        records = [claude_enqueue(answers.relay_text("Go.")), claude_assistant("still busy")]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(got["status"], "working")
        self.assertEqual(got["cause"], "queued behind the agent's current turn")

    def test_answer_truncated(self):
        records = [claude_peer("Go."), claude_assistant("x" * 5000), claude_turn_end()]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(len(got["answer"]), answers.ANSWER_LIMIT)
        self.assertTrue(got["truncated"])

    def test_unsupported_provider_is_unknown(self):
        got = answers.find_answer("gemini", [], "Go.")
        self.assertEqual(got["status"], "unknown")
        self.assertEqual(got["cause"], "answers not supported for gemini")


class FindAnswerBoundaryTest(unittest.TestCase):
    """Final review fixes: the answer ends at the next prompt, first match wins."""

    def test_claude_stops_at_next_user_prompt(self):
        records = [claude_peer("Go."), claude_assistant("first reply"),
                   claude_user("something unrelated"), claude_assistant("other reply"),
                   claude_turn_end()]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["answer"], "first reply")

    def test_claude_interrupt_is_no_reply(self):
        records = [claude_peer("Go."), claude_assistant("partial"),
                   claude_user("[Request interrupted by user]"), claude_user("new prompt"),
                   claude_assistant("other"), claude_turn_end()]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(got["status"], "no_reply")
        self.assertEqual(got["cause"], "turn interrupted")

    def test_claude_meta_and_compact_records_do_not_end_answer(self):
        skill = claude_user("Base directory for this skill: /Users/me/skills/x", meta=False)
        skill["isMeta"] = True
        compact = claude_user("Summary of earlier conversation")
        compact["isCompactSummary"] = True
        records = [claude_peer("Go."), claude_assistant("one"), skill, compact,
                   claude_assistant("two"), claude_turn_end()]
        got = answers.find_answer("claude", records, "Go.")
        self.assertEqual(got["answer"], "one\n\ntwo")

    def test_first_match_after_offset_wins(self):
        records = [claude_peer("Yes."), claude_assistant("Added the link."), claude_turn_end(),
                   claude_user("Yes. Now also the footer."), claude_assistant("Footer done."),
                   claude_turn_end()]
        got = answers.find_answer("claude", records, "Yes.")
        self.assertEqual(got["answer"], "Added the link.")


def codex_item(kind, text, ts="2026-11-22T11:20:00Z"):
    block = "text" if kind == "UserMessage" else "Text"
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "item_completed",
                        "item": {"type": kind, "content": [{"type": block, "text": text}]}}}


class FindAnswerCodexItemsTest(unittest.TestCase):
    """Codex 0.167 rollouts: item_completed UserMessage / AgentMessage items."""

    def test_codex_item_completed_answered(self):
        text = "Open the PR."
        records = [codex_item("UserMessage", answers.relay_text(text)),
                   {"type": "response_item",
                    "payload": {"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": "PR opened."}]}},
                   codex_item("AgentMessage", "PR opened."),
                   codex_event("task_complete", ts="2026-11-22T11:21:00Z")]
        got = answers.find_answer("codex", records, text)
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["answer"], "PR opened.")
        self.assertEqual(got["answered_at"], "2026-11-22T11:21:00Z")

    def test_codex_stops_at_next_user_message(self):
        text = "Open the PR."
        records = [codex_item("UserMessage", answers.relay_text(text)),
                   codex_item("AgentMessage", "Opening it."),
                   codex_item("UserMessage", "unrelated"),
                   codex_item("AgentMessage", "other"),
                   codex_event("task_complete")]
        got = answers.find_answer("codex", records, text)
        self.assertEqual(got["answer"], "Opening it.")


class FindAnswerCodexTest(unittest.TestCase):
    def test_codex_answered(self):
        text = "Open the PR."
        records = [codex_event("user_message", message=answers.relay_text(text)),
                   codex_event("agent_message", message="PR opened."),
                   codex_event("task_complete", ts="2026-11-22T11:21:00Z")]
        got = answers.find_answer("codex", records, text)
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["answer"], "PR opened.")
        self.assertEqual(got["answered_at"], "2026-11-22T11:21:00Z")

    def test_codex_aborted_is_no_reply(self):
        text = "Open the PR."
        records = [codex_event("user_message", message=answers.relay_text(text)),
                   codex_event("turn_aborted")]
        got = answers.find_answer("codex", records, text)
        self.assertEqual(got["status"], "no_reply")
        self.assertEqual(got["cause"], "turn interrupted")


class ReadRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="roundup-answers-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_records_from_offset_and_partial_line(self):
        path = os.path.join(self.tmp, "t.jsonl")
        line1 = (json.dumps({"n": 1}) + "\n").encode("utf-8")
        line2 = (json.dumps({"n": 2}) + "\n").encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(line1 + line2 + b'{"n": 3, "par')
        self.assertEqual(answers.read_records(path, len(line1)), [{"n": 2}])
        self.assertEqual(answers.read_records(path, 10 ** 9), [{"n": 1}, {"n": 2}])


class FakeClock:
    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.sleeps = []
        self.on_sleep = on_sleep

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="roundup-collect-")
        self.transcript = os.path.join(self.tmp, "t.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, *records, mode="a"):
        with open(self.transcript, mode, encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def sent(self, text="Go.", transcript=True):
        return {"key": "claude:a", "provider": "claude", "session_id": "a", "name": "app work",
                "workspace": "app", "pane": 101, "headless_id": None,
                "transcript": self.transcript if transcript else None, "offset": 0,
                "text": text, "sent_at": "2026-11-22T11:19:00Z"}

    def test_collect_polls_until_answered(self):
        self.write(claude_peer("Go."), claude_assistant("thinking about it"), mode="w")
        fake = FakeClock(on_sleep=lambda n: self.write(claude_assistant("Done."),
                                                       claude_turn_end()))
        out = answers.collect([self.sent()], wait=30, poll=3, sleep=fake.sleep, clock=fake.clock)
        entry = out["sessions"][0]
        self.assertEqual(entry["status"], "answered")
        self.assertEqual(entry["answer"], "thinking about it\n\nDone.")
        self.assertEqual(entry["name"], "app work")
        self.assertEqual(entry["workspace"], "app")
        self.assertEqual(entry["pane"], 101)
        self.assertEqual(entry["sent_at"], "2026-11-22T11:19:00Z")
        self.assertEqual(fake.sleeps, [3])

    def test_collect_stops_at_deadline(self):
        self.write(claude_peer("Go."), claude_assistant("busy"), mode="w")
        fake = FakeClock()
        out = answers.collect([self.sent()], wait=6, poll=3, sleep=fake.sleep, clock=fake.clock)
        self.assertEqual(out["sessions"][0]["status"], "working")
        self.assertEqual(fake.sleeps, [3, 3])

    def test_collect_pending_becomes_unknown(self):
        self.write(claude_assistant("unrelated"), mode="w")
        fake = FakeClock()
        out = answers.collect([self.sent()], wait=0, sleep=fake.sleep, clock=fake.clock)
        entry = out["sessions"][0]
        self.assertEqual(entry["status"], "unknown")
        self.assertEqual(entry["cause"], "message not found in transcript")
        self.assertEqual(fake.sleeps, [])

    def test_collect_no_transcript_path(self):
        fake = FakeClock()
        out = answers.collect([self.sent(transcript=False)], wait=30, sleep=fake.sleep,
                              clock=fake.clock)
        entry = out["sessions"][0]
        self.assertEqual((entry["status"], entry["cause"]), ("unknown", "no transcript path"))
        self.assertEqual(fake.sleeps, [])

    def test_collect_unreadable_transcript(self):
        fake = FakeClock()
        out = answers.collect([self.sent()], wait=0, sleep=fake.sleep, clock=fake.clock)
        entry = out["sessions"][0]
        self.assertEqual(entry["status"], "unknown")
        self.assertTrue(entry["cause"].startswith("transcript unreadable: "), entry["cause"])


class LoadSentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="roundup-sent-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_sent_missing_is_empty(self):
        self.assertEqual(answers.load_sent(self.tmp), [])

    def test_load_sent_malformed_raises_input_error(self):
        from roundup import InputError

        with open(os.path.join(self.tmp, answers.SENT_FILE), "w", encoding="utf-8") as fh:
            fh.write('{"key": "claude:a"}\nnot json\n')
        with self.assertRaises(InputError) as ctx:
            answers.load_sent(self.tmp)
        self.assertEqual(str(ctx.exception), "malformed sent.jsonl line 2")


if __name__ == "__main__":
    unittest.main()
