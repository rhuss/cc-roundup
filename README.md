# cc-roundup

Round up stray agent sessions. cc-roundup walks through every open top-level agent session across your [Corgi](https://github.com/tals/corgi) workspaces, recaps what each one was about, sorts them into *waiting on you*, *stale, decide*, *waiting on others* and *done, close it*, and proposes the step that closes each thread: close the pane, send the agent a follow-up, or copy a forgotten draft back to the clipboard. Nothing runs until you confirm it.

Status: first version. The `roundup` skill works with Corgi as its only backend. The design is in [brainstorm/01-session-triage.md](brainstorm/01-session-triage.md) and [specs/001-session-triage/](specs/001-session-triage/).

## Usage

Start the review from an agent that runs in a Corgi pane:

```text
/cc-roundup:roundup
/cc-roundup:roundup stale=7d
/cc-roundup:roundup archived
```

In Codex, invoke the `roundup` skill the same way, with the same optional words.

- `stale=<duration>` sets when a quiet session counts as stale (`Nd`, `Nh` or `Nm`, default `3d`).
- `archived` also includes archived workspaces.

The review takes one read-only snapshot of all open top-level sessions (subagents, Ask Corgi helper chats and the session running the review are left out). The agent then reads the last few messages of each session, and you get an overview grouped by category. Each session gets a one-line reason and a recap of at most three lines: what it was about, where it stopped, and how long it has been quiet.

## Categories

The rules are applied in order, and the first match wins.

| Category | When |
|---|---|
| *waiting on you* | The agent is blocked on an approval prompt (reason "approval pending"), or it asked you something, proposed a next step or offered named work you never answered, or a drafted message was copied to the clipboard and never pasted, or there is unfinished work: open checklist items in the last answer, uncommitted changes, unpushed commits, a branch never pushed, an interrupted last turn. |
| *waiting on others* | The agent is working or starting up, or the pull request it mentioned last is still open. |
| *done, close it* | The pull request it mentioned last is merged or closed, or the conversation shows the task was finished. |
| *stale, decide* | Nothing above applies. The reason shows how long the session has been quiet and says "stale" once that passes the threshold. |

A working agent, or uncommitted or unpushed work in a session's own folder, keeps the session out of *done, close it*. When several sessions share one folder (typically a main checkout), that folder's git state only adds a note to each reason. Missing data is reported as unknown with the cause and is never treated as "nothing found".

## Confirmation order

1. The close batch comes first. All *done, close it* sessions are preselected. You can drop entries or add *stale, decide*, hibernated or exited sessions, then confirm once. Closing ends the pane (or stops a headless agent); the conversation stays resumable through `corgi history` and `corgi resume`.
2. Then the follow-ups, one at a time. You send each draft as is, edit it first, or skip it.
3. Clipboard copy-backs come last and one at a time, because each copy replaces the clipboard. They use the same tool as the original copy (`pbcopy` or `slack-pbcopy` with its options) and need macOS.

You can stop at any step. Before every close or follow-up the tool checks the session again and skips the action if its state changed since the snapshot. Nothing is retried automatically, and the review itself never types into a pane; the one known exception is Corgi's own typing fallback for follow-ups, described below. The review ends with a report of what was done, skipped, failed and not reached.

### Follow-ups to Codex sessions

Follow-ups go only through the agent's own message channel. For Claude Code sessions the review can confirm that channel up front. For Codex sessions it can only check most of what Corgi needs, because Corgi also requires a recent protocol heartbeat that it does not expose. In rare cases (for Codex, or when a Claude Code session's inbox disappears between the check and the send) Corgi then falls back to typing the message into the pane. The review cannot prevent this, because Corgi's message command offers no way to turn the fallback off; it reports the outcome as a failure instead of hiding it, and the skill warns you before the first Codex follow-up. Making this strict would need a change in Corgi.

## Installation

cc-roundup ships as a single plugin directory (`roundup/`) with native manifests for Claude Code and Codex.

### Claude Code

```bash
claude plugin marketplace add /path/to/cc-roundup
claude plugin install cc-roundup@cc-roundup-plugin-development
```

Or from a clone: `make install`.

### Codex

```bash
codex plugin marketplace add /path/to/cc-roundup
codex plugin install cc-roundup@cc-roundup-plugin-development
```

Or from a clone: `make install-codex`.

## Requirements

- A running [Corgi](https://github.com/tals/corgi) runtime, with the agent started in a Corgi pane
- `python3` 3.9 or newer (standard library only, nothing to install)
- `git`
- `gh`, signed in, for pull request state (optional; without it the state is reported as unknown)
- macOS for clipboard copy-back (optional; elsewhere copy-back is reported as unavailable)

## Development

```bash
make test       # offline test suite: stub corgi, gh and clipboard tools, git fixture repositories
make validate   # plugin manifests
```

The tests never touch a live Corgi runtime, the network or the real clipboard. The synthetic fixtures under `tests/fixtures/` are generated by `tests/fixtures/generate.py`. The digest format that connects the Corgi adapter with the rest of the tool is documented in [docs/digest.md](docs/digest.md).

## License

MIT
