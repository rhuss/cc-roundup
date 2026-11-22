"""Git folder signals against real repositories built in temporary directories."""
import os
import shutil
import tempfile
import time
import unittest

from tests import helpers
from roundup.signals import git as gitsig


def items_by_kind(items):
    return {i["kind"]: i for i in items}


class GitSignalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def repo(self, name="r", **opts):
        return helpers.make_git_repo(os.path.join(self.tmp, name), **opts)

    def test_clean(self):
        st = gitsig.folder_state(self.repo())
        self.assertEqual(st["status"], "found")
        self.assertTrue(st["repo"])
        self.assertEqual(st["branch"], "feature")
        self.assertFalse(st["detached"])
        self.assertFalse(st["dirty"])
        self.assertEqual(st["upstream"], "ok")
        self.assertEqual(st["ahead"], 0)
        items = items_by_kind(gitsig.git_items(st, shared=False))
        self.assertEqual(items["uncommitted"]["status"], "not_found")
        self.assertEqual(items["unpushed"]["status"], "not_found")
        self.assertFalse(items["unpushed"]["shared"])

    def test_untracked_counted_even_when_hidden_by_config(self):
        path = self.repo()
        helpers.git(path, "config", "status.showUntrackedFiles", "no")
        with open(os.path.join(path, "new.txt"), "w") as fh:
            fh.write("x")
        self.assertTrue(gitsig.folder_state(path)["dirty"])

    def test_inherited_git_dir_is_ignored(self):
        clean = self.repo("clean")
        dirty = self.repo("dirty", dirty=True)
        saved = dict(os.environ)
        try:
            os.environ["GIT_DIR"] = os.path.join(dirty, ".git")
            os.environ["GIT_WORK_TREE"] = dirty
            st = gitsig.folder_state(clean)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertFalse(st["dirty"])

    def test_dirty(self):
        items = items_by_kind(gitsig.git_items(gitsig.folder_state(self.repo(dirty=True)), False))
        self.assertEqual(items["uncommitted"]["status"], "found")
        self.assertIn("uncommitted", items["uncommitted"]["detail"])

    def test_untracked_counts_as_uncommitted(self):
        path = self.repo()
        with open(os.path.join(path, "new.txt"), "w") as fh:
            fh.write("x")
        items = items_by_kind(gitsig.git_items(gitsig.folder_state(path), False))
        self.assertEqual(items["uncommitted"]["status"], "found")

    def test_ahead(self):
        st = gitsig.folder_state(self.repo(ahead=2))
        self.assertEqual(st["ahead"], 2)
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertEqual(items["unpushed"]["status"], "found")
        self.assertEqual(items["unpushed"]["detail"], "2 unpushed commits")

    def test_never_pushed(self):
        st = gitsig.folder_state(self.repo(upstream="none"))
        self.assertEqual(st["upstream"], "none")
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertNotIn("unpushed", items)
        self.assertEqual(items["never_pushed"]["status"], "found")
        self.assertEqual(items["never_pushed"]["detail"], "branch never pushed")

    def test_upstream_gone(self):
        st = gitsig.folder_state(self.repo(upstream="gone"))
        self.assertEqual(st["upstream"], "gone")
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertEqual(items["unpushed"]["status"], "unknown")
        self.assertEqual(items["unpushed"]["cause"], "upstream gone")

    def test_detached(self):
        st = gitsig.folder_state(self.repo(detached=True))
        self.assertTrue(st["detached"])
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertEqual(items["unpushed"]["status"], "unknown")
        self.assertEqual(items["unpushed"]["cause"], "detached HEAD")

    def test_no_remote(self):
        st = gitsig.folder_state(self.repo(remote=False))
        self.assertEqual(st["upstream"], "no_remote")
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertEqual(items["unpushed"]["status"], "unknown")
        self.assertEqual(items["unpushed"]["cause"], "no remote")

    def test_git_remote_failure_is_unknown(self):
        st = {"status": "found", "repo": True, "branch": "b", "detached": False, "dirty": False,
              "upstream": None, "ahead": None, "push_cause": "git remote failed: boom"}
        items = items_by_kind(gitsig.git_items(st, False))
        self.assertEqual(items["unpushed"]["status"], "unknown")
        self.assertEqual(items["unpushed"]["cause"], "git remote failed: boom")
        self.assertNotIn("never_pushed", items)

    def test_not_a_repository_and_missing_folder(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        for path, cause in ((plain, "not a git repository"),
                            (os.path.join(self.tmp, "missing"), "folder missing")):
            st = gitsig.folder_state(path)
            self.assertEqual(st["status"], "unknown")
            self.assertEqual(st["cause"], cause)
            self.assertFalse(st["repo"])
            items = gitsig.git_items(st, False)
            self.assertTrue(items)
            for item in items:
                self.assertEqual(item["status"], "unknown")
                self.assertEqual(item["cause"], cause)

    def test_no_folder(self):
        items = gitsig.git_items(gitsig.folder_state(None), False)
        self.assertTrue(all(i["status"] == "unknown" for i in items))

    def test_shared_marks_items(self):
        items = gitsig.git_items(gitsig.folder_state(self.repo(dirty=True)), shared=True)
        self.assertTrue(all(i["shared"] for i in items))

    def test_shared_folders_by_realpath(self):
        path = self.repo()
        link = os.path.join(self.tmp, "link")
        os.symlink(path, link)
        wt = os.path.join(self.tmp, "wt")
        helpers.git(path, "worktree", "add", "-q", "-b", "wt-branch", wt)
        shared = gitsig.find_shared({"a": path, "b": link, "c": wt, "d": None})
        self.assertEqual(shared["a"], ["b"])
        self.assertEqual(shared["b"], ["a"])
        self.assertEqual(shared["c"], [])  # another worktree is another folder
        self.assertEqual(shared["d"], [])
        self.assertEqual(gitsig.resolve(link), path)

    def test_gathering_does_not_write_to_the_repository(self):
        path = self.repo(dirty=True)
        index = os.path.join(path, ".git", "index")
        # Make the index stale so a plain `git status` would refresh and rewrite it.
        future = time.time() + 5
        os.utime(os.path.join(path, "feature.txt"), (future, future))
        def snapshot():
            with open(index, "rb") as fh:
                return os.stat(index).st_mtime_ns, fh.read()

        before = snapshot()
        gitsig.folder_state(path)
        after = snapshot()
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(os.path.join(path, ".git", "index.lock")))


if __name__ == "__main__":
    unittest.main()
