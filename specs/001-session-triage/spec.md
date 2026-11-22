# Feature Specification: Session Triage (roundup)

**Feature Branch**: `001-session-triage`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Brainstorm document `brainstorm/01-session-triage.md` (session triage review across Corgi workspaces, packaged as the `roundup` skill of the cc-roundup plugin).

## Overview

Over days and weeks, agent sessions pile up across Corgi workspaces (18 workspaces, 71 panes and 749 known conversations at the time of writing). Many are finished but never closed, some wait on an answer the user forgot, and some hold a drafted message that was copied to the clipboard and never pasted. Today the only way to find out is to walk through every pane and remember.

The roundup review walks through all open top-level sessions, reminds the user what each one was about, sorts them by what they need, proposes the one step that closes each thread, and carries out only the steps the user confirms. Closing a done session ends its pane; the conversation stays resumable from Corgi's history.

The feature ships as a plugin (`roundup/`) for both Claude Code and Codex. Corgi is the first and only backend. All Corgi interaction is confined to one adapter; everything else works on a backend-neutral **digest**.

## Clarifications

### Session 2026-11-21

- Q: Which part of the conversation counts for "open checklist items"? → A: Only unchecked task-list items (`- [ ]`) in the last assistant message.
- Q: Does an agent's closing courtesy ("let me know if you need anything else") count as an unanswered agent? → A: No. Only a concrete question, a proposed next step, or an offer to do a named piece of work counts; generic courtesies do not.
- Q: When do sessions share a folder? → A: When their folders resolve to the same absolute path; different worktrees of one repository are different folders.
- Q: Can the user end the review without taking any action? → A: Yes. The user can stop at any step; declining or skipping a step runs nothing from it, and the review then reports what was and was not done.
- Q: What is a session's quiet time measured from? → A: From Corgi's last change time to the moment the snapshot was taken; when the last change time is missing, from the timestamp of the last message, and the reason says so.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See every open session, sorted by what it needs (Priority: P1)

The user starts the roundup from an agent running in a Corgi pane. The review gathers one snapshot of all open top-level sessions in non-archived workspaces, then shows an overview grouped into four categories (*waiting on you*, *stale, decide*, *waiting on others*, *done, close it*). Each session shows a short recap (what it was about, where it stopped, how long it has been quiet) and a one-line reason for its category.

**Why this priority**: The overview alone delivers the core value: the user sees in one place which threads still need them and which can go. Every later action depends on it.

**Independent Test**: Run the roundup against a seeded set of sessions (recorded Corgi output, git fixtures, stubbed PR and clipboard tools) and check that every open top-level session appears exactly once with a category and a reason, and that nothing is changed.

**Acceptance Scenarios**:

1. **Given** 12 open top-level sessions in 4 non-archived workspaces plus 3 subagent sessions, 1 helper conversation and the caller's own session, **When** the user starts the roundup, **Then** the overview lists exactly the 12 sessions, each once, each with a category and a one-line reason, and no action is taken.
2. **Given** a session whose agent is blocked on an approval prompt, **When** the overview is shown, **Then** it appears under *waiting on you* with reason "approval pending" and no follow-up is proposed.
3. **Given** a session whose agent is currently working, and whose folder also has uncommitted changes, **When** the overview is shown, **Then** it appears under *waiting on others*, never under *done, close it*.
4. **Given** a session whose most recently mentioned pull request is merged and whose folder is clean, **When** the overview is shown, **Then** it appears under *done, close it* with a reason naming the merged pull request.
5. **Given** a session with no deciding signal that has been quiet for 5 days, **When** the overview is shown with the default threshold, **Then** it appears under *stale, decide* and its reason gives the quiet time and the word "stale".
6. **Given** a session with no deciding signal that has been quiet for 2 hours, **When** the overview is shown with the default threshold, **Then** it appears under *stale, decide* and its reason gives the quiet time without the word "stale".
7. **Given** a session whose pull request is merged and whose local branch's upstream was deleted after the merge, with a clean working tree, **When** the overview is shown, **Then** it appears under *done, close it* and the push state is reported as unknown ("upstream gone").
8. **Given** several sessions in each category, **When** the overview is shown, **Then** categories appear in the order *waiting on you*, *stale, decide*, *waiting on others*, *done, close it*, and within each the longest-quiet session comes first.

