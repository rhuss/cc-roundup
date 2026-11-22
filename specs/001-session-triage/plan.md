# Implementation Plan: Session Triage (roundup)

**Branch**: `001-session-triage` | **Date**: 2026-11-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-session-triage/spec.md`

## Summary

A `roundup` skill in the roundup plugin walks through every open top-level agent session in Corgi, recaps it, puts it into one of four categories with a visible reason, proposes one closing step, and runs only what the user confirms. A Python command line tool (`roundup/scripts/roundup`, standard library only) does the mechanical work: a Corgi adapter builds a versioned digest in one read-only snapshot, backend-neutral signal modules add git, PR and clipboard findings, and a deterministic category engine turns the digest plus the agent's judgments into the overview. The skill (`roundup/skills/roundup/SKILL.md`) drives the conversation: gather, judge, show, confirm in the fixed order, act, report.

## Technical Context

**Language/Version**: Python 3.9+ (standard library only), research R1

**Primary Dependencies**: Corgi CLI (`$CORGI_APP_EXE`), `git`; optional `gh`, `pbcopy`, `slack-pbcopy`

**Storage**: None persistent. The digest and judgments live in a per-run temporary directory deleted at the end of the run (research R14)

**Testing**: `unittest` via `make test`; stub executables on `PATH` for `corgi`, `gh`, `pbcopy`, `slack-pbcopy`; git fixture repositories created in temporary directories

**Target Platform**: macOS (primary, clipboard copy-back) and Linux (copy-back reported unavailable); Claude Code and Codex harnesses

**Project Type**: Agent plugin: a skill plus a command line tool

**Performance Goals**: Gathering under 30 s for about 70 sessions (one `list`, one bulk `grep`, one `history`, git and `gh` lookups in a thread pool of 8); overview under 2 minutes including judgment

**Constraints**: No Corgi changes (FR-030); gathering is read-only; no action without confirmation; never type into a pane (research R9 residual risk for Codex)

**Scale/Scope**: About 35 to 100+ live sessions; 1.2 MB `corgi list` reply; conversation copies up to several MB each (only the tail and PR links are kept)

## Global Constraints

Every task must respect these:

- Gathering is read-only and writes the digest to stdout only; nothing is kept between runs (FR-004). Git runs with `--no-optional-locks`.
- No Corgi change (FR-030). Only `adapters/corgi.py` runs Corgi (FR-028).
- No action without confirmation in the current sitting; no automatic retries; never `pane send` or `pane keys` (FR-022, FR-026).
- Python 3.9+ standard library only; no third-party packages.
- Limits: last 6 messages, 600 characters each; clipboard first line 80 characters; `about`/`stopped` 100 characters; `judgment_note` 80 characters; recap at most 3 lines; compact overview at 100 or more sessions; judge-view pages of 20.
- Stale threshold default `3d`; durations `Nd`, `Nh`, `Nm`.
- Copy-back only on macOS (`sys.platform == "darwin"`).
- Every signal is `found`, `not_found` or `unknown` with a cause; missing data is never `not_found` (FR-007).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the unfilled template, so there are no ratified principles to check. The project guidelines in `CLAUDE.md` serve as gates instead:

| Gate (CLAUDE.md) | Status |
|---|---|
| Single `roundup/` plugin directory with Claude Code and Codex manifests | Pass: skill under `roundup/skills/roundup/`, tool under `roundup/scripts/` and `roundup/lib/` |
| Only the Corgi adapter calls the `corgi` CLI; everything else works on the digest | Pass: `adapters/corgi.py` is the only module that runs Corgi (contract `corgi-adapter.md`); a test asserts no other module references the binary |
| Version kept in sync across `VERSION`, `roundup/VERSION`, marketplace and both manifests | Pass: no version bump in this feature beyond what `make validate` checks |
| `make validate` before committing manifest changes | Pass: manifests change only if the skill needs registration (Codex already points at `./skills/`) |

Post-design re-check: Pass. No violations, so Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-session-triage/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1 to R15
├── data-model.md        # Phase 1: entities, category engine, action rules
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── digest-v1.md     # Digest format, version 1
│   ├── judgments-v1.md  # Agent judgments file
│   ├── cli.md           # roundup subcommands and exit codes
│   └── corgi-adapter.md # Adapter interface and test stub
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
roundup/
├── scripts/
│   └── roundup                  # entry point; adds ../lib to sys.path
├── lib/
│   └── roundup/
│       ├── __init__.py
│       ├── cli.py               # argument parsing, subcommands, exit codes
│       ├── digest.py            # digest build/validate/load (format version 1)
│       ├── timefmt.py           # ISO/microsecond conversion, durations, --stale parsing
│       ├── adapters/
│       │   ├── __init__.py
│       │   └── corgi.py         # the only Corgi caller: snapshot, recheck, close, message
│       ├── signals/
│       │   ├── __init__.py
│       │   ├── conversation.py  # read copy, last 6 messages, PR links, checklist
│       │   ├── clipboard.py     # forgotten clipboard + heredoc extraction
│       │   ├── git.py           # folder state via git status --porcelain=v2 --branch
│       │   └── pr.py            # gh lookups, unknown causes
│       ├── engine.py            # category rules, reasons, quiet time, ordering, actions
│       ├── render.py            # judge-view and overview text/json
│       └── clipboard_out.py     # copy-back (pbcopy / slack-pbcopy), platform check
└── skills/
    └── roundup/
        ├── SKILL.md             # conversation flow, confirmation order, plugin-root resolution
        └── rules.md             # judged-signal guidance and recap/follow-up writing rules

tests/
├── helpers.py                   # stub PATH builder, git fixture repo factory, invocation log reader
├── stubs/                       # fake corgi, gh, pbcopy, slack-pbcopy (Python scripts)
├── fixtures/
│   ├── corgi/                   # recorded list/grep/history replies, conversation and tools copies
│   ├── gh/                      # recorded gh pr view replies
│   └── world/                   # seeded world: digest inputs + labelled expectations + judgments
├── test_timefmt.py
├── test_packaging.py
├── test_adapter_corgi.py
├── test_conversation.py
├── test_clipboard.py
├── test_git_signals.py
├── test_pr_signals.py
├── test_digest.py
├── test_engine.py
├── test_render.py
├── test_actions.py
├── test_seeded_world.py
└── test_architecture.py         # only adapters/corgi.py references the Corgi binary

docs/
└── digest.md                    # digest format for other consumers
```

