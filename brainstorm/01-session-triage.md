# Brainstorm: Session Triage

**Date:** 2026-11-21
**Status:** active
**Origin:** `corgi` repo, `brainstorm/03-session-triage.md`, plus the spec, clarifications and spec review from a first ship run there (branch `011-session-triage`, abandoned in favor of this repo, `cc-roundup`).

## Problem Framing

Over days and weeks, agent sessions pile up across Corgi workspaces (18 workspaces, 71 panes and 749 known conversations at the time of writing). Many are finished but never closed, some wait on an answer the user forgot, some hold a drafted message that was copied to the clipboard and never pasted. Today the only way to find out is to walk through every pane and remember.

The goal is a review that walks through all open top-level sessions, reminds the user what each one was about, sorts them by what they need, proposes the step that closes each thread, and carries out the steps the user confirms. Closing a done session kills its pane; the conversation stays resumable from `corgi history`.

Success: one sitting turns a cluttered set of workspaces into a short list of real open work, with dead panes gone and forgotten follow-ups surfaced.

Anti-goals:
- Acting without confirmation (closing panes, messaging agents, answering questions on the user's behalf).
- Category verdicts without a visible reason. The user's memory is the main judge; the review must jog it, not overrule it.
- Changing Corgi. `rhuss/corgi` is a fork of upstream Corgi; nothing here may require a Corgi change.

## Decision

A standalone repository, `cc-roundup`, packaged like the other `cc-*` plugins (layout as in `cc-review`): one plugin directory `roundup/` with native manifests for Claude Code (`.claude-plugin/plugin.json`) and Codex (`.codex-plugin/plugin.json`), skills under `roundup/skills/`, and a local development marketplace at the repo root. The plugin holds the skill, its category rules and a gathering script. Corgi is the first and only backend.

**Architecture: the digest is the seam.**
- **Corgi adapter**: the only code that calls Corgi (`corgi list --json`, `corgi grep --session`, `corgi pane close`, `corgi message`, `corgi headless stop`). It reads sessions and turns them into the digest, and it executes the action verbs.
- **Backend-neutral core**: git signals, `gh` PR lookups, clipboard detection, the digest format and the category rules only see the digest, never Corgi.
- **Action verbs**: the skill asks the adapter to `close` or `message` a session; it does not spell out Corgi commands itself.
- No plugin framework. A second backend (plain Claude Code sessions, tmux) later gets a second adapter, and the interface is extracted from what both need.

**Installation**: as a plugin, through the Claude Code or Codex plugin marketplace (`make install` / `make install-codex` from a clone, later via `cc-rhuss-marketplace`). The skill is `roundup` (`/cc-roundup:roundup` in Claude Code). It resolves its scripts and rules relative to the installed plugin directory, so it behaves the same in both harnesses. Nothing is built into Corgi.

**Later**: an Ask Corgi `/triage` built into Corgi could consume the same digest. Out of scope here.

## Requirements (carried over from the clarified spec)

**Scope and gathering**
- Top-level sessions only: no subagents, no Ask Corgi helper conversations, not the session the triage runs in.
- Non-archived workspaces only, unless the user asks for archived ones.
- One digest snapshot, built before any recap. Gathering is read-only and writes the digest to stdout only (the user may redirect it); nothing is saved in a repository or kept between runs.
- Per session: pane, workspace (ID and name), provider, session ID, name, folder, agent state, last change time, first activity time when known (first message in the conversation copy), and the last 6 user or assistant messages, each cut to at most 600 characters.
- Recent turns come from `corgi grep --session PROVIDER:ID`, whose header ends with the normalized conversation copy (JSONL: `role`, `timestamp`, `ref`, `text`; tool calls in the `.tools.jsonl` beside it).
- The digest has a documented, versioned format independent of presentation.

**Mechanical signals (computed by the gathering step, in the digest)**
Each signal has a status: found, not found, or unknown with a short cause. Missing data is never shown as clean.
- Agent state: working, starting up, blocked on an approval prompt, idle, exited.
- Forgotten clipboard: the last tool call copied text (`pbcopy` or `slack-pbcopy`) and no user message follows it. Keep the full text and the copy method. If the recorded text is truncated, copy-back is not offered.
- Unfinished work: open checklist items, uncommitted changes, unpushed commits, interrupted last turn. Unpushed is counted against the locally known upstream, no fetch; a branch without an upstream counts as found ("branch never pushed").
- Shared folder: when several sessions share one folder (typically a repo's main checkout), its git state only adds a note to each reason and does not decide the category.
- PR state: PR links in the conversation, state looked up with `gh` (open, merged, closed); unknown when `gh` is missing, not signed in, or the host is not GitHub. With several links, the most recently mentioned one decides; the others go into the recap.

**Judged signals (only in the category rules, not in the digest)**
- Unanswered agent: the last message is the agent's question, proposal or offer to continue, with no user reply.
- Task finished: the conversation shows that its task was completed.

**Categories**, each with a one-line reason naming the signal or conversation content behind it. First matching rule wins:
0. Agent blocked on an approval prompt: *waiting on you*, reason "approval pending", no follow-up (the user answers it in the pane).
1. Agent working or starting up: *waiting on others*.
2. Unanswered agent, forgotten clipboard or unfinished work (not counting shared-folder git state): *waiting on you*.
3. Open PR: *waiting on others*.
4. Merged or closed PR, or task finished: *done, close it*.
5. Anything else: *stale, decide*. The reason gives the quiet time and says "stale" once it reaches the threshold (default 3 days, adjustable per run).

A working agent, or a folder with its own uncommitted changes or unpushed commits, never lands in *done, close it*.

**Overview**: categories in the order *waiting on you*, *stale, decide*, *waiting on others*, *done, close it*; longest-quiet first within each. Recap per session in at most three lines: what it was about, where it stopped, how long it has been quiet; for a forgotten clipboard, the first line of the copied text (at most 80 characters).

**Actions**: at most one per session; nothing runs without confirmation in the current sitting.
- *done, close it*: close.
- Forgotten clipboard: copy-back (same method as the original copy), even when other unfinished work exists.
- Other *waiting on you*: follow-up message (for example "commit, push and open the PR"); the user can edit the text before it is sent.
- *waiting on others*: none.
- *stale, decide*: none preselected; the user can add it to the close batch or ask for a follow-up.
- Hibernated pane: no follow-up proposed, marked in the recap. Headless agent: close means `corgi headless stop`. Exited agent with a remaining shell: close offered, follow-up not.

**Confirmation order**: the close batch first (remove entries or add *stale, decide* ones, then confirm once), then follow-ups one by one, then copy-backs one by one (saying that a later copy replaces the clipboard).

**Execution**: before each action, re-check that the pane or headless session still exists and that agent state and last change time match the digest; git and PR signals are not re-gathered. On mismatch, skip and say why. Report each outcome (done, skipped, failed with reason); never retry automatically, never fall back to typing into a pane. Closed conversations stay resumable from `corgi history`.

**Edge cases**: no open sessions besides the caller (one line, nothing proposed); conversation copy not readable (session still listed with Corgi's data, limited recap, *stale, decide* unless another signal decides); folder not a git repo (git signals unknown); 100 or more sessions (grouped, compact, no per-session interaction while gathering); Corgi runtime not reachable (stop with Corgi's error).

**Success criteria**
- About 70 sessions to a categorized overview in under 2 minutes (manual check); gathering alone under 30 seconds.
- In a seeded world: every open top-level session exactly once, no subagents, helpers or caller; no action before confirmation; every session has a category and a reason.
- Seeded world of at least 10 sessions: 100% correct categories where mechanical signals decide, at least 9 of 10 where judgment is needed.
- All finished sessions closed with one confirmation; every closed session resumable from history.

**Testing**: the gathering step runs against recorded `corgi` output, git fixtures and stubbed `gh` and clipboard commands.

## Assumptions
- The triage runs from an agent in a Corgi pane with the `corgi` CLI and a shell; the Corgi runtime is running.
- `changed_at` from `corgi list` is a good enough proxy for when the user last touched a session.
- Clipboard copy-back targets macOS; elsewhere it reports itself unavailable.
- Interaction happens in the agent's normal conversation, not a dedicated UI.

## Open Questions
- Language of the gathering script (Bun/TypeScript to match Corgi, or a shell plus `jq` script)?
- Exact digest schema (field names, version field), to be fixed during planning.