---

### User Story 2 - Close all finished sessions with one confirmation (Priority: P2)

From the overview, the user is offered a close batch holding every *done, close it* session. They can drop entries from the batch or add *stale, decide* sessions to it, then confirm once. Each closed session's pane is ended (a headless agent is stopped); the conversation stays resumable from history.

**Why this priority**: Clearing finished sessions is the most common outcome of a roundup and the biggest source of clutter.

**Independent Test**: With a seeded set containing 4 done sessions and 2 stale ones, confirm a batch that drops one done session and adds one stale session; check that exactly 4 sessions are closed, each reported, and each still resumable from history.

**Acceptance Scenarios**:

1. **Given** an overview with 4 *done, close it* sessions, **When** the user confirms the close batch unchanged, **Then** all 4 are closed with a single confirmation and each outcome is reported.
2. **Given** a close batch, **When** the user removes one entry and adds one *stale, decide* session before confirming, **Then** exactly the edited batch is closed.
3. **Given** a session in the batch whose agent state or last change time differs from the snapshot when its turn comes, **When** the batch runs, **Then** that session is skipped with the reason, and the rest proceed.
4. **Given** a session in the batch that is a headless agent, **When** the batch runs, **Then** the headless agent is stopped instead of a pane being closed.
5. **Given** a close that fails, **When** the batch runs, **Then** the failure and its cause are reported, the action is not retried, and the other entries proceed.

---

### User Story 3 - Nudge agents that are waiting on the user (Priority: P3)

For each *waiting on you* session that is not blocked on an approval prompt and has no forgotten clipboard, the review proposes a follow-up message for the agent (for example "commit, push and open the PR"). After the close batch, follow-ups are presented one by one; the user can send, edit then send, or skip each.

**Why this priority**: Unblocks forgotten work, but each message needs individual judgment, so it comes after the batch close.

**Independent Test**: With a seeded session showing unpushed commits and an unanswered agent question, accept an edited follow-up and check that exactly the edited text reaches that session and nothing else is sent.

**Acceptance Scenarios**:

1. **Given** a *waiting on you* session with unpushed commits, **When** follow-ups are presented, **Then** a proposed message is shown that the user can edit before sending, and it is sent only after confirmation.
2. **Given** a session whose pane is hibernated, **When** follow-ups are presented, **Then** no follow-up is proposed for it and the recap marks it as hibernated.
3. **Given** a *waiting on you* session whose agent has exited but whose shell remains, **When** actions are proposed, **Then** no follow-up is proposed and the user can add the session to the close batch.
4. **Given** a *stale, decide* session, **When** the user asks for a follow-up for it, **Then** a follow-up is drafted and handled like any other.
5. **Given** a follow-up that cannot be delivered, **When** it is sent, **Then** the failure is reported and the review never falls back to typing into the pane.

---

### User Story 4 - Recover forgotten clipboard drafts (Priority: P4)

When a session's last tool call copied text to the clipboard and no user message followed, the review flags a forgotten clipboard, shows the first line of the copied text in the recap, and offers a copy-back using the same method as the original copy. Copy-backs come last, one by one, each saying that a later copy replaces the clipboard.

**Why this priority**: Rescues drafted messages that would otherwise be lost, but affects fewer sessions than the other stories.

**Independent Test**: With a seeded session whose last tool call was a rich-text clipboard copy and no later user message, accept the copy-back and check the stubbed clipboard tool received exactly the original text through the same method.

