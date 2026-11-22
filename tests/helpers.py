"""Shared test harness: stub executables on PATH, git fixture repositories.

Nothing here touches a live Corgi runtime, the network or the real clipboard.
The stub `corgi`, `gh`, `pbcopy` and `slack-pbcopy` executables log every
invocation (argv and stdin) so tests can assert exactly which commands ran.
"""
import atexit
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
PLUGIN_ROOT = os.path.join(REPO_ROOT, "roundup")
LIB_DIR = os.path.join(PLUGIN_ROOT, "lib")
ROUNDUP_SCRIPT = os.path.join(PLUGIN_ROOT, "scripts", "roundup")
STUBS_DIR = os.path.join(TESTS_DIR, "stubs")
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures")

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

# Fixed "now" for deterministic quiet times in tests.
TEST_NOW = "2026-11-22T12:00:00Z"

_CLEARED_VARS = (
    "CORGI_PANE",
    "CORGI_APP_EXE",
    "CORGI_SOCKET",
    "ROUNDUP_CORGI",
    "ROUNDUP_DEBUG",
    "ROUNDUP_NOW",
    "ROUNDUP_STUB_CORGI_FAIL",
    "ROUNDUP_STUB_GH_AUTH",
    # Repository selectors would point git at a real repository despite -C.
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_NAMESPACE",
)


class StubEnv:
    """Temporary directory with stub executables first on PATH.

    fixtures: name of a directory under tests/fixtures (or an absolute path);
    it is copied to <tmp>/fixtures so tests may modify it freely. The stubs
    replace @FIXTURES@ and @ROOT@ in served replies with the copied fixture
    directory and <tmp>/root.
    """

    def __init__(self, fixtures=None, caller_pane=None, now=TEST_NOW, extra_env=None):
        self.fixtures_src = fixtures
        self.caller_pane = caller_pane
        self.now = now
        self.extra_env = extra_env or {}

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="roundup-test-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name in os.listdir(STUBS_DIR):
            src = os.path.join(STUBS_DIR, name)
            if os.path.isfile(src):
                dst = os.path.join(self.bin, name)
                shutil.copy(src, dst)
                os.chmod(dst, 0o755)
        self.fixtures = os.path.join(self.tmp, "fixtures")
        if self.fixtures_src:
            src = self.fixtures_src
            if not os.path.isabs(src):
                src = os.path.join(FIXTURES_DIR, src)
            shutil.copytree(src, self.fixtures)
            gh_src = os.path.join(FIXTURES_DIR, "gh")
            if not os.path.isdir(os.path.join(self.fixtures, "gh")) and os.path.isdir(gh_src):
                shutil.copytree(gh_src, os.path.join(self.fixtures, "gh"))
        else:
            os.makedirs(self.fixtures)
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(self.root)
        self.log = os.path.join(self.tmp, "invocations.jsonl")
        env = dict(os.environ)
        for var in _CLEARED_VARS:
            env.pop(var, None)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["ROUNDUP_CORGI"] = os.path.join(self.bin, "corgi")
        env["ROUNDUP_STUB_FIXTURES"] = self.fixtures
        env["ROUNDUP_STUB_ROOT"] = self.root
        env["ROUNDUP_STUB_LOG"] = self.log
        # Keep the channel probes away from the developer's real agent homes.
        env["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "claude-home")
        env["CODEX_HOME"] = os.path.join(self.tmp, "codex-home")
        if self.caller_pane is not None:
            env["CORGI_PANE"] = str(self.caller_pane)
        if self.now:
            env["ROUNDUP_NOW"] = self.now
        env.update(self.extra_env)
        self.env = env
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def run(self, *args, input=None, env=None):
        """Run the roundup entry point as a subprocess under this environment."""
        full_env = dict(self.env)
        if env:
            for k, v in env.items():
                if v is None:
                    full_env.pop(k, None)
                else:
                    full_env[k] = v
        return subprocess.run(
            [sys.executable, ROUNDUP_SCRIPT] + list(args),
            input=input,
            stdin=None if input is not None else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=full_env,
            cwd=self.tmp,
            timeout=120,
        )

    @contextlib.contextmanager
    def patched(self, **overrides):
        """Apply this environment to os.environ for in-process tests."""
        saved = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(self.env)
            for k, v in overrides.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            yield self
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def invocations(self, tool=None):
        """List of {tool, argv, stdin} dicts in call order."""
        if not os.path.exists(self.log):
            return []
        out = []
        with open(self.log, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    if tool is None or rec.get("tool") == tool:
                        out.append(rec)
        return out

    def clear_log(self):
        if os.path.exists(self.log):
            os.remove(self.log)

    def write_fixture(self, relpath, content):
        p = os.path.join(self.fixtures, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            if isinstance(content, (dict, list)):
                json.dump(content, fh)
            else:
                fh.write(content)
        return p

    def load_fixture_json(self, relpath):
        with open(os.path.join(self.fixtures, relpath), encoding="utf-8") as fh:
            return json.load(fh)

    def build_world_repos(self):
        """Create git repositories described by <fixtures>/repos.json under @ROOT@."""
        spec_path = os.path.join(self.fixtures, "repos.json")
        if not os.path.exists(spec_path):
            return {}
        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
        made = {}
        for rel, opts in spec.items():
            target = os.path.join(self.root, rel)
            if opts.get("kind") == "plain_dir":
                os.makedirs(target, exist_ok=True)
            elif opts.get("kind") == "symlink":
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(os.path.join(self.root, opts["to"]), target)
            else:
                make_git_repo(target, **{k: v for k, v in opts.items() if k != "kind"})
            made[rel] = target
        return made


_TEMPLATE_DIR = []


def _empty_template_dir():
    if not _TEMPLATE_DIR:
        path = tempfile.mkdtemp(prefix="roundup-git-template-")
        atexit.register(shutil.rmtree, path, True)
        _TEMPLATE_DIR.append(path)
    return _TEMPLATE_DIR[0]


def _git_env():
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED_VARS}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_TERMINAL_PROMPT": "0",
            # No developer template hooks in fixture repositories (they would run on commit).
            "GIT_TEMPLATE_DIR": _empty_template_dir(),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": os.devnull,
        }
    )
    return env


