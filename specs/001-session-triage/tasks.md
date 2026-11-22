# Tasks: Session Triage (roundup)

**Input**: Design documents from `specs/001-session-triage/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. The spec requires offline tests against recorded Corgi output, git fixtures and stubbed `gh`/clipboard commands (SC-006) and recorded-command tests for actions (SC-007). Tests in each story are written first and must fail before the implementation task that follows.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5 from spec.md
- Paths are relative to the repository root. Python code: `roundup/lib/roundup/`; entry point: `roundup/scripts/roundup`; tests: `tests/`.

Reference material for the Corgi formats: research.md R3 to R12 and contracts/corgi-adapter.md. Redacted real samples (optional, may not exist later) were captured at `/private/tmp/claude-501/-Users-rhuss-Development-context-engineering-cc-roundup/29f99c01-06c4-430e-82ab-3299a395e10d/scratchpad/fixtures-sample/`; fixtures committed to the repository MUST be synthetic (no real conversation text, no real paths under a home directory other than `/Users/me` or `/home/me`).

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create the package layout from plan.md: `roundup/lib/roundup/__init__.py`, `roundup/lib/roundup/adapters/__init__.py`, `roundup/lib/roundup/signals/__init__.py`, `roundup/skills/roundup/` (remove `roundup/skills/.gitkeep`), `tests/__init__.py`, `tests/stubs/`, `tests/fixtures/corgi/`, `tests/fixtures/world/`
- [X] T002 Create the entry point `roundup/scripts/roundup` (executable, `#!/usr/bin/env python3`): resolve its own real path, insert `<plugin root>/lib` into `sys.path`, require Python ≥ 3.9 (exit 2 with a clear message otherwise), call `roundup.cli.main()`
- [X] T003 [P] Add a `test` target to `Makefile` running `python3 -m unittest discover -s tests -t .` and list it in the `help` target; add `.PHONY` entry
- [X] T004 [P] Add `__pycache__/` and `*.pyc` to `.gitignore`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared test harness, time handling, digest I/O and CLI skeleton used by every story.

