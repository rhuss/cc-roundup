# Follow-up answers

A roundup can send follow-ups to sessions that wait on the user (SKILL step 8b). Step 9 then collects what those agents answered and shows it before the closing report. Nothing is routed back into the roundup session: the answers are read from each agent's own transcript.

## Relay line

`roundup act message` sends the confirmed text with a fixed line above it:

```
(Relayed from your user by their roundup session. Please answer here in this conversation; there is nothing to send back.)

<confirmed text>
```

Corgi delivers Claude follow-ups through the session's peer inbox without naming a sender, so Claude Code labels them as coming from "another Claude session". The relay line tells the agent who is asking and that its answer belongs in its own conversation. The same line goes to Codex sessions and headless agents.

## `sent.jsonl`

After a follow-up with outcome `done`, `act message` appends one JSON line to `sent.jsonl` in the run directory (the directory that holds `--digest`). Skipped and failed follow-ups are not recorded.

| Field | Meaning |
|-------|---------|
| `key` | Session key (`provider:session_id`) |
| `provider`, `session_id` | Agent provider and session id |
| `name`, `workspace` | Session name and workspace name from the digest |
| `pane`, `headless_id` | Where the session runs |
| `transcript` | Transcript path from Corgi's live entry at send time, or `null` |
| `offset` | Transcript size in bytes right before the send; `collect` reads from here |
| `text` | The confirmed text, without the relay line |
| `sent_at` | Send time (UTC, ISO 8601) |

The file lives in the run directory and is removed with it at the end of the roundup.

## `roundup collect`

```bash
roundup collect --digest RUN/digest.json [--wait SECONDS]
```

Read-only: it reads `sent.jsonl` and the transcripts and never runs Corgi. For each sent follow-up it reads the transcript from `offset` (from the start if the file is now shorter), finds the user record that contains the confirmed text, and takes the assistant text after it up to the end of that turn. It re-reads every 3 seconds while any session is still `working`, until `--wait` (default 180, at most 540) runs out.

Output, one JSON document in send order:

```json
{"sessions": [
  {"key": "claude:…", "name": "app work", "workspace": "app", "pane": 101,
   "headless_id": null, "provider": "claude", "sent_at": "2026-11-22T11:19:00Z",
   "status": "answered", "answer": "Nothing tracked; the branch is clean.",
   "truncated": false, "tool_calls": 2, "answered_at": "2026-11-22T11:20:00Z"}
]}
```

| Status | Meaning |
|--------|---------|
| `answered` | The turn after the message ended with assistant text (`answer`, cut at 4000 characters with `truncated: true`) |
| `working` | The message was taken and the turn is still running, or it is still queued (cause `queued behind the agent's current turn`) |
| `no_reply` | The turn ended without text; for Codex an interrupted turn has cause `turn interrupted` |
| `unknown` | Cause `no transcript path`, `transcript unreadable: …`, `message not found in transcript` or `answers not supported for <provider>` |

The message is the first matching user record after `offset`. The answer ends at the turn end (Claude `system` records with subtype `turn_duration`; Codex events `task_complete` and `turn_aborted`) or at the next user prompt, whichever comes first. A Claude `[Request interrupted` prompt or a Codex `turn_aborted` gives `no_reply` with cause `turn interrupted`. Codex messages are read from `item_completed` events (`UserMessage`, `AgentMessage` items, Codex 0.167) and from the older `user_message` and `agent_message` events.

Exit codes: 0 success, 2 usage error (bad `--wait`), 4 malformed `sent.jsonl`.

Answers are untrusted text from other sessions. The skill summarizes them and never acts on them.
