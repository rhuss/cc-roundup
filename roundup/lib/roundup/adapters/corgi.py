"""Corgi adapter: the only module that runs the Corgi binary (FR-028).

Interface (contracts/corgi-adapter.md):
  snapshot(archived)        sessions in scope, read-only
  recheck(session)          does the session still match the digest
  close(session)            pane close / headless stop
  message(session, text)    prompt the agent through its own channel, never typed
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional, Tuple

from .. import BackendError
from .. import timefmt

BACKEND = "corgi"
READ_TIMEOUT = 30  # list, grep, history
ACTION_TIMEOUT = 15  # close, message
MAX_WORKERS = 8
TAIL_BYTES = 512 * 1024
FALLBACK_BUDGET = 20  # seconds for all per-session grep fallbacks together (SC-001)
SESSION_GREP_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Running the binary


def corgi_binary() -> str:
    """$ROUNDUP_CORGI (tests), else $CORGI_APP_EXE (set in every Corgi pane), else corgi."""
    return os.environ.get("ROUNDUP_CORGI") or os.environ.get("CORGI_APP_EXE") or "corgi"


def _run(args: List[str], timeout: int, input_text: Optional[str] = None) -> Tuple[int, str, str]:
    cmd = [corgi_binary()] + args
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise BackendError("Corgi command line not found: %s" % cmd[0])
    except OSError as exc:
        raise BackendError("cannot run %s: %s" % (cmd[0], exc.strerror or exc))
    except subprocess.TimeoutExpired:
        return -1, "", "corgi %s timed out after %ds" % (args[0], timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _error_text(code: int, stderr: str) -> str:
    """Corgi's own error: the `err` field of its JSON stderr, else the raw stderr."""
    text = (stderr or "").strip()
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                err = json.loads(line).get("err")
            except ValueError:
                continue
            if err:
                return str(err)
    return text or "corgi exited with status %d" % code


def _list() -> Dict[str, Any]:
    code, out, err = _run(["list", "--json"], READ_TIMEOUT)
    if code != 0 or not out.strip():
        raise BackendError(_error_text(code, err))
    try:
        doc = json.loads(out)
    except ValueError as exc:
        raise BackendError("unreadable reply from corgi list: %s" % exc)
    if not isinstance(doc, dict):
        raise BackendError("unreadable reply from corgi list: not a JSON object")
    if not doc.get("ok", True) or not isinstance(doc.get("result"), dict):
        raise BackendError(str(doc.get("err") or "corgi list failed"))
    return doc["result"]


# ---------------------------------------------------------------------------
# State mapping (research R4)


def _brand(pane: Dict[str, Any]) -> Optional[str]:
    if "brand" in pane:
        return pane.get("brand")
    return (pane.get("agent") or {}).get("brand")


def map_pane_state(pane: Dict[str, Any]) -> Tuple[str, Optional[str], bool]:
    """(agent_state, cause, hibernated) for a pane."""
    agent = pane.get("agent") or {}
    raw = agent.get("state")
    if pane.get("dormant"):
        return "idle", None, True
    if pane.get("exited") or raw == "done" or (raw == "unknown" and _brand(pane) is None):
        return "exited", None, False
    mapped = {"blocked": "blocked", "working": "working", "initializing": "starting",
              "idle": "idle"}.get(raw)
    if mapped:
        return mapped, None, False
    return "unknown", "raw agent state %s" % raw, False


