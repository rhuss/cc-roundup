#!/usr/bin/env python3
"""Regenerate the synthetic test fixtures under tests/fixtures/.

All content is invented. Paths use /Users/me, or the placeholders @FIXTURES@
(the copied fixture directory) and @ROOT@ (a per-test temporary directory)
that the stub corgi replaces when it serves a reply.

    python3 tests/fixtures/generate.py
"""
import hashlib
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = 1795348800  # 2026-11-22T12:00:00Z, matches tests/helpers.TEST_NOW
HOUR = 3600


def us_ago(hours):
    return int((NOW - hours * HOUR) * 1_000_000)


def ms_ago(hours):
    return int((NOW - hours * HOUR) * 1000)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(content, (dict, list)):
            json.dump(content, fh, indent=1)
            fh.write("\n")
        else:
            fh.write(content)


def jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def sid(n, provider="claude"):
    if provider == "codex":
        return "019a0000-0000-7000-8000-%012d" % n
    return "00000000-0000-4000-8000-%012d" % n


def conv_hash(key):
    return hashlib.md5(key.encode()).hexdigest()


def conversation_rows(messages, start_hours):
    """messages: list of (role, text); timestamps spread up to start_hours ago."""
    rows = []
    n = len(messages)
    for i, (role, text) in enumerate(messages):
        hours = start_hours * (n - i) / n if n else 0
        rows.append({"role": role, "timestamp": ms_ago(hours), "ref": str(10 + i * 10),
                     "text": text})
    return rows


def pane(pid, ws, provider, session, name, folder, state, changed_hours, *, brand="auto",
         exited=False, dormant=False, transcript="", obs="hook", account_dir=None,
         pane_account="", conv=0):
    if brand == "auto":
        brand = {"claude": "claude", "codex": "openai", None: None}[provider]
    agent = {
        "conversation": conv or pid,
        "subagents": {"running": 0, "blocked": 0, "waiting": False},
        "changed_at": us_ago(changed_hours) if changed_hours is not None else 0,
        "working_since": 0,
        "provider": provider,
        "account": None if account_dir is None else {
            "id": "[\"%s\",\"%s\"]" % (provider, account_dir), "name": provider,
            "directory": account_dir, "type": "oauth", "plan": "Max", "usage": None},
        "state": state,
        "attention": "none",
        "observation": {"source": obs, "pending_stop": False, "completed": 1, "read": 1,
                        "outcome": "completed"},
        "recent_activity": "",
        "name": name,
        "session": session,
        "transcript": transcript,
        "activity": "",
        "cwd": folder,
        "tool_active": False,
        "compacting": False,
        "compacting_since": 0,
        "paused": False,
        "retry_at": 0,
    }
    return {
        "tab": pid + 1000, "workspace": ws, "id": pid, "binding": 1, "name": "", "cwd": folder,
        "command": (provider or "") if brand else "", "brand": brand,
        "pid": -1 if (exited or dormant) else 40000 + pid, "cols": 100, "rows": 40,
        "exited": exited, "dormant": dormant, "restoring": "", "forking": False,
        "account": pane_account, "agent": agent,
    }


def headless(hid, ws, provider, session, name, folder, state, *, corgi=False, pane_id=None,
             exited=False, pending=0, changed_hours=1):
    agent = None
    if not corgi:
        agent = pane(0, ws, provider, session, name, folder, state, changed_hours,
                     obs="protocol")["agent"]
    entry = {"agent": agent, "session": session, "id": hid, "workspace": ws,
             "provider": provider, "cwd": folder, "corgi": corgi, "account": "", "model": "",
             "effort": None, "persist": True, "pane": pane_id, "ready": True, "exited": exited,
             "state": state, "attention": "none",
             "observation": {"source": "protocol", "pending_stop": False, "completed": 1,
                             "read": 0, "outcome": "completed"},
             "tool_active": False}
    if pending:
        entry["pending_requests"] = pending
    return entry


def conversation_entry(cid, ws, provider, session, parent=None, role=""):
    return {"id": cid, "parent": parent, "workspace": ws, "observed_at": 0, "role": role,
            "model": "", "model_name": "", "children_observed_at": 0,
            "agent": {"provider": provider, "session": session, "state": "unknown",
                      "changed_at": 0, "name": ""}}


