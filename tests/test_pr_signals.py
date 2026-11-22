"""Pull request state via the stub `gh` (fixtures in tests/fixtures/gh)."""
import os
import unittest

from tests import helpers
from roundup.signals import pr

OPEN = "https://github.com/me/app/pull/1"
MERGED = "https://github.com/me/app/pull/2"
CLOSED = "https://github.com/me/app/pull/3"
MISSING = "https://github.com/me/app/pull/404"


class PrSignalTest(unittest.TestCase):
    def run_signal(self, links, non_github=(), **env_overrides):
        with helpers.StubEnv("corgi") as env:
            with env.patched(**env_overrides):
                lookup = pr.make_lookup()
                sig = pr.pr_signal(list(links), list(non_github), lookup)
            self.gh_calls = env.invocations("gh")
        return sig

    def test_states(self):
        for url, state in ((OPEN, "open"), (MERGED, "merged"), (CLOSED, "closed")):
            sig = self.run_signal([url])
            self.assertEqual(sig["status"], "found")
            self.assertEqual(sig["current"], {"url": url, "state": state})
            self.assertEqual(sig["others"], [])

    def test_most_recent_decides_others_listed(self):
        sig = self.run_signal([MERGED, OPEN])
        self.assertEqual(sig["current"]["state"], "merged")
        self.assertEqual(sig["others"], [{"url": OPEN, "state": "open"}])

    def test_gh_missing(self):
        with helpers.StubEnv("corgi") as env:
            empty = env.path("emptybin")
            os.makedirs(empty)
            with env.patched(PATH=empty):
                sig = pr.pr_signal([OPEN], [], pr.make_lookup())
        self.assertEqual(sig["status"], "unknown")
        self.assertEqual(sig["cause"], "gh missing")

    def test_gh_not_signed_in(self):
        sig = self.run_signal([OPEN], ROUNDUP_STUB_GH_AUTH="1")
        self.assertEqual(sig["status"], "unknown")
        self.assertEqual(sig["cause"], "gh not signed in")

    def test_only_non_github_links(self):
        sig = self.run_signal([], ["https://gitlab.com/me/app/-/merge_requests/4"])
        self.assertEqual(sig["status"], "unknown")
        self.assertEqual(sig["cause"], "host not GitHub")
        self.assertEqual(self.gh_calls, [])

    def test_newest_link_not_github(self):
        sig = self.run_signal([OPEN], ["https://gitlab.com/me/app/-/merge_requests/4"])
        self.assertEqual(sig["status"], "found")  # GitHub link is the newest by default
        with helpers.StubEnv("corgi") as env, env.patched():
            sig = pr.pr_signal([OPEN], ["https://gitlab.com/me/app/-/merge_requests/4"],
                               pr.make_lookup(), newest_is_github=False)
        self.assertEqual((sig["status"], sig["cause"]), ("unknown", "host not GitHub"))
        self.assertEqual(sig["others"], [{"url": OPEN, "state": None}])

    def test_lookup_error(self):
        sig = self.run_signal([MISSING])
        self.assertEqual(sig["status"], "unknown")
        self.assertIn("Could not resolve", sig["cause"])
        self.assertEqual(sig["current"], {"url": MISSING, "state": None})

    def test_no_links(self):
        sig = self.run_signal([])
        self.assertEqual(sig, {"status": "not_found", "current": None, "others": []})
        self.assertEqual(self.gh_calls, [])

    def test_each_pr_looked_up_once(self):
        with helpers.StubEnv("corgi") as env:
            with env.patched():
                lookup = pr.make_lookup()
                pr.pr_signal([OPEN, MERGED], [], lookup)
                pr.pr_signal([MERGED], [], lookup)
                lookup(OPEN)
            views = [c["argv"] for c in env.invocations("gh") if c["argv"][:2] == ["pr", "view"]]
            auths = [c for c in env.invocations("gh") if c["argv"][:2] == ["auth", "status"]]
        self.assertEqual(sorted(v[2] for v in views), sorted([OPEN, MERGED]))
        self.assertEqual(len(auths), 1)
        self.assertIn(["pr", "view", OPEN, "--json", "state,mergedAt,closed"], views)

    def test_current_pr_looked_up_first_and_breaker(self):
        calls = []

        def lookup(url):
            calls.append(url)
            return "merged"

        sig = pr.pr_signal([MERGED, OPEN], [], lookup)
        self.assertEqual(calls[0], MERGED)
        self.assertEqual(sig["current"]["state"], "merged")

        lk = pr.make_lookup()
        lk._checked, lk._timeouts = True, pr.MAX_TIMEOUTS
        result = lk(OPEN)
        self.assertIsInstance(result, Exception)
        self.assertIn("unreachable", str(result))


class InternalErrorTest(unittest.TestCase):
    def test_unexpected_exception_is_one_line_exit_1(self):
        import io
        from contextlib import redirect_stderr
        from unittest import mock
        from roundup import cli

        err = io.StringIO()
        with mock.patch.object(cli, "cmd_judge_view", side_effect=RuntimeError("kaputt")):
            with redirect_stderr(err):
                code = cli.main(["judge-view", "--digest", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue().strip(), "roundup: internal error: RuntimeError: kaputt")


if __name__ == "__main__":
    unittest.main()
