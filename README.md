# cc-roundup

Round up stray agent sessions. cc-roundup walks through every open top-level agent session across your [Corgi](https://github.com/tals/corgi) workspaces, recaps what each one was about, sorts them into *waiting on you*, *stale, decide*, *waiting on others* and *done, close it*, and proposes the step that closes each thread: close the pane, send the agent a follow-up, or copy a forgotten draft back to the clipboard. Nothing runs until you confirm it.

Status: in design. See [brainstorm/01-session-triage.md](brainstorm/01-session-triage.md).

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

## Requirements

- A running [Corgi](https://github.com/tals/corgi) runtime, with the agent started in a Corgi pane
- `git`, `jq`
- `gh`, signed in, for pull request state (optional)
- macOS for clipboard copy-back (optional)

## License

MIT