def map_headless_state(entry: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    raw = entry.get("state")
    if entry.get("exited"):
        return "exited", None
    if (entry.get("pending_requests") or 0) > 0 or raw == "blocked":
        return "blocked", None
    mapped = {"working": "working", "initializing": "starting", "idle": "idle",
              "done": "exited"}.get(raw)
    if mapped:
        return mapped, None
    return "unknown", "raw headless state %s" % raw


def _account_dir(pane_account: Any, agent: Dict[str, Any]) -> Optional[str]:
    if isinstance(pane_account, str) and pane_account:
        return pane_account
    acct = agent.get("account")
    if isinstance(acct, dict) and acct.get("directory"):
        return acct["directory"]
    return None


# ---------------------------------------------------------------------------
# Session discovery (research R3)


def _workspace(ws_by_id: Dict[Any, Dict[str, Any]], wid: Any) -> Dict[str, Any]:
    ws = ws_by_id.get(wid) or {}
    name = ws.get("name")
    return {"id": wid, "name": name if isinstance(name, str) else "",
            "archived": bool(ws.get("archived", False))}


def _pane_candidate(pane: Dict[str, Any], ws: Dict[str, Any]) -> Dict[str, Any]:
    agent = pane.get("agent") or {}
    state, cause, hibernated = map_pane_state(pane)
    changed_us = int(agent.get("changed_at") or 0)
    obs = agent.get("observation") or {}
    s = {
        "key": "%s:%s" % (agent["provider"], agent["session"]),
        "provider": agent["provider"],
        "session_id": agent["session"],
        "name": agent.get("name") or "",
        "kind": "pane",
        "pane": pane.get("id"),
        "headless_id": None,
        "hibernated": hibernated,
        "workspace": ws,
        "folder": agent.get("cwd") or pane.get("cwd") or None,
        "agent_state": state,
        "backend_state": {
            "state": agent.get("state"),
            "changed_at_us": changed_us,
            "brand": _brand(pane),
            "exited": bool(pane.get("exited")),
            "dormant": bool(pane.get("dormant")),
            "account_dir": _account_dir(pane.get("account"), agent),
            "observation_source": obs.get("source"),
        },
        "changed_at": timefmt.us_to_iso(changed_us),
        "also_open_in": [],
        "transcript": agent.get("transcript") or None,
        # Dedupe preference: live pane, then exited pane, then hibernated pane.
        "_rank": (2 if hibernated else 1 if state == "exited" else 0, pane.get("id") or 0),
    }
    if cause:
        s["agent_state_cause"] = cause
    return s


def _headless_candidate(entry: Dict[str, Any], ws: Dict[str, Any]) -> Dict[str, Any]:
    agent = entry.get("agent") or {}
    state, cause = map_headless_state(entry)
    obs = entry.get("observation") or agent.get("observation") or {}
    s = {
        "key": "%s:%s" % (entry["provider"], entry["session"]),
        "provider": entry["provider"],
        "session_id": entry["session"],
        "name": agent.get("name") or "",
        "kind": "headless",
        "pane": entry.get("pane"),
        "headless_id": str(entry.get("id")),
        "hibernated": False,
        "workspace": ws,
        "folder": entry.get("cwd") or agent.get("cwd") or None,
        "agent_state": state,
        "backend_state": {
            "state": entry.get("state"),
            "changed_at_us": 0,
            "pending_requests": int(entry.get("pending_requests") or 0),
            "exited": bool(entry.get("exited")),
            "account_dir": _account_dir(entry.get("account"), agent),
            "observation_source": obs.get("source"),
        },
        # Headless sessions carry no change time; quiet time falls back to the last message.
        "changed_at": None,
        "also_open_in": [],
        "transcript": agent.get("transcript") or None,
        "_rank": (3, entry.get("pane") or 0),
    }
    if cause:
        s["agent_state_cause"] = cause
    return s


def _caller() -> Tuple[Optional[int], Optional[str]]:
    raw = os.environ.get("CORGI_PANE")
    if not raw:
        return None, "CORGI_PANE is not set"
    try:
        return int(raw), None
    except ValueError:
        return None, "CORGI_PANE %r is not a pane id" % raw


def discover(result: Dict[str, Any], archived: bool) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """(caller, sessions) from a `corgi list --json` result, deduplicated by key."""
    ws_by_id = {w.get("id"): w for w in result.get("workspaces") or []}
    caller_pane, caller_cause = _caller()
    caller_key = None
    caller_found = False
    candidates: List[Dict[str, Any]] = []
    for pane in result.get("panes") or []:
        agent = pane.get("agent") or {}
        if caller_pane is not None and pane.get("id") == caller_pane:
            caller_found = True
            if agent.get("provider") and agent.get("session"):
                caller_key = "%s:%s" % (agent["provider"], agent["session"])
            continue
        if not agent.get("provider") or not agent.get("session"):
            continue
        ws = _workspace(ws_by_id, pane.get("workspace"))
        if ws["archived"] and not archived:
            continue
        candidates.append(_pane_candidate(pane, ws))
    for entry in result.get("headless_sessions") or []:
        if entry.get("exited") or entry.get("corgi"):
            continue  # ended, or an Ask Corgi helper conversation
        if not entry.get("provider") or not entry.get("session"):
            continue
        ws = _workspace(ws_by_id, entry.get("workspace"))
        if ws["archived"] and not archived:
            continue
        candidates.append(_headless_candidate(entry, ws))

    if caller_pane is not None and not caller_found:
        caller_cause = "CORGI_PANE %d matches no pane" % caller_pane
    caller = {"pane": caller_pane if caller_found else None, "excluded": caller_found}
    if not caller_found:
        caller["cause"] = caller_cause

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        if caller_key and c["key"] == caller_key:
            continue
        groups.setdefault(c["key"], []).append(c)
    sessions = []
    for key in groups:
        group = sorted(groups[key], key=lambda c: c["_rank"])
        winner = group[0]
        winner["also_open_in"] = sorted(
            {c["pane"] for c in group[1:] if c.get("pane") is not None} - {winner.get("pane")})
        sessions.append(winner)
    for s in sessions:
        s.pop("_rank", None)
    return caller, sessions


# ---------------------------------------------------------------------------
# Conversation copies (research R5)


def _copy_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    cache = (row.get("source") or {}).get("cache")
    if not isinstance(cache, str) or not cache:
        return {"path": None, "tools_path": None,
                "cause": "corgi grep reported no conversation copy"}
    tools = cache[: -len(".jsonl")] + ".tools.jsonl" if cache.endswith(".jsonl") else None
    return {"path": cache, "tools_path": tools, "cause": None}


def _parse_rows(out: str) -> List[Dict[str, Any]]:
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("source"), dict):
            rows.append(rec)
    return rows


