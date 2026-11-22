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


if __name__ == "__main__":
    unittest.main()
