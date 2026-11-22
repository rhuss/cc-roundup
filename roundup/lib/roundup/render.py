"""Text and JSON views: the judge view (for the agent) and the overview (for the user)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import timefmt
from .engine import CATEGORY_LABELS, CATEGORY_ORDER

COMPACT_AT = 100
EMPTY_LINE = "No open sessions besides this one."


def page_count(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


def _flat(value: Any) -> str:
    """One line: session-controlled text must not fake judge-view structure."""
    return " ".join(str(value or "").split())


def _where(s: Dict[str, Any]) -> str:
    if s.get("kind") == "headless":
        return "headless %s" % s.get("headless_id")
    return "pane %s" % s.get("pane")


def _signal_summary(s: Dict[str, Any]) -> List[str]:
    sig = s.get("signals") or {}
    out = []
    clip = sig.get("clipboard") or {}
    if clip.get("status") == "found":
        extra = " (truncated)" if clip.get("truncated") else ""
        out.append('clipboard: copied via %s, never pasted%s: "%s"'
                   % (clip.get("method"), extra, _flat(clip.get("first_line", ""))))
    else:
        out.append("clipboard: %s%s" % (clip.get("status"),
                                         " (%s)" % _flat(clip["cause"]) if clip.get("cause") else ""))
    unf = sig.get("unfinished") or {}
    details = []
    for i in unf.get("items") or []:
        if i.get("status") == "found":
            details.append(_flat(i.get("detail")) or i["kind"])
        elif i.get("status") == "unknown":
            details.append("%s unknown (%s)" % (i["kind"], _flat(i.get("cause"))))
    out.append("unfinished: %s%s" % (unf.get("status"),
                                     ": " + "; ".join(details) if details else ""))
    pr = sig.get("pr") or {}
    cur = pr.get("current")
    if cur:
        out.append("PR: %s %s%s" % (cur.get("state") or "unknown", cur["url"],
                                    " (%s)" % pr["cause"] if pr.get("cause") else ""))
    else:
        out.append("PR: %s%s" % (pr.get("status"), " (%s)" % pr["cause"] if pr.get("cause") else ""))
    shared = sig.get("shared_folder") or {}
    if shared.get("shared"):
        out.append("folder shared with: " + ", ".join(shared.get("sessions") or []))
    return out


def render_judge_view(digest: Dict[str, Any], page: int, page_size: int) -> str:
    sessions = digest.get("sessions") or []
    pages = page_count(len(sessions), page_size)
    if page < 1 or page > pages:
        raise ValueError("page %d out of range (1 to %d)" % (page, pages))
    lines = ["Judge view: %d sessions, snapshot %s" % (len(sessions), digest["generated_at"])]
    if not sessions:
        lines.append("No sessions to judge.")
    start = (page - 1) * page_size
    for n, s in enumerate(sessions[start:start + page_size], start + 1):
        quiet_from = s.get("changed_at") or s.get("last_message_at")
        quiet = timefmt.seconds_between(quiet_from, digest["generated_at"])
        state = s.get("agent_state")
        if s.get("hibernated"):
            state += ", hibernated"
        lines.append("")
        lines.append("=== %d. %s" % (n, s["key"]))
        lines.append("name: %s | workspace: %s | %s | state: %s"
                     % (_flat(s.get("name")) or "(none)",
                        _flat((s.get("workspace") or {}).get("name", "")), _where(s), state))
        lines.append("folder: %s" % (_flat(s.get("folder")) or "(none)"))
        lines.append("quiet: %s%s | first activity: %s"
                     % ("unknown" if quiet is None else timefmt.format_duration(quiet),
                        "" if s.get("changed_at") or quiet is None else " (from last message)",
                        s.get("first_activity_at") or "unknown"))
        for line in _signal_summary(s):
            lines.append("signal " + line)
        conv = s.get("conversation") or {}
        if conv.get("status") != "found":
            lines.append("messages: conversation could not be read (%s)" % _flat(conv.get("cause")))
            continue
        lines.append("messages (oldest first):")
        for m in s.get("messages") or []:
            text = "\n      ".join((m.get("text") or "").splitlines())
            lines.append("  [%s %s] %s%s" % (m["role"], m.get("at") or "?", text,
                                             " [cut]" if m.get("cut") else ""))
    lines.append("")
    lines.append("page %d of %d" % (page, pages))
    return "\n".join(lines) + "\n"


def _action_text(e: Dict[str, Any]) -> str:
    a = e.get("action") or {}
    verb = a.get("verb")
    if verb == "close":
        what = "stop headless agent" if e.get("kind") == "headless" else "close pane"
        return "proposed: %s%s" % (what, " (preselected)" if a.get("preselected") else "")
    if verb == "message":
        return 'proposed: follow-up "%s"' % " ".join((a.get("text") or "").split())
    if verb == "copyback":
        method = a.get("method") + (" " + a["args"] if a.get("args") else "")
        return "proposed: copy back to the clipboard via %s" % method
    if e.get("addable_to_close"):
        return "proposed: nothing (can be added to the close batch)"
    return "proposed: nothing"


def _meta_lines(meta: Dict[str, Any], total: int) -> List[str]:
    lines = ["Roundup: %d open session%s (snapshot %s, stale after %s)"
             % (total, "" if total == 1 else "s", meta.get("generated_at"), meta.get("stale"))]
    caller = meta.get("caller") or {}
    if not caller.get("excluded", True):
        lines.append("Note: this review's own session could not be excluded (%s)."
                     % caller.get("cause", "unknown cause"))
    return lines


def render_entry(e: Dict[str, Any]) -> str:
    lines = [e["key"],
             "name: %s | workspace: %s | %s %s | state: %s"
             % (_flat(e.get("name")) or "(none)", _flat(e.get("workspace")), e.get("kind"),
                e.get("pane") if e.get("kind") == "pane" else e.get("headless_id"),
                e.get("agent_state")),
             "category: %s (rule %d)" % (e["category_label"], e["rule"]),
             "reason: %s" % e["reason"],
             "recap:"]
    lines += ["  " + r for r in e["recap"]]
    lines.append(_action_text(e))
    for n in e.get("notes") or []:
        lines.append("note: " + n)
    return "\n".join(lines) + "\n"


def render_overview(entries: List[Dict[str, Any]], fmt: str, key: Optional[str] = None,
                    meta: Optional[Dict[str, Any]] = None) -> str:
    meta = meta or {}
    if key is not None:
        match = [e for e in entries if e["key"] == key]
        if not match:
            raise KeyError(key)
        if fmt == "json":
            return json.dumps(match[0], indent=1, ensure_ascii=False) + "\n"
        return render_entry(match[0])
    compact = len(entries) >= COMPACT_AT
    if fmt == "json":
        counts = {c: sum(1 for e in entries if e["category"] == c) for c in CATEGORY_ORDER}
        doc = dict(meta)
        doc.update({"compact": compact, "counts": counts, "entries": entries})
        return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if not entries:
        return EMPTY_LINE + "\n"
    lines = _meta_lines(meta, len(entries))
    for cat in CATEGORY_ORDER:
        group = [e for e in entries if e["category"] == cat]
        if not group:
            continue
        lines.append("")
        lines.append("%s (%d)" % (CATEGORY_LABELS[cat], len(group)))
        for e in group:
            name = _flat(e.get("name")) or e["key"]
            if compact:
                lines.append("  - %s [%s] quiet %s: %s (%s)"
                             % (name, _flat(e.get("workspace")), e.get("quiet") or "unknown",
                                e["reason"], e["key"]))
                continue
            where = "headless %s" % e.get("headless_id") if e.get("kind") == "headless" \
                else "pane %s" % e.get("pane")
            lines.append("  - %s [%s, %s]: %s" % (name, _flat(e.get("workspace")), where,
                                                   _flat(e["reason"])))
            for r in e["recap"]:
                lines.append("      " + r)
            lines.append("      " + _action_text(e))
            for n in e.get("notes") or []:
                lines.append("      note: " + n)
    if compact:
        lines.append("")
        lines.append("Compact view (%d sessions). Full recap of one session: "
                     "roundup overview --digest FILE --judgments FILE --stale %s --key KEY"
                     % (len(entries), meta.get("stale") or "3d"))
    return "\n".join(lines) + "\n"