**Acceptance Scenarios**:

1. **Given** a session whose last tool call copied a drafted message and no user message follows, **When** the overview is shown, **Then** the session is *waiting on you*, its recap includes the first line of the copied text (at most 80 characters), and a copy-back is proposed even when the session also has other unfinished work.
2. **Given** two sessions with forgotten clipboards, **When** copy-backs are presented, **Then** each is offered separately and each prompt says that a later copy replaces the clipboard.
3. **Given** a forgotten clipboard whose recorded text is truncated, **When** actions are proposed, **Then** no copy-back is offered and the recap says why.
4. **Given** a machine that is not macOS, **When** a copy-back would be proposed, **Then** the review reports copy-back as unavailable instead of offering it.

---

### User Story 5 - Install once, run from either harness (Priority: P5)

The user installs cc-roundup from a plugin marketplace into Claude Code or Codex and starts the review with the `roundup` skill. The skill finds its own scripts and category rules relative to the installed plugin, so it behaves the same in both harnesses.

**Why this priority**: Required for distribution, but a developer can exercise stories 1 to 4 from a clone before packaging is polished.

**Independent Test**: Install the plugin from the local development marketplace into each harness and run the roundup against the seeded set; the overview matches across harnesses.

**Acceptance Scenarios**:

1. **Given** a clone of the repository, **When** the user runs the Claude Code install target, **Then** the `roundup` skill is available as `/cc-roundup:roundup`.
2. **Given** a clone of the repository, **When** the user runs the Codex install target, **Then** the `roundup` skill is available in Codex.
3. **Given** the plugin installed in an arbitrary directory, **When** the skill runs, **Then** it locates its gathering step and category rules without relying on the current working directory.

---

### Edge Cases

- **No other open sessions**: only the caller's session is open. The review says so in one line and proposes nothing.
- **Conversation copy unreadable**: the session is still listed with the data Corgi reports, gets a limited recap that says the conversation could not be read, and lands in *stale, decide* unless another signal decides.
- **Folder is not a git repository** (or is missing): git signals are reported as unknown with that cause, never as clean.
- **100 or more sessions**: the overview is grouped and compact, and gathering asks nothing per session.
- **Corgi runtime not reachable**: the review stops and shows Corgi's own error.
- **Shared folder**: several sessions share one folder (typically a repository's main checkout). Its git state adds a note to each session's reason but does not decide any session's category.
- **Several pull request links in one conversation**: the most recently mentioned one decides; the others are listed as a note below the recap (the recap itself stays at three lines).
- **Pull request lookup unavailable** (tool missing, not signed in, host not GitHub): pull request state is unknown with that cause.
- **Branch without upstream**: counts as unpushed work, reported as "branch never pushed".
- **Upstream gone, detached HEAD, or no remote**: push state is unknown with that cause and does not keep the session out of *done, close it*.
- **Caller's pane not identifiable**: every session is listed and the review says its own session could not be excluded.
- **Session changes between snapshot and action**: the action is skipped and the user is told what changed.
- **Archived workspaces**: excluded unless the user asks for them in that run.

## Requirements *(mandatory)*

### Functional Requirements

**Scope and gathering**

- **FR-001**: The review MUST consider only top-level agent sessions: it MUST exclude subagent sessions, helper conversations of Corgi's built-in assistant (Ask Corgi), and the session the review runs in (identified by the pane Corgi reports for the caller's environment). If the caller's pane cannot be identified, the review MUST still run, list every session, and say that its own session could not be excluded.
- **FR-002**: The review MUST include only non-archived workspaces by default, and MUST include archived workspaces when the user asks for them in that run.
- **FR-003**: The review MUST build one digest snapshot of all in-scope sessions before showing any recap, and all later recaps, categories and proposals MUST be based on that snapshot.
- **FR-004**: Gathering MUST be read-only: it MUST NOT change any session, pane, repository or clipboard, and MUST write the digest only to standard output. The review MUST NOT save anything in a repository or keep anything between runs.
- **FR-005**: For each session the digest MUST record: pane, workspace (identifier and name), provider, session identifier, session name, folder, agent state, hibernated marker, headless marker, last change time, first activity time when known (time of the first message in the conversation copy), the last 6 user or assistant messages, each cut to at most 600 characters, and all GitHub pull request links found anywhere in the full conversation copy, in order of last mention (links on other hosts only make pull request state unknown, see FR-012).
- **FR-006**: The digest MUST follow a documented, versioned format that carries a format version and is independent of how the overview is presented.

