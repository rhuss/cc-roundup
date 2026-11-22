# Research: Session Triage (roundup)

**Date**: 2026-11-22 | **Spec**: [spec.md](spec.md)

All findings below were verified read-only against a live Corgi runtime (custom build, protocol in `corgi list --json` `.result.protocol`) and its source (`src/agent_message.ts`, `src/grep_command.ts`, `src/headless.ts`, `src/runtime.ts`). Live counts at research time: 74 panes, 795 conversations, 34 live top-level agent panes (27 Claude, 7 Codex), 19 hibernated agent panes, 0 headless sessions.

## R1. Language of the gathering step

- **Decision**: Python 3 (3.9 or newer), standard library only. One package under `roundup/lib/roundup/`, one entry script `roundup/scripts/roundup`.
- **Rationale**: Gathering does real work: joining a 1.2 MB JSON reply, parsing JSONL conversation copies, extracting heredoc bodies from tool calls, running git and `gh` for about 35 folders in parallel, and a deterministic category engine that tests can pin to 100% on mechanical cases. Shell plus `jq` turns this into fragile string handling. Python's standard library covers JSON, subprocess, a thread pool and `unittest`, so the plugin adds no install step in either harness; `python3` is already a hard dependency of the spex tooling on the same machines.
- **Alternatives considered**:
  - *Bun/TypeScript* (matches Corgi): strong typing, fast, but adds a Bun requirement for every plugin user, and Corgi ships as a compiled binary, so users do not otherwise need Bun. The digest is the seam, so a later Ask Corgi `/triage` can consume the digest regardless of language.
  - *Shell plus `jq`*: no new runtime, but heredoc extraction, parallel lookups and a tested rule engine are hard to keep correct.

## R2. Which Corgi binary to call

- **Decision**: The adapter calls `$CORGI_APP_EXE` when set, else `corgi` on `PATH`. The binary is overridable with `ROUNDUP_CORGI` (used by tests to point at a stub).
- **Rationale**: Inside a pane, `corgi` is often a shell alias that scripts cannot see. The released `~/.local/bin/corgi` cannot talk to a custom-build daemon (exit 2, `JSON Parse error: Unexpected identifier "HTTP"`). `CORGI_APP_EXE` is set by Corgi in every pane and points at the matching build.

## R3. Session discovery (scope, FR-001, FR-002)

- **Decision**: One `corgi list --json` call (0.17 s). In scope:
  - panes with `agent.provider != null` in workspaces where `archived == false` (or any workspace with `--archived`), excluding the pane whose `id == $CORGI_PANE`;
  - headless sessions from `.result.headless_sessions[]` with `exited == false` and `corgi == false`.
- Panes always point at top-level conversations (no pane conversation has a `parent`), so subagents are excluded by construction. Ask Corgi helpers are exactly the headless sessions with `corgi: true`, which are excluded.
- Hibernated panes (`dormant == true`) in non-archived workspaces are in scope and marked hibernated. All panes in archived workspaces are dormant.
- Deduplication: the session key is `PROVIDER:SESSION_ID`. If one conversation appears more than once (open in two panes, or a headless session whose `pane` is also listed), exactly one entry is kept: a live pane beats a dormant pane, a pane beats a headless entry, then the lowest pane id wins. The other pane ids are recorded in `also_open_in` and shown as a note.
- Caller: `CORGI_PANE` matches `panes[].id` (same as `corgi current --json` `.result.pane`). If `CORGI_PANE` is unset or matches no pane, the digest records `caller.excluded = false` with a cause, and the skill says its own session could not be excluded (FR-001 fallback).
- **Rationale**: One call is fast and gives everything except conversation text.

## R4. Field mapping from `corgi list --json`