def workspace(wid, name, archived=False):
    return {"id": wid, "name": name, "cwd": "/Users/me/src/" + name, "archived": archived,
            "auto_archived": False, "archive_summary": None, "closed_agents": 0,
            "last_agent": "claude", "starting_agents": []}


def list_reply(workspaces, panes, conversations, headless_sessions):
    return {"ok": True, "viewers": [], "result": {
        "type": "session", "protocol": 5, "server_pid": 1, "revision": 1,
        "workspaces": workspaces, "panes": panes, "conversations": conversations,
        "headless_sessions": headless_sessions, "closed_panes": 0}}


def bulk_row(provider, session, folder, cache):
    return {"source": {"provider": provider, "account": "/Users/me/." + provider,
                       "session": session, "cwd": folder, "updated_at": ms_ago(1),
                       "source": "/Users/me/.%s/projects/x/%s.jsonl" % (provider, session),
                       "cache": cache}}


def bash_call(command, hours, ref, status="success", description="Copy to the clipboard"):
    return {"role": "tool", "timestamp": ms_ago(hours), "ref": str(ref),
            "tool": {"kind": "call", "name": "Bash", "call_id": "toolu_%d" % ref,
                     "status": status, "exit_code": None, "call_ref": str(ref),
                     "result_ref": str(ref + 1)},
            "text": "Bash\ncommand: %s\ndescription: %s\ntimeout: 120000" % (command,
                                                                             description)}


def tool_result(text, hours, ref):
    return {"role": "tool", "timestamp": ms_ago(hours), "ref": str(ref),
            "tool": {"kind": "result", "name": "Bash", "call_id": "toolu_%d" % (ref - 1),
                     "status": "success", "exit_code": None, "result_ref": str(ref),
                     "call_ref": str(ref - 1)},
            "text": text}


def history_entry(provider, session, interrupted):
    return {"provider": provider, "account": "", "session": session, "title": "",
            "first": "", "last": "", "cwd": "/Users/me/src", "branch": "main",
            "updated_at": NOW - 3600, "interrupted": interrupted}


# ---------------------------------------------------------------------------
# tests/fixtures/corgi: adapter scenarios (scope, states, dedupe, fallbacks).

