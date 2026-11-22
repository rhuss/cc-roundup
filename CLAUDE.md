# cc-roundup Development Guidelines

## Project Structure

```text
roundup/                 Plugin directory (distributable, all harnesses)
  .claude-plugin/        Claude Code plugin manifest
  .codex-plugin/         Codex plugin manifest
  skills/roundup/        The roundup skill (SKILL.md flow, rules.md judging rules)
  scripts/roundup        CLI entry point (Python 3.9+, standard library only)
  lib/roundup/           CLI package: adapters/corgi.py, signals/, digest, engine, render
tests/                   Offline unittest suite (not shipped)
  stubs/                 Fake corgi, gh, pbcopy, slack-pbcopy that log their calls
  fixtures/              Synthetic fixtures (regenerate with tests/fixtures/generate.py)
docs/                    User docs (digest format)
specs/                   Feature specs, plans and tasks
brainstorm/              Brainstorm documents (spex input)
```

## Plugin Architecture

The `roundup/` directory is a single distributable with native manifests for Claude Code and Codex. Each harness reads its own manifest and ignores the other.

Corgi is the first and only backend. Only the Corgi adapter calls the `corgi` CLI; everything else works on the digest it produces. See `brainstorm/01-session-triage.md`.

## Versioning

`VERSION`, `roundup/VERSION`, `.claude-plugin/marketplace.json` and both plugin manifests carry the same version.

Only `roundup/lib/roundup/adapters/corgi.py` may run the Corgi binary (`tests/test_architecture.py` enforces it). Gathering is read-only; actions run only after the user confirms them.

## Testing

Run `make test` (`python3 -m unittest discover -s tests -t .`). The suite uses stub executables and git repositories built in temporary directories; it never touches a live Corgi runtime, the network or the real clipboard. Committed fixtures must stay synthetic (no real conversation text, home paths only as `/Users/me` or `/home/me`).

## Validation

Run `make validate` before committing manifest changes.
