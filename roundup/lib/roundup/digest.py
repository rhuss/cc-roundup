"""Digest format, version 1 (contracts/digest-v1.md): load, validate, dump."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from . import InputError, timefmt

FORMAT = "roundup-digest"
VERSION = 1

SIGNAL_STATUSES = ("found", "not_found", "unknown")
AGENT_STATES = ("working", "starting", "blocked", "idle", "exited", "unknown")
UNFINISHED_KINDS = ("checklist", "uncommitted", "unpushed", "never_pushed", "interrupted")
MAX_MESSAGES = 6
MAX_MESSAGE_CHARS = 600

_REQUIRED_TOP = ("format", "version", "generated_at", "backend", "options", "caller", "sessions",
                 "folders")
_REQUIRED_SESSION = (
    "key", "provider", "session_id", "name", "kind", "pane", "headless_id", "hibernated",
    "workspace", "folder", "agent_state", "backend_state", "changed_at", "first_activity_at",
    "last_message_at", "conversation", "messages", "pr_links", "also_open_in", "signals",
)
_SIGNALS = ("clipboard", "unfinished", "shared_folder", "pr")


def cut(text: str, limit: int) -> str:
    """Shorten text to at most `limit` characters, ending with an ellipsis when cut."""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _check_signal(where: str, sig: Any, errors: List[str]) -> None:
    if not isinstance(sig, dict):
        errors.append("%s: not an object" % where)
        return
    status = sig.get("status")
    if status not in SIGNAL_STATUSES:
        errors.append("%s: status %r not in found|not_found|unknown" % (where, status))
    cause = sig.get("cause")
    if status == "unknown" and not (isinstance(cause, str) and cause):
        errors.append("%s: unknown status without cause" % where)
    elif cause is not None and not isinstance(cause, str):
        errors.append("%s: cause is not a string" % where)


def _is_time(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        timefmt.parse_iso(value)
    except ValueError:
        return False
    return True


def _check_shapes(where: str, s: Dict[str, Any], errors: List[str]) -> None:
    """Types of the nested fields the engine and the renderers read (exit 4, not a crash)."""
    for field in ("name", "provider", "session_id"):
        if field in s and not isinstance(s[field], str):
            errors.append("%s: %s is not a string" % (where, field))
    if isinstance(s.get("key"), str) and isinstance(s.get("provider"), str) and \
            isinstance(s.get("session_id"), str) and \
            s["key"] != "%s:%s" % (s["provider"], s["session_id"]):
        # Actions select by key and target by provider/session: they must name the same one.
        errors.append("%s: key does not match provider:session_id" % where)
    if s.get("kind") not in ("pane", "headless"):
        errors.append("%s: kind %r invalid" % (where, s.get("kind")))
    if "folder" in s and s["folder"] is not None and not isinstance(s["folder"], str):
        errors.append("%s: folder is not a string or null" % where)
    ws = s.get("workspace")
    if "workspace" in s and not (isinstance(ws, dict) and isinstance(ws.get("name", ""), str)):
        errors.append("%s: workspace is not an object with a name" % where)
    for field in ("backend_state",):
        if field in s and not isinstance(s[field], dict):
            errors.append("%s: %s is not an object" % (where, field))
    for field in ("also_open_in", "pr_links"):
        if field in s and not isinstance(s[field], list):
            errors.append("%s: %s is not a list" % (where, field))
    for field in ("changed_at", "first_activity_at", "last_message_at"):
        if field in s and not _is_time(s[field]):
            errors.append("%s: %s is not an ISO 8601 time or null" % (where, field))
    signals = s.get("signals") if isinstance(s.get("signals"), dict) else {}
    pr = signals.get("pr")
    if isinstance(pr, dict):
        prs = ([pr["current"]] if pr.get("current") is not None else []) + \
            (pr.get("others") if isinstance(pr.get("others"), list) else [])
        if pr.get("status") == "found" and not isinstance(pr.get("current"), dict):
            errors.append("%s.signals.pr: found without current" % where)
        if "others" in pr and not isinstance(pr["others"], list):
            errors.append("%s.signals.pr: others is not a list" % where)
        for obj in prs:
            if not (isinstance(obj, dict) and isinstance(obj.get("url"), str)):
                errors.append("%s.signals.pr: PR entry without a url" % where)
        if pr.get("status") == "found" and isinstance(pr.get("current"), dict) and \
                pr["current"].get("state") not in ("open", "merged", "closed"):
            errors.append("%s.signals.pr: current state invalid" % where)
    clip = signals.get("clipboard")
    if isinstance(clip, dict) and clip.get("status") == "found":
        if clip.get("method") not in ("pbcopy", "slack-pbcopy"):
            errors.append("%s.signals.clipboard: method %r invalid" % (where, clip.get("method")))
        if clip.get("text") is not None and not isinstance(clip.get("text"), str):
            errors.append("%s.signals.clipboard: text is not a string or null" % where)
        for field in ("args", "first_line"):
            if clip.get(field) is not None and not isinstance(clip.get(field), str):
                errors.append("%s.signals.clipboard: %s is not a string" % (where, field))
    shared = signals.get("shared_folder")
    if "shared_folder" in signals and not isinstance(shared, dict):
        errors.append("%s.signals.shared_folder: not an object" % where)
    elif isinstance(shared, dict) and "sessions" in shared and not (
            isinstance(shared["sessions"], list)
            and all(isinstance(k, str) for k in shared["sessions"])):
        errors.append("%s.signals.shared_folder: sessions is not a list of keys" % where)


def validate(doc: Any) -> List[str]:
    """Return a list of problems (empty when the digest is valid)."""
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["digest is not a JSON object"]
    for field in _REQUIRED_TOP:
        if field not in doc:
            errors.append("missing field %s" % field)
    if doc.get("format") != FORMAT:
        errors.append("format is not %s" % FORMAT)
    if not _is_version(doc.get("version")):
        errors.append("unsupported digest version %s" % doc.get("version"))
    if not (isinstance(doc.get("generated_at"), str) and _is_time(doc.get("generated_at"))):
        errors.append("generated_at is not an ISO 8601 time")
    if "caller" in doc and not isinstance(doc.get("caller"), dict):
        errors.append("caller is not an object")
    sessions = doc.get("sessions")
    if not isinstance(sessions, list):
        errors.append("sessions is not a list")
        return errors
    seen = set()
    for i, s in enumerate(sessions):
        where = "sessions[%d]" % i
        if not isinstance(s, dict):
            errors.append("%s: not an object" % where)
            continue
        for field in _REQUIRED_SESSION:
            if field not in s:
                errors.append("%s: missing field %s" % (where, field))
        key = s.get("key")
        if not isinstance(key, str) or not key:
            errors.append("%s: key is not a non-empty string" % where)
        elif key in seen:
            errors.append("%s: duplicate key %s" % (where, key))
        else:
            seen.add(key)
        _check_shapes(where, s, errors)
        if s.get("agent_state") not in AGENT_STATES:
            errors.append("%s: agent_state %r invalid" % (where, s.get("agent_state")))
        _check_signal(where + ".conversation", s.get("conversation"), errors)
        msgs = s.get("messages")
        if not isinstance(msgs, list):
            errors.append("%s: messages is not a list" % where)
            msgs = []
        if len(msgs) > MAX_MESSAGES:
            errors.append("%s: more than %d messages" % (where, MAX_MESSAGES))
        for m in msgs:
            if not isinstance(m, dict) or not isinstance(m.get("text"), str):
                errors.append("%s: message is not an object with text" % where)
                continue
            if len(m.get("text") or "") > MAX_MESSAGE_CHARS:
                errors.append("%s: message longer than %d characters" % (where, MAX_MESSAGE_CHARS))
            if m.get("role") not in ("user", "assistant"):
                errors.append("%s: message role %r invalid" % (where, m.get("role")))
        signals = s.get("signals")
        if not isinstance(signals, dict):
            errors.append("%s: signals is not an object" % where)
            signals = {}
        for name in _SIGNALS:
            if name not in signals:
                errors.append("%s.signals: missing %s" % (where, name))
            elif name != "shared_folder":
                _check_signal("%s.signals.%s" % (where, name), signals[name], errors)
        unfinished = signals.get("unfinished")
        items = unfinished.get("items") if isinstance(unfinished, dict) else None
        if items is not None and not isinstance(items, list):
            errors.append("%s.signals.unfinished: items is not a list" % where)
            items = None
        for j, item in enumerate(items or []):
            iw = "%s.signals.unfinished.items[%d]" % (where, j)
            if not isinstance(item, dict):
                errors.append("%s: not an object" % iw)
                continue
            for field in ("detail", "cause"):
                if item.get(field) is not None and not isinstance(item.get(field), str):
                    errors.append("%s: %s is not a string" % (iw, field))
            if item.get("kind") not in UNFINISHED_KINDS:
                errors.append("%s: kind %r invalid" % (iw, item.get("kind")))
            _check_signal(iw, item, errors)
        folder = s.get("folder")
        folders = doc.get("folders") if isinstance(doc.get("folders"), dict) else {}
        if isinstance(folder, str) and folder not in folders:
            errors.append("%s: folder %s not in folders" % (where, folder))
    return errors


def load(path: str) -> Dict[str, Any]:
    """Load and validate a digest file. Raises InputError on any problem."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise InputError("cannot read digest %s: %s" % (path, exc.strerror or exc))
    except ValueError as exc:
        raise InputError("digest %s is not valid JSON: %s" % (path, exc))
    return check(doc)


