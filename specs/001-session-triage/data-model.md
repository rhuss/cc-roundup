# Data Model: Session Triage (roundup)

**Date**: 2026-11-22 | **Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

The wire formats are fixed in [contracts/digest-v1.md](contracts/digest-v1.md) and [contracts/judgments-v1.md](contracts/judgments-v1.md). This file describes the entities, their rules and how they relate.

## Entities

### Digest (backend-neutral snapshot, FR-003 to FR-006)

| Field | Type | Rule |
|---|---|---|
| `format` | `"roundup-digest"` | constant |
| `version` | integer | `1`; consumers reject other major versions |
| `generated_at` | ISO 8601 UTC | snapshot time; quiet time is measured to this instant (FR-016a) |
| `backend` | string | `"corgi"` |
| `options` | object | `archived` (bool), as requested for this run |
| `caller` | object | `pane` (id or null), `excluded` (bool), `cause` (string when not excluded) |
| `sessions` | Session[] | in-scope sessions, each exactly once |
| `folders` | map path → FolderState | git state per unique resolved folder |

### Session

| Field | Type | Rule |
|---|---|---|
| `key` | string | `PROVIDER:SESSION_ID`, unique within the digest |
| `provider`, `session_id`, `name` | string | from the backend |
| `kind` | `pane` \| `headless` | |
| `pane` | integer \| null | pane id (null for headless without a pane) |
| `headless_id` | string \| null | |
| `hibernated` | bool | |
| `workspace` | `{id, name, archived}` | |
| `folder` | string \| null | absolute, resolved with `realpath` when it exists |
| `agent_state` | `working` \| `starting` \| `blocked` \| `idle` \| `exited` \| `unknown` | mapping in research R4 |
| `backend_state` | object | raw values used for the re-check: `state`, `changed_at_us` |
| `changed_at` | ISO 8601 \| null | last change time |
| `first_activity_at`, `last_message_at` | ISO 8601 \| null | from the conversation copy |
| `conversation` | Signal-like `{status, cause}` | `found` when the copy was read |
| `messages` | Message[] (≤ 6) | last user or assistant messages, oldest first |
| `pr_links` | string[] | all PR links in the full conversation, most recent mention first |
| `also_open_in` | integer[] | other pane ids showing the same conversation (dedupe, research R3) |
| `signals` | Signals | see below |

### Message

`{role: "user"|"assistant", at: ISO|null, text: string (≤ 600 chars), cut: bool}`

### Signal (common shape, FR-007)

`{status: "found"|"not_found"|"unknown", cause?: string, ...detail}`. `cause` is required when `status == "unknown"`. Missing data is always `unknown`, never `not_found`.

### Signals

- `clipboard`: Signal plus `method` (`pbcopy` | `slack-pbcopy`), `args` (string), `text` (full text or null), `truncated` (bool), `at` (ISO), `first_line` (≤ 80 chars).
- `unfinished`: Signal plus `items[]`, each `{kind, status, detail, shared}` with `kind` in `checklist`, `uncommitted`, `unpushed`, `never_pushed`, `interrupted`. `shared: true` marks git items from a shared folder; they never make `unfinished.status` `found` on their own (FR-011).
- `shared_folder`: `{shared: bool, sessions: [keys]}`.
- `pr`: Signal plus `current` (`{url, state: "open"|"merged"|"closed"|null}` or null; `state` is null when the lookup of that link failed and `status` is `unknown`) and `others` (`[{url, state|null}]`).

### FolderState (per unique folder)

`{status, cause?, repo: bool, branch|null, detached: bool, dirty: bool|null, upstream: "ok"|"none"|"gone"|"detached"|"no_remote"|null, ahead: int|null}`.

### Judgments (agent-produced, never in the digest, FR-013)

Per session key: `unanswered_agent` (bool), `task_finished` (bool), `about` (≤ 100 chars), `stopped` (≤ 100 chars), `followup` (draft text or null), `judgment_note` (optional, ≤ 80 chars, quoted in the reason when a judged signal decides).

### Overview entry (computed, not persisted)

`{key, category, rule, reason, quiet_seconds, recap: [≤ 3 lines], action: {verb: "close"|"message"|"copyback"|null, preselected: bool, text?: string, method?: string}, addable_to_close: bool, notes: [string]}`.

### Action outcome

`{key, verb, outcome: "done"|"skipped"|"failed", reason?: string, delivery?: "message"|"typed"}`.

## Rules

### Category engine (FR-014 to FR-016a), first match wins

| Rule | Condition | Category | Reason template |
|---|---|---|---|
| 0 | `agent_state == blocked` | waiting on you | `approval pending` |
| 1 | `agent_state in {working, starting}` | waiting on others | `agent working` / `agent starting up` |
| 2 | `unanswered_agent` or `clipboard.found` or `unfinished.found` (non-shared items) | waiting on you | first applicable: `agent asked: <note>`, `clipboard copy never pasted`, `<item detail>` |
| 3 | `pr.current.state == open` | waiting on others | `PR open: <url>` |
| 4 | `pr.current.state in {merged, closed}` or `task_finished` | done, close it | `PR merged: <url>` / `PR closed: <url>` / `task finished: <note>` |
| 5 | otherwise | stale, decide | `quiet <duration>` plus `, stale` when quiet ≥ threshold |

Invariants:
- Rule 4 never fires when the agent is working, or the session's own non-shared folder has `uncommitted` or `unpushed`/`never_pushed` items `found` (FR-015). Such items already fire rule 2, so this is an assertion in code and tests.
- An `unknown` push state never blocks rule 4 (spec clarification of finding 2).
- Shared-folder git items append `; shared folder: <detail>` to the reason.
- Agent state `unknown` (raw state outside the mapping) never matches rules 0 or 1, never gets close preselected and never gets a follow-up; it stays `addable_to_close`, and its reason ends with `; agent state unknown`.
- A conversation that could not be read contributes no judged signals (`unanswered_agent = task_finished = false`), so it lands in stale unless a mechanical signal decides.
- Quiet time: `generated_at − changed_at`; if `changed_at` is null, `generated_at − last_message_at` and the reason adds `(from last message)`; if both are null, `quiet unknown`.

### Ordering (FR-017)

Category order: waiting on you, stale decide, waiting on others, done close it. Within a category: largest quiet time first; unknown quiet time last; ties by key.

### Action proposal (FR-020, FR-021, FR-024)

| Situation | Action | Preselected |
|---|---|---|
| done, close it | close | yes |
| rule 2 with `clipboard.found`, not truncated, platform macOS (also when hibernated or exited; FR-021 only bans follow-ups) | copyback | offered one by one |
| rule 2 with clipboard truncated or non-macOS | none; recap says why | — |
| other rule 2, pane live (not hibernated, not exited) | message (draft) | offered one by one |
| rule 0 | none | — |
| waiting on others | none | — |
| stale decide | none; `addable_to_close`, follow-up on request | no |
| hibernated or exited (any category except done), no copy-back | none; `addable_to_close` | no |
| agent state `unknown` | none; `addable_to_close` | no |
| headless | close = stop headless | as above |

### State transitions of a proposed action

`proposed → confirmed → (re-check) → done | skipped | failed`, or `proposed → declined`. No transition back to `proposed`; no retries (FR-026).
