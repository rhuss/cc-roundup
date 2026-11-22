"""Corgi adapter: snapshot (US1) against the recorded fixtures in tests/fixtures/corgi."""
import unittest

from tests import helpers
from roundup import BackendError


def sid(n, provider="claude"):
    if provider == "codex":
        return "019a0000-0000-7000-8000-%012d" % n
    return "00000000-0000-4000-8000-%012d" % n


def key(n, provider="claude"):
    return "%s:%s" % (provider, sid(n, provider))


class SnapshotTest(unittest.TestCase):
    def snapshot(self, archived=False, caller_pane=108, **env_overrides):
        from roundup.adapters import corgi

        with helpers.StubEnv("corgi", caller_pane=caller_pane) as env:
            with env.patched(**env_overrides):
                snap = corgi.snapshot(archived)
            self.invocations = env.invocations("corgi")
        return snap

    def by_key(self, snap):
        return {s["key"]: s for s in snap["sessions"]}

    # --- scope ---------------------------------------------------------------
    def test_scope_non_archived_only(self):
        sessions = self.by_key(self.snapshot())
        self.assertNotIn(key(109), sessions)  # archived workspace
        self.assertIn(key(101), sessions)
        self.assertIn(key(106), sessions)  # hibernated, non-archived

    def test_archived_flag_includes_archived(self):
        sessions = self.by_key(self.snapshot(archived=True))
        self.assertIn(key(109), sessions)
        self.assertTrue(sessions[key(109)]["workspace"]["archived"])

    def test_caller_excluded(self):
        snap = self.snapshot()
        self.assertEqual(snap["caller"], {"pane": 108, "excluded": True})
        self.assertNotIn(key(108), self.by_key(snap))

    def test_caller_not_identifiable(self):
        snap = self.snapshot(caller_pane=None)
        self.assertFalse(snap["caller"]["excluded"])
        self.assertIn("CORGI_PANE", snap["caller"]["cause"])
        self.assertIn(key(108), self.by_key(snap))
        snap = self.snapshot(caller_pane=4242)
        self.assertFalse(snap["caller"]["excluded"])
        self.assertIn("4242", snap["caller"]["cause"])
        self.assertIn(key(108), self.by_key(snap))

    def test_subagent_helper_shell_and_exited_headless_never_present(self):
        snap = self.snapshot(archived=True, caller_pane=None)
        keys = set(self.by_key(snap))
        self.assertNotIn("claude:a5b0353b922e6bed2", keys)  # subagent
        self.assertNotIn(key(202), keys)  # Ask Corgi helper (headless corgi:true)
        self.assertNotIn(key(204), keys)  # exited headless session
        self.assertFalse(any(k.endswith(":") for k in keys))  # plain shell pane 110

    def test_each_key_once(self):
        snap = self.snapshot()
        keys = [s["key"] for s in snap["sessions"]]
        self.assertEqual(len(keys), len(set(keys)))

    # --- state mapping ---------------------------------------------------------
    def test_state_mapping(self):
        s = self.by_key(self.snapshot())
        self.assertEqual(s[key(101)]["agent_state"], "idle")
        self.assertEqual(s[key(102)]["agent_state"], "working")
        self.assertEqual(s[key(103, "codex")]["agent_state"], "starting")
        self.assertEqual(s[key(104)]["agent_state"], "blocked")
        self.assertEqual(s[key(105)]["agent_state"], "exited")  # unknown + brand null
        self.assertEqual(s[key(114)]["agent_state"], "exited")  # state done
        self.assertEqual(s[key(113)]["agent_state"], "unknown")
        self.assertIn("unknown", s[key(113)]["agent_state_cause"])

    def test_hibernated_is_idle_and_marked(self):
        s = self.by_key(self.snapshot())[key(106)]
        self.assertEqual(s["agent_state"], "idle")
        self.assertTrue(s["hibernated"])
        self.assertFalse(self.by_key(self.snapshot())[key(101)]["hibernated"])

    def test_headless_sessions(self):
        s = self.by_key(self.snapshot())
        h = s[key(201)]
        self.assertEqual(h["kind"], "headless")
        self.assertEqual(h["headless_id"], "5")
        self.assertIsNone(h["changed_at"])  # headless: last-message fallback for quiet time
        self.assertEqual(s[key(203, "codex")]["agent_state"], "blocked")  # pending_requests > 0

    def test_backend_state_kept_for_recheck(self):
        s = self.by_key(self.snapshot())[key(101)]
        self.assertEqual(s["backend_state"]["state"], "idle")
        self.assertIsInstance(s["backend_state"]["changed_at_us"], int)
        self.assertEqual(s["changed_at"], "2026-11-22T07:00:00Z")
        self.assertEqual(s["pane"], 101)
        self.assertEqual(s["workspace"], {"id": 1, "name": "app", "archived": False})
        self.assertEqual(s["folder"], "/Users/me/src/app")

    # --- dedupe ----------------------------------------------------------------
    def test_dedupe_live_beats_dormant(self):
        s = self.by_key(self.snapshot())[key(111)]
        self.assertEqual(s["pane"], 112)
        self.assertEqual(s["also_open_in"], [111])
        self.assertFalse(s["hibernated"])

    def test_dedupe_lowest_pane_id_between_live_panes(self):
        s = self.by_key(self.snapshot())[key(115)]
        self.assertEqual(s["pane"], 115)
        self.assertEqual(s["also_open_in"], [116])

    def test_dedupe_running_pane_beats_exited_pane(self):
        from roundup.adapters import corgi

        def p(pid, state, brand, exited=False, dormant=False):
            return {"id": pid, "workspace": 1, "brand": brand, "exited": exited,
                    "dormant": dormant, "cwd": "/x", "account": "",
                    "agent": {"provider": "claude", "session": "s1", "state": state,
                              "changed_at": 1, "name": "n", "cwd": "/x"}}

        result = {"workspaces": [{"id": 1, "name": "w", "archived": False}],
                  "panes": [p(3, "unknown", None, dormant=True, exited=True),
                            p(5, "unknown", None), p(9, "idle", "claude")],
                  "headless_sessions": []}
        with helpers.StubEnv() as env, env.patched():
            _caller, sessions = corgi.discover(result, False)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["pane"], 9)
        self.assertEqual(sessions[0]["also_open_in"], [3, 5])
        result["panes"] = result["panes"][:2]
        with helpers.StubEnv() as env, env.patched():
            _caller, sessions = corgi.discover(result, False)
        self.assertEqual(sessions[0]["pane"], 5)  # exited pane beats hibernated pane

    def test_history_row_without_flag_falls_back(self):
        from roundup.adapters import corgi

        with helpers.StubEnv("corgi", caller_pane=108) as env:
            doc = env.load_fixture_json("history.json")
            for c in doc["conversations"]:
                c.pop("interrupted")
            env.write_fixture("history.json", doc)
            with env.patched():
                flags, cause = corgi._history()
        self.assertEqual(flags, {})
        self.assertIsNone(cause)

    def test_dedupe_pane_beats_headless(self):
        s = self.by_key(self.snapshot())[key(101)]
        self.assertEqual(s["kind"], "pane")
        self.assertEqual(s["pane"], 101)

    # --- conversation copies -----------------------------------------------------
    def test_bulk_copy_paths(self):
        s = self.by_key(self.snapshot())[key(101)]
        self.assertTrue(s["copy"]["path"].endswith(".jsonl"))
        self.assertTrue(s["copy"]["tools_path"].endswith(".tools.jsonl"))

    def test_per_session_fallback(self):
        snap = self.snapshot()
        s = self.by_key(snap)
        self.assertIsNotNone(s[key(106)]["copy"]["path"])
        self.assertIsNone(s[key(107)]["copy"]["path"])
        self.assertTrue(s[key(107)]["copy"]["cause"])
        greps = [i["argv"] for i in self.invocations if i["argv"][0] == "grep"]
        self.assertIn(["grep", "--workspace", "*", "--max-age", "all", "--tools", "-l", "--json",
                       "--limit", "0", "--max-output", "0", "."], greps)
        self.assertIn(["grep", "--session", key(106), "--tools", "-l", "--json", "."], greps)
        self.assertIn(["grep", "--session", key(107), "--tools", "-l", "--json", "."], greps)
        self.assertNotIn(["grep", "--session", key(101), "--tools", "-l", "--json", "."], greps)

    def test_fallback_budget_marks_late_sessions_unknown(self):
        import time
        from unittest import mock
        from roundup.adapters import corgi

        real = corgi._session_copy

        def slow(k):
            if k == key(106):
                time.sleep(1.5)
            return real(k)

        with helpers.StubEnv("corgi", caller_pane=108) as env:
            with env.patched(), mock.patch.object(corgi, "FALLBACK_BUDGET", 0.5), \
                    mock.patch.object(corgi, "_session_copy", slow):
                s = self.by_key(corgi.snapshot(False))
        self.assertIsNone(s[key(106)]["copy"]["path"])
        self.assertIn("time budget", s[key(106)]["copy"]["cause"])
        self.assertTrue(s[key(107)]["copy"]["cause"])  # fast fallback still recorded
        self.assertNotIn("time budget", s[key(107)]["copy"]["cause"])

    def test_bulk_grep_failure_does_not_fan_out(self):
        from roundup.adapters import corgi

        with helpers.StubEnv("corgi", caller_pane=108) as env:
            env.write_fixture("grep-bulk.jsonl.exit", "2")
            env.write_fixture("grep-bulk.jsonl.stderr", '{"ok":false,"err":"grep exploded"}\n')
            with env.patched():
                snap = corgi.snapshot(False)
            greps = [i["argv"] for i in env.invocations("corgi") if i["argv"][0] == "grep"]
        self.assertEqual(len(greps), 1)  # only the bulk call, no per-session fallback
        for s in snap["sessions"]:
            self.assertIsNone(s["copy"]["path"])
            self.assertIn("grep exploded", s["copy"]["cause"])

    # --- interrupted ---------------------------------------------------------------
    def test_interrupted_from_history(self):
        s = self.by_key(self.snapshot())
        self.assertEqual(s[key(102)]["interrupted"]["status"], "found")
        self.assertEqual(s[key(101)]["interrupted"]["status"], "not_found")

    def test_interrupted_transcript_fallback(self):
        s = self.by_key(self.snapshot())
        self.assertEqual(s[key(104)]["interrupted"]["status"], "found")  # Claude tail
        self.assertEqual(s[key(103, "codex")]["interrupted"]["status"], "found")  # turn_aborted
        self.assertEqual(s[key(105)]["interrupted"]["status"], "unknown")
        self.assertTrue(s[key(105)]["interrupted"]["cause"])

    # --- errors and read-only ------------------------------------------------------
    def test_unreachable_runtime(self):
        from roundup.adapters import corgi

        with helpers.StubEnv("corgi", caller_pane=108) as env:
            with env.patched(ROUNDUP_STUB_CORGI_FAIL="unreachable"):
                with self.assertRaises(BackendError) as ctx:
                    corgi.snapshot(False)
        self.assertIn("connect ENOENT /nonexistent", str(ctx.exception))

    def test_only_read_commands(self):
        self.snapshot()
        commands = {i["argv"][0] for i in self.invocations}
        self.assertTrue(commands <= {"list", "grep", "history"}, commands)
        self.assertIn(["list", "--json"], [i["argv"] for i in self.invocations])
        self.assertIn(["history", "--json", "--limit", "1000"],
                      [i["argv"] for i in self.invocations])

    def test_binary_resolution(self):
        from roundup.adapters import corgi

        with helpers.StubEnv("corgi") as env:
            with env.patched(ROUNDUP_CORGI=None, CORGI_APP_EXE="/opt/corgi-custom"):
                self.assertEqual(corgi.corgi_binary(), "/opt/corgi-custom")
            with env.patched(ROUNDUP_CORGI="/x/stub", CORGI_APP_EXE="/opt/corgi-custom"):
                self.assertEqual(corgi.corgi_binary(), "/x/stub")
            with env.patched(ROUNDUP_CORGI=None, CORGI_APP_EXE=None):
                self.assertEqual(corgi.corgi_binary(), "corgi")


if __name__ == "__main__":
    unittest.main()
