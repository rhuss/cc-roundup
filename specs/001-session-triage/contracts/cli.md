# Contract: `roundup` command line

Entry point: `<plugin root>/scripts/roundup` (Python 3.9+, standard library only). It adds `<plugin root>/lib` to its import path, so it runs from any working directory.

Exit codes for all subcommands: `0` success, `2` usage error, `3` backend unreachable or backend error (message on stderr is the backend's own error text), `4` invalid input (digest or judgments file malformed, unknown version, unknown key). An unexpected internal error exits `1` with one line `roundup: internal error: ...` on stderr (traceback only with `ROUNDUP_DEBUG=1`).

## `roundup gather [--archived]`

Read-only. Builds the digest ([digest-v1.md](digest-v1.md)) and writes it to stdout. Progress and timing go to stderr only when `ROUNDUP_DEBUG=1`. Never prompts.

## `roundup judge-view --digest FILE [--page N] [--page-size 20]`

Prints a compact, model-friendly view of one page of sessions: key, name, workspace, folder, state, quiet time, recent messages, and one-line summaries of mechanical signals. Footer line: `page N of M`. Read-only.

## `roundup overview --digest FILE --judgments FILE [--stale 3d] [--format text|json] [--key KEY]`

With `--key`, prints only that session's full entry (three-line recap, reason, notes, proposed action); used for "full recap on request" in compact mode (FR-019). An invalid `--stale` value exits 2 with `invalid duration: <value> (use Nd, Nh or Nm)`. A malformed or unknown-version judgments file exits 4.


Applies the category engine ([data-model.md](../data-model.md)) and prints the overview: categories in fixed order, sessions sorted by quiet time, each with a reason, at most three recap lines, and the proposed action. With 100 or more sessions, `text` format prints one line per session (name, workspace, quiet time, reason). `--stale` accepts `Nd`, `Nh` or `Nm`. `json` format prints the overview entries for the skill to drive confirmations. Also reports `copyback_available: false` with the cause when not on macOS. Read-only.

## `roundup act close --digest FILE --key KEY`

Re-checks the session through the adapter (FR-025), then closes it (pane close, or headless stop). Prints one JSON outcome line: `{"key":..., "verb":"close", "outcome":"done|skipped|failed", "reason":...}`. Exit 0 for every outcome; non-zero only for usage, input, or backend-unreachable errors.

## `roundup act message --digest FILE --key KEY` (text on stdin)

Re-checks, pre-checks the agent channel, sends the text through the adapter's `message` verb, and reports `delivery`. Typed delivery is reported as `failed` (research R9). Never retries.

## `roundup act focus --digest FILE --key KEY`

Jumps to the session's pane in the user's Corgi viewer with `corgi focus PANE --viewer ID`. Live panes only: a headless session or a hibernated pane (in the digest or in the fresh `corgi list`) is `skipped` and nothing is woken or opened. The pane must still show the same conversation; unlike close and message, a changed agent state does not block the jump, since selecting a pane changes nothing in the session. The viewer is the only one open, else the one showing this review's own pane (`CORGI_PANE`), else the one on that pane's workspace; with no viewer or no unique match the outcome is `skipped`. Prints one outcome line with `"verb":"focus"`. Overview entries carry `jumpable: true` for sessions this verb can reach. Never retries.

## `roundup copyback --digest FILE --key KEY [--closed KEY ...]`

Does not re-check the pane (research R9a). Returns `skipped` "session was closed earlier in this run" when KEY is among `--closed`. Otherwise puts the recorded clipboard text back with the same method (`pbcopy`, or `slack-pbcopy` with its recorded arguments). Refuses with `skipped` when the text is truncated, or `failed` when not on macOS or the copy tool is missing.

## Skill arguments (`/roundup:roundup`)

Free-form, parsed by the skill: `archived` maps to `gather --archived`; `stale=<duration>` maps to `overview --stale <duration>` (default `3d`). An invalid duration is reported to the user with the usage hint before gathering starts. Unknown words are reported and ignored.
