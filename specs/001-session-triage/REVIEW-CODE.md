# Code Review: Session Triage (roundup)

**Spec:** specs/001-session-triage/spec.md
**Date:** 2026-11-22
**Reviewer:** Claude (speckit.spex-gates.review-code + spex-deep-review)
**Scope:** uncommitted work on branch 001-session-triage: roundup/lib, roundup/scripts, roundup/skills, tests, docs, Makefile, README.md, CLAUDE.md, .gitignore

## Compliance Summary

**Overall Score: 98%** (52 of 53 checked items; 96% before the fix loop)

- Functional Requirements: 32/33 (FR-001 to FR-032 plus FR-016a)
- Edge Cases: 13/13
- Success Criteria (testable parts): 7/7
- Spec-declared constants: none (no `## Constants` section)

Remaining deviation:

- **FR-005 (minor, spec evolution candidate):** the digest's `pr_links` holds only GitHub pull request links. Links on other hosts are detected, and when one of them is the most recent mention it decides the PR state ("host not GitHub", FR-012). They are not listed in `pr_links`, though FR-005 says "all pull request links". The digest contract (contracts/digest-v1.md) documents GitHub-only. Recommendation: evolve FR-005 to "all GitHub pull request links" or add a `pr_links_other` field. This is a product decision.

Fixed during review:

- **FR-009 / FR-024:** copy-back could restore text that differed from the original (unquoted heredoc expansion, heredoc not bound to the tool, stdin redirects, if/else with two copies). The text is now kept only when it is provably exact; otherwise no copy-back is offered.

## Compliance Matrix (abridged)

