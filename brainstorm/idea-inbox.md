# Idea Inbox

Ideas captured from code reviews for future brainstorming.

### provider-parsing-module

- **Source**: deep-review
- **Date**: 2026-11-22
- **Reference**: 001-session-triage
- **Summary**: Provider transcript parsing (Claude/Codex) and agent-channel probes live inside the Corgi adapter, although they do not talk to Corgi.

> A second backend (plain Claude Code sessions, tmux) would need the same provider logic. Extract a provider-level module when that backend is added, and keep the adapter contract (`BackendSnapshot.interrupted`) stable.

### stale-run-directory-sweep

- **Source**: deep-review
- **Date**: 2026-11-22
- **Reference**: 001-session-triage
- **Summary**: The run directory holds recent messages and clipboard drafts. Only the agent's own cleanup step removes it.

> After a crashed or killed session, the data stays in `$TMPDIR/roundup-*` until the OS cleans it up. Sweeping stale run directories at the start of each run would bound the exposure.

### skill-flow-contract-tests

- **Source**: deep-review
- **Date**: 2026-11-22
- **Reference**: 001-session-triage
- **Summary**: The confirmation order, the single batch confirmation and the clipboard-replacement wording live only in SKILL.md and are not under automated test.

> A packaging-level test could check that SKILL.md contains the required order and wording. A harness-level eval could cover the judged share of SC-004 (at least 90% correct).

### test-only-binary-override

- **Source**: deep-review
- **Date**: 2026-11-22
- **Reference**: 001-session-triage
- **Summary**: The test override `ROUNDUP_CORGI` takes precedence over `CORGI_APP_EXE` in production code.

> There is no injection risk, because only argv lists are used. Still, a test-only switch that picks the binary for destructive verbs could be gated behind an explicit test flag.
