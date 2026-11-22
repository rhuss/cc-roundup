"""Forgotten clipboard detection (FR-009, research R6).

Reads the tools copy next to the conversation copy: one JSON object per tool
call or result. The last call is a forgotten clipboard when it is a shell call
running pbcopy or slack-pbcopy and no user message follows it. The copied text
is the heredoc body; anything that cannot be reconstructed exactly is marked
truncated (no copy-back then).
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from .. import timefmt
from ..digest import cut

FIRST_LINE_CHARS = 80

# Input keys that may follow `command:` in a call's text (Claude Bash, Codex shell).
_NEXT_KEY = re.compile(
    r"^(description|timeout|run_in_background|dangerouslyDisableSandbox|workdir|timeout_ms|"
    r"justification|sandbox_permissions|with_escalated_permissions|yield_time_ms|"
    r"max_output_tokens|login|shell):( |$)")
_COMMAND_KEY = re.compile(r"^(command|cmd): ?(.*)$")
# The clipboard tool in command position: line start or after | ; & ( or $(, then an
# optional keyword or wrapper, optional NAME=value assignments and an optional path.
_METHOD = re.compile(
    r"(?:^|[|;&(]|\$\()\s*(?:(?:then|do|else|time|env|command|exec|nohup)\s+)?"
    r"(?:[A-Za-z_]\w*=\S*\s+)*(?:[^\s|;&()<>]*/)?(slack-pbcopy|pbcopy)(?=$|[\s;|&)<>])")
_SEPARATOR = re.compile(r"\|\||&&|;|(?<![>&|])&(?![>&])")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_ARGS_END = re.compile(r"<<|[|;&]")
_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
_REDIRECT = re.compile(r"^\d*(?:>>?|<|>&|<&)")
# Characters an unquoted heredoc body would expand ($VAR, $(...), `...`, backslash escapes).
_EXPANDS = re.compile(r"[$`\\]")
# Flags the copy-back may pass on, per method; anything else is not reproduced.
_ALLOWED_ARGS = {"pbcopy": {"-pboard": 1, "-Prefer": 1}, "slack-pbcopy": {"--tight": 0}}


def _command_value(text: str) -> Optional[str]:
    lines = text.split("\n")
    for i, line in enumerate(lines[1:], 1):
        m = _COMMAND_KEY.match(line)
        if not m:
            continue
        value = [m.group(2)]
        pending = _heredoc_tags(m.group(2))
        for nxt in lines[i + 1:]:
            if pending:
                # Inside a heredoc body: a line like "timeout: 5" is text, not an input key.
                tag, strip_tabs = pending[0]
                if (nxt.lstrip("\t") if strip_tabs else nxt) == tag:
                    pending.pop(0)
                value.append(nxt)
                continue
            if _NEXT_KEY.match(nxt):
                break
            value.append(nxt)
            pending = _heredoc_tags(nxt)
        command = "\n".join(value)
        if command.startswith("["):  # Codex argv form, e.g. ["bash","-lc","..."]
            try:
                argv = json.loads(command)
                if isinstance(argv, list) and all(isinstance(a, str) for a in argv):
                    command = argv[-1] if len(argv) >= 3 and argv[-2] in ("-lc", "-c") \
                        else " ".join(argv)
            except ValueError:
                pass
        return command
    return None


def _as_int(ref: Any) -> Optional[int]:
    try:
        return int(str(ref).split(".")[0])
    except (TypeError, ValueError):
        return None


def _ms(value: Any) -> Optional[int]:
    """A millisecond timestamp, or None when missing or malformed (never raises)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return ms if ms > 0 else None


def _user_follows(call_ts: Any, call_ref: Any,
                  user_refs: List[Tuple[Optional[int], Any]]) -> bool:
    cref = _as_int(call_ref)
    call_ms = _ms(call_ts)
    for ts, ref in user_refs:
        user_ms = _ms(ts)
        if user_ms and call_ms:
            if user_ms > call_ms:
                return True
        else:
            uref = _as_int(ref)
            if uref is not None and cref is not None and uref > cref:
                return True
    return False


def _heredoc_tags(line: str) -> List[Tuple[str, bool]]:
    return [(m.group(3), m.group(1) == "-") for m in _HEREDOC.finditer(_unquoted(line))]


def _unquoted(line: str) -> str:
    """The line with quoted strings blanked out (same length), so their content never matches.

    A quoted heredoc delimiter (<<'EOF', <<"EOF") is kept: it is syntax, not data.
    """
    def blank(m):
        if re.search(r"<<-?\s*$", line[: m.start()]):
            return m.group(0)
        return " " * len(m.group(0))
    return _QUOTED.sub(blank, line)


def find_copy(command: str) -> Optional[Tuple[Any, ...]]:
    """(line index, match[, single]) of the last clipboard tool in command position.

    Heredoc bodies and quoted strings are skipped. A third element False means the
    command holds several clipboard calls, so the copied text is not known exactly.
    """
    found = None
    count = 0
    pending: List[Tuple[str, bool]] = []
    for i, line in enumerate(command.split("\n")):
        if pending:
            tag, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == tag:
                pending.pop(0)
            continue
        m = None
        for m in _METHOD.finditer(_unquoted(line)):
            count += 1
        if m is not None:
            found = (i, m)
        pending = _heredoc_tags(line)
    if found is not None and count > 1:
        found = (found[0], found[1], False)  # several copies (if/else...): which one ran is unknown
    return found