def gen_corgi():
    base = os.path.join(HERE, "corgi")
    shutil.rmtree(base, ignore_errors=True)
    prefix = "@FIXTURES@"
    ws = [workspace(1, "app"), workspace(2, "docs"), workspace(3, "old", archived=True)]
    acct = "/Users/me/.claude"
    P = []
    P.append(pane(101, 1, "claude", sid(101), "idle claude", "/Users/me/src/app", "idle", 5,
                  account_dir=acct))
    P.append(pane(102, 1, "claude", sid(102), "working claude", "/Users/me/src/app", "working",
                  0.1, account_dir=acct))
    P.append(pane(103, 2, "codex", sid(103, "codex"), "starting codex", "/Users/me/src/docs",
                  "initializing", 0.05, obs="protocol",
                  transcript=prefix + "/transcripts/codex-103.jsonl"))
    P.append(pane(104, 2, "claude", sid(104), "blocked claude", "/Users/me/src/docs", "blocked",
                  1, account_dir=acct, transcript=prefix + "/transcripts/claude-104.jsonl"))
    P.append(pane(105, 2, "claude", sid(105), "exited to shell", "/Users/me/src/docs",
                  "unknown", 30, brand=None, account_dir=acct))
    P.append(pane(106, 1, "claude", sid(106), "hibernated claude", "/Users/me/src/app",
                  "unknown", 100, brand=None, exited=True, dormant=True, account_dir=acct))
    P.append(pane(107, 2, "claude", sid(107), "no conversation copy", "/Users/me/src/docs",
                  "idle", 3, account_dir=acct))
    P.append(pane(108, 1, "claude", sid(108), "caller", "/Users/me/src/app", "working", 0.01,
                  account_dir=acct))
    P.append(pane(109, 3, "claude", sid(109), "archived", "/Users/me/src/old", "unknown", 500,
                  brand=None, exited=True, dormant=True, account_dir=acct))
    P.append(pane(110, 1, None, "", "", "/Users/me/src/app", "unknown", None, brand=None))
    P.append(pane(111, 1, "claude", sid(111), "twice open (dormant)", "/Users/me/src/app",
                  "unknown", 50, brand=None, exited=True, dormant=True, account_dir=acct))
    P.append(pane(112, 1, "claude", sid(111), "twice open (live)", "/Users/me/src/app", "idle",
                  2, account_dir=acct))
    P.append(pane(113, 2, "claude", sid(113), "odd state", "/Users/me/src/docs", "unknown", 4,
                  account_dir=acct))
    P.append(pane(114, 2, "claude", sid(114), "session ended", "/Users/me/src/docs", "done", 6,
                  account_dir=acct))
    # Two live panes on one conversation, listed highest id first: lowest id wins.
    P.append(pane(116, 2, "claude", sid(115), "twice live (b)", "/Users/me/src/docs", "idle", 2,
                  account_dir=acct))
    P.append(pane(115, 2, "claude", sid(115), "twice live (a)", "/Users/me/src/docs", "idle", 2,
                  account_dir=acct))
    H = [
        headless(5, 1, "claude", sid(201), "headless task", "/Users/me/src/app", "idle"),
        headless(6, 1, "claude", sid(202), "", "/Users/me/src/app", "working", corgi=True,
                 pane_id=108),
        headless(7, 1, "claude", sid(101), "headless twin", "/Users/me/src/app", "idle",
                 pane_id=101),
        headless(8, 2, "codex", sid(203, "codex"), "headless asks", "/Users/me/src/docs",
                 "idle", pending=1),
        headless(9, 2, "claude", sid(204), "headless gone", "/Users/me/src/docs", "idle",
                 exited=True),
    ]
    C = [conversation_entry(p["id"], p["workspace"], p["agent"]["provider"],
                            p["agent"]["session"]) for p in P if p["agent"]["provider"]]
    C.append(conversation_entry(301, 1, "claude", "a5b0353b922e6bed2", parent=101,
                                role="general-purpose"))
    write(os.path.join(base, "list.json"), list_reply(ws, P, C, H))

    bulk = []
    in_bulk = [("claude", sid(n)) for n in (101, 102, 104, 105, 108, 109, 111, 113, 114, 115, 201,
                                            202, 204)]
    in_bulk += [("codex", sid(103, "codex")), ("codex", sid(203, "codex"))]
    for provider, s in in_bulk:
        h = conv_hash(provider + ":" + s)
        cache = "%s/conv/%s.jsonl" % (prefix, h)
        bulk.append(bulk_row(provider, s, "/Users/me/src/app", cache))
        write(os.path.join(base, "conv", h + ".jsonl"), jsonl(conversation_rows(
            [("user", "please look at the build"), ("assistant", "The build is green.")], 6)))
        write(os.path.join(base, "conv", h + ".tools.jsonl"), "")
    write(os.path.join(base, "grep-bulk.jsonl"), jsonl(bulk))
    # 106 is missing from the bulk reply but answers a per-session grep.
    h = conv_hash("claude:" + sid(106))
    write(os.path.join(base, "grep-session-claude-%s.jsonl" % sid(106)),
          jsonl([bulk_row("claude", sid(106), "/Users/me/src/app",
                          "%s/conv/%s.jsonl" % (prefix, h))]))
    write(os.path.join(base, "conv", h + ".jsonl"), jsonl(conversation_rows(
        [("user", "hello"), ("assistant", "hi")], 100)))
    write(os.path.join(base, "conv", h + ".tools.jsonl"), "")
    # 107 is missing from the bulk reply and has no per-session answer either.

    hist = [history_entry("claude", sid(n), n == 102) for n in
            (101, 102, 106, 107, 108, 109, 111, 113, 114, 115, 201, 204)]
    hist += [history_entry("codex", sid(203, "codex"), False)]
    # 103 (codex), 104 and 105 (claude) are missing from history on purpose.
    write(os.path.join(base, "history.json"), {"ok": True, "conversations": hist})

    write(os.path.join(base, "transcripts", "claude-104.jsonl"), jsonl([
        {"type": "user", "isSidechain": False,
         "message": {"role": "user", "content": "run the gate again"},
         "timestamp": "2026-11-22T10:00:00.000Z"},
        {"type": "assistant", "isSidechain": False,
         "message": {"role": "assistant", "content": [{"type": "text",
                                                       "text": "Running the gate..."}]},
         "timestamp": "2026-11-22T10:00:05.000Z"},
        {"type": "user", "isSidechain": False,
         "message": {"role": "user", "content": [{"type": "text",
                                                  "text": "[Request interrupted by user]"}]},
         "timestamp": "2026-11-22T10:00:09.000Z"},
    ]))
    write(os.path.join(base, "transcripts", "codex-103.jsonl"), jsonl([
        {"timestamp": "2026-11-22T11:00:00.000Z", "type": "event_msg",
         "payload": {"type": "user_message", "message": "fix the docs"}},
        {"timestamp": "2026-11-22T11:00:03.000Z", "type": "event_msg",
         "payload": {"type": "turn_aborted", "reason": "interrupted"}},
    ]))
    write(os.path.join(base, "message-reply.json"),
          {"ok": True, "result": {"delivery": "message", "queued": False}})
    write(os.path.join(base, "close-reply.json"), "closed pane\n")
    write(os.path.join(base, "headless-stop-reply.json"), {"ok": True})