| Digest field | Corgi source |
|---|---|
| pane id | `panes[].id` |
| workspace id, name, archived | `panes[].workspace` joined to `workspaces[].id`, `.name`, `.archived` |
| provider, session id | `panes[].agent.provider`, `panes[].agent.session` |
| name | `panes[].agent.name` |
| folder | `panes[].agent.cwd`, falling back to `panes[].cwd` |
| raw state | `panes[].agent.state` (`unknown initializing idle working blocked done`), `panes[].agent.brand`, `panes[].exited`, `panes[].dormant` |
| last change time | `panes[].agent.changed_at` (microseconds since epoch) |
| hibernated | `panes[].dormant` |
| transcript path | `panes[].agent.transcript` |
| headless | `headless_sessions[]` (`provider`, `session`, `state`, `pending_requests`, `exited`, `corgi`, `pane`) |

Agent state mapping (FR-008), evaluated in this order:

1. `exited` when `pane.exited == true`, or `state == "done"`, or (`state == "unknown"` and `brand == null`) (agent quit back to its shell).
2. `blocked` when `state == "blocked"` (approval prompt or question), or for headless `pending_requests > 0`.
3. `working` when `state == "working"`.
4. `starting` when `state == "initializing"`.
5. `idle` when `state == "idle"`.
6. otherwise `unknown` with the raw value as cause.

A hibernated pane reports agent state `idle` for categorization and carries `hibernated: true` (its `unknown` state is an artifact of `Agent.historical()`).

Headless sessions have no `changed_at`. Their re-check compares `state`, `pending_requests` and `exited`; their quiet time uses the last-message fallback (FR-016a).

## R5. Conversation copy and recent messages (FR-005)

