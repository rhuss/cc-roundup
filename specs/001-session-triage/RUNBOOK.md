---
runbook_version: 1
feature: 001-session-triage
status: drafted
mode: light
steps_total: 11
step_results: pending,pending,pending,pending,pending,pending,pending,pending,pending,pending,pending
drafted_at: 34d7a1a
drafted_fingerprint: 30de6cf4b7dfcc015cde0b76059dfb0c3ca970f616c0caf11ab550e49df696f1
tested_at:
tested_fingerprint:
updated: 2026-11-22
---

# Try it: Session Triage (roundup)

<!-- runbook-status -->
> **Status:** drafted · 0 of 11 steps · Mode: light · Drafted at 34d7a1a · 2026-11-22
<!-- /runbook-status -->

## What you're testing

The `roundup` skill reviews every open top-level agent session in your Corgi workspaces. It sorts each one into *waiting on you*, *stale, decide*, *waiting on others* or *done, close it*, gives a visible reason, and runs only the steps you confirm.

The journey goes from safe to live. First the offline test suite. Then a read-only gather against your running Corgi, the judge view and the mechanical overview. Then the error path when Corgi is unreachable. Finally, the plugin is installed and the full review runs on two throwaway sessions: one gets closed and one gets a follow-up, while your real sessions stay untouched.

Run every command from the repository root (the feature worktree), inside an agent or shell in a Corgi pane.

## Test environment

No fixtures are started for you. The live steps use your running Corgi runtime as it is. Step 9 asks you to open two short throwaway agent sessions by hand. All temporary files go to `${TMPDIR:-/tmp}/roundup-try`, removed in the last step.

## Steps

### Step 1 of 11: Run the offline test suite (US1)

**Why this step:** Proves the gathering, category rules and actions work against recorded Corgi output and stub tools, with no live runtime, network or clipboard.

**Needs:** Python 3.9+, `git`.

**Run:**

```
make test
```

**What you should see:** The last lines read `Ran 191 tests in ...` followed by `OK`.

**If you see something else:** `FAILED (failures=N)` points at a regression; the failing test name tells you which signal or rule. `python3: command not found` means Python is missing.

**Result:**

### Step 2 of 11: Confirm you are inside a Corgi pane (US1)

**Why this step:** The review needs Corgi's own binary and the caller's pane to exclude itself.

**Needs:** a running Corgi runtime.

**Run:**

```
echo "pane=$CORGI_PANE exe=$CORGI_APP_EXE" && "$CORGI_APP_EXE" current --json
```

**What you should see:** A non-empty pane number and binary path, then a JSON line starting `{"ok":true,"result":{"pane":` with the same pane number.

**If you see something else:** Empty `pane=` means you are not in a Corgi pane. `connect ENOENT` means the runtime is not running.

**Result:**

### Step 3 of 11: Gather a read-only digest of your live sessions (US1)

**Why this step:** Shows gathering is fast and changes nothing; the digest goes to stdout and you redirect it into a temporary folder.

**Needs:** Step 2.

**Run:**

```
mkdir -p "${TMPDIR:-/tmp}/roundup-try" && time roundup/scripts/roundup gather > "${TMPDIR:-/tmp}/roundup-try/digest.json"; echo "exit=$?"
```

**What you should see:** `exit=0` and a `real` time under 30 seconds (about 17 seconds was measured with 40 sessions).

**If you see something else:** `exit=3` with a Corgi error means the runtime could not be reached. A time above 30 seconds usually comes from a cold Corgi search index; run it once more.

**Result:**

### Step 4 of 11: Check scope and the caller exclusion (US1)

**Why this step:** Every open top-level session must appear exactly once, and this session must not.

**Needs:** Step 3.

**Run:**

```
jq '{format, version, caller, sessions: (.sessions | length), unique_keys: ([.sessions[].key] | unique | length), states: ([.sessions[].agent_state] | group_by(.) | map({(.[0]): length}) | add), caller_listed: ([.sessions[].pane] | index(env.CORGI_PANE | tonumber) != null)}' "${TMPDIR:-/tmp}/roundup-try/digest.json"
```

**What you should see:** `"format": "roundup-digest"`, `"version": 1`, `caller.excluded` is `true`, `sessions` equals `unique_keys`, `caller_listed` is `false`, and the session count matches the agent panes you have open in non-archived workspaces minus this one.

**If you see something else:** `caller.excluded: false` with a cause means `CORGI_PANE` did not match a pane. Differing `sessions` and `unique_keys` would be a duplicate bug.

**Result:**

### Step 5 of 11: Read the judge view (US1)

**Why this step:** This compact view is what the agent reads to judge each session; it shows recent messages and the mechanical signals in one place.

**Needs:** Step 3.

**Run:**

```
roundup/scripts/roundup judge-view --digest "${TMPDIR:-/tmp}/roundup-try/digest.json" --page 1 | tail -40
```

**What you should see:** Session blocks with key, name, workspace, state, quiet time, recent messages and one-line signal summaries (clipboard, unfinished work, PR), ending with `page 1 of N`.

**If you see something else:** `unsupported digest version` means the digest file came from another build.

**Result:**

### Step 6 of 11: Show the mechanical overview (US1)

**Why this step:** With an empty judgments file, only mechanical signals decide, so you see the category engine's own verdicts and reasons.