- [X] T005 [P] Write `tests/helpers.py`: `StubEnv` context manager that creates a temp dir, writes stub executables (from `tests/stubs/`) into a `bin/` dir prepended to `PATH`, sets `ROUNDUP_CORGI` to the stub `corgi`, sets `ROUNDUP_STUB_FIXTURES` and `ROUNDUP_STUB_LOG`, and exposes `invocations()` (list of `{argv, stdin}` parsed from the log); `make_git_repo(path, *, dirty=False, ahead=0, upstream="ok"|"none"|"gone", detached=False, remote=True)` that builds a real git repository with a local bare remote, no network
- [X] T006 [P] Write stub `tests/stubs/corgi` (Python): append `{"argv":..., "stdin":...}` as one JSON line to `$ROUNDUP_STUB_LOG`; answer from `$ROUNDUP_STUB_FIXTURES/corgi/` by a key derived from argv (`list.json`, `grep-bulk.jsonl`, `grep-session-<provider>-<id>.jsonl`, `history.json`, `message-reply.json`, `close-reply.json`, `headless-stop-reply.json`); support `ROUNDUP_STUB_CORGI_FAIL=unreachable` (exit 2, stderr `{"ok":false,"err":"connect ENOENT /nonexistent"}`)
- [X] T007 [P] Write stubs `tests/stubs/gh`, `tests/stubs/pbcopy`, `tests/stubs/slack-pbcopy` (Python): all log argv and stdin like T006; `gh` answers `auth status` (exit from `ROUNDUP_STUB_GH_AUTH`, default 0) and `pr view <url> --json ...` from `$ROUNDUP_STUB_FIXTURES/gh/<owner>-<repo>-<n>.json`
- [X] T008 [P] Implement `roundup/lib/roundup/timefmt.py`: `us_to_iso(us)`, `ms_to_iso(ms)`, `parse_iso`, `parse_duration("3d"|"12h"|"30m")` (raise `ValueError` otherwise), `format_duration(seconds)` as `"5d 3h"`/`"2h 10m"`/`"4m"`; with tests in `tests/test_timefmt.py`
- [X] T009 Implement `roundup/lib/roundup/digest.py` per contracts/digest-v1.md: constants `FORMAT = "roundup-digest"`, `VERSION = 1`; `load(path)` that rejects unknown versions with `unsupported digest version N` (raise `InputError`); `validate(doc)` checking required fields, `status` in `found|not_found|unknown`, `cause` present for `unknown`, `messages` at most 6 with `text` at most 600 characters; `dump(doc, stream)`; with tests in `tests/test_digest.py`
- [X] T010 Implement `roundup/lib/roundup/cli.py` skeleton with `argparse` subcommands `gather`, `judge-view`, `overview`, `act close`, `act message`, `copyback` (handlers raise `NotImplementedError` until their story), and exit-code mapping per contracts/cli.md: `0` success, `2` usage, `3` `BackendError` (print the backend's message on stderr), `4` `InputError`; define `BackendError` and `InputError` in `roundup/lib/roundup/__init__.py`

**Checkpoint**: `make test` runs (timefmt and digest tests pass).

---

## Phase 3: User Story 1 - See every open session, sorted by what it needs (Priority: P1) 🎯 MVP

**Goal**: `roundup gather` builds the digest read-only; the skill judges, then `roundup overview` shows the categorized overview with reasons and recaps. No actions yet.

**Independent Test**: seeded world through stubs → every open top-level session exactly once with category and reason; stub logs show only read-only Corgi commands.

### Tests for User Story 1 (write first, must fail)

- [X] T011 [P] [US1] Create synthetic Corgi fixtures in `tests/fixtures/corgi/` following research R3 to R5: `list.json` (`{ok, result:{workspaces, panes, conversations, headless_sessions, closed_panes}}`) with at least: 2 non-archived and 1 archived workspace; live Claude and Codex panes in states `idle`, `working`, `initializing`, `blocked`; one `state:"unknown", brand:null` exited pane; one `dormant:true` hibernated pane; the caller pane; a conversation with `parent` set (subagent); one headless session `corgi:true` (Ask Corgi helper) and one `corgi:false`; matching `grep-bulk.jsonl` rows `{"source":{provider,account,session,cwd,updated_at,source,cache}}`, conversation copies `<hash>.jsonl` (`{"role","timestamp"(ms),"ref","text"}`), tools copies `<hash>.tools.jsonl` (`{"role":"tool","text","timestamp","ref","tool":{"kind","name","call_id","status"}}`), and `history.json` (`{"ok":true,"conversations":[{provider,session,interrupted,...}]}`)
- [X] T012 [P] [US1] Write `tests/test_adapter_corgi.py` (snapshot part): scope rules (non-archived only; `--archived` includes archived; caller excluded via `CORGI_PANE`; caller not identifiable → `caller.excluded == false` with a cause and caller listed; subagent and Ask Corgi helper never present); state mapping table from research R4 (`working`, `starting`, `blocked`, `idle`, `exited`, `unknown` with cause; hibernated → `idle` plus `hibernated: true`; headless `pending_requests > 0` → `blocked`); interrupted from history, transcript-tail fallback, else `unknown`; per-session grep fallback when the bulk reply misses a session; dedupe when one conversation is open in two panes or a headless session's `pane` is also listed (one entry per key: live pane beats dormant pane, pane beats headless, then lowest pane id; others in `also_open_in`); unreachable runtime raises `BackendError` with `connect ENOENT /nonexistent`; stub log contains only `list`, `grep`, `history` invocations
- [X] T013 [P] [US1] Write `tests/test_conversation.py`: last 6 user/assistant messages oldest first, each "cut to at most 600 characters" with `cut: true`; first activity = first message timestamp; PR links from the whole copy normalized to `https://github.com/OWNER/REPO/pull/N`, most recent mention first, deduplicated; non-GitHub PR-like links recorded for the `host not GitHub` cause; checklist items = lines matching `^\s*[-*] \[ \]` in the last assistant message only; unreadable copy → `conversation.status == "unknown"` with cause; a trailing partial or malformed JSONL line is skipped, not fatal
- [X] T014 [P] [US1] Write `tests/test_clipboard.py` (detection part): last tool call `slack-pbcopy <<'EOF'` with no later user message → `found`, method `slack-pbcopy`, args kept (`--tight`), exact heredoc body, `first_line` cut to "at most 80 characters"; later user message → `not_found`; plain `pbcopy`; `<<EOF` and `<<"EOF"` variants; missing closing tag, piped `echo x | pbcopy`, or call status not `success` → `found` with `truncated: true` and `text: null`; command value ends at the next input key line (`description:`, `timeout:`, `run_in_background:`, `dangerouslyDisableSandbox:`); tools copy missing or unreadable → `unknown` with cause, never `not_found`; null timestamps → ordering by `ref` line numbers
- [X] T015 [P] [US1] Write `tests/test_git_signals.py` using `make_git_repo`: clean; dirty → `uncommitted` found; ahead 2 → `unpushed` found "2 unpushed commits"; no upstream with remote → `never_pushed` found "branch never pushed"; upstream gone → push `unknown` "upstream gone"; detached → `unknown` "detached HEAD"; no remote → `unknown` "no remote"; not a repository and missing folder → git `unknown` with cause; shared folder (two sessions, same `realpath`, including a symlinked path) → items marked `shared: true`; two worktrees of one repo → not shared; gathering leaves `.git/index` mtime and content unchanged and creates no `index.lock` (FR-004)
- [X] T016 [P] [US1] Write `tests/test_pr_signals.py`: open/merged/closed via stub `gh`; most recent link decides, others listed; `gh` missing from PATH → `unknown` "gh missing"; `auth status` failing → `unknown` "gh not signed in"; only non-GitHub links → `unknown` "host not GitHub"; lookup error → `unknown` with the error; no links → `not_found`; each unique PR looked up once
- [X] T017 [P] [US1] Write `tests/test_engine.py` covering every row of the data-model.md rule table and invariants: rule 0 reason "approval pending" and no action; working with dirty folder → waiting on others, never done; rule 2 variants (unanswered, clipboard, each unfinished kind); shared-folder git only adds "; shared folder: ..." and does not decide; open PR; merged PR with upstream gone → done; task finished; stale below threshold → reason has quiet time without "stale"; at/above threshold → contains "stale"; `--stale 7d` changes the threshold; quiet time from `changed_at`, fallback "(from last message)", "quiet unknown"; unreadable conversation → stale unless a mechanical signal decides; category order waiting on you, stale decide, waiting on others, done close it, longest quiet first, unknown quiet last; action table (close preselected for done; copyback only for rule 2; follow-up for other rule 2 live panes; none for rule 0, waiting on others; stale and hibernated/exited sessions `addable_to_close`, never preselected unless done; rule-2 clipboard sessions get copyback even when hibernated or exited); agent state `unknown` → no rule 0/1 match, no preselected close, no follow-up, `addable_to_close`, reason ends `; agent state unknown`; malformed judgments JSON, unknown version or unknown key → `InputError` (CLI exit 4); headless session quiet time uses the last-message fallback
- [X] T018 [P] [US1] Write `tests/test_render.py`: `judge-view` pages of 20 with footer `page N of M`; overview text shows categories in order, each session with reason and at most three recap lines (about, stopped, quiet), clipboard first line, "hibernated" marker; with 100 or more sessions one line per session (name, workspace, quiet time, reason); empty digest → one line "No open sessions besides this one." and no actions; `--format json` emits overview entries per data-model.md; `--key K` prints that session's full entry; invalid `--stale` exits 2 with `invalid duration: <value> (use Nd, Nh or Nm)`
- [X] T019 [P] [US1] Create the seeded world in `tests/fixtures/world/`: Corgi fixtures and git repo specs for at least 12 top-level sessions plus a subagent, an Ask Corgi helper and the caller; `expected.json` labelling each session's category, rule and whether the decision is mechanical or judged, with at least 10 judgment-dependent sessions (SC-004); `judgments.json` per contracts/judgments-v1.md
- [X] T020 [US1] Write `tests/test_seeded_world.py`: run `roundup gather` then `roundup overview --judgments` as subprocesses under `StubEnv`; assert every top-level session appears exactly once, none of the excluded ones, 100% of labelled categories match, every session has a reason, and the stub log contains no mutating Corgi command (`pane close`, `message`, `headless stop`, `pane send`, `pane keys`) and no clipboard invocation (SC-002, SC-003, SC-004 mechanical part)
- [X] T021 [P] [US1] Write `tests/test_architecture.py`: scan `roundup/lib/roundup/**/*.py`; only `adapters/corgi.py` may reference `CORGI_APP_EXE`, `ROUNDUP_CORGI` or invoke a `corgi` binary (FR-028, FR-029)

### Implementation for User Story 1

- [X] T022 [US1] Implement `roundup/lib/roundup/adapters/corgi.py` `snapshot(archived)` per contracts/corgi-adapter.md and research R2 to R7, R12: binary resolution `ROUNDUP_CORGI` → `CORGI_APP_EXE` → `corgi`; `list --json`; scope and caller rules; dedupe by key (research R3); state mapping; bulk `grep --workspace '*' --max-age all --tools -l --json --limit 0 --max-output 0 .` with per-session fallback `grep --session P:ID --tools -l --json .` (exit 1 = no conversation → cause); `history --json --limit 1000` for `interrupted`, transcript-tail fallback (Claude: last `type:"user"` record text starting `[Request interrupted` with no later typed prompt; Codex: `turn_aborted` after the last prompt); timeouts 30 s; `BackendError` with Corgi's `err` text on failure
- [X] T023 [P] [US1] Implement `roundup/lib/roundup/signals/conversation.py` per T013 (reads copy paths provided by the snapshot; never calls Corgi). Interface: `read_conversation(copy_path) -> Conversation` with fields `status`, `cause`, `messages` (last 6, cut), `first_activity_at`, `last_message_at`, `pr_links`, `non_github_pr_links`, `checklist_items`, `user_message_refs` (list of `(timestamp_ms|None, ref)`)
- [X] T024 [P] [US1] Implement forgotten-clipboard detection in `roundup/lib/roundup/signals/clipboard.py` per research R6 and T014 (shell tool names for Claude `Bash`, Codex calls identified by a `command:` key). Interface: `detect_clipboard(tools_path, user_message_refs) -> dict` returning the digest `signals.clipboard` object
- [X] T025 [P] [US1] Implement `roundup/lib/roundup/signals/git.py` per research R7 and T015: one `git --no-optional-locks -C <folder> status --porcelain=v2 --branch` per unique folder (environment also sets `GIT_OPTIONAL_LOCKS=0`; plus `git remote` when no upstream), 10 s timeout → `unknown` "timeout", folders keyed by `os.path.realpath`. Interface: `folder_state(path) -> dict` (digest FolderState) and `git_items(folder_state, shared) -> list[dict]` (unfinished items)
- [X] T026 [P] [US1] Implement `roundup/lib/roundup/signals/pr.py` per research R8 and T016: `gh pr view <url> --json state,mergedAt,closed`, 15 s timeout, one lookup per unique URL. Interface: `pr_signal(pr_links, non_github_links, lookup) -> dict` and `make_lookup() -> Callable[[str], str|Exception]` (cached, thread-safe, with the `gh missing` / `gh not signed in` checks done once)
- [X] T027 [US1] Implement digest assembly in `roundup/lib/roundup/digest.py` `build(snapshot, archived) -> dict` (calls only the T023 to T026 interfaces and adapter data): run conversation, clipboard, git (thread pool `max_workers=8`) and PR lookups; compute `unfinished` items and status exactly as in contracts/digest-v1.md "Field rules" (push causes `upstream gone`, `detached HEAD`, `no remote` never raise status); `shared_folder`; `generated_at` = snapshot time; output validates with `validate()`
- [X] T028 [US1] Wire `roundup gather [--archived]` in `roundup/lib/roundup/cli.py`: digest to stdout only, timings to stderr only with `ROUNDUP_DEBUG=1`, exit 3 on `BackendError`; no file writes anywhere (FR-004)
- [X] T029 [US1] Implement `roundup/lib/roundup/engine.py` per data-model.md. Interface: `load_judgments(path, digest) -> dict`, `evaluate(digest, judgments, stale_seconds, platform=sys.platform) -> list[OverviewEntry]` (entries as in data-model.md "Overview entry", already ordered). Behavior: load judgments (contracts/judgments-v1.md; unknown keys → `InputError`; missing key → both judged signals false), ordered rules 0 to 5 with reason templates, FR-015 invariant assertion, quiet time and stale threshold (FR-016, FR-016a), category ordering (FR-017), action proposals (FR-020, FR-021), copy-back availability (`sys.platform == "darwin"`, text not truncated)
- [X] T030 [US1] Implement `roundup/lib/roundup/render.py` and wire `judge-view` and `overview` in `cli.py` per contracts/cli.md and T018 (recap at most three lines; clipboard first line at most 80 characters; compact mode at 100 or more sessions; `--key K` full entry). Interface: `render_judge_view(digest, page, page_size) -> str`, `render_overview(entries, fmt, key=None) -> str`
- [X] T031 [US1] Write `roundup/skills/roundup/rules.md`: how to judge `unanswered_agent` (concrete question, proposed next step, or offer to do a named piece of work; generic courtesies such as "let me know if you need anything else" do not count) and `task_finished`; how to write `about`/`stopped` (one line, at most 100 characters each), `judgment_note` (at most 80 characters) and `followup` drafts; worked examples for each
- [X] T032 [US1] Write `roundup/skills/roundup/SKILL.md` (frontmatter `name: roundup`, description, argument hint `[archived] [stale=3d]`) with the overview part of the flow: resolve the plugin root from the skill's base directory (`<skill dir>/../..`, research R13); parse skill arguments (`archived` → `gather --archived`; `stale=<d>` → `overview --stale <d>`, validated before gathering, invalid value reported with the usage hint; unknown words reported and ignored); create a run dir with `mktemp -d "${TMPDIR:-/tmp}/roundup-XXXXXX"`; run `gather` into it; on exit 3 stop and show Corgi's error verbatim; on an empty digest print one line and stop; tell the user when its own session could not be excluded; read `judge-view` page by page and write `judgments.json` following `rules.md`; run `overview` and show it (in compact mode, offer full recaps via `overview --key`); never change anything in this part; end every review, including an early stop, with a closing report listing what was done, skipped, failed and not reached (FR-022); delete the run dir when the review ends or the user stops

**Checkpoint**: US1 delivers a read-only categorized overview; `make test` green.

---

## Phase 4: User Story 2 - Close all finished sessions with one confirmation (Priority: P2)

**Goal**: one confirmed close batch; re-check before each close; per-session outcomes.

**Independent Test**: seeded world with 4 done and 2 stale; edited batch (drop one done, add one stale) → exactly 4 recorded close commands, outcomes reported.

### Tests for User Story 2 (write first, must fail)

- [X] T033 [P] [US2] Write `tests/test_actions.py` (close part): `act close` re-checks via `list --json` then issues exactly `pane close <ID>`; headless session issues `headless stop <PROVIDER> <SESSION>`; pane gone, state changed or `changed_at` changed → `skipped` with what changed and no close command; Corgi error → `failed` with Corgi's message, no retry (single invocation in the log); hibernated pane closes with `pane close`; outcome JSON line shape per contracts/cli.md

### Implementation for User Story 2

- [X] T034 [US2] Implement `recheck(session)` and `close(session)` in `roundup/lib/roundup/adapters/corgi.py` per contracts/corgi-adapter.md and research R10, R11 (timeout 15 s, no retry, never `pane send`/`pane keys`)
- [X] T035 [US2] Wire `roundup act close --digest FILE --key KEY` in `roundup/lib/roundup/cli.py` printing one outcome line `{"key","verb":"close","outcome":"done|skipped|failed","reason"}` (exit 0 for every outcome)
- [X] T036 [US2] Extend `roundup/skills/roundup/SKILL.md` with the close-batch step: list preselected *done, close it* sessions; let the user remove entries and add *stale, decide*, hibernated or exited sessions marked `addable_to_close`; confirm once; run `act close` per entry; report each outcome; mention that closed conversations stay resumable via `corgi history` / `corgi resume`; declining the batch closes nothing; if `act` exits 3 mid-batch (runtime unreachable), stop the batch, report the remaining entries as not run with Corgi's error, and do not retry

**Checkpoint**: US1 + US2 work independently of US3 and US4.

---

## Phase 5: User Story 3 - Nudge agents that are waiting on the user (Priority: P3)

**Goal**: follow-ups one by one, editable, sent only through the agent's own channel.

**Independent Test**: seeded session with unpushed commits; accept an edited follow-up → stub log has exactly one `message pane:<ID> --stdin --json` with the edited text.

### Tests for User Story 3 (write first, must fail)

- [X] T037 [P] [US3] Extend `tests/test_actions.py` (message part): Claude channel confirmed (fixture account dir with `sessions/<x>.json` holding matching `sessionId`, `peerProtocol: 1`, `pid` of the test process) → `message pane:<ID> --stdin --json` with the exact text on stdin, outcome `done`, `delivery: "message"`; no peer file, dead pid or protocol mismatch → `skipped` "agent channel not available; not typing into the pane" and no Corgi call; Codex: `agent.observation.source == "protocol"`, pane not dormant or exited, 36-character session id and existing `app-server-control/app-server-control.sock` → sends; socket present but source not `protocol` → skipped; any other condition failing → skipped; reply `delivery: "typed"` → `failed` "Corgi typed the message into the pane (agent channel unavailable)"; headless → `message headless:<ID>`; re-check mismatch → skipped; hibernated or exited sessions never get `act message` (CLI refuses with `skipped`)

### Implementation for User Story 3

- [X] T038 [US3] Implement the channel pre-check and `message(session, text)` in `roundup/lib/roundup/adapters/corgi.py` per research R9 (account dir from `agent.account`; Codex default `~/.codex`; send with `--stdin --json`; inspect `result.delivery` and `queued`)
- [X] T039 [US3] Wire `roundup act message --digest FILE --key KEY` (text from stdin; empty text → exit 2) in `roundup/lib/roundup/cli.py`
- [X] T040 [US3] Extend `roundup/skills/roundup/SKILL.md` with the follow-up step after the close batch: one session at a time, show the drafted text, let the user send, edit then send, or skip; offer a follow-up for a *stale, decide* session when the user asks; never propose one for approval-pending, hibernated or exited sessions; report the outcome including skips for missing channels

---

## Phase 6: User Story 4 - Recover forgotten clipboard drafts (Priority: P4)

**Goal**: copy-back one by one with the original method, after follow-ups.

**Independent Test**: seeded `slack-pbcopy --tight` session; accept the copy-back → stub `slack-pbcopy` received `--tight` and exactly the original text.

### Tests for User Story 4 (write first, must fail)

- [X] T041 [P] [US4] Extend `tests/test_clipboard.py` (copy-back part): `copyback` runs the recorded method with recorded args and the exact text on stdin, without any Corgi call (no pane re-check, research R9a), also for hibernated or exited sessions; KEY listed in `--closed` → `skipped` "session was closed earlier in this run", no clipboard call; truncated → `skipped` "copied text was truncated", no clipboard call; non-macOS (patch `sys.platform`) → `failed` "copy-back is only available on macOS"; tool missing from PATH → `failed` naming the tool

### Implementation for User Story 4

- [X] T042 [US4] Implement `roundup/lib/roundup/clipboard_out.py` (backend-neutral, never calls Corgi, no pane re-check per research R9a). Interface: `copy_back(session_entry, closed_keys: set[str], platform=sys.platform) -> Outcome`; wire `--closed KEY ...` and wire `roundup copyback --digest FILE --key KEY` in `roundup/lib/roundup/cli.py`
- [X] T043 [US4] Extend `roundup/skills/roundup/SKILL.md` with the copy-back step last (and add to the close-batch step from T036 a warning when a session with a pending copy-back is added to the batch): pass the keys closed in this run as `--closed`; one at a time, show the first line, state that a later copy replaces the clipboard, run `copyback` only on confirmation, report outcomes; on non-macOS say copy-back is unavailable instead of offering it

---

## Phase 7: User Story 5 - Install once, run from either harness (Priority: P5)

**Goal**: plugin installs in Claude Code and Codex; the skill finds its files from any directory.

**Independent Test**: `make validate`; run the entry point from an unrelated working directory; install targets list the skill.

- [X] T044 [P] [US5] Add `tests/test_packaging.py`: `roundup/scripts/roundup --help` runs from a temp working directory via an absolute path and via a symlink to it; `roundup/skills/roundup/SKILL.md` has frontmatter `name: roundup` and a description; `roundup/.codex-plugin/plugin.json` `skills` points at `./skills/`; the versions in `VERSION`, `roundup/VERSION`, `.claude-plugin/marketplace.json` and both plugin manifests are equal
- [X] T045 [US5] Ensure `roundup/.claude-plugin/plugin.json` and `roundup/.codex-plugin/plugin.json` expose the skill (add fields only if `claude plugin validate` or the Codex manifest requires them) and run `make validate`
- [X] T046 [US5] Make sure `SKILL.md` refers to the entry point only through the resolved plugin root and never assumes the current directory, and that it works when the harness gives the skill path instead of printing a base directory (Codex)

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T047 [P] Update `README.md`: status, usage (`/cc-roundup:roundup [archived] [stale=7d]`), what each category means, confirmation order, the Codex follow-up caveat from research R9, requirements (`python3` 3.9+ added), `make test`
- [X] T048 [P] Document the digest for other consumers in `docs/digest.md` (copy of contracts/digest-v1.md adapted for users, plus versioning rules)
- [X] T049 Run quickstart.md sections 1, 2 and 5 and record results in `specs/001-session-triage/VALIDATION.md`; run section 3 (live, read-only `gather`) when a Corgi runtime is reachable and record session count and gathering time against the 30 s budget (SC-001); judged accuracy (SC-004): have the agent judge the seeded world's `judge-view` without seeing `judgments.json`, compare with `expected.json`, record the percentage (target at least 90%); list quickstart section 4 (harness installs, 2-minute end-to-end overview, resumability after close, overview parity across harnesses) as a manual check for the user, since it changes live panes
- [X] T050 Update `CLAUDE.md` project structure with `roundup/scripts/`, `roundup/lib/`, `tests/` and the `make test` command

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → US1 (Phase 3). US1 is the MVP and blocks the others because it provides gather, digest and engine.
- US2, US3, US4 each depend only on US1 and on T034 `recheck` (US3 and US4 reuse it; if run in parallel, implement T034's `recheck` first).
- US5 depends on US1 (a skill to package) and can run in parallel with US2 to US4.
- Polish after all stories.
- Within a story: tests → adapter/signal modules → digest/engine → CLI wiring → SKILL.md.

## Parallel Opportunities

- Phase 1: T003, T004.
- Phase 2: T005, T006, T007, T008 in parallel; then T009, T010.
- US1 tests T011 to T019 and T021 in parallel; implementations T023 to T026 in parallel after T022 starts the adapter shape.
- After US1: US2 (T033 to T036), US3 (T037 to T040), US4 (T041 to T043) and US5 (T044 to T046) can proceed in parallel once `recheck` (T034) exists.

## Implementation Strategy

1. MVP: Phases 1 to 3 give a read-only roundup that already answers "what needs me?".
2. Add US2 (biggest clutter reduction), then US3, then US4.
3. US5 hardening and Polish last; run quickstart before review.