- **Decision**: One bulk call per run: `corgi grep --workspace '*' --max-age all --tools -l --json --limit 0 --max-output 0 .` Each output line is `{"source":{provider, account, session, cwd, updated_at, source, cache}}`; rows are matched to sessions by `provider` + `session`. Measured at 1.05 s warm and 7.9 s cold, within the 30 s gathering budget.
- For sessions missing from the bulk reply, a fallback per-session call `corgi grep --session PROVIDER:ID --tools -l --json .` (about 0.8 s) runs in the thread pool.
- The conversation copy at `source.cache` is JSONL, one object per message: `{"role":"user"|"assistant","timestamp":<ms|null>,"ref":"<source line>","text":"..."}`. Text is complete. Injected text (system reminders, `[Request interrupted…`, command wrappers) is already filtered out by Corgi.
- The tool copy `<cache minus .jsonl>.tools.jsonl` exists after a `--tools` search: `{"role":"tool","text":"...","timestamp":ms,"ref":"...","tool":{"kind":"call"|"result","name":"Bash","call_id":"...","status":"success"|"error"|"running"|"interrupted"|null,...}}`. A Bash call's text is `Bash\ncommand: <command>\ndescription: ...` with input keys in order.
- First activity time = timestamp of the first message in the copy. Last 6 user or assistant messages, each cut to 600 characters with `cut: true` marked.
- If no cache path is available or the file is unreadable, `conversation.status = "unknown"` with the cause; the session is still listed (spec edge case).
- **Side effect, accepted**: `grep --tools` makes Corgi write its own `.tools.jsonl` cache files under `~/.cache/corgi/conversation-grep-v2/`. This is Corgi's search cache, not a session, pane, repository or clipboard, so FR-004 holds.
- Conversation copies may be written while gathering runs: a trailing partial or malformed JSONL line is skipped, not fatal.
- **Alternatives considered**: per-session `grep --session` for every session (35 × 0.8 s ≈ 28 s sequential, too close to the budget); reading provider transcripts directly (duplicates Corgi's provider-specific normalization).

## R6. Forgotten clipboard detection (FR-009)

- **Decision**: In the tools copy, take the last `kind == "call"` entry. It is a forgotten clipboard when it is a `Bash` call whose command runs `pbcopy` or `slack-pbcopy`, and no `user` message in the conversation copy has a timestamp later than that call. Method = `slack-pbcopy` or `pbcopy` (plus `slack-pbcopy` flags such as `--tight`, kept verbatim).
- Text extraction: the `command:` value runs until the next line starting with a known input key (`description:`, `timeout:`, `run_in_background:`, `dangerouslyDisableSandbox:`). Within it, the heredoc body between `<<'TAG'` / `<<TAG` / `<<"TAG"` and the closing `TAG` line is the copied text. Piped forms (`printf ... | pbcopy`, `echo ... | pbcopy`) are not reconstructed.
- `truncated: true` (so no copy-back, FR-024) when the body cannot be extracted exactly: no heredoc, closing tag missing, or the call status is not `success`.
- Codex sessions: same rule on the Codex tool name for shell calls (`shell` / `exec_command`, matched by the presence of a `command:` key).
- Ordering: "no user message follows" compares timestamps; when either timestamp is null, it compares the source line numbers (`ref`), which share one transcript.
- Missing or unreadable tools copy: clipboard status `unknown` with cause, never `not_found` (FR-007).
- **Rationale**: The tools copy is complete text, so no raw transcript read is needed in the common heredoc case.

## R7. Unfinished work (FR-010)

- **Checklist**: lines matching `^\s*[-*] \[ \]` in the last assistant message.
- **Git** (per unique folder, parallel): `git --no-optional-locks -C <folder> status --porcelain=v2 --branch` gives dirty state, branch, upstream and ahead count in one call without a fetch. `--no-optional-locks` (also `GIT_OPTIONAL_LOCKS=0` in the environment) stops `git status` from taking `index.lock` and refreshing the index, so gathering never writes to a repository (FR-004) and never collides with a working agent's own git commands.
  - not a repository or folder missing: git status `unknown` with cause.
  - `# branch.head (detached)`: push state `unknown` ("detached HEAD").
  - no `# branch.upstream` line: if `git remote` is empty, push state `unknown` ("no remote"), else `found` ("branch never pushed").
  - upstream line present but the upstream ref is missing (`# branch.ab` absent): push state `unknown` ("upstream gone").
  - `# branch.ab +N -M` with N > 0: push state `found` ("N unpushed commits").
- **Interrupted last turn**: `corgi history --json --limit 1000` (0.15 s) gives `interrupted` per conversation. When a live session is missing from history (observed for 2 of 35 sessions), the adapter reads the tail of `pane.agent.transcript`: Claude, the last `type:"user"` record whose text starts with `[Request interrupted` and no later typed prompt; Codex, a `turn_aborted` event after the last prompt. If neither source answers, `interrupted` is `unknown` with the cause.
- **Shared folder** (FR-011): sessions whose folder resolves (`realpath`) to the same absolute path. Git findings for a shared folder are recorded with `shared: true` and only add a note.

## R8. Pull request state (FR-012)

- **Decision**: During gathering, scan the full conversation copy (all messages, not just the last 6) for `https://github.com/<owner>/<repo>/pull/<n>` links; record them in order of last mention. The most recent decides. Look up each unique PR once with `gh pr view <url> --json state,mergedAt,closed` in the thread pool.
- `unknown` causes: `gh` not on PATH ("gh missing"), `gh auth status` fails ("gh not signed in"), only non-GitHub PR-like links ("host not GitHub"), lookup error (message).
- No PR links: status `not_found`.

## R9. Sending follow-ups without typing (FR-026, FR-030)

- **Finding**: `corgi message pane:ID` tries the agent's own channel first (Claude: peer inbox socket listed in `<account>/sessions/*.json`; Codex: the app-server WebSocket). If no channel exists, it falls back to typing (bracketed paste plus Enter). No flag disables this, and adding one would need a Corgi change (forbidden by FR-030).
- **Decision**: The adapter's `message` verb:
  1. Pre-checks the channel, mirroring Corgi's own lookup (`src/agent_message.ts`, `src/providers/*/index.ts`):
     - Claude: a session file in the account's `sessions/` directory (account dir from `agent.account`) with matching `sessionId`, `peerProtocol == 1` and a live `pid`.
     - Codex: the pane's `agent.observation.source == "protocol"` (per session; Claude panes show `hook` or `transcript`), the pane is neither dormant nor exited, the session id is a 36-character UUID, and the account's app-server control socket `<account dir or ~/.codex>/app-server-control/app-server-control.sock` exists (per account, so on its own it would pass for every Codex session). Corgi additionally requires a protocol heartbeat within the last 5 seconds (`agent.protocol_at`), which `corgi list --json` does not expose, so this pre-check is necessary but not sufficient.
     - Headless: always a channel (`delivery: "message"`).
     If the channel cannot be confirmed, the verb returns `skipped` with "agent channel not available; not typing into the pane" and does not call Corgi.
  2. Sends with `--json --stdin` and checks `result.delivery`. If Corgi reports `typed`, the outcome is `failed` with "Corgi typed the message into the pane (agent channel unavailable)".
- **Residual risk**: when the pre-check passes but Corgi still finds no channel (Codex heartbeat older than 5 s, or a race), Corgi types the text. The adapter cannot prevent this without a Corgi change; it reports it as a failure, never hides it. Resolved at review-plan (user decision 1a): FR-026 now forbids the review from typing itself and requires a typed fallback by the backend to be reported as failed; the Codex limitation is listed in the spec's Assumptions.

## R9a. Copy-back and the close batch (FR-025)

- **Decision** (user decision at review-plan): copy-back does not re-check the pane, because the text comes from the digest. It is skipped only when the same session was closed earlier in this run (the skill passes the closed keys). When a session with a pending copy-back is added to the close batch, the skill warns that closing it means its copy-back will be skipped later in the run.

## R10. Closing and resumability (FR-021, FR-027)

- `corgi pane close ID` kills the process, keeps an undo-close entry and leaves the transcript, so `corgi resume PROVIDER SESSION` and `corgi history` still work.
- Headless: `corgi headless stop PROVIDER SESSION`.
- Close of a hibernated pane uses `pane close` too (no wake needed).

## R11. Re-check before acting (FR-025)

- **Decision**: The adapter re-reads `corgi list --json` (0.17 s) before each action and compares the session's pane or headless entry, mapped agent state and `changed_at` with the digest. Mismatch returns `skipped` with what changed. Git and PR are not re-gathered.

## R12. Runtime unreachable (FR-032)

- `corgi list --json` exits 2 with empty stdout and stderr `{"ok":false,"err":"connect ENOENT <socket>"}`. The adapter raises with Corgi's `err` text; `roundup gather` exits 3 and prints it on stderr; the skill stops and shows it.

## R13. Locating plugin files from the skill (FR-031)

- **Decision**: The skill resolves the plugin root from its own base directory (Claude Code prints "Base directory for this skill"; Codex gives the `SKILL.md` path): `<skill dir>/../..`. The entry point is `<plugin root>/scripts/roundup`, which adds `<plugin root>/lib` to `sys.path` itself, so no install step or working-directory assumption is needed.

## R14. Holding the digest during a run (FR-004)

- **Decision**: `roundup gather` writes the digest to stdout only. The skill redirects it to a file under `${TMPDIR:-/tmp}/roundup-<random>/` (outside any repository), uses it for the run, and deletes the directory at the end of the run, including when the user stops early.
- **Rationale**: The digest for about 70 sessions is a few hundred KB; later steps (overview, actions) need it, and reading it fully into the conversation would waste context. Nothing persists between runs.

## R15. Judgment and the deterministic rule engine (FR-013 to FR-017)

- **Decision**: Judged signals come from the agent running the skill. It reads a compact per-session judge view (`roundup judge-view`, recent messages plus signal summaries, in pages of 20 sessions) and writes a judgments file: per session `unanswered_agent`, `task_finished`, a recap (`about`, `stopped`), and a draft follow-up. A deterministic `roundup overview` then applies the ordered rules, computes reasons and quiet times, sorts, and proposes actions. Judgments are never written into the digest.
- **Rationale**: Mechanical decisions become unit-testable at 100% (SC-004); only the two judged booleans and the recap text depend on the model.
