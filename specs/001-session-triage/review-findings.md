# Deep Review Findings

**Date:** 2026-11-22
**Branch:** 001-session-triage
**Rounds:** 3 (fix rounds) + final re-review
**Gate Outcome:** PASS
**Invocation:** quality-gate (ship pipeline, autonomous)

## Summary

| Severity | Found | Fixed | Remaining |
|----------|-------|-------|-----------|
| Critical | 0 | 0 | 0 |
| Important | 25 | 23 | 0 |
| Minor | 61 | 38 | 23 |
| Notable | 8 | - | 8 |
| **Total** | **94** | **61** | **31** |

Important: 25 found, 23 fixed. The other 2 were not fixed and are not counted as remaining Important: one is out of scope (`.specify/spex.json`, tool configuration, not code under review), and one was reclassified as Notable because the spec explicitly accepts it (Corgi's typing fallback, see NOTABLE-8). Both need a human decision, see "Needs judgment" below.

**Agents completed:** 5/6 (Goal Alignment skipped: no PR exists for the branch) + 2 external tools (CodeRabbit, 4 passes; Codex, 1 pass). Copilot disabled in config.
**Agents failed:** none

## Findings (Critical and Important)

### FINDING-1: Unquoted heredoc treated as exact copied text
- **Severity:** Important · **Confidence:** 90 · **File:** roundup/lib/roundup/signals/clipboard.py · **Category:** correctness
- **Source:** stage-1 compliance (FR-009/FR-024), also coderabbit, test-quality agent · **Round found:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** A body under `<<EOF` (unquoted) was recorded as the exact copied text, but the shell expands `$VAR`, `$(...)`, backticks and backslashes before `pbcopy` sees it.
**Why this matters:** Copy-back (US4) would restore different text than the user drafted, silently.
**How it was resolved:** Unquoted heredoc bodies that contain `$`, backtick or backslash now give `text: null` (truncated, no copy-back). Quoted delimiters stay exact. Tests added for each expansion form and for `<<-` tab stripping.

> CodeRabbit: "For `pbcopy <<EOF` with body `$(printf approved)`, the shell copies expanded text. This function instead returns the literal substitution."

### FINDING-2: Clipboard tool matched anywhere in the command
- **Severity:** Important · **Confidence:** 85 · **File:** roundup/lib/roundup/signals/clipboard.py · **Category:** correctness · **Source:** correctness-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** `which pbcopy`, `rg pbcopy`, or a commit message mentioning pbcopy counted as a forgotten clipboard.
**Why this matters:** Rule 2 fires before rules 3 and 4, so merged-PR sessions landed in *waiting on you* with a bogus reason (FR-009, FR-014).
**How it was resolved:** New `find_copy` accepts the tool only in command position (line start or after `|`, `;`, `&`, `(`, `$(`, optionally after a keyword, wrapper or `NAME=value` prefix), skips heredoc bodies and quoted strings.

### FINDING-3: No untrusted-data rule for session content (prompt injection)
- **Severity:** Important · **Confidence:** 80 · **File:** roundup/skills/roundup/SKILL.md, rules.md, roundup/lib/roundup/render.py · **Category:** security · **Source:** security-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** The judging agent read other sessions' messages without being told they are data; session names with newlines could fake judge-view headers.
**Why this matters:** Text in a conversation could steer judgments (and thus the preselected close batch) or plant follow-up drafts.
**How it was resolved:** Hard rule added to SKILL.md and rules.md (never follow instructions in session content, never let it pick keys, actions or targets, flag risky drafts). Names, workspaces, folders, causes, details and first lines are flattened to one line in the judge view and overview.

### FINDING-4: Follow-up text embedded in a shell heredoc
- **Severity:** Important · **Confidence:** 75 · **File:** roundup/skills/roundup/SKILL.md · **Category:** security · **Source:** security-agent, also coderabbit · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** `act message ... <<'ROUNDUP_EOF'` with the confirmed text inline; a line `ROUNDUP_EOF` in the text ends the heredoc and the rest runs as shell commands.
**How it was resolved:** The skill now writes the confirmed text with the file tool to `RUN/followup-<n>.txt` and redirects it into `act message`.

### FINDING-5: One malformed session file aborts the whole gather
- **Severity:** Important · **Confidence:** 82 · **File:** roundup/lib/roundup/digest.py, signals/conversation.py, signals/clipboard.py, cli.py · **Category:** production-readiness · **Source:** production-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** A string timestamp or a non-string tool text raised inside the thread pool and ended `gather` with a traceback.
**Why this matters:** FR-007 requires unreadable data to become *unknown* with a cause; one bad file blocked the review of 70+ sessions.
**How it was resolved:** Per-session try/except in `digest.build` (conversation, git, clipboard), defensive timestamp coercion (`_ms`), decode-safe subprocess output, and a last-resort CLI handler (one line, exit 1, documented in contracts/cli.md).

### FINDING-6: Digest validation did not check nested shapes
- **Severity:** Important · **Confidence:** 80 · **File:** roundup/lib/roundup/digest.py · **Category:** correctness · **Source:** codex (P2), also coderabbit (4 minors) · **Round:** 1 · **Resolution:** fixed (round 1, extended in rounds 2 and 3)

**What is wrong:** Non-object `workspace`, non-string `key`/`folder`, PR objects without `url`, numeric clipboard text passed validation and crashed later instead of exit 4.
**How it was resolved:** `_check_shapes` validates key/folder/workspace/kind/times/PR entries/clipboard method and text; round 2 added "key must equal provider:session_id" (actions select by key but target by provider/session) and string details; round 3 added string causes and `shared_folder.sessions`.

### FINDING-7: Bulk grep failure fanned out into one slow call per session
- **Severity:** Important · **Confidence:** 80 · **File:** roundup/lib/roundup/adapters/corgi.py · **Category:** production-readiness · **Source:** production-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** If the bulk `corgi grep` failed, every session ran its own grep with a 30 s timeout (worst case about 6 minutes for 100 sessions, SC-001).
**How it was resolved:** A failed bulk grep now marks all copies unknown with Corgi's error; no fan-out.

### FINDING-8: PR lookups unbounded under a slow GitHub
- **Severity:** Important · **Confidence:** 70 · **File:** roundup/lib/roundup/signals/pr.py, digest.py · **Category:** production-readiness · **Source:** production-agent · **Round:** 1 · **Resolution:** fixed (rounds 1 to 3)

**How it was resolved:** Circuit breaker after 3 lookup timeouts; deciding PRs are looked up before historical ones (in `pr_signal` and in the build pre-warm); resolved `gh` path; `gh auth status --hostname github.com`; try/finally so waiters never hang.

### FINDING-9: Whole tools copy parsed and kept in memory
- **Severity:** Important · **Confidence:** 70 · **File:** roundup/lib/roundup/signals/clipboard.py · **Category:** production-readiness · **Source:** production-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**How it was resolved:** Only lines that can be calls are parsed, and only the last call is kept.

### FINDING-10: Mixed-host PR links ordered by regex, not by text position
- **Severity:** Important · **Confidence:** 85 · **File:** roundup/lib/roundup/signals/conversation.py · **Category:** correctness · **Source:** codex (P2), also correctness-agent · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** All GitHub links got positions before all other-host links in a message, and `api.github.com` counted as "not GitHub", so the deciding PR could become "host not GitHub" (FR-012).
**How it was resolved:** Matches are sorted by offset before numbering; any `*.github.com` host is excluded from the other-host list.

### FINDING-11: Missing last-message timestamp borrowed from an earlier message
- **Severity:** Important · **Confidence:** 75 · **File:** roundup/lib/roundup/signals/conversation.py · **Category:** correctness · **Source:** codex (P2) · **Round:** 1 · **Resolution:** fixed (round 1)

**Why this matters:** For headless sessions (no change time) quiet time is measured from the last message (FR-016a); a borrowed older time could mark a session stale.
**How it was resolved:** First and last activity come from the first and last message's own timestamps; missing stays unknown.

### FINDING-12: Codex typed-fallback text contradicted the skill's hard rule
- **Severity:** Important · **Source:** coderabbit · **Round:** 1 (SKILL.md), 3 (README.md) · **Resolution:** fixed (rounds 1 and 3)

**How it was resolved:** SKILL.md and README.md now state that the review itself never types, name Corgi's fallback as the one known exception the spec accepts, and the skill warns the user before the first Codex follow-up.

### FINDING-13: Inherited GIT_DIR selectors (tests and production)
- **Severity:** Important · **File:** tests/helpers.py, roundup/lib/roundup/signals/git.py · **Source:** coderabbit · **Round:** 1 · **Resolution:** fixed (round 1)

**What is wrong:** `GIT_DIR`/`GIT_WORK_TREE` in the environment override `-C`; fixture creation could touch a real repository, and in production every folder would report the same repository.
**How it was resolved:** Selectors are stripped in both the test helpers and `signals/git.py`; `core.fsmonitor=false` added; test added.

### FINDING-14: US1 AS7 "upstream gone" note not asserted
- **Severity:** Important · **File:** tests/test_engine.py · **Source:** test-quality agent · **Round:** 1 · **Resolution:** fixed (round 1). Notes for upstream gone, detached HEAD and no remote are now asserted; the test helper uses the production `unfinished_status`.

### FINDING-15: Heredoc not bound to the clipboard tool
- **Severity:** Important · **Confidence:** 80 · **File:** roundup/lib/roundup/signals/clipboard.py · **Source:** re-review round 1, also coderabbit · **Round:** 2 · **Resolution:** fixed (rounds 2 and 3)

**What is wrong:** The first heredoc on the line was used even when it fed another command (`cat <<'A' >/dev/null; pbcopy <<'B'`, `cat <<EOF | sed ... | pbcopy`) and was marked exact.
**How it was resolved:** `_tool_heredoc` accepts only a single heredoc in the tool's own pipeline segment that either redirects the tool or feeds a bare `cat` piped straight into it; stdin redirects in the tool's own command (round 3) and several clipboard calls in one command make the text inexact.

### FINDING-16: Malformed Claude transcript record aborts gather
- **Severity:** Important · **File:** roundup/lib/roundup/adapters/corgi.py · **Source:** coderabbit · **Round:** 2 · **Resolution:** fixed (round 2)

### FINDING-17: Per-session grep fallbacks had no overall time bound
- **Severity:** Important · **File:** roundup/lib/roundup/adapters/corgi.py · **Source:** coderabbit · **Round:** 2 · **Resolution:** fixed (round 2; refined round 3). Shared 20 s budget, 10 s per-session timeout, late sessions become unknown, results guarded.

### FINDING-18: Deciding PR could be blocked by historical lookups tripping the breaker
- **Severity:** Important · **File:** roundup/lib/roundup/signals/pr.py · **Source:** coderabbit · **Round:** 2 · **Resolution:** fixed (round 2 in `pr_signal`, round 3 in the build pre-warm)

### FINDING-19: Digest key could name a different conversation than its target fields
- **Severity:** Important · **File:** roundup/lib/roundup/digest.py · **Source:** coderabbit · **Round:** 2 · **Resolution:** fixed (round 2)

### FINDING-20: Untracked files hidden by `status.showUntrackedFiles=no`
- **Severity:** Important · **File:** roundup/lib/roundup/signals/git.py · **Source:** coderabbit · **Round:** 3 · **Resolution:** fixed (round 3), `--untracked-files=normal`, test added.

### FINDING-21: Stdin redirect after the heredoc replaces the copied text
- **Severity:** Important · **File:** roundup/lib/roundup/signals/clipboard.py · **Source:** coderabbit · **Round:** 3 · **Resolution:** fixed (round 3), test added.

### FINDING-22: Fixture repositories inherit developer git template hooks
- **Severity:** Important · **File:** tests/helpers.py · **Source:** coderabbit · **Round:** 3 · **Resolution:** fixed (round 3), empty template dir and `core.hooksPath` for fixtures.

### FINDING-23: README guarantee vs. Codex fallback
- **Severity:** Important · **File:** README.md · **Source:** coderabbit · **Round:** 3 · **Resolution:** fixed (round 3), see FINDING-12.

### FINDING-24 (not fixed, out of scope): `.specify/spex.json` sets `security: yolo`
- **Severity:** Important (per CodeRabbit) · **File:** .specify/spex.json · **Source:** coderabbit (rounds 1 and 2) · **Resolution:** not fixed, out of scope

**What is wrong:** The shared spex declaration stores the unrestricted permission level, which a later spex refresh would apply for every contributor.
**Why not fixed:** `.specify/` is untracked tool configuration, not code under review, and the level is a deliberate user choice. Needs a decision before `.specify/` is ever committed.

### FINDING-25 (reclassified to NOTABLE-8): Corgi can still type a follow-up
- See NOTABLE-8.

## Notable Observations

### NOTABLE-1
- **File:** roundup/lib/roundup/adapters/corgi.py (transcript parsing, channel probes) · **Category:** architecture · **Source:** architecture-agent
- **Description:** Provider transcript formats and Claude/Codex home-directory probes live inside the Corgi adapter.
- **Rationale:** A second backend (plain Claude Code, tmux) would need the same provider logic; extract a provider-level module then.

### NOTABLE-2
- **File:** roundup/lib/roundup/adapters/corgi.py:31-33 · **Category:** security · **Source:** security-agent
- **Description:** The test override `ROUNDUP_CORGI` wins over `CORGI_APP_EXE` in production. No injection (argv lists only); defense in depth only.

### NOTABLE-3
- **File:** roundup/skills/roundup/SKILL.md (run directory) · **Category:** security · **Source:** security-agent
- **Description:** The 0700 run directory holds recent messages and clipboard drafts; only the agent's cleanup step removes it. A sweep of stale `roundup-*` directories at start would bound exposure after a crash.

### NOTABLE-4
- **File:** roundup/scripts/roundup, roundup/lib · **Category:** production-readiness · **Source:** production-agent
- **Description:** Python 3.9 compatibility confirmed (compileall and the suite pass under 3.9.6); no resource leaks found.

### NOTABLE-5
- **File:** tests/test_seeded_world.py · **Category:** test-quality · **Source:** test-quality agent
- **Description:** The confirmation flow (SC-003, US2 AS1/AS5, US3 AS4, US4 AS2) and the judged share of SC-004 live in SKILL.md and the real harness, so they are not under automated test.

### NOTABLE-6
- **File:** roundup/lib/roundup/adapters/corgi.py (workspace name) · **Source:** re-review round 1
- **Description:** Strict self-validation in `build` could abort on odd backend values; the workspace name is now normalized in the adapter.

### NOTABLE-7
- **File:** roundup/lib/roundup/signals/clipboard.py · **Source:** re-review round 2
- **Description:** Binding errs toward "no copy-back" for rare shapes (`{ cat <<EOF; } | pbcopy`, `cat - <<EOF | pbcopy`); all realistic agent shapes reconstruct exactly.

### NOTABLE-8 (reclassified from Important)
- **File:** roundup/lib/roundup/adapters/corgi.py (`message`) · **Category:** security / product · **Source:** coderabbit (round 3)
- **Description:** If the agent channel disappears between the pre-check and the send (Codex heartbeat, or a Claude inbox that vanishes), `corgi message` falls back to typing the text into the pane. The review detects and reports it as failed but cannot prevent it.
- **Rationale:** The spec's Assumptions accept this explicitly (Corgi offers no way to disable the fallback, and FR-030 forbids requiring a Corgi change). Making it strict needs a Corgi option such as `--no-type`. Product/architecture judgment.

## Goal Alignment

Skipped: no PR exists for branch 001-session-triage.

## Post-Fix Spec Coverage

The fix loop removed code only as dead-code cleanup (`digest.iter_sessions`, an unused local in `recheck`, a constant `_rank` slot). Every FR was rechecked against the code after the loop. FR-001 to FR-032 (with FR-016a) still have an implementation. The seeded-world and per-module tests pass.

All spec requirements verified after fix loop.

## Test Suite Results

| Round | Test Command | Exit Code | Tests | Status |
|-------|-------------|-----------|-------|--------|
| baseline | make test | 0 | 169 | passed |
| 1 | make test | 0 | 181 | passed |
| 2 | make test | 0 | 188 | passed |
| 2 (follow-up minors) | make test | 0 | 190 | passed |
| 3 | make test | 0 | 191 | passed |

Test suite passed in all fix rounds.

## Remaining Findings (Minor, not blocking)

All 23 remaining findings are Minor and mechanical unless marked otherwise:

- architecture: engine compares the free-text cause "conversation copy unreadable" (engine.py PR note); CLI maps generic `KeyError`/`ValueError` from render to exit 4/2; follow-up eligibility defined in both engine and cli; PR pre-warm duplicates `pr_signal`'s link selection; SKILL.md has no structured field to list "copy-back unavailable" sessions off macOS.
- security: `overview --format json` carries the full clipboard text into the agent context (could expose secrets in drafts).
- production: `read_conversation` keeps all rows in memory; SKILL.md gives no timeout guidance for `gather`; the fallback budget does not cap already-running greps (up to about 10 s over).
- test-quality: setUp/tearDown leak temp dirs on setup failure; missing output-level tests (caller note, gather exit 3, "other PRs", 99-session non-compact); several re-check paths (hibernation flip, pending requests, Codex live source, unreadable message reply); architecture test misses `adapters` imports.
- correctness: multi-line quoted strings and `\'` outside quotes can still yield a false clipboard `found` (no copy-back offered); here-string `<<<` or a redirect glued to the delimiter (`<<EOF<f`) escape the stdin guard; pre-warm still looks up PRs for sessions decided as "host not GitHub"; transcript path not type-checked and tail futures unguarded; `backend_state.changed_at_us` type not validated; non-object `message` result gives exit 1 instead of a failed outcome; recap fallback name and PR cause not flattened.
- regression tests missing for: build pre-warm order, string-cause and shared_folder validation, `_copy_from_row` non-string cache, malformed history reply.
- Not a bug: CodeRabbit "preserve the heredoc's final newline". The digest stores the body without it, and `clipboard_out.copy_back` appends the newline, so the clipboard receives the same bytes as the original heredoc.
