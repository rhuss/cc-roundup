# Rename cc-roundup to corgi-roundup

Small change, short design.

## Intent

The project is a Corgi tool, so the repository becomes `corgi-roundup`. The plugin gets the short name `roundup`, so the skill is invoked as `/roundup:roundup` (or `/roundup`).

## Goals

- GitHub repository `rhuss/cc-roundup` renamed to `rhuss/corgi-roundup`, `origin` updated.
- Plugin name `roundup` in both manifests (Claude Code, Codex) and in the dev marketplace entry.
- Dev marketplace renamed to `corgi-roundup-plugin-development`; Makefile `MARKETPLACE`/`PLUGIN` follow.
- Repo URLs, README title, CLAUDE.md, docstring, CLI description, and `tests/test_packaging.py` use the new names.
- Commands and install lines in specs and docs use `/roundup:roundup` and `roundup@corgi-roundup-plugin-development`.
- Version bump to 0.3.0 (install ID changes), in all version-carrying files.
- Local install switched: old plugin and marketplace removed, new one installed via `make install`.
- `cc-rhuss-marketplace` README section updated (separate commit in that repo).

## Non-goals

- The local directory stays `~/Development/context-engineering/cc-roundup` for now (keeps Claude's per-project memory path).
- Historical mentions (for example the brainstorm origin line "abandoned in favor of this repo, `cc-roundup`") and recorded paths (scratchpad paths in tasks.md) stay as written.

## Approaches

1. **Full rename now (chosen):** repo, plugin, marketplace, docs in one pass. GitHub redirects cover old links.
2. Rename the plugin only, keep the repo name: leaves the `cc-` prefix the user wants gone.
3. New repo and deprecate the old one: loses history and redirects for no gain.

## Left to the builder

Order of steps: code and docs first (tests and `make validate` green), commit, reinstall locally, then rename the GitHub repo and update `origin`, then the marketplace README.
