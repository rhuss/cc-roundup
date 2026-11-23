# Contract: Judgments file, version 1

Written by the agent running the skill (never by `roundup gather`, never merged into the digest). Read by `roundup overview`. Lives next to the digest in the run's temporary directory and is deleted with it.

```json
{
  "format": "roundup-judgments",
  "version": 1,
  "sessions": {
    "claude:3f306ab4-...": {
      "unanswered_agent": false,
      "task_finished": true,
      "judgment_note": "agent reported the PR merged",
      "about": "Login flow for the app",
      "stopped": "PR #42 merged, branch cleaned up",
      "followup": null
    }
  }
}
```

Rules:

- Keys MUST be digest session keys. Unknown keys are an error; a missing key means all judged signals are false and the recap falls back to the session name and the last message's first line.
- `unanswered_agent`: true only for a concrete question, proposed next step, or offer to do a named piece of work in the last message, with no user reply. Generic closing courtesies are false (spec clarification).
- `task_finished`: true when the conversation shows the task was completed.
- `pr_round_only`: optional, default false. True when the session did one bounded round of work on an existing pull request (triage, review replies, a requested fix round) and does not own the PR's lifecycle. With `task_finished` true, an open PR no longer holds the session in *waiting on others* (rule 3); it lands in *done, close it* with the reason `task finished: <note>; PR still open: <url>`.
- `about`, `stopped`: at most 100 characters each, one line.
- `followup`: a short message proposed for sessions that will land in *waiting on you* under rule 2 without a clipboard (for example "commit, push and open the PR"); null otherwise.
- `judgment_note`: at most 80 characters, quoted in the reason when a judged signal decides the category.
