"""Clipboard copy-back (FR-024, research R9a). Backend-neutral: never talks to the backend.

The text comes from the digest, so no pane re-check is needed. Skipped when the
session was closed earlier in this run, has no forgotten clipboard, or its text is
truncated; failed off macOS, for an unknown method, or when the tool is missing or fails.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable

COPY_TIMEOUT = 15


def _outcome(key: str, result: str, reason: str) -> Dict[str, Any]:
    return {"key": key, "verb": "copyback", "outcome": result, "reason": reason}


def copy_back(session: Dict[str, Any], closed_keys: Iterable[str],
              platform: str = sys.platform) -> Dict[str, Any]:
    key = session["key"]
    clip = (session.get("signals") or {}).get("clipboard") or {}
    if key in set(closed_keys):
        return _outcome(key, "skipped", "session was closed earlier in this run")
    if clip.get("status") != "found":
        return _outcome(key, "skipped", "no forgotten clipboard in this session")
    if clip.get("truncated") or clip.get("text") is None:
        return _outcome(key, "skipped", "copied text was truncated")
    if platform != "darwin":
        return _outcome(key, "failed", "copy-back is only available on macOS")
    method = clip.get("method")
    if method not in ("pbcopy", "slack-pbcopy"):
        return _outcome(key, "failed", "unknown copy method %r" % method)
    tool = shutil.which(method)
    if not tool:
        return _outcome(key, "failed", "%s not found on PATH" % method)
    try:
        args = shlex.split(clip.get("args") or "")
    except ValueError as exc:
        return _outcome(key, "failed", "cannot parse recorded arguments: %s" % exc)
    # The original heredoc delivered its body followed by a newline; do the same.
    text = clip["text"] + "\n"
    try:
        proc = subprocess.run([tool] + args, input=text, capture_output=True, text=True,
                              timeout=COPY_TIMEOUT)
    except subprocess.TimeoutExpired:
        return _outcome(key, "failed", "%s timed out" % method)
    except OSError as exc:
        return _outcome(key, "failed", "%s failed: %s" % (method, exc))
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return _outcome(key, "failed", "%s failed: %s" % (method, err[0] if err else
                                                          "exit %d" % proc.returncode))
    return _outcome(key, "done", "copied back to the clipboard via %s" % method)