**Structure Decision**: One plugin directory as required by `CLAUDE.md`. Python code sits in `roundup/lib/roundup/` so it ships with the plugin; tests stay at the repository root (not shipped). `Makefile` gains a `test` target.

## Design Notes

- **Flow in the skill**: resolve plugin root → `gather` into a temp dir (stop on exit 3 with Corgi's error) → empty digest: one line, done → `judge-view` page by page, write `judgments.json` following `rules.md` → `overview --format json` and show the text overview → close batch (edit, confirm once) → follow-ups one by one (send/edit/skip) → copy-backs one by one (warn that a later copy replaces the clipboard) → report every outcome → delete the temp dir. The user can stop at any step (FR-022).
- **Judging at scale**: pages of 20 sessions keep each judgment step small; at 100+ sessions the overview switches to one line per session (FR-019).
- **Exclusions**: caller via `CORGI_PANE`; subagents by construction (panes point at top-level conversations); Ask Corgi helpers via `headless_sessions[].corgi == true` (research R3).
- **Concurrency**: git per unique folder and `gh` per unique PR run in a `ThreadPoolExecutor(max_workers=8)` with per-call timeouts (git 10 s, `gh` 15 s); a timeout becomes `unknown` with cause `timeout`.
- **Re-check**: one `corgi list --json` per action (0.17 s); acceptable for batches of tens.
- **Message channel** (research R9): pre-check Claude peer session file or Codex app-server socket; typed delivery reported as failed. Residual Codex risk documented.

## Complexity Tracking

No constitution violations.
