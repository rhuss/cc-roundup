"""Category engine (data-model.md, FR-013 to FR-021).

Turns the digest plus the agent's judgments into ordered overview entries:
category, rule, one-line reason, quiet time, a recap of at most three lines,
and at most one proposed action per session. Deterministic and read-only.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from . import InputError, timefmt
from .digest import PUSH_CAUSES_IGNORED, cut

JUDGMENTS_FORMAT = "roundup-judgments"
JUDGMENTS_VERSION = 1

WAITING_ON_YOU = "waiting_on_you"
STALE_DECIDE = "stale_decide"
WAITING_ON_OTHERS = "waiting_on_others"
DONE_CLOSE_IT = "done_close_it"
CATEGORY_ORDER = (WAITING_ON_YOU, STALE_DECIDE, WAITING_ON_OTHERS, DONE_CLOSE_IT)
CATEGORY_LABELS = {
    WAITING_ON_YOU: "Waiting on you",
    STALE_DECIDE: "Stale, decide",
    WAITING_ON_OTHERS: "Waiting on others",
    DONE_CLOSE_IT: "Done, close it",
}

RECAP_CHARS = 100
NOTE_CHARS = 80
GIT_KINDS = ("uncommitted", "unpushed", "never_pushed")

_DEFAULT_FOLLOWUPS = {
    "unanswered": "Yes, please go ahead with what you proposed.",
    "checklist": "Please continue with the open checklist items.",
    "uncommitted": "Please commit your changes, push them and open a PR if needed.",
    "unpushed": "Please push your commits and open a PR if needed.",
    "never_pushed": "Please push the branch and open a PR.",
    "interrupted": "Your last turn was interrupted. Please pick up where you left off.",
}


# ---------------------------------------------------------------------------
# Judgments file (contracts/judgments-v1.md)


def _one_line(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    return cut(" ".join(str(value).split()), limit)


def load_judgments(path: str, digest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Read and check a judgments file against the digest. Raises InputError."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise InputError("cannot read judgments %s: %s" % (path, exc.strerror or exc))
    except ValueError as exc:
        raise InputError("judgments %s is not valid JSON: %s" % (path, exc))
    if not isinstance(doc, dict) or doc.get("format") != JUDGMENTS_FORMAT:
        raise InputError("judgments file format is not %s" % JUDGMENTS_FORMAT)
    version = doc.get("version")
    if type(version) is not int or version != JUDGMENTS_VERSION:
        raise InputError("unsupported judgments version %s" % version)
    sessions = doc.get("sessions")
    if not isinstance(sessions, dict):
        raise InputError("judgments sessions is not an object")
    known = {s["key"] for s in digest.get("sessions") or []}
    out = {}
    for key, j in sessions.items():
        if key not in known:
            raise InputError("unknown session key in judgments: %s" % key)
        if not isinstance(j, dict):
            raise InputError("judgment for %s is not an object" % key)
        for flag in ("unanswered_agent", "task_finished"):
            if flag in j and not isinstance(j[flag], bool):
                raise InputError("judgment %s.%s must be true or false" % (key, flag))
        for text in ("about", "stopped", "followup", "judgment_note"):
            if j.get(text) is not None and not isinstance(j[text], str):
                raise InputError("judgment %s.%s must be a string or null" % (key, text))
        out[key] = {
            "unanswered_agent": bool(j.get("unanswered_agent", False)),
            "task_finished": bool(j.get("task_finished", False)),
            "about": _one_line(j.get("about"), RECAP_CHARS),
            "stopped": _one_line(j.get("stopped"), RECAP_CHARS),
            "followup": j["followup"] if (j.get("followup") or "").strip() else None,
            "judgment_note": _one_line(j.get("judgment_note"), NOTE_CHARS),
        }
    return out


# ---------------------------------------------------------------------------
# Evaluation


def _quiet(session: Dict[str, Any], generated_at: str):
    """(seconds or None, measured from last message?)"""
    if session.get("changed_at"):
        return timefmt.seconds_between(session["changed_at"], generated_at), False
    if session.get("last_message_at"):
        return timefmt.seconds_between(session["last_message_at"], generated_at), True
    return None, False


def _quiet_text(seconds: Optional[int], from_message: bool) -> str:
    if seconds is None:
        return "quiet unknown"
    text = "quiet " + timefmt.format_duration(seconds)
    return text + " (from last message)" if from_message else text


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _recap(session, j, conv_ok, quiet_seconds, from_message, clip,
           copyback_note=None) -> List[str]:
    about = (j.get("about") if conv_ok else None) or session.get("name") or session["key"]
    if not conv_ok:
        cause = (session.get("conversation") or {}).get("cause") or "unreadable"
        stopped = "conversation could not be read (%s)" % cause
    else:
        msgs = session.get("messages") or []
        stopped = j.get("stopped") or (_first_line(msgs[-1]["text"]) if msgs else "no messages")
    status = [_quiet_text(quiet_seconds, from_message)]
    if session.get("hibernated"):
        status.append("hibernated")
    if session.get("agent_state") == "exited":
        status.append("agent exited, shell remains" if session.get("kind") == "pane"
                      else "agent exited")
    if clip.get("status") == "found":
        entry = 'clipboard: "%s"' % (clip.get("first_line") or "")
        if clip.get("truncated") or clip.get("text") is None:
            entry += " (no copy-back: copied text was truncated)"
        elif copyback_note:
            entry += " (%s)" % copyback_note
        status.append(entry)
    return [cut(about, RECAP_CHARS), cut(stopped, RECAP_CHARS), "; ".join(status)]


def _note(j: Dict[str, Any], fallback: str) -> str:
    return j.get("judgment_note") or j.get("stopped") or fallback


def evaluate(digest: Dict[str, Any], judgments: Dict[str, Dict[str, Any]],
             stale_seconds: int, platform: str = sys.platform) -> List[Dict[str, Any]]:
    """Overview entries, already in display order (FR-017)."""
    generated_at = digest["generated_at"]
    entries = []
    for s in digest.get("sessions") or []:
        entries.append(_evaluate_one(s, judgments.get(s["key"]) or {}, generated_at,
                                     stale_seconds, platform))
    entries.sort(key=lambda e: (CATEGORY_ORDER.index(e["category"]), e["quiet_seconds"] is None,
                                -(e["quiet_seconds"] or 0), e["key"]))
    return entries


def _evaluate_one(s, j, generated_at, stale_seconds, platform) -> Dict[str, Any]:
    sig = s.get("signals") or {}
    state = s.get("agent_state")
    conv_ok = (s.get("conversation") or {}).get("status") == "found"
    unanswered = conv_ok and bool(j.get("unanswered_agent"))
    finished = conv_ok and bool(j.get("task_finished"))
    clip = sig.get("clipboard") or {}
    clip_found = clip.get("status") == "found"
    items = (sig.get("unfinished") or {}).get("items") or []
    own_found = [i for i in items if not i.get("shared") and i.get("status") == "found"]
    shared_found = [i for i in items if i.get("shared") and i.get("status") == "found"]
    pr = sig.get("pr") or {}
    pr_cur = pr.get("current") if pr.get("status") == "found" else None
    pr_state = (pr_cur or {}).get("state")
    quiet_seconds, from_message = _quiet(s, generated_at)

    if state == "blocked":
        category, rule, reason = WAITING_ON_YOU, 0, "approval pending"
    elif state in ("working", "starting"):
        category, rule = WAITING_ON_OTHERS, 1
        reason = "agent working" if state == "working" else "agent starting up"
    elif unanswered or clip_found or own_found:
        category, rule = WAITING_ON_YOU, 2
        if unanswered:
            reason = "agent asked: " + _note(j, "question pending")
        elif clip_found:
            reason = "clipboard copy never pasted"
        else:
            reason = own_found[0].get("detail") or own_found[0]["kind"]
    elif pr_state == "open":
        category, rule, reason = WAITING_ON_OTHERS, 3, "PR open: " + pr_cur["url"]
    elif pr_state in ("merged", "closed") or finished:
        category, rule = DONE_CLOSE_IT, 4
        if pr_state in ("merged", "closed"):
            reason = "PR %s: %s" % (pr_state, pr_cur["url"])
        else:
            reason = "task finished: " + _note(j, "per conversation")
    else:
        category, rule = STALE_DECIDE, 5
        reason = _quiet_text(quiet_seconds, from_message)
        if quiet_seconds is not None and quiet_seconds >= stale_seconds:
            reason += ", stale"

    # FR-015: never done while working or with own uncommitted/unpushed work.
    if category == DONE_CLOSE_IT and (
            state == "working" or any(i["kind"] in GIT_KINDS for i in own_found)):
        raise RuntimeError("FR-015 invariant violated for %s" % s["key"])

    if from_message and rule != 5:
        reason += "; quiet time from last message"
    if shared_found:
        reason += "; shared folder: " + ", ".join(i.get("detail") or i["kind"]
                                                   for i in shared_found)
    if state == "unknown":
        reason += "; agent state unknown"

    notes = []
    hibernated = bool(s.get("hibernated"))
    live = not hibernated and state not in ("exited", "unknown")
    action: Dict[str, Any] = {"verb": None, "preselected": False}
    if state == "unknown":
        notes.append("agent state unknown (%s)" % (s.get("agent_state_cause") or "unmapped"))
    if rule == 2 and clip_found:
        # Copy-back needs no live pane (FR-025), so an unknown agent state does not block it.
        if clip.get("truncated") or clip.get("text") is None:
            notes.append("no copy-back: copied text was truncated")
        elif platform != "darwin":
            notes.append("copy-back unavailable: only on macOS")
        else:
            action = {"verb": "copyback", "preselected": False, "text": clip["text"],
                      "method": clip.get("method"), "args": clip.get("args") or ""}
    elif state == "unknown":
        pass  # no follow-up and no preselected close for an unmapped state; it stays addable
    elif category == DONE_CLOSE_IT:
        action = {"verb": "close", "preselected": True}
    elif rule == 2 and live:
        kind = "unanswered" if unanswered else own_found[0]["kind"]
        action = {"verb": "message", "preselected": False,
                  "text": j.get("followup") or _DEFAULT_FOLLOWUPS.get(kind, "Please continue.")}
    addable = category != DONE_CLOSE_IT or state == "unknown"
    addable = addable and (category == STALE_DECIDE or hibernated
                           or state in ("exited", "unknown"))

    if not conv_ok:
        notes.append("conversation could not be read: %s"
                     % ((s.get("conversation") or {}).get("cause") or "unknown cause"))
    if hibernated:
        notes.append("hibernated pane")
    if state == "exited":
        notes.append("agent exited")
    if s.get("kind") == "headless":
        notes.append("headless agent (close stops it)")
    if s.get("also_open_in"):
        notes.append("also open in pane " + ", ".join(str(p) for p in s["also_open_in"]))
    if (sig.get("shared_folder") or {}).get("shared"):
        notes.append("folder shared with %d other session(s)"
                     % len(sig["shared_folder"].get("sessions") or []))
    if pr.get("others"):
        notes.append("other PRs: " + ", ".join(
            "%s (%s)" % (o["url"], o.get("state") or "unknown") for o in pr["others"]))
    if pr.get("status") == "unknown" and pr.get("cause") != "conversation copy unreadable":
        notes.append("PR state unknown: " + pr["cause"])
    for i in items:
        if i.get("status") == "unknown" and i["kind"] in ("unpushed", "never_pushed") \
                and i.get("cause") in PUSH_CAUSES_IGNORED:
            notes.append("push state unknown (%s)" % i["cause"])

    return {
        "key": s["key"],
        "name": s.get("name") or "",
        "provider": s.get("provider"),
        "kind": s.get("kind"),
        "pane": s.get("pane"),
        "headless_id": s.get("headless_id"),
        "workspace": (s.get("workspace") or {}).get("name", ""),
        "hibernated": hibernated,
        "agent_state": state,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "rule": rule,
        "reason": reason,
        "quiet_seconds": quiet_seconds,
        "quiet": None if quiet_seconds is None else timefmt.format_duration(quiet_seconds),
        "quiet_from_last_message": from_message,
        "recap": _recap(s, j, conv_ok, quiet_seconds, from_message, clip,
                        copyback_note="copy-back unavailable: only on macOS"
                        if platform != "darwin" else None),
        "action": action,
        "addable_to_close": addable,
        "notes": notes,
    }