**Mechanical signals (computed during gathering, recorded in the digest)**

- **FR-007**: Every mechanical signal MUST carry a status of *found*, *not found*, or *unknown* with a short cause. Missing or unreadable data MUST NOT be reported as *not found*.
- **FR-008**: Agent state MUST be one of: working, starting up, blocked on an approval prompt, idle, exited, or unknown (a backend state outside this list, kept with the raw value as cause). A session with an unknown agent state matches neither rule 0 nor rule 1, never gets an action preselected or a follow-up proposed, and can be added to the close batch by the user.
- **FR-009**: Forgotten clipboard MUST be *found* when the session's last tool call copied text to the clipboard (plain copy or rich-text copy for chat apps) and no user message follows it. The digest MUST keep the full copied text, the copy method, and whether the recorded text is truncated.
- **FR-010**: Unfinished work MUST be *found* when any of these hold: unchecked task-list items (`- [ ]`) in the last assistant message, uncommitted changes in the folder, commits not yet pushed to the locally known upstream (no network fetch), a branch that has no upstream ("branch never pushed"), or an interrupted last turn. The digest MUST say which of these applied. Push state MUST be *unknown* with the cause, never *found*, when the upstream branch is gone ("upstream gone", typically after a merged pull request deleted it), HEAD is detached ("detached HEAD"), or the repository has no remote ("no remote"). An *unknown* push state MUST NOT keep a session out of *done, close it*; uncommitted changes still do.
- **FR-011**: When several in-scope sessions share one folder (their folders resolve to the same absolute path; different worktrees of one repository are different folders), the digest MUST mark the folder as shared, and that folder's git state MUST only add a note to each session's reason and MUST NOT decide any session's category.
- **FR-012**: Pull request state MUST be derived from the pull request links recorded in the digest (taken from the full conversation copy during gathering), looked up as open, merged or closed. When several links exist, the most recently mentioned one MUST decide and the others MUST be kept for the recap. The state MUST be *unknown* with a cause when the lookup tool is missing, not signed in, or the host is not GitHub.

**Judged signals and categories**