def _bulk_copies() -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Optional[str]]:
    """(copies by (provider, session), failure cause or None)."""
    code, out, err = _run(["grep", "--workspace", "*", "--max-age", "all", "--tools", "-l",
                           "--json", "--limit", "0", "--max-output", "0", "."], READ_TIMEOUT)
    if code not in (0, 1):
        return {}, "corgi grep failed: %s" % _error_text(code, err)
    copies = {}
    for row in _parse_rows(out):
        src = row["source"]
        copies[(src.get("provider"), src.get("session"))] = _copy_from_row(row)
    return copies, None


def _session_copy(key: str) -> Dict[str, Any]:
    code, out, err = _run(["grep", "--session", key, "--tools", "-l", "--json", "."],
                          SESSION_GREP_TIMEOUT)
    if code == 0:
        rows = _parse_rows(out)
        if rows:
            return _copy_from_row(rows[0])
    if code in (0, 1):
        return {"path": None, "tools_path": None,
                "cause": "no conversation copy (corgi grep found none)"}
    return {"path": None, "tools_path": None,
            "cause": "corgi grep failed: %s" % _error_text(code, err)}


# ---------------------------------------------------------------------------
# Interrupted last turn (research R7)


def _history() -> Tuple[Dict[Tuple[str, str], bool], Optional[str]]:
    code, out, err = _run(["history", "--json", "--limit", "1000"], READ_TIMEOUT)
    if code != 0:
        return {}, "corgi history failed: %s" % _error_text(code, err)
    try:
        doc = json.loads(out)
    except ValueError:
        return {}, "unreadable corgi history reply"
    rows = doc.get("conversations") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return {}, "unreadable corgi history reply"
    flags = {}
    for c in rows:
        if isinstance(c, dict) and isinstance(c.get("interrupted"), bool):
            flags[(c.get("provider"), c.get("session"))] = c["interrupted"]
    return flags, None


