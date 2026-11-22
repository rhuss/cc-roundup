# The roundup digest (format version 1)

`roundup gather` writes one JSON document to stdout: a read-only snapshot of every open top-level agent session plus the mechanical signals found for each. All later steps of a review (judge view, overview, actions, copy-back) read this file, and so can other tools that want to present or triage the same sessions. The digest knows nothing about how the overview looks.

The Corgi adapter (`roundup/lib/roundup/adapters/corgi.py`) is the only code that produces backend data. Everything in the digest is backend-neutral except `backend_state`, which keeps raw values for the pre-action re-check.

## Versioning

- `format` is always `"roundup-digest"`, and `version` is an integer (currently `1`).
- Adding an optional field keeps the version. Removing or renaming a field, or changing what a field means, increments it.
- Consumers must reject a digest whose version they do not know, with the message `unsupported digest version N`. The `roundup` tool does so with exit code 4.

## Top level

| Field | Type | Meaning |
|---|---|---|
| `format` | string | `"roundup-digest"` |
| `version` | integer | `1` |
| `generated_at` | ISO 8601 UTC | snapshot time; quiet times are measured up to this instant |
| `backend` | string | `"corgi"` |
| `options` | object | `archived`: whether archived workspaces were included |
| `caller` | object | `pane` (id or null), `excluded` (bool), `cause` (why the caller could not be excluded) |
| `folders` | object | resolved absolute folder path to its git state (see below) |
| `sessions` | array | one entry per in-scope session, each key exactly once |

## Session

| Field | Type | Meaning |
|---|---|---|
| `key` | string | `PROVIDER:SESSION_ID`, unique in the digest |
| `provider`, `session_id`, `name` | string | identity and display name from the backend |
| `kind` | `pane` or `headless` | where the agent runs |
| `pane` | integer or null | pane id (a headless session may have none) |
| `headless_id` | string or null | headless session id |
| `hibernated` | bool | the pane is asleep (process stopped, screen kept) |
| `workspace` | object | `id`, `name`, `archived` |
| `folder` | string or null | resolved absolute path; a key of `folders` |
| `agent_state` | string | `working`, `starting`, `blocked`, `idle`, `exited` or `unknown` |
| `agent_state_cause` | string | optional, the raw value when the state is `unknown` |
| `backend_state` | object | raw backend values for the re-check (`state`, `changed_at_us`, and more) |
| `changed_at` | ISO 8601 or null | the backend's last change time (null for headless sessions) |
| `first_activity_at`, `last_message_at` | ISO 8601 or null | first and last message time in the conversation copy |
| `conversation` | object | `status` (`found` or `unknown`) and `cause` when it could not be read |
| `messages` | array | the last 6 user or assistant messages, oldest first: `role`, `at`, `text` (at most 600 characters), `cut` |
| `pr_links` | array | all GitHub pull request URLs in the whole conversation, normalized to `https://github.com/OWNER/REPO/pull/N`, most recent mention first |
| `also_open_in` | array | other pane ids that show the same conversation |
| `signals` | object | see below |

A hibernated pane reports `agent_state: "idle"` together with `hibernated: true`.

## Signals

Every signal except `shared_folder` has a `status` of `found`, `not_found` or `unknown`. An `unknown` status always carries a `cause`. Missing or unreadable data is `unknown`, never `not_found`.