def _is_version(value: Any) -> bool:
    return type(value) is int and value == VERSION


def check(doc: Any) -> Dict[str, Any]:
    if isinstance(doc, dict) and doc.get("format") == FORMAT and not _is_version(doc.get("version")):
        raise InputError("unsupported digest version %s" % doc.get("version"))
    errors = validate(doc)
    if errors:
        raise InputError("invalid digest: " + "; ".join(errors[:5]))
    return doc


def dump(doc: Dict[str, Any], stream) -> None:
    json.dump(doc, stream, indent=1, ensure_ascii=False)
    stream.write("\n")


def find_session(doc: Dict[str, Any], key: str) -> Dict[str, Any]:
    for s in doc.get("sessions") or []:
        if s.get("key") == key:
            return s
    raise InputError("no session %s in the digest" % key)


# ---------------------------------------------------------------------------
# Assembly (gather). Uses only the backend snapshot and the signal modules.

PUSH_CAUSES_IGNORED = ("upstream gone", "detached HEAD", "no remote")
MAX_WORKERS = 8


def unfinished_status(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`unfinished` status from non-shared items (contracts/digest-v1.md field rules)."""
    own = [i for i in items if not i.get("shared")]
    if any(i["status"] == "found" for i in own):
        return {"status": "found", "items": items}
    unknown = [i for i in own if i["status"] == "unknown"
               and not (i["kind"] in ("unpushed", "never_pushed")
                        and i.get("cause") in PUSH_CAUSES_IGNORED)]
    if unknown:
        return {"status": "unknown", "cause": "; ".join(sorted({i["cause"] for i in unknown})),
                "items": items}
    return {"status": "not_found", "items": items}


def _checklist_item(conv) -> Dict[str, Any]:
    if conv.status != "found":
        return {"kind": "checklist", "status": "unknown", "cause": conv.cause, "detail": "",
                "shared": False}
    n = len(conv.checklist_items)
    if n:
        return {"kind": "checklist", "status": "found", "shared": False,
                "detail": "%d open checklist item%s" % (n, "" if n == 1 else "s"),
                "open_items": conv.checklist_items[:10]}
    return {"kind": "checklist", "status": "not_found", "detail": "", "shared": False}


def _interrupted_item(flag: Dict[str, Any]) -> Dict[str, Any]:
    item = {"kind": "interrupted", "status": flag.get("status", "unknown"), "shared": False,
            "detail": "last turn interrupted" if flag.get("status") == "found" else ""}
    if item["status"] == "unknown":
        item["cause"] = flag.get("cause") or "interrupted flag unknown"
    return item


def build(snap: Dict[str, Any], lookup=None, log=None) -> Dict[str, Any]:
    """Digest from a backend snapshot (adapters.corgi.snapshot)."""
    from concurrent.futures import ThreadPoolExecutor

    from .signals import clipboard as clipsig
    from .signals import conversation as convsig
    from .signals import git as gitsig
    from .signals import pr as prsig

    log = log or (lambda msg: None)
    raw = snap.get("sessions") or []
    folders_by_key = {s["key"]: gitsig.resolve(s.get("folder")) for s in raw}
    unique_folders = sorted({f for f in folders_by_key.values() if f})
    shared = gitsig.find_shared(folders_by_key)
    lookup = lookup or prsig.make_lookup()

    # One bad file or failing tool for one session must degrade that session's signal to
    # unknown with a cause (FR-007), never abort the whole gathering.
    def read_conv(s):
        try:
            return convsig.read_conversation((s.get("copy") or {}).get("path"))
        except Exception as exc:
            log("conversation %s: %r" % (s.get("key"), exc))
            return convsig.Conversation(status="unknown",
                                        cause="conversation copy unreadable: %s" % exc)

    def folder(path):
        try:
            return gitsig.folder_state(path)
        except Exception as exc:
            log("git %s: %r" % (path, exc))
            return gitsig.unknown_state("git status failed: %s" % exc)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        convs = list(pool.map(read_conv, raw))
        log("conversations read")
        states = dict(zip(unique_folders, pool.map(folder, unique_folders)))
        log("git state of %d folders" % len(unique_folders))

        def clip(pair):
            s, conv = pair
            if conv.status != "found":
                return {"status": "unknown", "cause": "conversation copy unreadable"}
            try:
                return clipsig.detect_clipboard((s.get("copy") or {}).get("tools_path"),
                                                conv.user_message_refs)
            except Exception as exc:
                log("clipboard %s: %r" % (s.get("key"), exc))
                return {"status": "unknown", "cause": "tools copy unreadable: %s" % exc}

        clips = list(pool.map(clip, zip(raw, convs)))
        # Deciding links first, so slow historical links cannot trip the gh circuit breaker
        # before every session's deciding PR has been looked up (FR-012).
        # Sessions whose newest PR-like link is on another host are decided as "host not
        # GitHub" without any lookup, so their GitHub links are never looked up.
        github_convs = [conv for conv in convs if conv.pr_links and conv.newest_pr_is_github]
        deciding = sorted({conv.pr_links[0] for conv in github_convs})
        list(pool.map(lookup, deciding))
        urls = set(deciding)
        for conv in github_convs:
            urls.update(conv.pr_links[1: 1 + prsig.MAX_OTHER_LOOKUPS])
        list(pool.map(lookup, sorted(urls - set(deciding))))
        log("%d pull requests looked up" % len(urls))

    sessions = []
    for s, conv, clip_sig in zip(raw, convs, clips):
        key = s["key"]
        folder = folders_by_key[key]
        is_shared = bool(shared.get(key))
        items = [_checklist_item(conv)]
        items += gitsig.git_items(states[folder] if folder else gitsig.folder_state(None),
                                  is_shared)
        items.append(_interrupted_item(s.get("interrupted") or {}))
        if conv.status == "found":
            pr_sig = prsig.pr_signal(conv.pr_links, conv.non_github_pr_links, lookup,
                                     newest_is_github=conv.newest_pr_is_github)
        else:
            pr_sig = {"status": "unknown", "cause": "conversation copy unreadable",
                      "current": None, "others": []}
        conversation = {"status": conv.status}
        if conv.status != "found":
            conversation["cause"] = ((s.get("copy") or {}).get("cause") or conv.cause
                                     or "conversation copy unreadable")
        out = {
            "key": key,
            "provider": s["provider"],
            "session_id": s["session_id"],
            "name": s.get("name") or "",
            "kind": s["kind"],
            "pane": s.get("pane"),
            "headless_id": s.get("headless_id"),
            "hibernated": bool(s.get("hibernated")),
            "workspace": s["workspace"],
            "folder": folder,
            "agent_state": s["agent_state"],
            "backend_state": s["backend_state"],
            "changed_at": s.get("changed_at"),
            "first_activity_at": conv.first_activity_at,
            "last_message_at": conv.last_message_at,
            "conversation": conversation,
            "messages": conv.messages,
            "pr_links": conv.pr_links,
            "also_open_in": s.get("also_open_in") or [],
            "signals": {
                "clipboard": clip_sig,
                "unfinished": unfinished_status(items),
                "shared_folder": {"shared": is_shared, "sessions": shared.get(key, [])},
                "pr": pr_sig,
            },
        }
        if s.get("agent_state_cause"):
            out["agent_state_cause"] = s["agent_state_cause"]
        sessions.append(out)

    doc = {
        "format": FORMAT,
        "version": VERSION,
        "generated_at": snap["generated_at"],
        "backend": snap["backend"],
        "options": {"archived": bool(snap.get("archived"))},
        "caller": snap["caller"],
        "folders": {f: states[f] for f in unique_folders},
        "sessions": sessions,
    }
    errors = validate(doc)
    if errors:
        raise ValueError("internal error, digest does not validate: " + "; ".join(errors[:5]))
    return doc
