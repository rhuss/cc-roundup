# Contract: Digest format, version 1

Produced by `roundup gather` on stdout as one JSON document (UTF-8, pretty-printing optional). Consumers: `roundup judge-view`, `roundup overview`, `roundup act`, `roundup copyback`, and any future presenter (for example an Ask Corgi `/triage`). Field semantics: [data-model.md](../data-model.md).

## Versioning

- `format` is always `"roundup-digest"`; `version` is an integer.
- Adding optional fields keeps `version`. Removing or renaming a field, or changing a field's meaning, increments it.
- Consumers MUST reject a digest whose `version` they do not know, with the message `unsupported digest version N`.

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
      "changed_at": "2026-11-18T14:00:00Z",
      "first_activity_at": "2026-11-17T08:02:11Z",
      "last_message_at": "2026-11-18T13:59:40Z",
      "conversation": {"status": "found"},
      "messages": [
        {"role": "user", "at": "2026-11-18T13:58:02Z", "text": "merge it", "cut": false},
        {"role": "assistant", "at": "2026-11-18T13:59:40Z", "text": "Merged https://github.com/me/app/pull/42 ...", "cut": false}
      ],
      "pr_links": ["https://github.com/me/app/pull/42"],
      "also_open_in": [],
      "signals": {
        "clipboard": {"status": "not_found"},
        "unfinished": {
          "status": "not_found",
          "items": [
            {"kind": "unpushed", "status": "unknown", "cause": "upstream gone", "shared": false}
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

## Field rules

- Every `signals.*` object (except `shared_folder`) has `status` in `found | not_found | unknown`; `cause` is required for `unknown`.
- `unfinished.status` is computed from non-shared items only:
  - `found` when any of them is `found`;
  - otherwise `unknown` when any of them is `unknown`, ignoring push items whose cause is `upstream gone`, `detached HEAD` or `no remote` (those never block *done, close it*);
  - otherwise `not_found`.
- `clipboard`: when `found`, carries `method`, `args`, `text` (null when `truncated`), `truncated`, `at`, `first_line`.
- `messages`: at most 6, oldest first, each `text` at most 600 characters, `cut` true when shortened.
- `pr_links`: GitHub PR URLs normalized to `https://github.com/OWNER/REPO/pull/N`, most recent mention first, no duplicates.
- Times are ISO 8601 UTC strings or null. `backend_state.changed_at_us` keeps the backend's raw value for exact re-check comparison.
- `folders` keys are resolved absolute paths; a session's `folder` is one of them (or null).
