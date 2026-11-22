# Contract: Corgi adapter

Module `roundup/lib/roundup/adapters/corgi.py`. The only code that runs the Corgi binary (FR-028). Binary: `$ROUNDUP_CORGI`, else `$CORGI_APP_EXE`, else `corgi` (research R2). Every call has a timeout (30 s for list and grep, 15 s for actions).

## Interface (what the core may call)

| Function | Purpose | Corgi commands used |
|---|---|---|
| `snapshot(archived: bool) -> BackendSnapshot` | sessions in scope, caller, raw states, conversation copy paths, interrupted flags | `list --json`; `grep --workspace '*' --max-age all --tools -l --json --limit 0 --max-output 0 .`; per-session fallback `grep --session P:ID --tools -l --json .`; `history --json --limit 1000`; transcript tail read |
| `recheck(session) -> RecheckResult` | does the pane or headless session still exist, do state and `changed_at` still match (headless: `state`, `pending_requests`, `exited`) | `list --json` |
| `close(session) -> Outcome` | end a session | `pane close ID` or `headless stop PROVIDER SESSION` |
| `message(session, text) -> Outcome` | prompt the agent through its own channel | channel pre-check (filesystem), then `message pane:ID --stdin --json` or `message headless:ID --stdin --json` |

`BackendSnapshot` carries, per session: the Session fields of the digest that come from the backend (identity, pane, workspace, folder, state mapping inputs, `changed_at`, hibernated, headless), the conversation copy path and tools copy path (or a cause), the transcript path, and `interrupted` (`true | false | null` plus cause).

## Behavior

- Backend unreachable: raise `BackendError(text)` where `text` is the `err` field of Corgi's JSON stderr, or the raw stderr. The CLI maps it to exit 3.
- `message` never calls Corgi when the channel pre-check fails; it returns `skipped` with `agent channel not available; not typing into the pane`. A reply with `delivery: "typed"` returns `failed` (research R9).
- `close`/`message` never retry and never fall back to `pane send` or `pane keys`.
- The adapter never calls a mutating command during `snapshot` or `recheck`.

## Test stub

Tests put a fake `corgi` executable first on `PATH` (and set `ROUNDUP_CORGI` to it). It serves recorded replies from a fixture directory keyed by arguments, and appends every invocation (argv and stdin) to a log file, so tests can assert exactly which commands ran (SC-006, SC-007).
