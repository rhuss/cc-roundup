"""Pull request state from the links in the conversation (FR-012, research R8).

Each unique PR is looked up once with `gh pr view <url> --json state,mergedAt,closed`.
Unknown causes: "gh missing", "gh not signed in", "host not GitHub", or the
lookup error text.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from typing import Callable, Dict, List, Union

GH_TIMEOUT = 15
MAX_OTHER_LOOKUPS = 3  # older links in the recap; bounded to keep gathering fast
MAX_TIMEOUTS = 3  # after this many lookup timeouts, the rest fail fast (SC-001)


class LookupFailed(Exception):
    pass


Lookup = Callable[[str], Union[str, Exception]]


class _GhLookup:
    """Cached, thread-safe `gh` lookups; availability checks run once."""

    def __init__(self):
        self._lock = threading.Lock()
        self._checked = False
        self._unavailable = None
        self._gh = "gh"
        self._timeouts = 0
        self._cache: Dict[str, Union[str, Exception]] = {}
        self._pending: Dict[str, threading.Event] = {}

    def _check(self):
        with self._lock:
            if self._checked:
                return self._unavailable
            self._checked = True
            gh = shutil.which("gh")
            if not gh:
                self._unavailable = LookupFailed("gh missing")
            else:
                self._gh = gh
                try:
                    proc = subprocess.run([gh, "auth", "status", "--hostname", "github.com"],
                                          stdin=subprocess.DEVNULL,
                                          capture_output=True, text=True, timeout=GH_TIMEOUT)
                    if proc.returncode != 0:
                        self._unavailable = LookupFailed("gh not signed in")
                except subprocess.TimeoutExpired:
                    self._unavailable = LookupFailed("gh auth status timeout")
                except OSError as exc:
                    self._unavailable = LookupFailed("gh failed: %s" % exc)
            return self._unavailable

    def _fetch(self, url: str) -> Union[str, Exception]:
        with self._lock:
            if self._timeouts >= MAX_TIMEOUTS:
                # Circuit breaker: GitHub is not answering; do not wait out every timeout.
                return LookupFailed("GitHub unreachable (repeated timeouts)")
        try:
            proc = subprocess.run([self._gh, "pr", "view", url, "--json", "state,mergedAt,closed"],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  errors="replace", timeout=GH_TIMEOUT)
        except subprocess.TimeoutExpired:
            with self._lock:
                self._timeouts += 1
            return LookupFailed("timeout")
        except OSError as exc:
            return LookupFailed("gh failed: %s" % exc)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            return LookupFailed(err[0] if err else "gh pr view failed")
        try:
            state = str(json.loads(proc.stdout).get("state", "")).lower()
        except (ValueError, AttributeError):
            return LookupFailed("unreadable gh reply")
        if state not in ("open", "merged", "closed"):
            return LookupFailed("unexpected PR state %r" % state)
        return state

    def __call__(self, url: str) -> Union[str, Exception]:
        unavailable = self._check()
        if unavailable is not None:
            return unavailable
        with self._lock:
            if url in self._cache:
                return self._cache[url]
            event = self._pending.get(url)
            owner = event is None
            if owner:
                event = self._pending[url] = threading.Event()
        if not owner:
            event.wait()
            return self._cache[url]
        result: Union[str, Exception] = LookupFailed("lookup failed")
        try:
            result = self._fetch(url)
        except Exception as exc:  # never leave waiters hanging on this URL
            result = LookupFailed("gh failed: %s" % exc)
        finally:
            with self._lock:
                self._cache[url] = result
                self._pending.pop(url, None)
            event.set()
        return result


def make_lookup() -> Lookup:
    return _GhLookup()


def pr_signal(pr_links: List[str], non_github_links: List[str], lookup: Lookup,
              newest_is_github: bool = True) -> dict:
    """The digest `signals.pr` object; pr_links are ordered most recent mention first.

    newest_is_github is False when the most recently mentioned PR-like link is not on
    GitHub: that link decides (FR-012), so the state is unknown "host not GitHub".
    """
    if pr_links and not newest_is_github:
        others = [{"url": url, "state": None} for url in pr_links]
        return {"status": "unknown", "cause": "host not GitHub", "current": None,
                "others": others}
    if not pr_links:
        if non_github_links:
            return {"status": "unknown", "cause": "host not GitHub", "current": None,
                    "others": []}
        return {"status": "not_found", "current": None, "others": []}
    # The deciding PR first, so slow historical links can never trip the circuit breaker on it.
    result = lookup(pr_links[0])
    others = []
    for i, url in enumerate(pr_links[1:]):
        state = lookup(url) if i < MAX_OTHER_LOOKUPS else None
        others.append({"url": url, "state": None if isinstance(state, Exception) else state})
    if isinstance(result, Exception):
        return {"status": "unknown", "cause": str(result) or "lookup failed",
                "current": {"url": pr_links[0], "state": None}, "others": others}
    return {"status": "found", "current": {"url": pr_links[0], "state": result},
            "others": others}
