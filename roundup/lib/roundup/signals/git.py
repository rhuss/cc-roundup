"""Git state of a session's folder (FR-010, FR-011, research R7).

One `git --no-optional-locks status --porcelain=v2 --branch` per folder (plus
`git remote` when there is no upstream). No fetch, no lock, no index refresh:
gathering never writes to a repository (FR-004).
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional

GIT_TIMEOUT = 10
_GIT_SELECTORS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                  "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")

_PUSH_CAUSES = {"gone": "upstream gone", "detached": "detached HEAD", "no_remote": "no remote"}


def resolve(path: Optional[str]) -> Optional[str]:
    """Absolute resolved folder (symlinks followed) when it exists, else the path as given."""
    if not path:
        return None
    return os.path.realpath(path) if os.path.exists(path) else path


def unknown_state(cause: str) -> Dict[str, Any]:
    """A FolderState whose git state is unknown for the given cause."""
    return _unknown(cause)


def _unknown(cause: str) -> Dict[str, Any]:
    return {"status": "unknown", "cause": cause, "repo": False, "branch": None,
            "detached": False, "dirty": None, "upstream": None, "ahead": None}


def _git(path: str, *args: str) -> subprocess.CompletedProcess:
    # Inherited repository selectors would make every folder report the same repository.
    env = {k: v for k, v in os.environ.items() if k not in _GIT_SELECTORS}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                           "-C", path] + list(args),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          errors="replace", timeout=GIT_TIMEOUT, env=env)


def folder_state(path: Optional[str]) -> Dict[str, Any]:
    """FolderState for one folder (data-model.md)."""
    if not path:
        return _unknown("no folder")
    if not os.path.isdir(path):
        return _unknown("folder missing")
    try:
        proc = _git(path, "status", "--porcelain=v2", "--branch", "--untracked-files=normal")
    except FileNotFoundError:
        return _unknown("git missing")
    except subprocess.TimeoutExpired:
        return _unknown("timeout")
    except OSError as exc:
        return _unknown("git failed: %s" % (exc.strerror or exc))
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "not a git repository" in err:
            return _unknown("not a git repository")
        return _unknown(err.splitlines()[0] if err else "git status failed")

    branch = None
    detached = False
    has_upstream = False
    ahead = None
    dirty = False
    for line in proc.stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):]
            detached = head == "(detached)"
            branch = None if detached else head
        elif line.startswith("# branch.upstream "):
            has_upstream = True
        elif line.startswith("# branch.ab "):
            parts = line.split()
            try:
                ahead = int(parts[2].lstrip("+"))
            except (IndexError, ValueError):
                ahead = None
        elif line and not line.startswith("#"):
            dirty = True

    if detached:
        upstream = "detached"
        ahead = None
    elif has_upstream:
        upstream = "ok" if ahead is not None else "gone"
    else:
        ahead = None
        try:
            remotes = _git(path, "remote")
        except subprocess.TimeoutExpired:
            remotes = None
            push_cause = "git remote timeout"
        except OSError as exc:
            remotes = None
            push_cause = "git remote failed: %s" % exc
        if remotes is not None and remotes.returncode != 0:
            push_cause = "git remote failed: %s" % ((remotes.stderr or "").strip() or "error")
            remotes = None
        if remotes is None:
            return {"status": "found", "repo": True, "branch": branch, "detached": detached,
                    "dirty": dirty, "upstream": None, "ahead": None, "push_cause": push_cause}
        upstream = "none" if remotes.stdout.strip() else "no_remote"
    return {"status": "found", "repo": True, "branch": branch, "detached": detached,
            "dirty": dirty, "upstream": upstream, "ahead": ahead}


def git_items(state: Dict[str, Any], shared: bool) -> List[Dict[str, Any]]:
    """Unfinished-work items from a FolderState (uncommitted and push state)."""
    if state.get("status") != "found":
        cause = state.get("cause") or "git state unknown"
        return [
            {"kind": "uncommitted", "status": "unknown", "cause": cause, "detail": "",
             "shared": shared},
            {"kind": "unpushed", "status": "unknown", "cause": cause, "detail": "",
             "shared": shared},
        ]
    items = []
    if state.get("dirty"):
        items.append({"kind": "uncommitted", "status": "found", "detail": "uncommitted changes",
                      "shared": shared})
    else:
        items.append({"kind": "uncommitted", "status": "not_found", "detail": "",
                      "shared": shared})
    upstream = state.get("upstream")
    if upstream == "ok":
        ahead = state.get("ahead") or 0
        if ahead > 0:
            detail = "%d unpushed commit%s" % (ahead, "" if ahead == 1 else "s")
            items.append({"kind": "unpushed", "status": "found", "detail": detail,
                          "shared": shared})
        else:
            items.append({"kind": "unpushed", "status": "not_found", "detail": "",
                          "shared": shared})
    elif upstream == "none":
        items.append({"kind": "never_pushed", "status": "found", "detail": "branch never pushed",
                      "shared": shared})
    else:
        cause = _PUSH_CAUSES.get(upstream) or state.get("push_cause") or "push state unknown"
        items.append({"kind": "unpushed", "status": "unknown", "cause": cause, "detail": "",
                      "shared": shared})
    return items


def find_shared(folders_by_key: Dict[str, Optional[str]]) -> Dict[str, List[str]]:
    """For each session key, the other keys whose folder resolves to the same path."""
    resolved_by_key = {key: resolve(path) for key, path in folders_by_key.items()}
    by_folder: Dict[str, List[str]] = {}
    for key, resolved in resolved_by_key.items():
        if resolved:
            by_folder.setdefault(resolved, []).append(key)
    return {key: [k for k in by_folder.get(resolved, []) if k != key] if resolved else []
            for key, resolved in resolved_by_key.items()}