def _read_tail(path: str) -> List[Dict[str, Any]]:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - TAIL_BYTES)
        fh.seek(start)
        data = fh.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # first line is partial
    records = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _claude_typed_text(rec: Dict[str, Any]) -> Optional[str]:
    if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isMeta"):
        return None
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return None


def transcript_interrupted(provider: str, path: Optional[str]) -> Dict[str, Any]:
    """Interrupted flag from the tail of the provider transcript."""
    if not path:
        return {"status": "unknown", "cause": "not in corgi history and no transcript path"}
    try:
        records = _read_tail(path)
    except OSError as exc:
        return {"status": "unknown", "cause": "transcript unreadable: %s" % (exc.strerror or exc)}
    try:
        return _interrupted_from(provider, records)
    except Exception as exc:  # a malformed record must not abort gathering (FR-007)
        return {"status": "unknown", "cause": "transcript unreadable: %s" % exc}


def _interrupted_from(provider: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if provider == "claude":
        last = None
        for rec in records:
            text = _claude_typed_text(rec)
            if text is not None:
                last = text
        if last is None:
            return {"status": "unknown", "cause": "no prompt in transcript tail"}
        return {"status": "found" if last.startswith("[Request interrupted") else "not_found"}
    if provider == "codex":
        last_prompt = last_abort = -1
        for i, rec in enumerate(records):
            payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            kind = payload.get("type")
            if kind == "user_message":
                last_prompt = i
            elif kind == "turn_aborted":
                last_abort = i
        if last_prompt < 0 and last_abort < 0:
            return {"status": "unknown", "cause": "no prompt in transcript tail"}
        return {"status": "found" if last_abort > last_prompt else "not_found"}
    return {"status": "unknown", "cause": "interrupted flag not supported for %s" % provider}


# ---------------------------------------------------------------------------
# snapshot


def snapshot(archived: bool = False, log=None) -> Dict[str, Any]:
    """Read-only snapshot of all in-scope sessions (BackendSnapshot)."""
    log = log or (lambda msg: None)
    result = _list()
    generated_at = timefmt.now_iso()
    caller, sessions = discover(result, archived)
    log("corgi list: %d sessions in scope" % len(sessions))
    copies, copies_cause = _bulk_copies() if sessions else ({}, None)
    if copies_cause:
        log(copies_cause)
    history, history_cause = _history() if sessions else ({}, None)
    if history_cause:
        log(history_cause)

    if copies_cause:
        # The bulk lookup failed: do not fan out one slow call per session (SC-001).
        for s in sessions:
            copies[(s["provider"], s["session_id"])] = {"path": None, "tools_path": None,
                                                        "cause": copies_cause}
    missing = [s for s in sessions if (s["provider"], s["session_id"]) not in copies]
    log("per-session copy lookups: %d" % len(missing))
    needs_tail = [s for s in sessions if (s["provider"], s["session_id"]) not in history]
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        # Per-session grep fallbacks share one time budget; late ones become unknown (SC-001).
        tail_futures = {s["key"]: pool.submit(transcript_interrupted, s["provider"],
                                              s.get("transcript")) for s in needs_tail}
        futures = {s["key"]: pool.submit(_session_copy, s["key"]) for s in missing}
        done, _late = wait(list(futures.values()), timeout=FALLBACK_BUDGET)
        fallback = {}
        for k, fut in futures.items():
            if fut in done:
                try:
                    fallback[k] = fut.result()
                except Exception as exc:  # one session's failure never aborts gathering
                    fallback[k] = {"path": None, "tools_path": None,
                                   "cause": "corgi grep failed: %s" % exc}
            else:
                fut.cancel()
                fallback[k] = {"path": None, "tools_path": None,
                               "cause": "corgi grep skipped: gathering time budget exceeded"}
        tails = {k: f.result() for k, f in tail_futures.items()}
    finally:
        pool.shutdown(wait=False)
    for s in sessions:
        ident = (s["provider"], s["session_id"])
        s["copy"] = copies.get(ident) or fallback.get(s["key"])
        if ident in history:
            s["interrupted"] = {"status": "found" if history[ident] else "not_found"}
        else:
            tail = tails[s["key"]]
            if tail["status"] == "unknown" and history_cause:
                tail = {"status": "unknown", "cause": "%s; %s" % (history_cause, tail["cause"])}
            s["interrupted"] = tail
    return {
        "backend": BACKEND,
        "generated_at": generated_at,
        "archived": archived,
        "caller": caller,
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# Re-check and actions (research R9 to R11). Never retried, never typed.


def outcome(session: Dict[str, Any], verb: str, result: str, reason: str,
            **extra: Any) -> Dict[str, Any]:
    out = {"key": session["key"], "verb": verb, "outcome": result, "reason": reason}
    out.update(extra)
    return out


def _find_live(result: Dict[str, Any], session: Dict[str, Any]) -> Tuple[Optional[Dict], str]:
    """The pane or headless entry for this session in a fresh list, or a reason."""
    if session.get("kind") == "headless":
        same = [e for e in result.get("headless_sessions") or []
                if e.get("provider") == session["provider"]
                and e.get("session") == session["session_id"] and not e.get("corgi")]
        for entry in same:  # the very headless agent the digest recorded
            if str(entry.get("id")) == str(session.get("headless_id")):
                return entry, ""
        if same:
            return None, "headless agent %s was replaced by another one" % session.get("headless_id")
        return None, "headless session no longer exists"
    pane_id = session.get("pane")
    for pane in result.get("panes") or []:
        if pane.get("id") == pane_id:
            agent = pane.get("agent") or {}
            if agent.get("provider") != session["provider"] or \
                    agent.get("session") != session["session_id"]:
                return None, "pane %s now shows another conversation" % pane_id
            return pane, ""
    return None, "pane %s no longer exists" % pane_id


def recheck(session: Dict[str, Any]) -> Dict[str, Any]:
    """Compare the live session with the digest (FR-025). Raises BackendError if unreachable.

    Returns {"ok": bool, "reason": str, "live": entry or None}.
    """
    result = _list()
    live, reason = _find_live(result, session)
    if live is None:
        return {"ok": False, "reason": reason, "live": None}
    expected = session.get("backend_state") or {}
    if session.get("kind") == "headless":
        changes = []
        if live.get("state") != expected.get("state"):
            changes.append("state changed: %s -> %s" % (expected.get("state"), live.get("state")))
        if int(live.get("pending_requests") or 0) != int(expected.get("pending_requests") or 0):
            changes.append("pending requests changed")
        if bool(live.get("exited")) != bool(expected.get("exited")):
            changes.append("headless agent exited")
        if changes:
            return {"ok": False, "reason": "; ".join(changes), "live": live}
        return {"ok": True, "reason": "", "live": live}
    state, _cause, hibernated = map_pane_state(live)
    changes = []
    if state != session.get("agent_state"):
        changes.append("agent state changed: %s -> %s" % (session.get("agent_state"), state))
    if hibernated != bool(session.get("hibernated")):
        changes.append("pane was %s" % ("hibernated" if hibernated else "woken up"))
    live_changed = int((live.get("agent") or {}).get("changed_at") or 0)
    if live_changed != int(expected.get("changed_at_us") or 0):
        changes.append("last change time changed since the snapshot")
    if changes:
        return {"ok": False, "reason": "; ".join(changes), "live": live}
    return {"ok": True, "reason": "", "live": live}


def close(session: Dict[str, Any]) -> Dict[str, Any]:
    """End the session: `pane close ID` or `headless stop PROVIDER SESSION`. No retry."""
    if session.get("kind") == "headless":
        args = ["headless", "stop", session["provider"], session["session_id"]]
        done = "headless agent stopped"
    else:
        args = ["pane", "close", str(session["pane"])]
        done = "pane %s closed" % session["pane"]
    code, _out, err = _run(args, ACTION_TIMEOUT)
    if code == 0:
        return outcome(session, "close", "done", done)
    return outcome(session, "close", "failed", _error_text(code, err))


NO_CHANNEL = "agent channel not available; not typing into the pane"
TYPED = "Corgi typed the message into the pane (agent channel unavailable)"


def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _claude_channel(account_dir: Optional[str], session_id: str) -> bool:
    """A peer inbox exists: <account>/sessions/*.json with our sessionId, protocol 1, live pid."""
    base = account_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    sessions_dir = os.path.join(base, "sessions")
    try:
        names = os.listdir(sessions_dir)
    except OSError:
        return False
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(sessions_dir, name), encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        if (isinstance(info, dict) and info.get("sessionId") == session_id
                and info.get("peerProtocol") == 1 and _pid_alive(info.get("pid"))):
            return True
    return False


def _codex_channel(account_dir: Optional[str], session_id: str, observation_source: Any,
                   dormant: bool, exited: bool) -> bool:
    """Necessary (not sufficient) conditions for Corgi's Codex app-server channel (R9)."""
    if observation_source != "protocol" or dormant or exited or len(session_id or "") != 36:
        return False
    base = account_dir or os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return os.path.exists(os.path.join(base, "app-server-control", "app-server-control.sock"))


def channel_available(session: Dict[str, Any], live: Optional[Dict[str, Any]] = None) -> bool:
    """Pre-check that a follow-up can reach the agent without typing (filesystem only)."""
    if session.get("kind") == "headless":
        return True
    state = session.get("backend_state") or {}
    provider = session.get("provider")
    if provider == "claude":
        return _claude_channel(state.get("account_dir"), session["session_id"])
    if provider == "codex":
        source = state.get("observation_source")
        dormant, exited = bool(state.get("dormant")), bool(state.get("exited"))
        if live is not None:
            source = ((live.get("agent") or {}).get("observation") or {}).get("source")
            dormant, exited = bool(live.get("dormant")), bool(live.get("exited"))
        return _codex_channel(state.get("account_dir"), session["session_id"], source,
                              dormant, exited)
    return False


def message(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Send a follow-up through the agent's own channel; never typed, never retried.

    Raises BackendError when the runtime is unreachable during the re-check.
    """
    if not channel_available(session):
        return outcome(session, "message", "skipped", NO_CHANNEL)
    check = recheck(session)
    if not check["ok"]:
        return outcome(session, "message", "skipped", check["reason"])
    if session.get("provider") == "codex" and not channel_available(session, check["live"]):
        return outcome(session, "message", "skipped", NO_CHANNEL)
    if session.get("kind") == "headless":
        target = "headless:%s" % session.get("headless_id")
    else:
        target = "pane:%s" % session.get("pane")
    code, out, err = _run(["message", target, "--stdin", "--json"], ACTION_TIMEOUT,
                          input_text=text)
    if code != 0:
        return outcome(session, "message", "failed", _error_text(code, err))
    try:
        reply = json.loads(out)
    except ValueError:
        return outcome(session, "message", "failed", "unreadable reply from corgi message")
    result = reply.get("result") if isinstance(reply, dict) else None
    delivery = (result or {}).get("delivery")
    if delivery == "typed":
        return outcome(session, "message", "failed", TYPED, delivery="typed")
    if delivery != "message":
        return outcome(session, "message", "failed",
                       "unexpected delivery %r from corgi message" % delivery,
                       delivery=delivery)
    reason = "message delivered"
    if (result or {}).get("queued"):
        reason += " (queued while the agent works)"
    return outcome(session, "message", "done", reason, delivery="message",
                   queued=bool((result or {}).get("queued")))
