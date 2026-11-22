# Rename cc-roundup to corgi-roundup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the repository to `corgi-roundup` and the plugin to `roundup`, so the skill runs as `/roundup:roundup` (or `/roundup`).

**Architecture:** Pure rename. Manifests, Makefile, tests and docs change in the repo first; then the local install is switched; then the GitHub repo and `origin` are renamed; then the separate `cc-rhuss-marketplace` README follows.

**Tech Stack:** JSON manifests, Make, Python unittest, `gh`, `claude plugin`.

**Spec:** `docs/superpowers/specs/2026-11-22-rename-corgi-roundup-design.md`

## Global Constraints

- Repository: `rhuss/corgi-roundup`. Plugin name: `roundup`. Dev marketplace: `corgi-roundup-plugin-development`. Install ID: `roundup@corgi-roundup-plugin-development`.
- Version `0.3.0` in `VERSION`, `roundup/VERSION`, `.claude-plugin/marketplace.json`, `roundup/.claude-plugin/plugin.json`, `roundup/.codex-plugin/plugin.json`.
- Local directory stays `~/Development/context-engineering/cc-roundup`.
- Keep historical mentions and recorded paths as written: `brainstorm/01-session-triage.md:5` ("abandoned in favor of this repo, `cc-roundup`"), the scratchpad path in `specs/001-session-triage/tasks.md:15`, and earlier plans under `docs/superpowers/plans/`.
- Commits use the `Assisted-By: 🤖 Claude Code` trailer. No `.mcp.json` in commits.

## Review Focus

1. Stale `cc-roundup` in a user-facing command or install line: `rg -n 'cc-roundup' --hidden -g '!.git'` must list only the kept historical lines and the local directory paths.
2. Old install left enabled next to the new one: `claude plugin list` shows only `roundup@corgi-roundup-plugin-development`.
3. `/roundup` short form: after reinstall, a new Claude Code session offers both `/roundup` and `/roundup:roundup`.
4. Old GitHub URL: `https://github.com/rhuss/cc-roundup` redirects to the renamed repo after `gh repo rename`.
5. Codex install with the new ID: `make install-codex` runs with `roundup@corgi-roundup-plugin-development`.

---

### Task 1: Rename plugin, marketplace and docs in the repo

**Files:**
- Modify: `roundup/.claude-plugin/plugin.json` (name `roundup`, repository/homepage `https://github.com/rhuss/corgi-roundup`, version `0.3.0`)
- Modify: `roundup/.codex-plugin/plugin.json` (name `roundup`, version `0.3.0`)
- Modify: `.claude-plugin/marketplace.json` (marketplace name `corgi-roundup-plugin-development`, description "Local development marketplace for the corgi-roundup plugin.", plugin name `roundup`, version `0.3.0`, homepage `https://github.com/rhuss/corgi-roundup`, repository `https://github.com/rhuss/corgi-roundup.git`)
- Modify: `VERSION`, `roundup/VERSION` (`0.3.0`)
- Modify: `Makefile:3-4` (`MARKETPLACE := corgi-roundup-plugin-development`, `PLUGIN := roundup@$(MARKETPLACE)`)
- Modify: `roundup/lib/roundup/cli.py:167` (description "Round up open agent sessions (corgi-roundup).")
- Modify: `roundup/lib/roundup/__init__.py:1` (docstring "(corgi-roundup plugin)")
- Modify: `README.md` (title and prose `corgi-roundup`, commands `/roundup:roundup`, install lines `roundup@corgi-roundup-plugin-development`, marketplace path `/path/to/corgi-roundup`)
- Modify: `CLAUDE.md:1` (`# corgi-roundup Development Guidelines`)
- Modify: `brainstorm/01-session-triage.md:22,30`, `specs/001-session-triage/{spec.md,plan.md,quickstart.md,contracts/cli.md,RUNBOOK.md,tasks.md:150,VALIDATION.md}`: `/cc-roundup:roundup` becomes `/roundup:roundup`, "cc-roundup plugin" becomes "roundup plugin", `cc-roundup@cc-roundup-plugin-development` becomes `roundup@corgi-roundup-plugin-development`, the standalone repository name becomes `corgi-roundup`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: install ID `roundup@corgi-roundup-plugin-development` (used by Task 2).

- [ ] **Step 1: Write the failing test.** In `tests/test_packaging.py`, change `test_codex_manifest_points_at_skills` to assert `manifest["name"] == "roundup"`, and add:

```python
def test_plugin_names(self):
    claude = json.loads(read(PLUGIN, ".claude-plugin", "plugin.json"))
    market = json.loads(read(ROOT, ".claude-plugin", "marketplace.json"))
    self.assertEqual(claude["name"], "roundup")
    self.assertEqual(market["name"], "corgi-roundup-plugin-development")
    self.assertEqual(market["plugins"][0]["name"], "roundup")
    self.assertEqual(claude["repository"], "https://github.com/rhuss/corgi-roundup")
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_packaging -v`. Expected: the two name tests FAIL.
- [ ] **Step 3: Apply all file changes listed above.** Note: `specs/001-session-triage/RUNBOOK.md` has an uncommitted change already; edit it in place and keep that change.
- [ ] **Step 4: Run** `make test` and `make validate`. Expected: all tests pass, both manifests validate.
- [ ] **Step 5: Check leftovers.** Run `rg -n 'cc-roundup' --hidden -g '!.git'`. Expected: only the kept lines from Global Constraints, this plan, the design doc and the earlier plans.
- [ ] **Step 6: Commit** the design doc, this plan and the rename: `git commit -m "chore: rename cc-roundup to corgi-roundup, plugin to roundup"`.

### Task 2: Switch the local install

- [ ] **Step 1:** `claude plugin rm cc-roundup@cc-roundup-plugin-development` and `claude plugin marketplace rm cc-roundup-plugin-development`.
- [ ] **Step 2:** `make install`. Expected: `roundup@corgi-roundup-plugin-development` installed.
- [ ] **Step 3:** `claude plugin list | rg roundup`. Expected: only the new ID. `rg -n 'cc-roundup' ~/.claude/settings.json ~/.claude/plugins/installed_plugins.json` returns nothing.
- [ ] **Step 4:** If Codex has the old plugin (`rg -n roundup ~/.codex/config.toml`), remove it and run `make install-codex`.

### Task 3: Rename the GitHub repository (outward-facing, confirm with the user first)

- [ ] **Step 1:** `gh repo rename corgi-roundup -R rhuss/cc-roundup --yes`.
- [ ] **Step 2:** `git remote set-url origin https://github.com/rhuss/corgi-roundup.git`, then `git remote -v`. Expected: the new URL.
- [ ] **Step 3:** `git push origin main`. Expected: success.
- [ ] **Step 4:** `curl -sI https://github.com/rhuss/cc-roundup | rg -i '^location'`. Expected: redirect to `corgi-roundup`.

### Task 4: Update cc-rhuss-marketplace README

**Files:** Modify `~/Development/context-engineering/cc-rhuss-marketplace/README.md:64-77` (heading `corgi-roundup`, prose name, `/roundup:roundup`, link `https://github.com/rhuss/corgi-roundup`).

- [ ] **Step 1:** Apply the edits, then `rg -n 'cc-roundup' README.md` there. Expected: no output.
- [ ] **Step 2:** Commit in that repo: `docs: rename cc-roundup to corgi-roundup`. Push only after the user confirms.