def _args(method: str, rest: str) -> Optional[List[str]]:
    """Allowed flags after the tool name, without redirections; None if not reproducible."""
    try:
        tokens = shlex.split(rest, comments=True)
    except ValueError:
        return None
    allowed = _ALLOWED_ARGS[method]
    out: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^0?<(?!<)", tok):
            return None  # stdin comes from a file, not from a recorded heredoc
        if _REDIRECT.match(tok):
            # "2>/dev/null" carries its target; a bare ">" or "2>" takes the next token.
            bare = re.fullmatch(r"\d*(?:>>?|<|>&|<&)", tok) is not None
            i += 2 if bare else 1
            continue
        if tok not in allowed:
            return None
        nvals = allowed[tok]
        if nvals and i + nvals >= len(tokens):
            return None  # flag without its value
        out.extend(tokens[i:i + 1 + nvals])
        i += 1 + nvals
    return out


def _tool_heredoc(u: str, m: "re.Match") -> Tuple[Optional["re.Match"], bool]:
    """The heredoc on the tool's line and whether it provably is the tool's input.

    Bound only when it is the line's single heredoc, in the tool's own pipeline segment,
    and either redirects the tool itself or feeds a bare `cat` piped straight into it.
    """
    heredocs = list(_HEREDOC.finditer(u))
    if not heredocs:
        return None, True
    hd = heredocs[0]
    if len(heredocs) > 1:
        return hd, False
    tool_start, tool_end = m.start(1), m.end(1)
    seg_start, seg_end = 0, len(u)
    for sep in _SEPARATOR.finditer(u):
        if sep.end() <= tool_start:
            seg_start = sep.end()
        elif sep.start() >= tool_end:
            seg_end = sep.start()
            break
    if not (seg_start <= hd.start() < seg_end):
        return hd, False
    # The tool's own simple command: a later stdin redirect would replace the heredoc.
    own_end = seg_end
    pipe = u.find("|", tool_end, seg_end)
    if pipe >= 0:
        own_end = pipe
    if re.search(r"(?:^|\s)0?<(?!<)", re.sub(r"<<-?\s*\S+", " ", u[tool_end:own_end])):
        return hd, False
    if hd.start() >= tool_end:
        return hd, "|" not in u[tool_end:hd.start()]
    between = u[hd.end():tool_start]
    owner = u[seg_start:hd.start()].strip().lstrip("(").strip()
    piped = re.fullmatch(r"\s*\|\s*(?:[A-Za-z_]\w*=\S*\s+)*(?:[^\s|;&()<>]*/)?", between)
    return hd, bool(piped) and owner in ("cat", "/bin/cat")


def extract(command: str, where: Optional[Tuple[Any, ...]] = None) -> Dict[str, Any]:
    """Method, args and heredoc body of a clipboard command (text None when not exact)."""
    where = where or find_copy(command)
    if where is None:
        raise ValueError("no clipboard command in command position")
    line_no, m = where[0], where[1]
    single = len(where) < 3 or where[2]
    method = m.group(1)
    lines = command.split("\n")
    line = lines[line_no]
    rest = line[m.end(1):]
    end = _ARGS_END.search(_unquoted(rest))
    arg_list = _args(method, rest[: end.start()] if end else rest)
    exact = arg_list is not None and single
    args = " ".join(shlex.quote(a) for a in arg_list) if arg_list else ""
    body: Optional[List[str]] = None
    closed = False
    hd, bound = _tool_heredoc(_unquoted(line), m)
    if not bound:
        exact = False  # the heredoc on this line does not (provably) feed the clipboard tool
    if hd:
        tag, strip_tabs, quoted = hd.group(3), hd.group(1) == "-", bool(hd.group(2))
        body = []
        for nxt in lines[line_no + 1:]:
            if (nxt.lstrip("\t") if strip_tabs else nxt) == tag:
                closed = True
                break
            body.append(nxt.lstrip("\t") if strip_tabs else nxt)
        if not quoted and any(_EXPANDS.search(b) for b in body):
            exact = False  # the shell expanded the body; the recorded text is not what was copied
    text = "\n".join(body) if (body is not None and closed and exact) else None
    preview_source = "\n".join(body) if body else line
    first = next((l for l in preview_source.split("\n") if l.strip()), "")
    return {"method": method, "args": args, "text": text,
            "first_line": cut(" ".join(first.split()), FIRST_LINE_CHARS)}


def detect_clipboard(tools_path: Optional[str],
                     user_message_refs: List[Tuple[Optional[int], Any]]) -> Dict[str, Any]:
    """The digest `signals.clipboard` object for one session."""
    if not tools_path:
        return {"status": "unknown", "cause": "no tools copy"}
    last = None
    try:
        with open(tools_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # Only the last call matters: skip parsing results and other lines cheaply.
                if '"call"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                tool = rec.get("tool") if isinstance(rec, dict) else None
                if isinstance(tool, dict) and tool.get("kind") == "call":
                    last = rec
    except OSError as exc:
        return {"status": "unknown", "cause": "cannot read tools copy: %s" % (exc.strerror or exc)}
    if last is None:
        return {"status": "not_found"}
    text = last.get("text")
    command = _command_value(text if isinstance(text, str) else "")
    where = find_copy(command) if command is not None else None
    if where is None:
        return {"status": "not_found"}
    if _user_follows(last.get("timestamp"), last.get("ref"), user_message_refs):
        return {"status": "not_found"}
    info = extract(command, where)
    truncated = info["text"] is None or (last.get("tool") or {}).get("status") != "success"
    return {
        "status": "found",
        "method": info["method"],
        "args": info["args"],
        "text": None if truncated else info["text"],
        "truncated": truncated,
        "at": timefmt.ms_to_iso(_ms(last.get("timestamp"))),
        "first_line": info["first_line"],
    }
