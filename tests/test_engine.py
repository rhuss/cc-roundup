"""Category engine: rules 0 to 5, reasons, quiet time, ordering, action proposals."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import helpers
from roundup import InputError, engine

H = 3600
D = 86400
STALE = 3 * D


def at(seconds_ago):
    """ISO time `seconds_ago` before helpers.TEST_NOW."""
    from roundup import timefmt

    base = timefmt.parse_iso(helpers.TEST_NOW).timestamp()
    import datetime as dt

    return dt.datetime.fromtimestamp(base - seconds_ago, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def item(kind, status="found", detail=None, cause=None, shared=False):
    d = {"kind": kind, "status": status, "detail": detail or kind, "shared": shared}
    if cause:
        d["cause"] = cause
    return d


def unfinished(*items):
    from roundup import digest

    return digest.unfinished_status(list(items))


def pr_sig(state, url="https://github.com/me/app/pull/42"):
    return {"status": "found", "current": {"url": url, "state": state}, "others": []}


CLIP = {"status": "found", "method": "slack-pbcopy", "args": "--tight", "text": "Hello team",
        "truncated": False, "at": "2026-11-21T10:00:00Z", "first_line": "Hello team"}


def evaluate(sessions, judgments=None, stale=STALE, platform="darwin"):
    doc = helpers.make_digest(sessions)
    entries = engine.evaluate(doc, judgments or {}, stale, platform=platform)
    return entries


def one(session, judgment=None, **kw):
    judgments = {session["key"]: judgment} if judgment else {}
    return evaluate([session], judgments, **kw)[0]


def J(unanswered=False, finished=False, note=None, followup=None, about="About", stopped="Stopped",
      round_only=None):
    d = {"unanswered_agent": unanswered, "task_finished": finished, "about": about,
         "stopped": stopped, "followup": followup}
    if round_only is not None:
        d["pr_round_only"] = round_only
    if note:
        d["judgment_note"] = note
    return d


class RulesTest(unittest.TestCase):
    def test_rule0_approval_pending(self):
        e = one(helpers.make_session(1, agent_state="blocked",
                                     unfinished=unfinished(item("uncommitted")), clipboard=CLIP))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_you", 0))
        self.assertEqual(e["reason"], "approval pending")
        self.assertIsNone(e["action"]["verb"])

    def test_rule1_working_dirty_never_done(self):
        s = helpers.make_session(1, agent_state="working", pr=pr_sig("merged"),
                                 unfinished=unfinished(item("uncommitted")))
        e = one(s, J(finished=True))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_others", 1))
        self.assertEqual(e["reason"], "agent working")
        e = one(helpers.make_session(1, agent_state="starting"))
        self.assertEqual((e["category"], e["reason"]), ("waiting_on_others", "agent starting up"))

    def test_rule2_variants(self):
        e = one(helpers.make_session(1), J(unanswered=True, note="open the PR?", followup="Yes"))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_you", 2))
        self.assertEqual(e["reason"], "agent asked: open the PR?")
        e = one(helpers.make_session(1, clipboard=CLIP))
        self.assertEqual(e["reason"], "clipboard copy never pasted")
        for kind, detail in (("checklist", "2 open checklist items"),
                             ("uncommitted", "uncommitted changes"),
                             ("unpushed", "2 unpushed commits"),
                             ("never_pushed", "branch never pushed"),
                             ("interrupted", "last turn interrupted")):
            e = one(helpers.make_session(1, unfinished=unfinished(item(kind, detail=detail))))
            self.assertEqual((e["category"], e["rule"]), ("waiting_on_you", 2), kind)
            self.assertEqual(e["reason"], detail)

    def test_rule2_beats_task_finished_and_merged_pr(self):
        s = helpers.make_session(1, pr=pr_sig("merged"),
                                 unfinished=unfinished(item("unpushed", detail="1 unpushed commits")))
        e = one(s, J(finished=True))
        self.assertEqual(e["category"], "waiting_on_you")

    def test_shared_folder_only_adds_note(self):
        s = helpers.make_session(1, pr=pr_sig("merged"), unfinished=unfinished(
            item("uncommitted", detail="uncommitted changes", shared=True)),
            shared_folder={"shared": True, "sessions": ["claude:other"]})
        e = one(s)
        self.assertEqual((e["category"], e["rule"]), ("done_close_it", 4))
        self.assertEqual(e["reason"],
                         "PR merged: https://github.com/me/app/pull/42; shared folder: uncommitted changes")

    def test_rule3_open_pr(self):
        e = one(helpers.make_session(1, pr=pr_sig("open")))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_others", 3))
        self.assertEqual(e["reason"], "PR open: https://github.com/me/app/pull/42")

    def test_rule4_merged_closed_and_upstream_gone(self):
        s = helpers.make_session(1, pr=pr_sig("merged"), unfinished=unfinished(
            item("uncommitted", status="not_found"),
            item("unpushed", status="unknown", cause="upstream gone")))
        e = one(s)
        self.assertEqual((e["category"], e["rule"]), ("done_close_it", 4))
        self.assertEqual(e["reason"], "PR merged: https://github.com/me/app/pull/42")
        self.assertIn("push state unknown (upstream gone)", e["notes"])  # US1 AS7
        for cause in ("detached HEAD", "no remote"):
            s = helpers.make_session(1, pr=pr_sig("merged"), unfinished=unfinished(
                item("uncommitted", status="not_found"),
                item("unpushed", status="unknown", cause=cause)))
            e = one(s)
            self.assertEqual(e["category"], "done_close_it", cause)
            self.assertIn("push state unknown (%s)" % cause, e["notes"])
        e = one(helpers.make_session(1, pr=pr_sig("closed")))
        self.assertEqual(e["reason"], "PR closed: https://github.com/me/app/pull/42")

    def test_rule3_open_pr_beats_task_finished(self):
        e = one(helpers.make_session(1, pr=pr_sig("open")), J(finished=True, round_only=False))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_others", 3))

    def test_rule4_finished_pr_round_on_open_pr(self):
        # A triage or review round on a PR is done although the PR stays open.
        s = helpers.make_session(1, pr=pr_sig("open"))
        e = one(s, J(finished=True, round_only=True, note="review replies posted"))
        self.assertEqual((e["category"], e["rule"]), ("done_close_it", 4))
        self.assertEqual(e["reason"], "task finished: review replies posted; "
                                      "PR still open: https://github.com/me/app/pull/42")
        self.assertEqual(e["action"], {"verb": "close", "preselected": True})
        # An unfinished round keeps waiting on others.
        e = one(s, J(round_only=True))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_others", 3))
        # Own unfinished work still wins (rule 2).
        s2 = helpers.make_session(1, pr=pr_sig("open"),
                                  unfinished=unfinished(item("unpushed", detail="1 unpushed commits")))
        e = one(s2, J(finished=True, round_only=True))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_you", 2))

    def test_pr_round_only_ignored_when_conversation_unreadable(self):
        s = helpers.make_session(1, pr=pr_sig("open"))
        s["conversation"] = {"status": "unknown", "cause": "unreadable"}
        e = one(s, J(finished=True, round_only=True))
        self.assertEqual((e["category"], e["rule"]), ("waiting_on_others", 3))

    def test_rule4_task_finished(self):
        e = one(helpers.make_session(1), J(finished=True, note="report written"))
        self.assertEqual((e["category"], e["rule"]), ("done_close_it", 4))
        self.assertEqual(e["reason"], "task finished: report written")

    def test_rule5_stale_threshold(self):
        e = one(helpers.make_session(1, changed_at=at(2 * H)))
        self.assertEqual((e["category"], e["rule"]), ("stale_decide", 5))
        self.assertEqual(e["reason"], "quiet 2h")
        self.assertNotIn("stale", e["reason"])
        e = one(helpers.make_session(1, changed_at=at(5 * D)))
        self.assertEqual(e["reason"], "quiet 5d, stale")
        e = one(helpers.make_session(1, changed_at=at(3 * D)))
        self.assertIn("stale", e["reason"])  # at the threshold
        e = one(helpers.make_session(1, changed_at=at(5 * D)), stale=7 * D)
        self.assertNotIn("stale", e["reason"])

    def test_quiet_time_fallbacks(self):
        e = one(helpers.make_session(1, changed_at=None, last_message_at=at(4 * D)))
        self.assertEqual(e["quiet_seconds"], 4 * D)
        self.assertEqual(e["reason"], "quiet 4d (from last message), stale")
        e = one(helpers.make_session(1, changed_at=None, last_message_at=None))
        self.assertIsNone(e["quiet_seconds"])
        self.assertEqual(e["reason"], "quiet unknown")

    def test_fallback_quiet_named_in_every_reason(self):
        s = helpers.make_session(1, changed_at=None, last_message_at=at(2 * H),
                                 pr=pr_sig("merged"))
        self.assertTrue(one(s)["reason"].endswith("; quiet time from last message"))

    def test_headless_quiet_uses_last_message(self):
        s = helpers.make_session(1, kind="headless", pane=None, headless_id="7", changed_at=None,
                                 last_message_at=at(5 * H))
        e = one(s)
        self.assertEqual(e["quiet_seconds"], 5 * H)
        self.assertIn("(from last message)", e["reason"])

    def test_unreadable_conversation_lands_in_stale(self):
        s = helpers.make_session(1, conversation={"status": "unknown", "cause": "copy missing"},
                                 messages=[], changed_at=at(10 * D))
        e = one(s, J(unanswered=True, finished=True))  # judged signals are ignored
        self.assertEqual(e["category"], "stale_decide")
        self.assertTrue(any("could not be read" in line for line in e["recap"]))
        s = helpers.make_session(1, conversation={"status": "unknown", "cause": "copy missing"},
                                 messages=[], pr=pr_sig("merged"))
        self.assertEqual(one(s)["category"], "done_close_it")  # a mechanical signal decides

    def test_agent_state_unknown(self):
        s = helpers.make_session(1, agent_state="unknown", agent_state_cause="raw state unknown",
                                 pr=pr_sig("merged"))
        e = one(s)
        self.assertEqual(e["category"], "done_close_it")
        self.assertTrue(e["reason"].endswith("; agent state unknown"))
        self.assertFalse(e["action"]["preselected"])
        self.assertTrue(e["addable_to_close"])
        s = helpers.make_session(1, agent_state="unknown", agent_state_cause="x")
        e = one(s, J(unanswered=True, followup="go"))
        self.assertEqual(e["category"], "waiting_on_you")
        self.assertIsNone(e["action"]["verb"])
        self.assertTrue(e["addable_to_close"])
        # A forgotten clipboard still gets its copy-back: it needs no live pane (FR-020, FR-025).
        s = helpers.make_session(1, agent_state="unknown", agent_state_cause="x", clipboard=CLIP)
        e = one(s)
        self.assertEqual((e["rule"], e["action"]["verb"]), (2, "copyback"))


class OrderingTest(unittest.TestCase):
    def test_category_order_and_quiet_order(self):
        sessions = [
            helpers.make_session(1, pr=pr_sig("merged"), changed_at=at(1 * H)),
            helpers.make_session(2, pr=pr_sig("open"), changed_at=at(2 * H)),
            helpers.make_session(3, changed_at=at(1 * H)),
            helpers.make_session(4, clipboard=CLIP, changed_at=at(1 * H)),
            helpers.make_session(5, clipboard=CLIP, changed_at=at(9 * H)),
            helpers.make_session(6, clipboard=CLIP, changed_at=None, last_message_at=None),
            helpers.make_session(7, changed_at=at(8 * D)),
        ]
        entries = evaluate(sessions)
        self.assertEqual([e["key"][-1] for e in entries], ["5", "4", "6", "7", "3", "2", "1"])
        self.assertEqual([e["category"] for e in entries], [
            "waiting_on_you", "waiting_on_you", "waiting_on_you", "stale_decide", "stale_decide",
            "waiting_on_others", "done_close_it"])


class ActionTest(unittest.TestCase):
    def test_done_close_preselected(self):
        e = one(helpers.make_session(1, pr=pr_sig("merged")))
        self.assertEqual(e["action"], {"verb": "close", "preselected": True})
        self.assertFalse(e["addable_to_close"])

    def test_jumpable_only_for_live_panes(self):
        self.assertTrue(one(helpers.make_session(1))["jumpable"])
        self.assertTrue(one(helpers.make_session(1, agent_state="blocked"))["jumpable"])
        self.assertFalse(one(helpers.make_session(1, hibernated=True))["jumpable"])
        s = helpers.make_session(1, kind="headless", pane=None, headless_id="3")
        self.assertFalse(one(s)["jumpable"])

    def test_headless_done_close(self):
        s = helpers.make_session(1, kind="headless", pane=None, headless_id="3", pr=pr_sig("merged"))
        self.assertEqual(one(s)["action"]["verb"], "close")

    def test_copyback_for_rule2_clipboard(self):
        s = helpers.make_session(1, clipboard=CLIP, unfinished=unfinished(item("uncommitted")))
        e = one(s, J(unanswered=True, followup="go on"))
        self.assertEqual(e["action"]["verb"], "copyback")
        self.assertEqual(e["action"]["method"], "slack-pbcopy")
        self.assertEqual(e["action"]["args"], "--tight")
        self.assertEqual(e["action"]["text"], "Hello team")
        self.assertFalse(e["action"]["preselected"])
        self.assertTrue(any("Hello team" in line for line in e["recap"]))

    def test_copyback_also_when_hibernated_or_exited(self):
        for overrides in ({"hibernated": True}, {"agent_state": "exited"}):
            e = one(helpers.make_session(1, clipboard=CLIP, **overrides))
            self.assertEqual(e["action"]["verb"], "copyback", overrides)
            self.assertTrue(e["addable_to_close"], overrides)

    def test_no_copyback_for_rule0_or_1(self):
        for state in ("blocked", "working"):
            e = one(helpers.make_session(1, agent_state=state, clipboard=CLIP))
            self.assertIsNone(e["action"]["verb"], state)

    def test_copyback_truncated_or_not_macos(self):
        clip = dict(CLIP, text=None, truncated=True)
        e = one(helpers.make_session(1, clipboard=clip))
        self.assertIsNone(e["action"]["verb"])
        self.assertTrue(any("truncated" in n for n in e["notes"]))
        self.assertIn("truncated", e["recap"][2])  # the recap says why
        e = one(helpers.make_session(1, clipboard=CLIP), platform="linux")
        self.assertIsNone(e["action"]["verb"])
        self.assertTrue(any("macOS" in n for n in e["notes"]))
        self.assertIn("macOS", e["recap"][2])
        e = one(helpers.make_session(1, clipboard=dict(CLIP, text="", first_line="")))
        self.assertEqual(e["action"]["verb"], "copyback")  # empty text is not truncation

    def test_followup_for_other_rule2_live_panes(self):
        e = one(helpers.make_session(1, unfinished=unfinished(item("unpushed", detail="2 unpushed commits"))),
                J(followup="commit, push and open the PR"))
        self.assertEqual(e["action"], {"verb": "message", "preselected": False,
                                       "text": "commit, push and open the PR"})
        e = one(helpers.make_session(1, unfinished=unfinished(item("unpushed", detail="2 unpushed commits"))))
        self.assertEqual(e["action"]["verb"], "message")
        self.assertTrue(e["action"]["text"])  # a default draft when the judgment has none

    def test_no_followup_for_hibernated_or_exited(self):
        for overrides in ({"hibernated": True}, {"agent_state": "exited"}):
            s = helpers.make_session(1, unfinished=unfinished(item("uncommitted")), **overrides)
            e = one(s, J(followup="go"))
            self.assertEqual(e["category"], "waiting_on_you")
            self.assertIsNone(e["action"]["verb"], overrides)
            self.assertTrue(e["addable_to_close"], overrides)
            if overrides.get("hibernated"):
                self.assertTrue(any("hibernated" in line for line in e["recap"]))

    def test_hibernated_done_is_preselected(self):
        e = one(helpers.make_session(1, hibernated=True, pr=pr_sig("merged")))
        self.assertEqual(e["action"], {"verb": "close", "preselected": True})

    def test_none_for_rule0_and_waiting_on_others(self):
        self.assertIsNone(one(helpers.make_session(1, agent_state="blocked"))["action"]["verb"])
        self.assertIsNone(one(helpers.make_session(1, pr=pr_sig("open")))["action"]["verb"])
        self.assertFalse(one(helpers.make_session(1, pr=pr_sig("open")))["addable_to_close"])

    def test_stale_addable_never_preselected(self):
        e = one(helpers.make_session(1, changed_at=at(5 * D)))
        self.assertIsNone(e["action"]["verb"])
        self.assertFalse(e["action"]["preselected"])
        self.assertTrue(e["addable_to_close"])

    def test_recap_at_most_three_lines(self):
        e = one(helpers.make_session(1, clipboard=CLIP, hibernated=True),
                J(about="A" * 300, stopped="B" * 300))
        self.assertLessEqual(len(e["recap"]), 3)
        self.assertLessEqual(len(e["recap"][0]), 100)
        self.assertLessEqual(len(e["recap"][1]), 100)
        e = one(helpers.make_session(1))
        self.assertEqual(e["recap"][0], "session 1")  # name when no judgment
        self.assertEqual(e["recap"][1], "Done.")  # last message first line


class JudgmentsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = helpers.make_digest([helpers.make_session(1)])
        self.key = self.doc["sessions"][0]["key"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, content):
        p = os.path.join(self.tmp, "judgments.json")
        with open(p, "w") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content))
        return p

    def test_valid(self):
        p = self.write({"format": "roundup-judgments", "version": 1,
                        "sessions": {self.key: J(finished=True, note="x" * 200)}})
        j = engine.load_judgments(p, self.doc)
        self.assertTrue(j[self.key]["task_finished"])
        self.assertLessEqual(len(j[self.key]["judgment_note"]), 80)
        self.assertFalse(j[self.key]["pr_round_only"])  # default when left out
        p = self.write({"format": "roundup-judgments", "version": 1,
                        "sessions": {self.key: J(finished=True, round_only=True)}})
        self.assertTrue(engine.load_judgments(p, self.doc)[self.key]["pr_round_only"])

    def test_invalid(self):
        bad = [
            "{nope",
            {"format": "roundup-judgments", "version": 2, "sessions": {}},
            {"format": "other", "version": 1, "sessions": {}},
            {"format": "roundup-judgments", "version": 1, "sessions": {"claude:unknown": J()}},
            {"format": "roundup-judgments", "version": 1, "sessions": {self.key: {"unanswered_agent": "yes"}}},
            {"format": "roundup-judgments", "version": 1, "sessions": {self.key: {"pr_round_only": 1}}},
        ]
        for content in bad:
            with self.assertRaises(InputError, msg=str(content)[:60]):
                engine.load_judgments(self.write(content), self.doc)
        with self.assertRaises(InputError):
            engine.load_judgments(os.path.join(self.tmp, "missing.json"), self.doc)

    def test_cli_exit_4(self):
        dpath = helpers.write_json(os.path.join(self.tmp, "digest.json"), self.doc)
        jpath = self.write({"format": "roundup-judgments", "version": 1,
                            "sessions": {"claude:unknown": J()}})
        proc = subprocess.run([sys.executable, helpers.ROUNDUP_SCRIPT, "overview", "--digest",
                               dpath, "--judgments", jpath], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 4, proc.stderr)


if __name__ == "__main__":
    unittest.main()
