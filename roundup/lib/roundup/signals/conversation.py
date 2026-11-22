"""Read a normalized conversation copy: recent messages, PR links, checklist (research R5, R7, R8).

The copy is JSONL, one {"role","timestamp"(ms|null),"ref","text"} object per
user or assistant message. Backend-neutral: the path comes from the snapshot.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .. import timefmt
from ..digest import MAX_MESSAGE_CHARS, MAX_MESSAGES, cut

_GITHUB_PR = re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
_OTHER_PR = re.compile(
    r"https?://([\w.-]+)/[^\s)\]>\"']*?/(?:pull|pulls|merge_requests|pull-requests)/\d+")
_CHECKLIST = re.compile(r"^\s*[-*] \[ \]\s*(.*)$")


@dataclass
class Conversation:
    status: str = "found"
    cause: Optional[str] = None
    messages: List[dict] = field(default_factory=list)
    first_activity_at: Optional[str] = None
    last_message_at: Optional[str] = None
    pr_links: List[str] = field(default_factory=list)
    non_github_pr_links: List[str] = field(default_factory=list)
    checklist_items: List[str] = field(default_factory=list)
    newest_pr_is_github: bool = True
    user_message_refs: List[Tuple[Optional[int], str]] = field(default_factory=list)


def _ordered_by_last_mention(positions: dict) -> List[str]:
    return [url for url, _ in sorted(positions.items(), key=lambda kv: kv[1], reverse=True)]


def _ms(value) -> Optional[int]:
    """A millisecond timestamp, or None when missing or malformed (never raises)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return ms if ms > 0 else None


def read_conversation(copy_path: Optional[str]) -> Conversation:
    if not copy_path:
        return Conversation(status="unknown", cause="no conversation copy")
    rows = []
    try:
        with open(copy_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # partial or malformed line (copy being written): skip
                if isinstance(rec, dict) and rec.get("role") in ("user", "assistant"):
                    rows.append(rec)
    except OSError as exc:
        return Conversation(status="unknown",
                            cause="cannot read conversation copy: %s" % (exc.strerror or exc))

    conv = Conversation()
    github, other = {}, {}
    position = 0
    for rec in rows:
        text = rec.get("text") if isinstance(rec.get("text"), str) else ""
        # Collect matches of both kinds, then number them in text order (FR-012).
        found = []
        for m in _GITHUB_PR.finditer(text):
            found.append((m.start(), "https://github.com/%s/%s/pull/%s" % m.groups(), True))
        for m in _OTHER_PR.finditer(text):
            host = m.group(1).lower()
            if host == "github.com" or host.endswith(".github.com"):
                continue  # github.com itself is matched above; api.github.com is not a PR page
            found.append((m.start(), m.group(0), False))
        for _start, url, is_github in sorted(found):
            position += 1
            (github if is_github else other)[url] = position
        if rec["role"] == "user":
            conv.user_message_refs.append((_ms(rec.get("timestamp")), str(rec.get("ref", ""))))
    conv.newest_pr_is_github = max(github.values(), default=0) >= max(other.values(), default=0)
    conv.pr_links = _ordered_by_last_mention(github)
    conv.non_github_pr_links = _ordered_by_last_mention(other)

    # The endpoints are the first and the last message; a missing timestamp stays unknown
    # instead of borrowing a neighbour's time (FR-005, FR-016a).
    if rows:
        conv.first_activity_at = timefmt.ms_to_iso(_ms(rows[0].get("timestamp")))
        conv.last_message_at = timefmt.ms_to_iso(_ms(rows[-1].get("timestamp")))

    for rec in rows[-MAX_MESSAGES:]:
        text = rec.get("text") if isinstance(rec.get("text"), str) else ""
        conv.messages.append({
            "role": rec["role"],
            "at": timefmt.ms_to_iso(_ms(rec.get("timestamp"))),
            "text": cut(text, MAX_MESSAGE_CHARS),
            "cut": len(text) > MAX_MESSAGE_CHARS,
        })

    last_assistant = next((r for r in reversed(rows) if r["role"] == "assistant"), None)
    if last_assistant is not None:
        text = last_assistant.get("text") if isinstance(last_assistant.get("text"), str) else ""
        for line in text.splitlines():
            m = _CHECKLIST.match(line)
            if m:
                conv.checklist_items.append(m.group(1).strip())
    return conv
