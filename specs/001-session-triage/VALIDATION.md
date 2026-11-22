# Validation: Session Triage (roundup)

**Date**: 2026-11-22 | **Quickstart**: [quickstart.md](quickstart.md)

## 1. Offline test suite

`make test`: **169 tests, all passing** (about 60 s, mostly git fixture repositories). No live Corgi runtime, no network, no real clipboard: every external tool is a stub that logs its argv and stdin. Covers SC-002, SC-003, SC-004 (mechanical part), SC-006 and SC-007.

A check over `tests/` finds no real home paths or conversation text; the fixtures use only `/Users/me`, `@ROOT@` and `@FIXTURES@`.

## 2. Seeded world

`python3 -m unittest tests.test_seeded_world -v`: **7 of 7 passing.**

- 22 top-level sessions in 4 non-archived workspaces. Each appears exactly once. The caller pane, the Ask Corgi helper, three subagents, the archived pane and the plain shell pane are absent (SC-002).
- 100% of labelled categories and rules match: 11 mechanical and 11 judgment-dependent sessions, using the recorded judgments (SC-004).
- Every session has a reason. The proposed actions match the labels. The stub log contains no mutating Corgi command and no clipboard call (SC-003).

## 3. Live gathering (read-only)

`roundup gather` ran against the running Corgi runtime from pane 878:

| Measure | Result |
|---|---|
| Gathering time | **17.4 s** (budget 30 s, SC-001). The snapshot took 13.5 s, most of it the bulk `corgi grep --tools`. Git for 20 folders took 0.5 s, `gh` lookups for 36 PRs took 3.2 s |
| Sessions | **40**, equal to the 40 agent panes in non-archived workspaces minus the caller (36 live, 4 hibernated, 0 headless) |
| Caller | `{"pane": 878, "excluded": true}` |
| Agent states | 38 idle, 1 blocked, 1 exited |
| Unknowns | 1 session without a conversation copy ("no conversation copy (corgi grep found none)"). Push state unknown for 3 detached HEADs. 10 folders are not git repositories. Interrupted is unknown for 3 sessions (not in history, transcript missing or without a prompt) |

Only read-only Corgi commands ran (`list --json`, `grep`, `history --json`). The live digest was deleted after the check.

## 4. Manual checks for the user (change live panes)

Not run here, because they close panes or send messages:

- `make install` and `make install-codex`. Then start `/cc-roundup:roundup` in Claude Code and the `roundup` skill in Codex.
- A categorized overview in under 2 minutes for about 70 sessions, from start to overview (SC-001).
- Declining every step leaves all panes untouched.
- A closed session shows up in `corgi history` and resumes with `corgi resume PROVIDER SESSION` (SC-005, FR-027).
- The overview matches across both harnesses for the same snapshot (US5).

## 5. Unreachable runtime

`CORGI_SOCKET=/nonexistent roundup/scripts/roundup gather` gives **exit 3**, and stderr shows Corgi's own error `connect ENOENT /nonexistent` (FR-032).

## Judged accuracy (SC-004, judgment part)

A fresh agent judged the seeded world's `judge-view` (2 pages, 22 sessions) using only `rules.md`. It did not see `judgments.json` or `expected.json`. Its judgments, run through `roundup overview` and compared with `expected.json`:

| Decided by | Correct |
|---|---|
| Judgment (unanswered agent, task finished) | **11 / 11 (100%)**, target at least 90% |
| Mechanical signals | 11 / 11 (100%) |

## Checkpoint reviews during implementation

| Checkpoint | Findings | Fixed |
|---|---|---|
| 1 (after T016) | 6 | 6 |
| 2 (after T033) | 7 | 7 |