# ---------------------------------------------------------------------------
# tests/fixtures/world: the seeded world with labelled expectations.

def gen_world():
    base = os.path.join(HERE, "world")
    shutil.rmtree(base, ignore_errors=True)
    cbase = os.path.join(base, "corgi")
    prefix = "@FIXTURES@/corgi"
    claude_acct = "@ROOT@/accounts/claude"
    codex_acct = "@ROOT@/accounts/codex"
    ws = [workspace(1, "app"), workspace(2, "docs"), workspace(3, "infra"),
          workspace(4, "notes"), workspace(9, "attic", archived=True)]
    repos = {}
    panes, heads, convs, bulk, hist = [], [], [], [], []
    expected, judgments = {}, {}

    def repo(name, **opts):
        repos["repos/" + name] = opts
        return "@ROOT@/repos/" + name

    def add(n, wsid, folder, state, hours, messages, exp, judg, *, provider="claude",
            dormant=False, exited=False, brand="auto", interrupted=False, tools=None,
            headless_id=None, unreadable=False, obs="hook"):
        s = sid(n, provider)
        key = "%s:%s" % (provider, s)
        h = conv_hash(key)
        cache = "%s/conv/%s.jsonl" % (prefix, h)
        if unreadable:
            cache = "%s/conv/missing-%s.jsonl" % (prefix, h)
        else:
            write(os.path.join(cbase, "conv", h + ".jsonl"),
                  jsonl(conversation_rows(messages, hours + 1)))
            write(os.path.join(cbase, "conv", h + ".tools.jsonl"), jsonl(tools or []))
        bulk.append(bulk_row(provider, s, folder, cache))
        hist.append(history_entry(provider, s, interrupted))
        name = judg.pop("_name")
        if headless_id is not None:
            heads.append(headless(headless_id, wsid, provider, s, name, folder, state))
        else:
            acct = claude_acct if provider == "claude" else codex_acct
            panes.append(pane(200 + n, wsid, provider, s, name, folder, state, hours,
                              dormant=dormant, exited=exited or dormant, brand=brand,
                              obs="protocol" if provider == "codex" else obs,
                              account_dir=acct,
                              pane_account=codex_acct if provider == "codex" else ""))
        convs.append(conversation_entry(200 + n, wsid, provider, s))
        expected[key] = exp
        judgments[key] = judg

    def J(name, about, stopped, unanswered=False, finished=False, note=None, followup=None):
        d = {"_name": name, "unanswered_agent": unanswered, "task_finished": finished,
             "about": about, "stopped": stopped, "followup": followup}
        if note:
            d["judgment_note"] = note
        return d

    def E(category, rule, decided_by, action=None):
        return {"category": category, "rule": rule, "decided_by": decided_by,
                "action": action}

    # --- mechanical -------------------------------------------------------
    add(1, 1, repo("r01", dirty=True), "blocked", 1,
        [("user", "Run the database migration on staging."),
         ("assistant", "I need to run `make migrate ENV=staging`. Waiting for approval.")],
        E("waiting_on_you", 0, "mechanical"),
        J("staging migration", "Database migration on staging", "Waiting for approval to run make migrate"))
    add(2, 1, repo("r02", dirty=True), "working", 0.2,
        [("user", "Refactor the session store."), ("assistant", "Working on the store module now.")],
        E("waiting_on_others", 1, "mechanical"),
        J("session store refactor", "Refactor of the session store", "Agent is editing the store module"))
    add(3, 2, "/Users/me/scratch-missing", "initializing", 0.05,
        [("user", "Summarize the docs folder.")],
        E("waiting_on_others", 1, "mechanical"),
        J("docs summary", "Summary of the docs folder", "Agent is starting up"), provider="codex")
    add(4, 2, repo("r04", ahead=2), "idle", 20,
        [("user", "Fix the parser bug and commit."),
         ("assistant", "Fixed the parser bug and committed it in two commits. All tests pass.")],
        E("waiting_on_you", 2, "mechanical", "message"),
        J("parser fix", "Parser bug fix", "Committed in two commits, not pushed", finished=True,
          note="parser fix committed", followup="Please push the branch and open a PR."))
    clip_text = "Hi team, the WG kickoff is today at 17:00 CET.\n\n- agenda in the doc\n- bring questions"
    add(5, 4, repo("r05", kind="plain_dir"), "idle", 30,
        [("user", "Draft a Slack note about the WG kickoff and copy it for me."),
         ("assistant", "Drafted the note and copied it to the clipboard as rich text.")],
        E("waiting_on_you", 2, "mechanical", "copyback"),
        J("WG kickoff note", "Slack note about the WG kickoff", "Note copied to the clipboard"),
        tools=[bash_call("slack-pbcopy --tight <<'EOF'\n%s\nEOF" % clip_text, 30.5, 40),
               tool_result("public.html\t120 bytes", 30.5, 41)])
    add(6, 1, repo("r06", upstream="gone"), "idle", 48,
        [("user", "Open a PR for the login flow."),
         ("assistant", "Opened https://github.com/me/app/pull/5 first, then replaced it."),
         ("user", "Merge the new one."),
         ("assistant", "Merged https://github.com/me/app/pull/6 and deleted the branch.")],
        E("done_close_it", 4, "mechanical", "close"),
        J("login flow", "Login flow for the app", "PR #6 merged, branch deleted"))
    add(7, 2, repo("r07"), "idle", 3,
        [("user", "Open a PR for the docs fix."),
         ("assistant", "Opened https://github.com/me/app/pull/7 for review.")],
        E("waiting_on_others", 3, "mechanical"),
        J("docs fix PR", "Docs fix", "PR #7 open for review"))
    add(8, 3, repo("r08"), "unknown", 144,
        [("user", "Try the alternative cache approach."),
         ("assistant", "Closed https://github.com/me/app/pull/8 since the approach did not work.")],
        E("done_close_it", 4, "mechanical", "close"),
        J("cache experiment", "Alternative cache approach", "PR #8 closed without merge"),
        dormant=True, brand=None)
    add(9, 3, repo("r09", upstream="none"), "unknown", 96,
        [("user", "Start the infra cleanup branch."),
         ("assistant", "Created the branch and committed the first cleanup step.")],
        E("waiting_on_you", 2, "mechanical"),
        J("infra cleanup", "Infra cleanup branch", "First cleanup step committed locally"),
        brand=None)
    add(10, 4, repo("r10", kind="plain_dir"), "idle", 240, [],
        E("stale_decide", 5, "mechanical"),
        J("lost notes", "Unknown (conversation unreadable)", "Unknown"), unreadable=True)
    add(11, 1, repo("r11"), "idle", 6,
        [("user", "Regenerate the API client."),
         ("assistant", "Regenerating the client from the OpenAPI spec now.")],
        E("waiting_on_you", 2, "mechanical", "message"),
        J("API client", "API client regeneration", "Last turn was interrupted",
          followup="Your last turn was interrupted. Please finish regenerating the API client."),
        interrupted=True)
    # --- judged -----------------------------------------------------------
    add(12, 1, repo("r12"), "idle", 26,
        [("user", "Wire up the login form."),
         ("assistant", "The login form is wired up and validated. Should I also add the password reset link to the footer?")],
        E("waiting_on_you", 2, "judged", "message"),
        J("login form", "Login form wiring", "Asked whether to add a password reset link",
          unanswered=True, note="add password reset link?",
          followup="Yes, please add the password reset link to the footer."))
    add(13, 2, repo("r13"), "idle", 50,
        [("user", "Move the dashboards to the new endpoint."),
         ("assistant", "All three dashboards now load from the new endpoint and the tests pass. The task is complete.")],
        E("done_close_it", 4, "judged", "close"),
        J("dashboards", "Dashboards on the new endpoint", "All three dashboards migrated, tests pass",
          finished=True, note="dashboards migrated, tests pass"))
    add(14, 4, repo("r14", kind="plain_dir"), "idle", 120,
        [("user", "What are our options for caching the search results?"),
         ("assistant", "Options: an in-process LRU, Redis, or HTTP caching at the proxy."),
         ("user", "I'll think about it and come back to this."),
         ("assistant", "Sounds good. Let me know if you need anything else.")],
        E("stale_decide", 5, "judged"),
        J("caching options", "Caching options for search results", "User deferred the decision"))
    add(15, 4, repo("r15", kind="plain_dir"), "idle", 2,
        [("user", "Let's look at the flaky CI test later today."),
         ("assistant", "Noted. So far the CI log shows the timeout in the network setup step.")],
        E("stale_decide", 5, "judged"),
        J("flaky CI test", "Flaky CI test investigation", "First look at the CI log"))
    add(16, 1, repo("r16"), "idle", 8,
        [("user", "Find the memory leak in the image service."),
         ("assistant", "I traced the leak to the image cache. Next step would be an LRU limit of 200 entries. Want me to implement that?")],
        E("waiting_on_you", 2, "judged", "message"),
        J("memory leak", "Memory leak in the image service", "Proposed an LRU limit for the cache",
          unanswered=True, note="implement LRU limit?", followup="Yes, please implement the LRU limit."))
    add(17, 2, repo("r17"), "idle", 30,
        [("user", "Cut the v1.2.0 release."),
         ("assistant", "Release v1.2.0 is tagged and published, and the changelog is updated. Everything you asked for is done.")],
        E("done_close_it", 4, "judged", "close"),
        J("release v1.2.0", "Release v1.2.0", "Tagged, published, changelog updated", finished=True,
          note="v1.2.0 released"))
    add(18, 3, repo("r18"), "idle", 12,
        [("user", "Rename the CLI flags to kebab case."),
         ("assistant", "Renamed all CLI flags. I can also update the README with the new flag names if you want.")],
        E("waiting_on_you", 2, "judged", "message"),
        J("CLI flags", "CLI flag rename", "Offered to update the README", unanswered=True,
          note="offered README update", followup="Yes, please update the README with the new flags."),
        provider="codex")
    add(19, 4, repo("r19"), "idle", 96,
        [("user", "Write the quarterly report into report.md."),
         ("assistant", "The report is written to report.md with all four sections. That covers everything you asked for.")],
        E("done_close_it", 4, "judged", "close"),
        J("quarterly report", "Quarterly report", "report.md written with all sections", finished=True,
          note="report.md written"))
    shared = repo("shared", dirty=True)
    add(20, 1, shared, "idle", 72,
        [("user", "Fix the typo in the config loader."),
         ("assistant", "Fixed the typo in the config loader and verified that the service starts. Done.")],
        E("done_close_it", 4, "judged", "close"),
        J("config typo", "Typo in the config loader", "Fixed and verified", finished=True,
          note="typo fixed and verified"))
    repos["repos/shared-link"] = {"kind": "symlink", "to": "repos/shared"}
    add(21, 1, "@ROOT@/repos/shared-link", "idle", 24,
        [("user", "Plan the schema migration."),
         ("assistant", "I drafted two options: A adds a column, B adds a new table. Which one do you prefer?")],
        E("waiting_on_you", 2, "judged", "message"),
        J("schema migration", "Schema migration plan", "Asked to choose option A or B",
          unanswered=True, note="option A or B?", followup="Let's go with option A."))
    add(22, 2, repo("r22", kind="plain_dir"), "idle", 5,
        [("user", "Summarize the incident timeline."),
         ("assistant", "I summarized the incident timeline. Should I post it to the incident channel?")],
        E("waiting_on_you", 2, "judged", "message"),
        J("incident summary", "Incident timeline summary", "Asked whether to post it",
          unanswered=True, note="post to incident channel?", followup="Yes, please post it."),
        headless_id=12)

    # --- excluded -----------------------------------------------------------
    caller_sid = sid(900)
    panes.append(pane(900, 1, "claude", caller_sid, "roundup itself", "/Users/me/src/app",
                      "working", 0.01, account_dir=claude_acct))
    convs.append(conversation_entry(900, 1, "claude", caller_sid))
    panes.append(pane(950, 9, "claude", sid(950), "archived work", "/Users/me/src/attic",
                      "unknown", 900, brand=None, exited=True, dormant=True,
                      account_dir=claude_acct))
    convs.append(conversation_entry(950, 9, "claude", sid(950)))
    panes.append(pane(960, 2, None, "", "", "/Users/me/src/docs", "unknown", None, brand=None))
    for i, parent in enumerate((212, 216, 900)):
        convs.append(conversation_entry(970 + i, 1, "claude", "a00000000000000%02d" % i,
                                        parent=parent, role="general-purpose"))
    heads.append(headless(13, 1, "claude", sid(990), "", "/Users/me/src/app", "working",
                          corgi=True, pane_id=900))

    write(os.path.join(cbase, "list.json"), list_reply(ws, panes, convs, heads))
    write(os.path.join(cbase, "grep-bulk.jsonl"), jsonl(bulk))
    write(os.path.join(cbase, "history.json"), {"ok": True, "conversations": hist})
    write(os.path.join(cbase, "message-reply.json"),
          {"ok": True, "result": {"delivery": "message", "queued": False}})
    write(os.path.join(cbase, "close-reply.json"), "closed pane\n")
    write(os.path.join(cbase, "headless-stop-reply.json"), {"ok": True})
    write(os.path.join(base, "repos.json"), repos)
    write(os.path.join(base, "expected.json"), {"caller_pane": 900, "sessions": expected})
    write(os.path.join(base, "judgments.json"),
          {"format": "roundup-judgments", "version": 1, "sessions": judgments})
    gh = os.path.join(base, "gh")
    write(os.path.join(gh, "me-app-5.json"),
          {"state": "MERGED", "mergedAt": "2026-11-19T10:00:00Z", "closed": True})
    write(os.path.join(gh, "me-app-6.json"),
          {"state": "MERGED", "mergedAt": "2026-11-20T10:00:00Z", "closed": True})
    write(os.path.join(gh, "me-app-7.json"), {"state": "OPEN", "mergedAt": None, "closed": False})
    write(os.path.join(gh, "me-app-8.json"),
          {"state": "CLOSED", "mergedAt": None, "closed": True})


def gen_gh():
    base = os.path.join(HERE, "gh")
    shutil.rmtree(base, ignore_errors=True)
    write(os.path.join(base, "me-app-1.json"), {"state": "OPEN", "mergedAt": None, "closed": False})
    write(os.path.join(base, "me-app-2.json"),
          {"state": "MERGED", "mergedAt": "2026-11-20T10:00:00Z", "closed": True})
    write(os.path.join(base, "me-app-3.json"), {"state": "CLOSED", "mergedAt": None, "closed": True})


if __name__ == "__main__":
    gen_corgi()
    gen_world()
    gen_gh()
    print("fixtures regenerated in", HERE)
