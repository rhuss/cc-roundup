"""Command line interface (contracts/cli.md).

Exit codes: 0 success, 2 usage error, 3 backend unreachable or backend error
(the backend's own message on stderr), 4 invalid input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import BackendError, InputError

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BACKEND = 3
EXIT_INPUT = 4
EXIT_INTERNAL = 1


class UsageError(Exception):
    """Bad arguments detected after parsing (exit 2)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2 on usage errors; keep that.
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, "%s: error: %s\n" % (self.prog, message))


def _debug_logger():
    if os.environ.get("ROUNDUP_DEBUG") != "1":
        return None
    start = time.monotonic()

    def log(msg):
        sys.stderr.write("[roundup %.2fs] %s\n" % (time.monotonic() - start, msg))

    return log


def cmd_gather(args) -> int:
    from . import digest
    from .adapters import corgi

    log = _debug_logger()
    snap = corgi.snapshot(archived=args.archived, log=log)
    if log:
        log("snapshot: %d sessions" % len(snap["sessions"]))
    doc = digest.build(snap, log=log)
    if log:
        log("digest built")
    digest.dump(doc, sys.stdout)
    return EXIT_OK


def cmd_judge_view(args) -> int:
    from . import digest, render

    if args.page_size < 1:
        raise UsageError("--page-size must be at least 1")
    doc = digest.load(args.digest)
    try:
        sys.stdout.write(render.render_judge_view(doc, args.page, args.page_size))
    except ValueError as exc:
        raise UsageError(str(exc))
    return EXIT_OK


def cmd_overview(args) -> int:
    from . import digest, engine, render, timefmt

    try:
        stale_seconds = timefmt.parse_duration(args.stale)
    except ValueError as exc:
        raise UsageError(str(exc))
    doc = digest.load(args.digest)
    judgments = engine.load_judgments(args.judgments, doc)
    entries = engine.evaluate(doc, judgments, stale_seconds, platform=sys.platform)
    copyback = sys.platform == "darwin"
    meta = {
        "generated_at": doc["generated_at"],
        "stale": args.stale,
        "stale_seconds": stale_seconds,
        "caller": doc.get("caller"),
        "copyback_available": copyback,
    }
    if not copyback:
        meta["copyback_cause"] = "copy-back is only available on macOS"
    try:
        sys.stdout.write(render.render_overview(entries, args.format, key=args.key, meta=meta))
    except KeyError:
        raise InputError("no session %s in the digest" % args.key)
    return EXIT_OK


def _print_outcome(result) -> int:
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return EXIT_OK


def cmd_act_close(args) -> int:
    from . import digest
    from .adapters import corgi

    session = digest.find_session(digest.load(args.digest), args.key)
    check = corgi.recheck(session)
    if not check["ok"]:
        return _print_outcome(corgi.outcome(session, "close", "skipped", check["reason"]))
    return _print_outcome(corgi.close(session))


_NO_FOLLOWUP = {
    "exited": "agent exited; no follow-up (add it to the close batch instead)",
    "blocked": "approval pending; no follow-up",
    "unknown": "agent state unknown; no follow-up",
}


def cmd_act_message(args) -> int:
    from . import answers, digest, timefmt
    from .adapters import corgi

    text = sys.stdin.read()
    if not text.strip():
        raise UsageError("empty follow-up text on stdin")
    session = digest.find_session(digest.load(args.digest), args.key)
    if session.get("hibernated"):
        return _print_outcome(corgi.outcome(
            session, "message", "skipped",
            "pane is hibernated; no follow-up (add it to the close batch instead)"))
    refusal = _NO_FOLLOWUP.get(session.get("agent_state"))
    if refusal:
        return _print_outcome(corgi.outcome(session, "message", "skipped", refusal))
    sent_at = timefmt.now_iso()
    result = corgi.message(session, answers.relay_text(text))
    transcript = result.pop("transcript", None)
    offset = result.pop("transcript_offset", 0)
    if result["outcome"] == "done":
        run_dir = os.path.dirname(os.path.abspath(args.digest))
        answers.record_sent(run_dir, session, text, transcript, offset, sent_at)
    return _print_outcome(result)


def cmd_copyback(args) -> int:
    from . import clipboard_out, digest

    session = digest.find_session(digest.load(args.digest), args.key)
    return _print_outcome(clipboard_out.copy_back(session, set(args.closed or []),
                                                  platform=sys.platform))


def cmd_collect(args) -> int:
    from . import answers

    if not 0 <= args.wait <= answers.MAX_WAIT:
        raise UsageError("--wait must be between 0 and %d seconds" % answers.MAX_WAIT)
    run_dir = os.path.dirname(os.path.abspath(args.digest))
    doc = answers.collect(answers.load_sent(run_dir), args.wait)
    sys.stdout.write(json.dumps(doc, ensure_ascii=False) + "\n")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="roundup", description="Round up open agent sessions (corgi-roundup).")
    sub = p.add_subparsers(dest="command", parser_class=_Parser)
    sub.required = True

    g = sub.add_parser("gather", help="build the digest (read-only) and print it to stdout")
    g.add_argument("--archived", action="store_true", help="include archived workspaces")
    g.set_defaults(func=cmd_gather)

    j = sub.add_parser("judge-view", help="compact per-session view for judging, page by page")
    j.add_argument("--digest", required=True)
    j.add_argument("--page", type=int, default=1)
    j.add_argument("--page-size", type=int, default=20)
    j.set_defaults(func=cmd_judge_view)

    o = sub.add_parser("overview", help="categorize sessions and print the overview")
    o.add_argument("--digest", required=True)
    o.add_argument("--judgments", required=True)
    o.add_argument("--stale", default="3d")
    o.add_argument("--format", choices=("text", "json"), default="text")
    o.add_argument("--key")
    o.set_defaults(func=cmd_overview)

    a = sub.add_parser("act", help="run a confirmed action on one session")
    asub = a.add_subparsers(dest="verb", parser_class=_Parser)
    asub.required = True
    ac = asub.add_parser("close", help="re-check, then close the pane or stop the headless agent")
    ac.add_argument("--digest", required=True)
    ac.add_argument("--key", required=True)
    ac.set_defaults(func=cmd_act_close)
    am = asub.add_parser("message", help="re-check, then send stdin text through the agent channel")
    am.add_argument("--digest", required=True)
    am.add_argument("--key", required=True)
    am.set_defaults(func=cmd_act_message)

    c = sub.add_parser("copyback", help="put a forgotten clipboard text back (macOS)")
    c.add_argument("--digest", required=True)
    c.add_argument("--key", required=True)
    c.add_argument("--closed", nargs="*", default=[], metavar="KEY")
    c.set_defaults(func=cmd_copyback)

    co = sub.add_parser("collect", help="read the answers to this run's follow-ups (read-only)")
    co.add_argument("--digest", required=True)
    co.add_argument("--wait", type=float, default=180, metavar="SECONDS")
    co.set_defaults(func=cmd_collect)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as exc:
        sys.stderr.write("roundup: %s\n" % exc)
        return EXIT_USAGE
    except BackendError as exc:
        sys.stderr.write("%s\n" % exc)
        return EXIT_BACKEND
    except InputError as exc:
        sys.stderr.write("roundup: %s\n" % exc)
        return EXIT_INPUT
    except Exception as exc:  # last resort: one line instead of a traceback
        if os.environ.get("ROUNDUP_DEBUG") == "1":
            import traceback
            traceback.print_exc()
        sys.stderr.write("roundup: internal error: %s: %s\n" % (type(exc).__name__, exc))
        return EXIT_INTERNAL
