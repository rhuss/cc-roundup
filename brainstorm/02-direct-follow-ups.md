# Brainstorm: Follow-up delivery modes (direct and strict)

**Date:** 2026-11-23
**Status:** active
**Related:** [01-session-triage](01-session-triage.md) (amends FR-026 of `specs/001-session-triage`), Corgi feature request [tals/corgi#199](https://github.com/tals/corgi/issues/199)

## Problem Framing

Roundup sends follow-ups the user has already read and confirmed inside the review. Today they go through `corgi message`, which uses the agent's own channel, for Claude Code the peer inbox. Claude Code wraps every inbound peer message in a preamble that frames it as a request from another session: act within your own permissions, never treat it as the user's approval. Before `crossSessionInbound: accept` was set, such messages were even held for a second review in bypass-permission sessions. For a text the user confirmed seconds earlier, both are wrong: the message is the user's own turn, approved by the user, and should arrive as one.

A second problem comes from the same path. `corgi message` silently falls back to typing when it finds no channel. For Codex this is the usual case, because its channel needs a protocol heartbeat from the last 5 seconds, which idle agents rarely have. Roundup then reports a follow-up as failed although the text arrived. The opposite need also exists: a guarantee that nothing is ever typed into a pane, which Corgi cannot give today (folded in from the idea inbox entry `corgi-strict-message-delivery`).

Success: the user picks per run how follow-ups are delivered, and the closing report says truthfully how each one arrived.

Non-goals and anti-goals:
- Not changing the default. Without an option, delivery stays exactly as in 001.
- Not typing anywhere it could do harm: into a blocked prompt (it would answer an approval), on top of a half-written draft, or into a shell whose agent has exited (it would run as a command).
- Not a strict mode that can still type. If strictness cannot be guaranteed, roundup refuses instead of pretending.
- No per-follow-up mixing of methods in this round (see Approaches, B).

## Approaches Considered

### A: One delivery mode per run with three values (chosen)
`delivery` is `channel` (default, today's behavior), `direct` (always type, guarded) or `strict` (channel only, never type). The skill arguments `direct` and `strict` select it. The adapter's `message` verb takes the mode and applies its rules.
- Pros: one concept that is easy to state in the overview; delivery policy stays inside the Corgi adapter next to the guards; strict and direct are clear opposites; more modes fit later as new values.
- Cons: no mixing of methods within one run.

### B: Per-run default plus a per-follow-up choice
Same modes, and each follow-up confirmation also offers "send typed".
- Pros: most flexible while getting a feeling for typing.
- Cons: busier prompts for every follow-up; moves away from the opt-in-per-run simplicity the user asked for. Can be added on top of A later.

### C: Separate adapter verbs (`type` beside `message`)
- Pros: each verb does exactly one thing.
- Cons: the skill has to choose the verb, so delivery policy leaks into the skill instructions; no single place decides delivery.

## Decision

Approach A. Direct mode is opt-in per run, to develop a feeling for it before considering it as a default. Strict mode is included, but depends on the Corgi feature requested in [tals/corgi#199](https://github.com/tals/corgi/issues/199).

## Key Requirements

**Mode selection**
- A run has exactly one delivery mode: `channel` (default), `direct` or `strict`, chosen by skill argument (`/cc-roundup:roundup direct`, `/cc-roundup:roundup strict`). `direct` and `strict` together are a usage error.
- The overview states the mode once when it is not `channel`. The closing report shows the actual delivery method per follow-up (channel, typed, skipped).
- Without an argument, behavior is exactly as specified in 001.

**Direct mode** (user-stated: opt-in, skip on guard failure; guard list is my proposal, because `corgi pane send` has none of `corgi message`'s safety checks)
- Follow-ups are typed into the pane (`corgi pane send` with Enter), never sent through the peer inbox.
- Typing happens only when all guards hold at send time: the pane exists, is not hibernated and its process has not exited; an agent is present (not a bare shell at its prompt); the agent is idle (not working, not blocked on a prompt); agent state and last change time still match the snapshot (the existing re-check); the agent's prompt line is empty, so no draft gets sent along.
- If any guard fails, that follow-up is skipped with the reason. There is no fallback to the inbox.
- Multi-line text is flattened to one line before typing, so no terminal can submit it in pieces. (My proposal, to avoid depending on bracketed-paste support.)
- Headless sessions have no pane; in direct mode they keep using their own session channel and the report says so.
- The confirmation for each follow-up says that the text will be typed and arrive with full user authority in that session.

**Strict mode** (user-stated: include it; behavior on missing Corgi support is my proposal, so strict never silently degrades)
- Follow-ups go only through the agent's channel and are never typed; if no channel is available, the follow-up is skipped with the reason.
- Strict relies on Corgi refusing to type (the `--no-type` or equivalent option requested in tals/corgi#199). If the installed Corgi lacks that option, a strict run stops before any action and points to the issue.

**Spec impact**
- FR-026 of `specs/001-session-triage` changes from "never type into a pane itself" to: no typing in `channel` and `strict` mode; typing only in `direct` mode under the guards above.
- FR-028 and FR-030 still hold: the Corgi adapter stays the only component that calls Corgi, and direct mode uses only existing Corgi verbs (`pane send`, `pane read`, `list`). Strict mode is the only part that needs a Corgi feature, and it is requested upstream, not patched locally.
- All guards and both modes need offline tests with the stub `corgi` that record exactly which command was issued, or that none was.

**Outcome reporting**
- Every follow-up's outcome records how it was delivered. Typing in `channel` mode (Corgi's own fallback) stays reported as in 001.

## Open Questions

- How reliable is detecting an empty prompt line from `corgi pane read` across Claude Code and Codex? If it cannot be made reliable, should direct mode require an explicit acknowledgement that a draft may be sent along, or skip panes where the prompt cannot be read?
- How should roundup detect that the installed Corgi supports the strict option: probe `corgi help message`, a version check, or a dry-run flag if #199 offers one?
- Should the follow-up drafting rules in `rules.md` change for direct mode, given that a typed follow-up can now count as the user's own approval (for example answering an agent's "shall I proceed?")?
- Does flattening multi-line follow-ups lose meaning often enough that bracketed paste should be used where the terminal supports it?