def git(path, *args):
    return subprocess.run(
        ["git", "-C", path, "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
        + list(args),
        check=True,
        capture_output=True,
        text=True,
        env=_git_env(),
    ).stdout


def _commit(path, name, content):
    with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
        fh.write(content)
    git(path, "add", name)
    git(path, "commit", "-q", "-m", "change " + name)


def make_git_repo(path, *, dirty=False, ahead=0, upstream="ok", detached=False, remote=True,
                  worktree=None):
    """Build a real git repository at `path` with a local bare remote (no network).

    upstream: "ok" (feature branch pushed and tracked), "none" (never pushed),
    "gone" (tracked upstream deleted after push). worktree: if set, also add a
    linked worktree at that path (on its own branch).
    """
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q")
    git(path, "checkout", "-q", "-b", "main")
    _commit(path, "README.md", "hello\n")
    if remote:
        bare = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".origin.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True, capture_output=True,
                       env=_git_env())
        git(path, "remote", "add", "origin", bare)
        git(path, "push", "-q", "-u", "origin", "main")
    git(path, "checkout", "-q", "-b", "feature")
    _commit(path, "feature.txt", "feature\n")
    if remote and upstream in ("ok", "gone"):
        git(path, "push", "-q", "-u", "origin", "feature")
        if upstream == "gone":
            git(path, "push", "-q", "origin", "--delete", "feature")
    for i in range(ahead):
        _commit(path, "ahead%d.txt" % i, "x%d\n" % i)
    if detached:
        git(path, "checkout", "-q", "--detach")
    if dirty:
        with open(os.path.join(path, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("local edit\n")
    if worktree:
        git(path, "worktree", "add", "-q", "-b", "wt-branch", worktree)
    return path


# ---------------------------------------------------------------------------
# Hand-built digests for unit tests of the backend-neutral core.

def make_signal(status="not_found", **extra):
    sig = {"status": status}
    sig.update(extra)
    return sig


def make_session(n=1, **overrides):
    """A valid digest session (idle Claude pane, nothing found) with overrides.

    Signals can be overridden one by one via clipboard=, unfinished=, pr=,
    shared_folder= keyword arguments.
    """
    sid = "00000000-0000-4000-8000-%012d" % n
    signals = {
        "clipboard": overrides.pop("clipboard", {"status": "not_found"}),
        "unfinished": overrides.pop("unfinished", {"status": "not_found", "items": []}),
        "shared_folder": overrides.pop("shared_folder", {"shared": False, "sessions": []}),
        "pr": overrides.pop("pr", {"status": "not_found", "current": None, "others": []}),
    }
    session = {
        "key": "claude:" + sid,
        "provider": "claude",
        "session_id": sid,
        "name": "session %d" % n,
        "kind": "pane",
        "pane": 100 + n,
        "headless_id": None,
        "hibernated": False,
        "workspace": {"id": 1, "name": "app", "archived": False},
        "folder": None,
        "agent_state": "idle",
        "backend_state": {"state": "idle", "changed_at_us": 1795320000000000},
        "changed_at": "2026-11-22T04:00:00Z",
        "first_activity_at": "2026-11-21T08:00:00Z",
        "last_message_at": "2026-11-22T03:59:00Z",
        "conversation": {"status": "found"},
        "messages": [
            {"role": "user", "at": "2026-11-22T03:58:00Z", "text": "please do it", "cut": False},
            {"role": "assistant", "at": "2026-11-22T03:59:00Z", "text": "Done.", "cut": False},
        ],
        "pr_links": [],
        "also_open_in": [],
        "signals": signals,
    }
    session.update(overrides)
    return session


def make_digest(sessions, generated_at=TEST_NOW, folders=None, caller=None):
    folders = dict(folders or {})
    for s in sessions:
        if s.get("folder") and s["folder"] not in folders:
            folders[s["folder"]] = {"status": "found", "repo": True, "branch": "main",
                                   "detached": False, "dirty": False, "upstream": "ok",
                                   "ahead": 0}
    return {
        "format": "roundup-digest",
        "version": 1,
        "generated_at": generated_at,
        "backend": "corgi",
        "options": {"archived": False},
        "caller": caller or {"pane": 900, "excluded": True},
        "folders": folders,
        "sessions": sessions,
    }


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path