**Needs:** Step 3.

**Run:**

```
printf '%s\n' '{"format":"roundup-judgments","version":1,"sessions":{}}' > "${TMPDIR:-/tmp}/roundup-try/judgments.json" && roundup/scripts/roundup overview --digest "${TMPDIR:-/tmp}/roundup-try/digest.json" --judgments "${TMPDIR:-/tmp}/roundup-try/judgments.json" --stale 3d | head -60
```

**What you should see:** Category headings in the order *waiting on you*, *stale, decide*, *waiting on others*, *done, close it*; within each, the longest-quiet session first; every session with a one-line reason (for example `approval pending`, `agent working`, `2 unpushed commits`, `PR merged: ...`, `quiet 5d, stale`). Blocked agents sit under *waiting on you*, working agents under *waiting on others*.

**If you see something else:** A working agent under *done, close it* would break FR-015. Exit 2 with `invalid duration` means the `--stale` value is malformed.

**Result:**

### Step 7 of 11: Unreachable runtime stops with Corgi's error (US1)

**Why this step:** When Corgi cannot be reached, the review must stop and show Corgi's own message, not guess.

**Run:**

```
CORGI_SOCKET=/nonexistent roundup/scripts/roundup gather > /dev/null; echo "exit=$?"
```

**What you should see:** A line on stderr containing `connect ENOENT /nonexistent`, then `exit=3`.

**If you see something else:** `exit=0` means the socket override was ignored.

**Result:**

### Step 8 of 11: Install the plugin in Claude Code (US5)

**Why this step:** The skill must work from the installed plugin, not only from the clone.

**Run:**

```
make validate && make install
```

**What you should see:** Both manifests validate, then the install finishes with `cc-roundup@cc-roundup-plugin-development` installed. In a new Claude Code session, `/cc-roundup:roundup` is offered.

**If you see something else:** A validation error names the manifest field at fault.

**Result:**

### Step 9 of 11: Run the full review on two throwaway sessions (US2, US3)

**Why this step:** Exercises the confirmation flow end to end: close batch first, then follow-ups, with nothing running before you confirm.

**Needs:** Step 8.

**Do:**

1. Open a new Corgi tab, start Claude Code, and send: `Reply with the single word DONE and nothing else.` Wait for the reply. This is throwaway A (finished).
2. Open another tab, start Claude Code, and send: `Ask me whether you should create a file named roundup-test.txt, then wait.` Wait for the question. This is throwaway B (waiting on you).
3. In a third Claude Code session in a Corgi pane, run `/cc-roundup:roundup`.
4. Check the overview, then in the close batch remove every entry except throwaway A and confirm.
5. In the follow-up step, accept or edit the draft for throwaway B (for example `No, do not create it.`) and send it; skip every other follow-up. Skip all copy-backs.

**What you should see:** Throwaway A under *done, close it* (or *stale, decide*, which you can add to the batch) and throwaway B under *waiting on you* with a reason quoting its question. Nothing happens before each confirmation. The closing report lists A as closed, B's follow-up as done (delivery through the agent's channel, not typed), and everything else as not run. A's tab is gone, B's agent answers your follow-up, and all your other panes are unchanged.

**If you see something else:** A follow-up reported as `skipped` with "agent channel not available" means Corgi had no channel for that agent, so the review refused to type. A `failed` outcome naming typed delivery is the known Codex limitation.

**Result:**

### Step 10 of 11: Confirm the closed session can be resumed (US2)

**Why this step:** Closing must not lose the conversation (FR-027).

**Needs:** Step 9.

**Run:**

```
"$CORGI_APP_EXE" history --limit 5
```

**What you should see:** Throwaway A's conversation near the top, titled with its prompt. `corgi resume claude <session>` with the id shown there opens it again.

**If you see something else:** If A is missing, check `"$CORGI_APP_EXE" history --limit 50`; history listing gaps were observed in research for some live sessions.

**Result:**

### Step 11 of 11: Clean up the temporary files (US1)

**Why this step:** The digest holds real conversation excerpts; nothing may be kept between runs.

**Run:**

```
rm -rf "${TMPDIR:-/tmp}/roundup-try" && ls "${TMPDIR:-/tmp}" | grep -c '^roundup-' || true
```

**What you should see:** `0`: no `roundup-` run folders left behind (the skill deletes its own run folder at the end of each review).

**If you see something else:** A leftover `roundup-XXXXXX` folder means a skill run did not clean up after itself.

**Result:**

## Not covered here

- Copy-back of a real forgotten clipboard draft: it needs a session whose last tool call copied text and was never followed up, which cannot be produced on demand without overwriting your clipboard. The offline suite covers it with stubbed `pbcopy` and `slack-pbcopy` (Step 1).
- The Codex harness run and the overview comparison across harnesses: `make install-codex` plus a second full review. It repeats Step 9 in Codex and is left out to keep the journey short.
- The 2-minute end-to-end target with about 70 sessions depends on how many sessions you have open; Step 3 measures the gathering half.

## Coverage

- **US1** (overview): Steps 1 to 7 and 11.
- **US2** (close batch): Steps 9 and 10.
- **US3** (follow-ups): Step 9.
- **US4** (copy-back): offline only (Step 1); see Not covered here.
- **US5** (installation): Step 8 for Claude Code; Codex is not covered here.

## Results