- `clipboard`: the last tool call copied text to the clipboard and no user message followed. When `found`, it carries `method` (`pbcopy` or `slack-pbcopy`), `args` (for example `--tight`), `text` (the exact text, or null when `truncated`; also null when the text cannot be reproduced exactly, such as an unquoted heredoc the shell expanded, or arguments other than the supported flags), `truncated`, `at` and `first_line` (at most 80 characters).
- `unfinished`: `items`, each `{kind, status, detail, shared, cause?}` with `kind` one of `checklist`, `uncommitted`, `unpushed`, `never_pushed`, `interrupted`. The overall `status` is computed from the items whose `shared` is false: `found` if any is found; otherwise `unknown` if any is unknown, except push items whose cause is `upstream gone`, `detached HEAD` or `no remote`; otherwise `not_found`. Items with `shared: true` come from a folder that several sessions use and never decide a category.
- `shared_folder`: `shared` (bool) and `sessions` (the other keys using the same resolved folder). Different worktrees of one repository are different folders.
- `pr`: `current` (`{url, state}` for the most recently mentioned link, `state` being `open`, `merged`, `closed`, or null when the lookup failed) and `others` (`[{url, state}]`). Causes for `unknown` include `gh missing`, `gh not signed in`, `host not GitHub` and the lookup error.

## Folder state

Each entry of `folders` has `status`, optional `cause`, `repo` (bool), `branch`, `detached` (bool), `dirty` (bool or null), `upstream` (`ok`, `none`, `gone`, `detached`, `no_remote`, or null when unknown) `ahead` (integer or null) and, when `git remote` itself failed, `push_cause` (why the push state is unknown). Gathering reads it with `git --no-optional-locks status --porcelain=v2 --branch` (with `core.fsmonitor` off and inherited `GIT_DIR`-style selectors removed) and never fetches or writes to the repository.

## Example (abridged)

```json
{
  "format": "roundup-digest",
  "version": 1,
  "generated_at": "2026-11-22T09:15:00Z",
  "backend": "corgi",
  "options": {"archived": false},
  "caller": {"pane": 878, "excluded": true},
  "folders": {
    "/Users/me/src/app": {
      "status": "found", "repo": true, "branch": "042-login", "detached": false,
      "dirty": false, "upstream": "gone", "ahead": null
    }
  },
  "sessions": [
    {
      "key": "claude:3f306ab4-6579-4f7b-b6c7-5f9e3cec9834",
      "provider": "claude",
      "session_id": "3f306ab4-6579-4f7b-b6c7-5f9e3cec9834",
      "name": "login flow",
      "kind": "pane",
      "pane": 812,
      "headless_id": null,
      "hibernated": false,
      "workspace": {"id": 11, "name": "app", "archived": false},
      "folder": "/Users/me/src/app",
      "agent_state": "idle",
      "backend_state": {"state": "idle", "changed_at_us": 1795320000000000},
      "changed_at": "2026-11-22T04:00:00Z",
      "first_activity_at": "2026-11-21T08:02:11Z",
      "last_message_at": "2026-11-22T03:59:40Z",
      "conversation": {"status": "found"},
      "messages": [
        {"role": "user", "at": "2026-11-22T03:58:02Z", "text": "merge it", "cut": false},
        {"role": "assistant", "at": "2026-11-22T03:59:40Z", "text": "Merged https://github.com/me/app/pull/42.", "cut": false}
      ],
      "pr_links": ["https://github.com/me/app/pull/42"],
      "also_open_in": [],
      "signals": {
        "clipboard": {"status": "not_found"},
        "unfinished": {
          "status": "not_found",
          "items": [
            {"kind": "checklist", "status": "not_found", "detail": "", "shared": false},
            {"kind": "uncommitted", "status": "not_found", "detail": "", "shared": false},
            {"kind": "unpushed", "status": "unknown", "cause": "upstream gone", "detail": "", "shared": false},
            {"kind": "interrupted", "status": "not_found", "detail": "", "shared": false}
          ]
        },
        "shared_folder": {"shared": false, "sessions": []},
        "pr": {
          "status": "found",
          "current": {"url": "https://github.com/me/app/pull/42", "state": "merged"},
          "others": []
        }
      }
    }
  ]
}
```

## What the digest leaves out

The agent's judgments (whether the agent asked something, whether the task looks finished, the recap text and follow-up drafts) live in a separate judgments file and are never merged into the digest. Categories and proposed actions are computed by `roundup overview` from both files and are not stored anywhere. The digest itself exists only for the duration of one review; the skill keeps it in a temporary directory and deletes it at the end.
