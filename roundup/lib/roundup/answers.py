"""Follow-up answers: the relay header, and finding an agent's answer in its transcript.

Answers are untrusted session text. This module only reads transcript files; it never
runs Corgi and never acts on what an answer says.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import InputError

SENT_FILE = "sent.jsonl"
RELAY_HEADER = ("(Relayed from your user by their roundup session. Please answer here in this "
                "conversation; there is nothing to send back.)")
ANSWER_LIMIT = 4000
QUEUED = "queued behind the agent's current turn"


def relay_text(text: str) -> str:
    """The text `act message` sends: the relay header, a blank line, the confirmed text."""
    return RELAY_HEADER + "\n\n" + text


def record_sent(run_dir: str, session: Dict[str, Any], text: str, transcript: Optional[str],
                offset: int, sent_at: str) -> None:
    """Append one sent follow-up to RUN/sent.jsonl (`text` is the confirmed text, no header)."""
    rec = {
        "key": session["key"],
        "provider": session.get("provider"),
        "session_id": session.get("session_id"),
        "name": session.get("name") or "",
        "workspace": (session.get("workspace") or {}).get("name") or "",
        "pane": session.get("pane"),
        "headless_id": session.get("headless_id"),
        "transcript": transcript,
        "offset": offset,
        "text": text,
        "sent_at": sent_at,
    }
    with open(os.path.join(run_dir, SENT_FILE), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_sent(run_dir: str) -> List[Dict[str, Any]]:
    """The sent records of this run in send order; [] when nothing was sent."""
    path = os.path.join(run_dir, SENT_FILE)
    if not os.path.exists(path):
        return []
    records = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                rec = None
            if not isinstance(rec, dict) or not rec.get("key"):
                raise InputError("malformed sent.jsonl line %d" % n)
            records.append(rec)
    return records


def read_records(path: str, offset: int) -> List[Dict[str, Any]]:
    """JSON objects from byte `offset` to the end (from 0 if the file is shorter).

    Lines that do not parse (a partial line being written) are skipped. Raises OSError.
    """
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(offset if 0 <= offset <= size else 0)
        data = fh.read().decode("utf-8", errors="replace")
    records = []
    for line in data.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Provider record readers


def _content_text(content: Any) -> Optional[str]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return None


def _claude_user_text(rec: Dict[str, Any]) -> Optional[str]:
    # isMeta records count: Claude Code stores peer messages as meta user records.
    if rec.get("type") != "user" or rec.get("isSidechain"):
        return None
    message = rec.get("message")
    return _content_text(message.get("content") if isinstance(message, dict) else None)


def _claude_assistant(rec: Dict[str, Any]):
    """(texts, tool calls) of an assistant record, or None for other records."""
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return None
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content], 0
    texts, tools = [], 0
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            tools += 1
    return texts, tools


def _payload(rec: Dict[str, Any]) -> Dict[str, Any]:
    payload = rec.get("payload")
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# Answer detection


def _result(status: str, parts: List[str], tools: int, cause: Optional[str] = None,
            answered_at: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"status": status, "truncated": False, "tool_calls": tools}
    if cause:
        out["cause"] = cause
    if parts:
        answer = "\n\n".join(parts)
        if len(answer) > ANSWER_LIMIT:
            answer = answer[:ANSWER_LIMIT]
            out["truncated"] = True
        out["answer"] = answer
    if answered_at:
        out["answered_at"] = answered_at
    return out


def _claude_answer(records: List[Dict[str, Any]], needle: str) -> Dict[str, Any]:
    start = -1
    for i, rec in enumerate(records):
        text = _claude_user_text(rec)
        if text is not None and needle in text:
            start = i
    if start < 0:
        queued = any(rec.get("type") == "queue-operation" and rec.get("operation") == "enqueue"
                     and needle in str(rec.get("content") or "") for rec in records)
        if queued:
            return _result("working", [], 0, cause=QUEUED)
        return _result("pending", [], 0)
    parts: List[str] = []
    tools = 0
    for rec in records[start + 1:]:
        if rec.get("type") == "system" and rec.get("subtype") == "turn_duration":
            return _result("answered" if parts else "no_reply", parts, tools,
                           answered_at=rec.get("timestamp") if parts else None)
        got = _claude_assistant(rec)
        if got:
            parts.extend(got[0])
            tools += got[1]
    return _result("working", parts, tools)


def _codex_answer(records: List[Dict[str, Any]], needle: str) -> Dict[str, Any]:
    start = -1
    for i, rec in enumerate(records):
        payload = _payload(rec)
        if payload.get("type") == "user_message" and needle in str(payload.get("message") or ""):
            start = i
    if start < 0:
        return _result("pending", [], 0)
    parts: List[str] = []
    for rec in records[start + 1:]:
        payload = _payload(rec)
        kind = payload.get("type")
        if kind == "agent_message" and payload.get("message"):
            parts.append(str(payload["message"]))
        elif kind == "task_complete":
            return _result("answered" if parts else "no_reply", parts, 0,
                           answered_at=rec.get("timestamp") if parts else None)
        elif kind == "turn_aborted":
            return _result("no_reply", parts, 0, cause="turn interrupted")
    return _result("working", parts, 0)


def find_answer(provider: str, records: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """The agent's answer to `text` in transcript `records`.

    Status: answered, working, no_reply, pending (message not in the records yet) or unknown.
    """
    needle = (text or "").strip()
    if provider == "claude":
        return _claude_answer(records, needle)
    if provider == "codex":
        return _codex_answer(records, needle)
    return _result("unknown", [], 0, cause="answers not supported for %s" % provider)