| Area | Requirements | Implementation | Status |
|------|--------------|----------------|--------|
| Scope and gathering | FR-001 to FR-006 | adapters/corgi.py `discover`, `snapshot`; digest.py `build`, `validate`; cli.py `gather` | Compliant except FR-005 (above) |
| Mechanical signals | FR-007 to FR-012 | signals/git.py, signals/clipboard.py, signals/conversation.py, signals/pr.py, digest.py `unfinished_status` | Compliant |
| Judged signals and categories | FR-013 to FR-016a | engine.py `evaluate`, rules.md, SKILL.md step 6 | Compliant |
| Overview | FR-017 to FR-019 | engine.py sort, render.py `render_overview` (compact at 100) | Compliant |
| Actions and confirmation | FR-020 to FR-024 | engine.py action proposal, SKILL.md steps 8a to 8c, clipboard_out.py | Compliant |
| Execution | FR-025 to FR-027 | adapters/corgi.py `recheck`, `close`, `message`; cli.py `act`; clipboard_out.py | Compliant (FR-026 typed fallback reported as failed, as the spec's Assumptions accept) |
| Architecture and packaging | FR-028 to FR-032 | only adapters/corgi.py runs Corgi (tests/test_architecture.py); plugin-relative paths in scripts/roundup and SKILL.md; BackendError exit 3 | Compliant |
| Edge cases | 13 listed | empty roundup line, unreadable copy, non-git folder, 100+ compact, unreachable Corgi, shared folder, several PR links, PR lookup unavailable, never pushed, upstream gone/detached/no remote, caller unidentifiable, change between snapshot and action, archived | Compliant |

### Extra behavior (not in spec, judged helpful)

- `unknown` agent state (raw Corgi state not mapped): such sessions get no follow-up and no preselected close, but can be added to the close batch. FR-008 lists five states, so the spec could mention `unknown` explicitly.
- Checklist items written with `*` as well as `-`.
- Gathering time budget and gh circuit breaker: sessions that hit them become *unknown* with a cause (FR-007), to keep SC-001.

## Code Review Guide

Where a reviewer should look first:

1. `roundup/lib/roundup/signals/clipboard.py`: shell-command parsing for forgotten clipboards. It decides whether copy-back may run. Rule: when in doubt, `text: null` (no copy-back).
2. `roundup/lib/roundup/adapters/corgi.py`: the only Corgi caller. Read `recheck`, `close` and `message` for FR-025/FR-026, and `snapshot` for the read-only gathering and its time budget.
3. `roundup/lib/roundup/engine.py`: the rule order (FR-014) and the action proposal (FR-020/FR-021).
4. `roundup/skills/roundup/SKILL.md`: the confirmation order, the untrusted-data rule, and the file-based follow-up hand-off.
5. `tests/test_seeded_world.py` and `tests/test_actions.py`: end-to-end checks against stubbed Corgi, gh and clipboard tools.

## Deep Review Report

**Gate: PASS** (after fix round 3; final re-review found no Critical or Important issues)

| Severity | Found | Fixed | Remaining |
|----------|-------|-------|-----------|
| Critical | 0 | 0 | 0 |
| Important | 25 | 23 | 0 |
| Minor | 61 | 38 | 23 |
| Notable | 8 | - | 8 |

Important: 25 found, 23 fixed, 2 not fixed. One is out of scope (`.specify/spex.json` `security: yolo`, untracked tool configuration). The other was reclassified to Notable because the spec explicitly accepts it (Corgi's typing fallback for follow-ups, see "Needs judgment"). Full details are in `review-findings.md`.

### Review agents

| Agent | Found | Fixed | Remaining | Status |
|-------|-------|-------|-----------|--------|
| Correctness | 6 | 6 | 0 | completed |
| Architecture & Idioms | 13 | 7 | 5 (+1 Notable) | completed |
| Security | 8 | 5 | 1 (+2 Notable) | completed |
| Production Readiness | 10 | 7 | 2 (+1 Notable) | completed |
| Test Quality | 11 | 6 | 4 (+1 Notable) | completed |
| Goal Alignment | 0 | 0 | 0 | skipped (no PR found) |
| Re-review rounds 1 to 3 | 17 | 10 | 5 (+2 Notable) | completed |
| CodeRabbit (external, 4 passes) | 35 | 26 | 7 (+2 not fixed: out of scope / reclassified) | completed |
| Copilot (external) | 0 | 0 | 0 | skipped (disabled in config) |
| Codex (external) | 3 | 3 | 0 | completed |
| Test Suite (regression) | 0 | 0 | 0 | passed in every round |

Rows overlap where several sources reported the same issue. The severity table above is deduplicated.

MVP: Architecture & Idioms (13 findings)

### Key fixes applied

1. Clipboard detection: the tool is matched only in command position. The heredoc must be the tool's own input. Expanded, redirected or ambiguous text is never offered for copy-back (correctness, coderabbit, test-quality).
2. Prompt-injection hardening: an untrusted-data rule in SKILL.md and rules.md, and session-controlled text flattened in every view (security).
3. Follow-up text goes through a file, not a shell heredoc (security, coderabbit).
4. Gathering degrades per session instead of aborting: try/except per signal, defensive timestamps, malformed transcript and history replies, and a one-line internal-error exit (production, coderabbit).
5. Time bounds for SC-001: no per-session fan-out after a failed bulk grep, a shared 20 s fallback budget, a gh circuit breaker, and deciding PRs looked up first (production, coderabbit).
6. Strict digest validation of nested shapes, including key = provider:session_id so an action cannot target a different conversation (codex, coderabbit).
7. PR mention order across hosts, and last-message time no longer borrowed from older messages (codex, correctness).
8. Git isolation: inherited `GIT_DIR` selectors stripped, `core.fsmonitor=false`, untracked files always counted. The test fixtures no longer inherit template hooks (coderabbit, security).
9. Headless re-check matches the recorded headless id. Copy-back is still offered for sessions with an unknown agent state (security, correctness).
10. 22 new regression tests (169 to 191).

### Needs judgment (not fixed)

- **Corgi typing fallback** (product/architecture): `corgi message` types into the pane when the agent channel disappears after the pre-check. The review reports this as failed and warns the user before the first Codex follow-up, but cannot prevent it without a Corgi option (FR-030 forbids requiring a Corgi change). The spec's Assumptions accept it.
- **`.specify/spex.json` `security: yolo`** (project/tooling decision): this is outside the code under review. Decide before committing `.specify/`.
- **FR-005 scope** (spec evolution): whether `pr_links` should also list non-GitHub links.

### Remaining Minor findings

23 remaining, all mechanical. See the "Remaining Findings" section in `review-findings.md`.

Post-fix spec coverage: 33/33 functional requirements still implemented. No requirement was dropped.

Notable observations: 5 captured to brainstorm/idea-inbox.md.

Final `make test`: 191 tests, OK.
