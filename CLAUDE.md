# cc-roundup Development Guidelines

## Project Structure

```text
roundup/                 Plugin directory (distributable, all harnesses)
  .claude-plugin/        Claude Code plugin manifest
  .codex-plugin/         Codex plugin manifest
  skills/                Skills (Claude Code and Codex)
brainstorm/              Brainstorm documents (spex input)
```

## Plugin Architecture

The `roundup/` directory is a single distributable with native manifests for Claude Code and Codex. Each harness reads its own manifest and ignores the other.

Corgi is the first and only backend. Only the Corgi adapter calls the `corgi` CLI; everything else works on the digest it produces. See `brainstorm/01-session-triage.md`.

## Versioning

`VERSION`, `roundup/VERSION`, `.claude-plugin/marketplace.json` and both plugin manifests carry the same version.

## Validation

Run `make validate` before committing manifest changes.
