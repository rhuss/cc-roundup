"""Forgotten clipboard detection (US1) and copy-back (US4)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests import helpers
from roundup.signals import clipboard

TEXT = "Hi team, the WG kickoff is today at 17:00 CET.\n\n- point one\n- point two"


def call(command, ts=1795340000000, ref="100", status="success", name="Bash", extra_keys=None):
    keys = extra_keys if extra_keys is not None else [
        "description: Copy the Slack reply to the clipboard as rich text", "timeout: 120000"]
    return {"role": "tool", "timestamp": ts, "ref": ref,
            "tool": {"kind": "call", "name": name, "call_id": "toolu_" + ref, "status": status,
                     "exit_code": None, "call_ref": ref, "result_ref": str(int(ref) + 1)},
            "text": "\n".join([name, "command: " + command] + keys)}


def result(ts=1795340001000, ref="101"):
    return {"role": "tool", "timestamp": ts, "ref": ref,
            "tool": {"kind": "result", "name": "Bash", "call_id": "toolu_x", "status": "success"},
            "text": "exit=0"}


class DetectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tools(self, rows):
        p = os.path.join(self.tmp, "c.tools.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return p

    def detect(self, rows, user_refs=()):
        return clipboard.detect_clipboard(self.tools(rows), list(user_refs))

    def test_malformed_timestamps_fall_back_to_ref_order(self):
        cmd = "slack-pbcopy <<'EOF'\n" + TEXT + "\nEOF"
        sig = self.detect([call(cmd, ts="garbage")], user_refs=[("not-a-number", "50")])
        self.assertEqual(sig["status"], "found")
        self.assertIsNone(sig["at"])
        sig = self.detect([call(cmd, ts="garbage")], user_refs=[(None, "150")])
        self.assertEqual(sig["status"], "not_found")

    def test_slack_pbcopy_heredoc_found(self):
        cmd = "slack-pbcopy --tight <<'EOF'\n%s\nEOF\necho \"exit=$?\"" % TEXT
        sig = self.detect([call(cmd), result()], [(1795330000000, "50")])
        self.assertEqual(sig["status"], "found")
        self.assertEqual(sig["method"], "slack-pbcopy")
        self.assertEqual(sig["args"], "--tight")
        self.assertEqual(sig["text"], TEXT)
        self.assertFalse(sig["truncated"])
        self.assertEqual(sig["first_line"], "Hi team, the WG kickoff is today at 17:00 CET.")
        self.assertTrue(sig["at"].endswith("Z"))

    def test_first_line_cut_to_80(self):
        long_line = "x" * 120
        sig = self.detect([call("pbcopy <<'EOF'\n%s\nEOF" % long_line)])
        self.assertLessEqual(len(sig["first_line"]), 80)
        self.assertEqual(sig["first_line"], "x" * 79 + "…")
        self.assertEqual(sig["text"], long_line)

    def test_later_user_message_not_found(self):
        cmd = "pbcopy <<'EOF'\nhello\nEOF"
        sig = self.detect([call(cmd, ts=1795340000000)], [(1795340005000, "120")])
        self.assertEqual(sig["status"], "not_found")

    def test_plain_pbcopy_and_tag_variants(self):
        for opener in ("<<EOF", "<<\"EOF\"", "<< 'EOF'", "<<-EOF"):
            sig = self.detect([call("pbcopy %s\nhello world\nEOF" % opener)])
            self.assertEqual(sig["status"], "found", opener)
            self.assertEqual(sig["method"], "pbcopy", opener)
            self.assertEqual(sig["args"], "", opener)
            self.assertEqual(sig["text"], "hello world", opener)
            self.assertFalse(sig["truncated"], opener)

    def test_unquoted_heredoc_with_shell_expansion_is_truncated(self):
        # The shell expanded these bodies, so the recorded text is not what was copied.
        for body in ("Home is $HOME", "today is $(date)", "run `date`", "a\\", "tab\\tx"):
            sig = self.detect([call("pbcopy <<EOF\n%s\nEOF" % body)])
            self.assertEqual(sig["status"], "found", body)
            self.assertTrue(sig["truncated"], body)
            self.assertIsNone(sig["text"], body)
        # A quoted delimiter keeps the body literal: exact text, copy-back possible.
        sig = self.detect([call("pbcopy <<'EOF'\nHome is $HOME and `date`\nEOF")])
        self.assertEqual(sig["text"], "Home is $HOME and `date`")
        self.assertFalse(sig["truncated"])

    def test_dash_heredoc_strips_leading_tabs(self):
        sig = self.detect([call("pbcopy <<-'EOF'\n\tline one\n\t\tline two\n\tEOF")])
        self.assertEqual(sig["text"], "line one\nline two")
        self.assertFalse(sig["truncated"])

    def test_tool_only_mentioned_is_not_a_copy(self):
        for cmd in ("which pbcopy", "rg -n pbcopy roundup/", "man slack-pbcopy",
                    "git commit -F - <<'EOF'\nfeat: wire pbcopy fallback\nEOF",
                    "echo 'a | pbcopy'"):
            self.assertEqual(self.detect([call(cmd)])["status"], "not_found", cmd)

    def test_copy_in_command_position(self):
        for cmd in ("echo hi | pbcopy", "echo hi | /usr/bin/pbcopy", "x && pbcopy <<'EOF'\nhi\nEOF"):
            self.assertEqual(self.detect([call(cmd)])["status"], "found", cmd)

    def test_input_key_lines_inside_heredoc_are_text(self):
        sig = self.detect([call("pbcopy <<'EOF'\nline\ndescription: of the bug\ntimeout: 30s\nEOF")])
        self.assertEqual(sig["text"], "line\ndescription: of the bug\ntimeout: 30s")
        self.assertFalse(sig["truncated"])

    def test_redirections_are_not_args_and_unknown_args_block_copyback(self):
        sig = self.detect([call("pbcopy 2>/dev/null <<'EOF'\nhi\nEOF")])
        self.assertEqual((sig["args"], sig["text"]), ("", "hi"))
        sig = self.detect([call("pbcopy -pboard find <<'EOF'\nhi\nEOF")])
        self.assertEqual((sig["args"], sig["text"]), ("-pboard find", "hi"))
        sig = self.detect([call("pbcopy somefile <<'EOF'\nhi\nEOF")])
        self.assertTrue(sig["truncated"])
        self.assertIsNone(sig["text"])

    def test_heredoc_must_feed_the_clipboard_tool(self):
        # Copy-back must restore exactly what the tool received; otherwise no exact text.
        for cmd in ("echo x | pbcopy && cat <<'EOF' >> log.txt\nnot copied\nEOF",
                    "cat <<'EOF' > /tmp/x && sed s/a/b/ /tmp/x | pbcopy\nbody\nEOF",
                    "cat <<'EOF' > /tmp/x && pbcopy < /tmp/x\nbody\nEOF",
                    "cat <<'A' >/dev/null; pbcopy <<'B'\nignore\nA\ndraft\nB",
                    "cat <<'EOF' | sed s/a/b/ | pbcopy\nhello\nEOF",
                    "pbcopy <<'EOF' </tmp/replacement\nhello\nEOF"):
            sig = self.detect([call(cmd)])
            self.assertEqual(sig["status"], "found", cmd)
            self.assertIsNone(sig["text"], cmd)
            self.assertTrue(sig["truncated"], cmd)

    def test_several_copies_are_not_exact(self):
        cmd = ("if command -v slack-pbcopy >/dev/null; then slack-pbcopy <<'EOF'\nhi\nEOF\n"
               "else pbcopy <<'EOF2'\nhi\nEOF2\nfi")
        sig = self.detect([call(cmd)])
        self.assertEqual(sig["status"], "found")
        self.assertIsNone(sig["text"])

    def test_prefixes_keywords_and_comments(self):
        for cmd in ("LC_ALL=en_US.UTF-8 pbcopy <<'EOF'\nhi\nEOF",
                    "cat <<'EOF' | LANG=en_US.UTF-8 pbcopy\nhi\nEOF",
                    "if true; then pbcopy <<'EOF'\nhi\nEOF\nfi",
                    "cat <<'EOF' | pbcopy  # copy draft\nhi\nEOF"):
            sig = self.detect([call(cmd)])
            self.assertEqual((sig["status"], sig["text"]), ("found", "hi"), cmd)

    def test_codex_argv_command(self):
        cmd = json.dumps(["bash", "-lc", "pbcopy <<'EOF'\nfrom argv\nEOF"])
        sig = self.detect([call(cmd, name="shell", extra_keys=["workdir: /x"])])
        self.assertEqual(sig["text"], "from argv")

    def test_cat_heredoc_piped_into_pbcopy(self):
        sig = self.detect([call("cat <<'EOF' | pbcopy\nhello\nEOF")])
        self.assertEqual(sig["status"], "found")
        self.assertEqual(sig["text"], "hello")

    def test_truncated_cases(self):
        cases = [
            call("slack-pbcopy <<'EOF'\nhello\nno closing tag"),
            call("echo hello | pbcopy"),
            call("pbcopy <<'EOF'\nhello\nEOF", status="error"),
            call("pbcopy <<'EOF'\nhello\nEOF", status="interrupted"),
        ]
        for c in cases:
            sig = self.detect([c])
            self.assertEqual(sig["status"], "found", c["text"])
            self.assertTrue(sig["truncated"], c["text"])
            self.assertIsNone(sig["text"], c["text"])
            self.assertIn("first_line", sig)

    def test_command_ends_at_next_input_key(self):
        for key in ("description: x", "timeout: 5", "run_in_background: true",
                    "dangerouslyDisableSandbox: true"):
            sig = self.detect([call("pbcopy <<'EOF'\nbody\nEOF", extra_keys=[key])])
            self.assertEqual(sig["text"], "body", key)
            self.assertFalse(sig["truncated"], key)

    def test_heredoc_tag_never_closed_before_next_key(self):
        sig = self.detect([call("pbcopy <<'EOF'\nbody", extra_keys=["description: EOF"])])
        self.assertTrue(sig["truncated"])

    def test_last_call_not_clipboard(self):
        rows = [call("pbcopy <<'EOF'\nold\nEOF", ref="100"), call("ls -la", ref="110")]
        self.assertEqual(self.detect(rows)["status"], "not_found")

    def test_no_tool_calls(self):
        self.assertEqual(self.detect([])["status"], "not_found")

    def test_codex_shell_call(self):
        rows = [call("pbcopy <<'EOF'\nfrom codex\nEOF", name="shell", extra_keys=["workdir: /x"])]
        sig = self.detect(rows)
        self.assertEqual(sig["status"], "found")
        self.assertEqual(sig["text"], "from codex")

    def test_missing_tools_copy_is_unknown(self):
        sig = clipboard.detect_clipboard(os.path.join(self.tmp, "nope.tools.jsonl"), [])
        self.assertEqual(sig["status"], "unknown")
        self.assertTrue(sig["cause"])
        sig = clipboard.detect_clipboard(None, [])
        self.assertEqual(sig["status"], "unknown")

    def test_null_timestamps_use_ref_order(self):
        c = call("pbcopy <<'EOF'\nhi\nEOF", ts=None, ref="200")
        self.assertEqual(self.detect([c], [(None, "150")])["status"], "found")
        self.assertEqual(self.detect([c], [(None, "250")])["status"], "not_found")
        self.assertEqual(self.detect([c], [(1795340000000, "250")])["status"], "not_found")


CLIP = {"status": "found", "method": "slack-pbcopy", "args": "--tight", "text": TEXT,
        "truncated": False, "at": "2026-11-21T10:00:00Z",
        "first_line": "Hi team, the WG kickoff is today at 17:00 CET."}


class CopyBackTest(unittest.TestCase):
    """Copy-back puts the recorded text back with the original method (US4)."""

    def setUp(self):
        self.env = helpers.StubEnv().__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def digest(self, *sessions):
        return helpers.write_json(self.env.path("digest.json"), helpers.make_digest(list(sessions)))

    def run_copyback(self, k, *closed):
        args = ["copyback", "--digest", self.env.path("digest.json"), "--key", k]
        if closed:
            args += ["--closed"] + list(closed)
        proc = self.env.run(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip())

    @unittest.skipUnless(sys.platform == "darwin", "copy-back runs only on macOS")
    def test_same_method_args_and_text_without_corgi(self):
        for overrides in ({}, {"hibernated": True}, {"agent_state": "exited"}):
            self.env.clear_log()
            s = helpers.make_session(1, clipboard=CLIP, **overrides)
            self.digest(s)
            out = self.run_copyback(s["key"])
            self.assertEqual(out["outcome"], "done", overrides)
            self.assertEqual(out["verb"], "copyback")
            calls = self.env.invocations()
            self.assertEqual([c["tool"] for c in calls], ["slack-pbcopy"], overrides)
            self.assertEqual(calls[0]["argv"], ["--tight"])
            # A heredoc delivers its body plus the final newline; copy-back does the same.
            self.assertEqual(calls[0]["stdin"], TEXT + "\n")

    @unittest.skipUnless(sys.platform == "darwin", "copy-back runs only on macOS")
    def test_plain_pbcopy(self):
        s = helpers.make_session(1, clipboard=dict(CLIP, method="pbcopy", args=""))
        self.digest(s)
        self.assertEqual(self.run_copyback(s["key"])["outcome"], "done")
        calls = self.env.invocations()
        self.assertEqual([(c["tool"], c["argv"]) for c in calls], [("pbcopy", [])])

    def test_closed_earlier_is_skipped(self):
        s = helpers.make_session(1, clipboard=CLIP)
        self.digest(s)
        out = self.run_copyback(s["key"], "claude:other", s["key"])
        self.assertEqual((out["outcome"], out["reason"]),
                         ("skipped", "session was closed earlier in this run"))
        self.assertEqual(self.env.invocations(), [])

    def test_truncated_is_skipped(self):
        s = helpers.make_session(1, clipboard=dict(CLIP, text=None, truncated=True))
        self.digest(s)
        out = self.run_copyback(s["key"])
        self.assertEqual((out["outcome"], out["reason"]), ("skipped", "copied text was truncated"))
        self.assertEqual(self.env.invocations(), [])

    def test_no_clipboard_is_skipped(self):
        s = helpers.make_session(1)
        self.digest(s)
        self.assertEqual(self.run_copyback(s["key"])["outcome"], "skipped")
        self.assertEqual(self.env.invocations(), [])

    def test_not_macos_fails(self):
        from roundup import clipboard_out

        s = helpers.make_session(1, clipboard=CLIP)
        with self.env.patched():
            out = clipboard_out.copy_back(s, set(), platform="linux")
        self.assertEqual((out["outcome"], out["reason"]),
                         ("failed", "copy-back is only available on macOS"))
        self.assertEqual(self.env.invocations(), [])

    def test_tool_missing_fails(self):
        from roundup import clipboard_out

        empty = self.env.path("emptybin")
        os.makedirs(empty)
        s = helpers.make_session(1, clipboard=CLIP)
        with self.env.patched(PATH=empty):
            out = clipboard_out.copy_back(s, set(), platform="darwin")
        self.assertEqual(out["outcome"], "failed")
        self.assertIn("slack-pbcopy", out["reason"])


if __name__ == "__main__":
    unittest.main()