- **FR-013**: The category rules MUST evaluate two judged signals from the conversation content: *unanswered agent* (the last message is the agent's concrete question, proposed next step, or offer to do a named piece of work, with no user reply; generic closing courtesies such as "let me know if you need anything else" do not count) and *task finished* (the conversation shows its task was completed). Judged signals MUST NOT be stored in the digest. Judged signals and recaps MUST use only digest fields (session name, first activity time, the recent messages, signal details); the review MUST NOT read the full conversation copy after gathering.
- **FR-014**: The review MUST assign every session exactly one category using these rules in order, the first match winning:
  0. Agent blocked on an approval prompt: *waiting on you*, reason "approval pending", no follow-up proposed.
  1. Agent working or starting up: *waiting on others*.
  2. Unanswered agent, forgotten clipboard, or unfinished work (excluding git state of a shared folder): *waiting on you*.
  3. Open pull request: *waiting on others*.
  4. Merged or closed pull request, or task finished: *done, close it*.
  5. Anything else: *stale, decide*.
- **FR-015**: A session whose agent is working, or whose own (non-shared) folder has uncommitted changes or unpushed commits, MUST NOT be placed in *done, close it*.
- **FR-016**: Every session MUST show a one-line reason naming the signal or conversation content behind its category. For *stale, decide*, the reason MUST give the quiet time and MUST contain the word "stale" once the quiet time reaches the stale threshold; below the threshold the reason gives the quiet time without the word "stale". The threshold defaults to 3 days and can be set per run as a skill argument (for example `stale=7d`).
- **FR-016a**: Quiet time MUST be measured from the session's last change time to the moment the snapshot was taken. When the last change time is missing, it MUST be measured from the timestamp of the last message, and the reason MUST say so.

**Overview**

- **FR-017**: The overview MUST list categories in the order *waiting on you*, *stale, decide*, *waiting on others*, *done, close it*, and within each category the longest-quiet session first.
- **FR-018**: Each session's recap MUST be at most three lines: what it was about, where it stopped, how long it has been quiet. For a forgotten clipboard, the recap MUST include the first line of the copied text, cut to at most 80 characters. A hibernated pane MUST be marked in its recap.
- **FR-019**: With 100 or more sessions, the overview MUST stay grouped by category but show one line per session (name, workspace, quiet time, reason), with full recaps only on request, and gathering MUST NOT ask the user anything per session.

**Actions and confirmation**

- **FR-020**: The review MUST propose at most one action per session: *done, close it* gets close; a forgotten clipboard gets copy-back when the session is categorized *waiting on you* under rule 2 (even when other unfinished work exists), and no copy-back is proposed for sessions decided by rules 0 or 1; other *waiting on you* sessions get a follow-up message, except approval-pending ones; *waiting on others* gets none; *stale, decide* gets none preselected, but the user can add it to the close batch or ask for a follow-up.
- **FR-021**: Hibernated panes and exited agents with a remaining shell MUST be categorized by the normal rules. The review MUST NOT propose a follow-up for them; instead the user can add them to the close batch, and their close is preselected only when they are *done, close it*. For a headless agent, close MUST mean stopping the headless agent.
- **FR-022**: The review MUST NOT run any action without the user's confirmation given in the current sitting. The user MUST be able to stop at any step; declining or skipping a step runs nothing from it, and the review then reports what was and was not done.
- **FR-023**: Confirmation MUST follow this order: first the close batch (the user may remove entries or add *stale, decide* sessions and the hibernated or exited sessions of FR-021, then confirms once); then follow-ups one by one, each editable before sending; then copy-backs one by one, each stating that a later copy replaces the clipboard.
- **FR-024**: Copy-back MUST use the same copy method as the original copy and MUST NOT be offered when the recorded text is truncated or when the platform is not macOS (reported as unavailable).

**Execution**

- **FR-025**: Before each close or follow-up, the review MUST re-check, through the adapter's read path, that the pane or headless session still exists and that its agent state and last change time match the digest. Git and pull request signals MUST NOT be re-gathered. On mismatch, the action MUST be skipped with the reason. Copy-back does not need a live pane (its text comes from the digest); it MUST only be skipped when that session was closed earlier in the same run, and the review MUST warn when a session with a pending copy-back is added to the close batch.
- **FR-026**: The review MUST report each action's outcome as done, skipped (with reason) or failed (with reason). It MUST NOT retry automatically and MUST NOT type into a pane itself. When the agent's own channel cannot be confirmed beforehand, the follow-up MUST be skipped. If the backend nevertheless falls back to typing, the outcome MUST be reported as failed with that cause.
- **FR-027**: Closed sessions MUST remain resumable from Corgi's history.

**Architecture and packaging**

- **FR-028**: The Corgi adapter MUST be the only component that talks to Corgi. It reads sessions into the digest, re-reads a single session for the pre-action re-check, and executes the action verbs *close* and *message*. The skill MUST request actions through these verbs and MUST NOT run Corgi commands itself; it may name Corgi commands to the user as information (for example how to resume a closed conversation).
- **FR-029**: Git signals, pull request lookups, clipboard detection, the digest format and the category rules MUST work only on the digest (or the session's folder and conversation as referenced by it) and MUST NOT depend on Corgi.
- **FR-030**: This feature MUST NOT require a change to Corgi.
- **FR-031**: The feature MUST ship as the `roundup` skill in the `roundup/` plugin directory, with native manifests for Claude Code and Codex, installable from a plugin marketplace (and from a clone via the existing install targets), and MUST resolve its scripts and rules relative to the installed plugin directory.
- **FR-032**: If the Corgi runtime is not reachable, the review MUST stop and show Corgi's error.

### Key Entities

- **Session**: one open top-level agent conversation in a pane or headless agent. Attributes: pane, workspace, provider, session identifier, name, folder, agent state, last change time, first activity time, recent messages, hibernated or headless markers.
- **Digest**: the versioned snapshot of all in-scope sessions with their mechanical signals, produced once per run. The seam between the Corgi adapter and the backend-neutral core.
- **Signal**: a mechanical observation about a session (agent state, forgotten clipboard, unfinished work, shared folder, pull request state) with status *found*, *not found* or *unknown* plus cause and supporting detail.
- **Category**: one of *waiting on you*, *stale, decide*, *waiting on others*, *done, close it*, assigned with a one-line reason.
- **Proposed action**: at most one per session: close, follow-up message (editable text), or copy-back (text plus method).
- **Action outcome**: done, skipped or failed, with reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With about 70 open sessions, the user gets from starting the roundup to a categorized overview in under 2 minutes (manual check); gathering alone takes under 30 seconds.
- **SC-002**: In a seeded world, every open top-level session appears exactly once, and no subagent, helper conversation or caller session appears.
- **SC-003**: In a seeded world, no action runs before the user confirms it, and every session has a category and a reason.
- **SC-004**: In a seeded world with labelled expected categories, 100% of categories are correct for sessions decided by mechanical signals, and at least 90% are correct across at least 10 sessions whose category depends on judgment.
- **SC-005**: All finished sessions are closed with a single confirmation, and every closed session can be resumed from history afterwards.
- **SC-006**: The gathering step's tests run entirely against recorded Corgi output, git fixtures and stubbed pull request and clipboard tools, with no live Corgi runtime, network or real clipboard.
- **SC-007**: The action verbs (*close*, *message*), copy-back, and the re-check skip path are tested against stubbed Corgi and clipboard commands that record what they receive, confirming the exact commands issued and that a mismatch issues none.

## Assumptions

- The roundup runs from an agent in a Corgi pane that has the Corgi command line tool and a shell, and the Corgi runtime is running.
- Corgi exposes the caller's pane to processes in that pane through the environment (`CORGI_PANE`), which is how the caller's own session is excluded.
- Corgi's per-session last change time is a good enough proxy for when the user last touched a session.
- Recent turns are available through Corgi's per-session search, whose output points to a normalized copy of the conversation (one message per line with role, timestamp, reference and text, and tool calls in a companion file).
- Clipboard copy-back targets macOS; elsewhere it reports itself unavailable.
- Corgi's message command types the text into the pane when it finds no agent channel, and offers no way to turn that off. For Codex sessions the review can confirm the channel only approximately (Corgi also requires a recent protocol heartbeat that it does not expose), so a follow-up to a Codex session can occasionally end up typed; it is then reported as failed. Making this strict would need a Corgi change, which is out of scope.
- Interaction happens in the agent's normal conversation, not in a dedicated user interface.
- `git` and `jq` are available; `gh` is optional (pull request state becomes unknown without it).
- The language of the gathering step and the exact digest field names are decided during planning.
- A second backend (plain Claude Code sessions, tmux) is out of scope; the adapter interface will be extracted when one is added. An Ask Corgi `/triage` built into Corgi is out of scope.
